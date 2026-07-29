# Copyright 2026 ByteBerry Analytics LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Project: https://github.com/monsieurgoodmood/google-ads-mcp-plus

"""Performance Max campaign creation — one atomic bulk mutate.

Everything (budget, campaign, criteria, asset group, assets, extensions) goes in
a SINGLE ``GoogleAdsService.mutate`` call. That is deliberate: if any operation
fails, nothing is created. Sequential mutations leave half-built campaigns
behind when they break in the middle.

Hard-won ordering rules encoded here — get these wrong and the API rejects the
whole request with confusing errors:

1. **Emit every text-asset ``create`` BEFORE any ``AssetGroupAsset`` link.**
   Interleaving create/link makes the asset group fail its minimum-asset
   validation (``NOT_ENOUGH_HEADLINE`` / ``NOT_ENOUGH_DESCRIPTION``) even when
   the assets are all present.
2. **Temporary negative resource IDs must be unique across the whole request**,
   not just per resource type, or you get ``RESOURCE_NOT_FOUND``.
3. **PMax requires a non-shared budget** (``explicitly_shared = False``).
4. **With ``brand_guidelines_enabled = False``**, ``BUSINESS_NAME`` and ``LOGO``
   belong to the asset group. Turning it on moves them to campaign assets.
5. ``CampaignConversionGoalService`` does not support partial failure, so goals
   are applied after creation in their own atomic call.

Campaigns are created **PAUSED**. There is no flag here to create them enabled.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import validators

logger = logging.getLogger("google-ads-mcp-plus.pmax")

# Asset-group minimums enforced by Google. Checked offline before any API call
# so the failure message is useful instead of a proto error.
MIN_HEADLINES = 3
MIN_LONG_HEADLINES = 1
MIN_DESCRIPTIONS = 2
MAX_LONG_HEADLINE = 90
MAX_BUSINESS_NAME = 25
# Google caps campaign-level callouts at 20.
MAX_CAMPAIGN_CALLOUTS = 20


class PMaxConfigError(ValueError):
    """Raised when the requested Performance Max campaign cannot be built."""


def validate_pmax_content(spec: Dict[str, Any]) -> List[str]:
    """Offline validation of a PMax spec. Returns a list of problems.

    Runs with no credentials and no network, so a caller can check ad copy long
    before touching an account.
    """
    errors: List[str] = []

    headlines = spec.get("headlines") or []
    long_headlines = spec.get("long_headlines") or []
    descriptions = spec.get("descriptions") or []

    # Reuse the shared character-limit validators for headlines/descriptions.
    errors.extend(validators.validate_campaign_content({
        "rsa": {
            "headlines": headlines,
            "descriptions": descriptions,
            "final_url": spec.get("final_url", "https://example.com"),
        }
    }))

    if len(headlines) < MIN_HEADLINES:
        errors.append(f"headlines: PMax needs at least {MIN_HEADLINES}, got {len(headlines)}")
    if len(long_headlines) < MIN_LONG_HEADLINES:
        errors.append(
            f"long_headlines: PMax needs at least {MIN_LONG_HEADLINES}, "
            f"got {len(long_headlines)}"
        )
    if len(descriptions) < MIN_DESCRIPTIONS:
        errors.append(
            f"descriptions: PMax needs at least {MIN_DESCRIPTIONS}, got {len(descriptions)}"
        )

    for i, lh in enumerate(long_headlines):
        n = validators.glyph_length(str(lh))
        if n > MAX_LONG_HEADLINE:
            errors.append(
                f"long_headlines[{i}]: {n} chars exceeds limit of "
                f"{MAX_LONG_HEADLINE} -> {lh!r}"
            )

    business_name = spec.get("business_name") or ""
    if not business_name.strip():
        errors.append("business_name: required for a Performance Max asset group")
    elif validators.glyph_length(business_name) > MAX_BUSINESS_NAME:
        errors.append(
            f"business_name: {validators.glyph_length(business_name)} chars "
            f"exceeds limit of {MAX_BUSINESS_NAME}"
        )

    if not (spec.get("final_url") or "").strip():
        errors.append("final_url: required")

    if not spec.get("daily_budget"):
        errors.append("daily_budget: required")

    callouts = spec.get("callout_asset_ids") or []
    if len(callouts) > MAX_CAMPAIGN_CALLOUTS:
        errors.append(
            f"callout_asset_ids: {len(callouts)} exceeds the campaign-level cap "
            f"of {MAX_CAMPAIGN_CALLOUTS}"
        )

    return errors


def build_operations(client, customer_id: str, spec: Dict[str, Any]):
    """Build the full list of MutateOperation for one PMax campaign.

    Returns ``(operations, summary)``. Nothing is sent to the API here.
    """
    enums = client.enums
    ft = enums.AssetFieldTypeEnum
    ops = []
    summary = {"text_assets": 0, "asset_group_assets": 0,
               "campaign_assets": 0, "campaign_criteria": 0}

    budget_tmp = f"customers/{customer_id}/campaignBudgets/-1"
    campaign_tmp = f"customers/{customer_id}/campaigns/-2"
    asset_group_tmp = f"customers/{customer_id}/assetGroups/-3"

    # ---- 1. Budget (non-shared — PMax requires it) --------------------------
    op = client.get_type("MutateOperation")
    b = op.campaign_budget_operation.create
    b.resource_name = budget_tmp
    b.name = spec.get("budget_name") or f"{spec['campaign_name']} — Budget"
    b.amount_micros = int(round(float(spec["daily_budget"]) * 1_000_000))
    b.delivery_method = enums.BudgetDeliveryMethodEnum.STANDARD
    b.explicitly_shared = False
    ops.append(op)

    # ---- 2. Campaign (PMax, PAUSED) -----------------------------------------
    op = client.get_type("MutateOperation")
    c = op.campaign_operation.create
    c.resource_name = campaign_tmp
    c.name = spec["campaign_name"]
    c.status = enums.CampaignStatusEnum.PAUSED  # never anything else
    c.advertising_channel_type = enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    c.campaign_budget = budget_tmp

    bidding = (spec.get("bidding") or "maximize_conversions").lower()
    if bidding == "maximize_conversion_value":
        c.maximize_conversion_value = client.get_type("MaximizeConversionValue")
        if spec.get("target_roas"):
            c.maximize_conversion_value.target_roas = float(spec["target_roas"])
    else:
        c.maximize_conversions = client.get_type("MaximizeConversions")
        if spec.get("target_cpa"):
            c.maximize_conversions.target_cpa_micros = int(
                round(float(spec["target_cpa"]) * 1_000_000))

    # Keep traffic on the chosen landing page unless explicitly allowed to expand.
    c.url_expansion_opt_out = bool(spec.get("url_expansion_opt_out", True))
    # False keeps BUSINESS_NAME and LOGO in the asset group (see module docstring).
    c.brand_guidelines_enabled = False
    # Required on creation since API v19.2/v20.1 or the mutate is rejected.
    c.contains_eu_political_advertising = (
        enums.EuPoliticalAdvertisingStatusEnum
        .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )
    ops.append(op)

    # ---- 3. Geo criteria ----------------------------------------------------
    for geo_id in spec.get("geo_target_ids") or []:
        op = client.get_type("MutateOperation")
        cc = op.campaign_criterion_operation.create
        cc.campaign = campaign_tmp
        cc.location.geo_target_constant = f"geoTargetConstants/{geo_id}"
        ops.append(op)
        summary["campaign_criteria"] += 1

    # ---- 4. Language criteria -----------------------------------------------
    for lang_id in spec.get("language_ids") or []:
        op = client.get_type("MutateOperation")
        cc = op.campaign_criterion_operation.create
        cc.campaign = campaign_tmp
        cc.language.language_constant = f"languageConstants/{lang_id}"
        ops.append(op)
        summary["campaign_criteria"] += 1

    # ---- 5. Ad schedule -----------------------------------------------------
    schedule = spec.get("ad_schedule")
    if schedule:
        days = [enums.DayOfWeekEnum.MONDAY, enums.DayOfWeekEnum.TUESDAY,
                enums.DayOfWeekEnum.WEDNESDAY, enums.DayOfWeekEnum.THURSDAY,
                enums.DayOfWeekEnum.FRIDAY, enums.DayOfWeekEnum.SATURDAY,
                enums.DayOfWeekEnum.SUNDAY]
        for day in days:
            op = client.get_type("MutateOperation")
            cc = op.campaign_criterion_operation.create
            cc.campaign = campaign_tmp
            cc.ad_schedule.day_of_week = day
            cc.ad_schedule.start_hour = int(schedule.get("start_hour", 0))
            cc.ad_schedule.start_minute = enums.MinuteOfHourEnum.ZERO
            cc.ad_schedule.end_hour = int(schedule.get("end_hour", 24))
            cc.ad_schedule.end_minute = enums.MinuteOfHourEnum.ZERO
            ops.append(op)
            summary["campaign_criteria"] += 1

    # ---- 6. Negative keywords (brand exclusion etc.) ------------------------
    for kw in spec.get("negative_keywords") or []:
        op = client.get_type("MutateOperation")
        cc = op.campaign_criterion_operation.create
        cc.campaign = campaign_tmp
        cc.negative = True
        cc.keyword.text = str(kw).strip().strip('[]"')
        cc.keyword.match_type = enums.KeywordMatchTypeEnum.PHRASE
        ops.append(op)
        summary["campaign_criteria"] += 1

    # ---- 7. Asset group -----------------------------------------------------
    op = client.get_type("MutateOperation")
    ag = op.asset_group_operation.create
    ag.resource_name = asset_group_tmp
    ag.name = spec.get("asset_group_name") or f"{spec['campaign_name']} — Asset Group 1"
    ag.campaign = campaign_tmp
    ag.final_urls.append(spec["final_url"])
    ag.status = enums.AssetGroupStatusEnum.ENABLED
    ops.append(op)

    # ---- 8. Text assets, then links (ORDER MATTERS — see module docstring) --
    tmp_index = [-1000]
    link_specs = []

    def create_text_asset(text, field_type_enum):
        tmp_index[0] -= 1
        rn = f"customers/{customer_id}/assets/{tmp_index[0]}"
        op_a = client.get_type("MutateOperation")
        a = op_a.asset_operation.create
        a.resource_name = rn
        a.text_asset.text = str(text)
        ops.append(op_a)
        summary["text_assets"] += 1
        link_specs.append((rn, field_type_enum))

    for h in spec["headlines"]:
        create_text_asset(h, ft.HEADLINE)
    for lh in spec["long_headlines"]:
        create_text_asset(lh, ft.LONG_HEADLINE)
    for d in spec["descriptions"]:
        create_text_asset(d, ft.DESCRIPTION)
    create_text_asset(spec["business_name"], ft.BUSINESS_NAME)

    # Reuse existing image assets by resource name — never re-upload.
    for img in spec.get("marketing_image_asset_ids") or []:
        link_specs.append((f"customers/{customer_id}/assets/{img}", ft.MARKETING_IMAGE))
    for img in spec.get("square_marketing_image_asset_ids") or []:
        link_specs.append((f"customers/{customer_id}/assets/{img}",
                           ft.SQUARE_MARKETING_IMAGE))
    for img in spec.get("logo_asset_ids") or []:
        link_specs.append((f"customers/{customer_id}/assets/{img}", ft.LOGO))

    # Only now emit the links.
    for asset_rn, field_type_enum in link_specs:
        op_l = client.get_type("MutateOperation")
        aga = op_l.asset_group_asset_operation.create
        aga.asset = asset_rn
        aga.asset_group = asset_group_tmp
        aga.field_type = field_type_enum
        ops.append(op_l)
        summary["asset_group_assets"] += 1

    # ---- 9. Campaign-level extensions (reused assets) ----------------------
    def link_campaign_asset(asset_id, field_type_enum):
        op_c = client.get_type("MutateOperation")
        ca = op_c.campaign_asset_operation.create
        ca.campaign = campaign_tmp
        ca.asset = f"customers/{customer_id}/assets/{asset_id}"
        ca.field_type = field_type_enum
        ops.append(op_c)
        summary["campaign_assets"] += 1

    for a in spec.get("sitelink_asset_ids") or []:
        link_campaign_asset(a, ft.SITELINK)
    for a in spec.get("callout_asset_ids") or []:
        link_campaign_asset(a, ft.CALLOUT)
    for a in spec.get("structured_snippet_asset_ids") or []:
        link_campaign_asset(a, ft.STRUCTURED_SNIPPET)
    for a in spec.get("promotion_asset_ids") or []:
        link_campaign_asset(a, ft.PROMOTION)
    for a in spec.get("price_asset_ids") or []:
        link_campaign_asset(a, ft.PRICE)

    return ops, summary


def execute(client, customer_id: str, spec: Dict[str, Any],
            validate_only: bool = True) -> Dict[str, Any]:
    """Validate offline, then send one atomic mutate.

    With ``validate_only=True`` (the default) the API checks everything and
    creates nothing.
    """
    errors = validate_pmax_content(spec)
    if errors:
        raise PMaxConfigError("; ".join(errors))

    from google.ads.googleads.errors import GoogleAdsException

    ops, summary = build_operations(client, customer_id, spec)

    request = client.get_type("MutateGoogleAdsRequest")
    request.customer_id = customer_id
    request.mutate_operations.extend(ops)
    request.partial_failure = False  # atomic: all or nothing
    request.validate_only = validate_only

    service = client.get_service("GoogleAdsService")
    try:
        response = service.mutate(request=request)
    except GoogleAdsException as ex:
        details = [f"{e.error_code}: {e.message}" for e in ex.failure.errors]
        raise PMaxConfigError(
            f"Google Ads rejected the request (request_id={ex.request_id}): "
            + " | ".join(details[:5])
        )

    result = {
        "validate_only": validate_only,
        "operations": len(ops),
        "summary": summary,
        "campaign_status": "PAUSED",
    }

    if validate_only:
        result["status"] = "VALIDATED — nothing was created"
        return result

    created = []
    campaign_id = None
    for res in response.mutate_operation_responses:
        rtype = res._pb.WhichOneof("response")
        if not rtype:
            continue
        rn = getattr(res, rtype).resource_name
        created.append({"type": rtype, "resource_name": rn})
        if rtype == "campaign_result":
            campaign_id = rn.split("/")[-1]

    result["status"] = "CREATED — campaign is PAUSED"
    result["campaign_id"] = campaign_id
    result["created_count"] = len(created)
    result["created"] = created[:20]
    return result


def set_conversion_goals(client, customer_id: str, campaign_id: str,
                         primary: Dict[str, str],
                         secondary: Optional[List[Dict[str, str]]] = None) -> Dict:
    """Make one goal biddable and the others not, for a single campaign.

    ``CampaignConversionGoalService`` does not support partial failure, so this
    is atomic: every (category, origin) pair must already exist on the campaign
    or the whole call fails.
    """
    from google.api_core import protobuf_helpers

    service = client.get_service("CampaignConversionGoalService")
    ops = []

    def goal_op(category: str, origin: str, biddable: bool):
        op = client.get_type("CampaignConversionGoalOperation")
        g = op.update
        g.resource_name = service.campaign_conversion_goal_path(
            customer_id, campaign_id, category, origin)
        g.biddable = biddable
        client.copy_from(op.update_mask,
                         protobuf_helpers.field_mask(None, g._pb))
        return op

    ops.append(goal_op(primary["category"], primary["origin"], True))
    for g in secondary or []:
        ops.append(goal_op(g["category"], g["origin"], False))

    resp = service.mutate_campaign_conversion_goals(
        customer_id=customer_id, operations=ops)
    return {
        "status": "APPLIED",
        "goals_set": len(resp.results),
        "primary": f"{primary['category']}/{primary['origin']}",
        "secondary_count": len(secondary or []),
    }
