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

"""Standard Shopping campaigns and shared negative keyword lists.

Two things live here because both are built from the same primitives and both
have non-obvious API rules that cost real time to discover.

SHOPPING RULES ENCODED HERE
---------------------------
1. **The listing group tree must be exhaustive.** A root ``SUBDIVISION`` needs
   both an included ``UNIT`` (with a case value) *and* an excluded catch-all
   ``UNIT`` (same dimension, **no** value, ``negative = True``). Without the
   catch-all the API rejects the tree — every subdivision must account for
   every product.
2. **Ad group criterion temp resource names use a different format**:
   ``customers/{cid}/adGroupCriteria/{ad_group_id}~-1``. Note the ``~`` and the
   real ad group ID. Getting this wrong yields ``RESOURCE_NOT_FOUND``.
3. **``cpc_bid_micros`` is required on the biddable unit**, even under
   Maximize Clicks where it is inert. Omitting it fails validation.
4. **The Shopping product ad carries no content**: an empty
   ``ShoppingProductAdInfo``. The feed supplies everything.
5. **``feed_label`` replaced ``sales_country``.** It must match the value in
   Merchant Center exactly.
6. Ad group type must be ``SHOPPING_PRODUCT_ADS``; content network off.
7. Budgets are non-shared (``explicitly_shared = False``).

SHARED NEGATIVE LIST RULES
--------------------------
A shared list is three objects: a ``SharedSet`` (type ``NEGATIVE_KEYWORDS``),
one ``SharedCriterion`` per keyword, and one ``CampaignSharedSet`` per campaign
it applies to. Building it as a list rather than per-campaign negatives means
one edit updates every campaign — which is what you want for brand or
competitor exclusions.

Everything here is built as operations and returned; nothing is sent to the API
by these builders. Campaigns are created **PAUSED**.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("google-ads-mcp-plus.shopping")

# Placeholder bid on the biddable listing unit. Required by the API, inert
# under Maximize Clicks / Target Spend.
DEFAULT_LISTING_BID_MICROS = 1_000_000

PRODUCT_DIMENSIONS = {
    "product_type_level1": ("product_type", "LEVEL1"),
    "product_type_level2": ("product_type", "LEVEL2"),
    "product_type_level3": ("product_type", "LEVEL3"),
    "brand": ("product_brand", None),
    "condition": ("product_condition", None),
    "item_id": ("product_item_id", None),
}


class ShoppingConfigError(ValueError):
    """Raised when a Shopping request cannot be built."""


def validate_shopping_spec(spec: Dict[str, Any]) -> List[str]:
    """Offline validation. No credentials, no network."""
    errors: List[str] = []

    if not (spec.get("campaign_name") or "").strip():
        errors.append("campaign_name: required")
    if not spec.get("daily_budget"):
        errors.append("daily_budget: required")
    if not spec.get("merchant_id"):
        errors.append(
            "merchant_id: required — the Merchant Center account ID holding "
            "your product feed"
        )
    if not (spec.get("feed_label") or "").strip():
        errors.append(
            "feed_label: required. It replaced sales_country and must match "
            "the feed label in Merchant Center exactly."
        )

    priority = spec.get("campaign_priority", 0)
    if priority not in (0, 1, 2):
        errors.append("campaign_priority: must be 0 (low), 1 (medium) or 2 (high)")

    dimension = spec.get("dimension", "product_type_level1")
    if dimension not in PRODUCT_DIMENSIONS:
        errors.append(
            f"dimension: {dimension!r} is not supported. Use one of: "
            f"{', '.join(sorted(PRODUCT_DIMENSIONS))}"
        )

    values = spec.get("include_values") or []
    if not values:
        errors.append(
            "include_values: give at least one value to include (for example "
            "the exact product_type as it appears in Merchant Center). "
            "Everything else is excluded by a catch-all node."
        )

    return errors


def build_listing_group_ops(client, customer_id: str, ad_group_id: str,
                            dimension: str, include_values: List[str],
                            bid_micros: int = DEFAULT_LISTING_BID_MICROS):
    """Build an exhaustive listing group tree for one ad group.

    Produces: root SUBDIVISION, one biddable UNIT per included value, and one
    excluded catch-all UNIT. The catch-all is mandatory — a subdivision that
    does not cover every product is rejected.
    """
    enums = client.enums
    field, level = PRODUCT_DIMENSIONS[dimension]
    ag_rn = f"customers/{customer_id}/adGroups/{ad_group_id}"
    # Note the '~' separator and the real ad group ID — this temp resource name
    # format is specific to ad group criteria.
    root_tmp = f"customers/{customer_id}/adGroupCriteria/{ad_group_id}~-1"

    def set_case_value(criterion, value: Optional[str]):
        case = getattr(criterion.listing_group.case_value, field)
        if level:
            case.level = getattr(enums.ProductTypeLevelEnum, level)
        # A catch-all node sets the dimension but leaves the value unset.
        if value is not None:
            case.value = value

    ops = []

    # Root subdivision.
    op = client.get_type("AdGroupCriterionOperation")
    cr = op.create
    cr.resource_name = root_tmp
    cr.ad_group = ag_rn
    cr.status = enums.AdGroupCriterionStatusEnum.ENABLED
    cr.listing_group.type_ = enums.ListingGroupTypeEnum.SUBDIVISION
    ops.append(op)

    # One biddable unit per included value.
    temp_id = -2
    for value in include_values:
        op = client.get_type("AdGroupCriterionOperation")
        cr = op.create
        cr.resource_name = (
            f"customers/{customer_id}/adGroupCriteria/{ad_group_id}~{temp_id}")
        cr.ad_group = ag_rn
        cr.status = enums.AdGroupCriterionStatusEnum.ENABLED
        # Required even under Maximize Clicks, where it has no effect.
        cr.cpc_bid_micros = bid_micros
        cr.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
        cr.listing_group.parent_ad_group_criterion = root_tmp
        set_case_value(cr, str(value))
        ops.append(op)
        temp_id -= 1

    # Excluded catch-all — mandatory, or the tree is not exhaustive.
    op = client.get_type("AdGroupCriterionOperation")
    cr = op.create
    cr.resource_name = (
        f"customers/{customer_id}/adGroupCriteria/{ad_group_id}~{temp_id}")
    cr.ad_group = ag_rn
    cr.negative = True
    cr.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
    cr.listing_group.parent_ad_group_criterion = root_tmp
    set_case_value(cr, None)
    ops.append(op)

    return ops


def build_shopping_ops(client, customer_id: str, spec: Dict[str, Any]):
    """Build budget + campaign + ad group + product ad for a Shopping campaign.

    The listing group tree is NOT included: ad group criteria need the real ad
    group ID, which only exists after creation. Create the campaign first, then
    call ``build_listing_group_ops`` with the returned ad group ID.
    """
    enums = client.enums
    ops = []

    budget_tmp = f"customers/{customer_id}/campaignBudgets/-1"
    campaign_tmp = f"customers/{customer_id}/campaigns/-2"
    ad_group_tmp = f"customers/{customer_id}/adGroups/-3"

    # Budget — non-shared.
    op = client.get_type("MutateOperation")
    b = op.campaign_budget_operation.create
    b.resource_name = budget_tmp
    b.name = spec.get("budget_name") or f"{spec['campaign_name']} — budget"
    b.amount_micros = int(round(float(spec["daily_budget"]) * 1_000_000))
    b.delivery_method = enums.BudgetDeliveryMethodEnum.STANDARD
    b.explicitly_shared = False
    ops.append(op)

    # Campaign.
    op = client.get_type("MutateOperation")
    c = op.campaign_operation.create
    c.resource_name = campaign_tmp
    c.name = spec["campaign_name"]
    c.status = enums.CampaignStatusEnum.PAUSED  # never anything else
    c.advertising_channel_type = enums.AdvertisingChannelTypeEnum.SHOPPING
    c.campaign_budget = budget_tmp
    c.target_spend = client.get_type("TargetSpend")  # Maximize clicks
    c.contains_eu_political_advertising = (
        enums.EuPoliticalAdvertisingStatusEnum
        .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )
    c.shopping_setting.merchant_id = int(spec["merchant_id"])
    c.shopping_setting.feed_label = spec["feed_label"]
    c.shopping_setting.campaign_priority = int(spec.get("campaign_priority", 0))
    c.shopping_setting.enable_local = bool(spec.get("enable_local", False))
    c.network_settings.target_google_search = True
    c.network_settings.target_search_network = True
    c.network_settings.target_content_network = False
    ops.append(op)

    # Geo / language criteria.
    for geo_id in spec.get("geo_target_ids") or []:
        op = client.get_type("MutateOperation")
        cc = op.campaign_criterion_operation.create
        cc.campaign = campaign_tmp
        cc.location.geo_target_constant = f"geoTargetConstants/{geo_id}"
        ops.append(op)
    for lang_id in spec.get("language_ids") or []:
        op = client.get_type("MutateOperation")
        cc = op.campaign_criterion_operation.create
        cc.campaign = campaign_tmp
        cc.language.language_constant = f"languageConstants/{lang_id}"
        ops.append(op)

    # Ad group.
    op = client.get_type("MutateOperation")
    g = op.ad_group_operation.create
    g.resource_name = ad_group_tmp
    g.name = spec.get("ad_group_name") or spec["campaign_name"]
    g.campaign = campaign_tmp
    g.type_ = enums.AdGroupTypeEnum.SHOPPING_PRODUCT_ADS
    g.status = enums.AdGroupStatusEnum.PAUSED
    ops.append(op)

    # Product ad — deliberately empty. The Merchant Center feed supplies
    # images, titles and prices; there is nothing to write here.
    op = client.get_type("MutateOperation")
    a = op.ad_group_ad_operation.create
    a.ad_group = ad_group_tmp
    a.status = enums.AdGroupAdStatusEnum.PAUSED
    a.ad.shopping_product_ad = client.get_type("ShoppingProductAdInfo")
    ops.append(op)

    return ops


def create_shopping_campaign(client, customer_id: str, spec: Dict[str, Any],
                             validate_only: bool = True) -> Dict[str, Any]:
    """Validate offline, then create the campaign (and its listing group tree).

    With ``validate_only=True`` nothing is created: the campaign request is
    checked by the API and the listing group tree is described but not sent,
    because it needs a real ad group ID that does not exist yet.
    """
    errors = validate_shopping_spec(spec)
    if errors:
        raise ShoppingConfigError("; ".join(errors))

    from google.ads.googleads.errors import GoogleAdsException

    ops = build_shopping_ops(client, customer_id, spec)
    dimension = spec.get("dimension", "product_type_level1")
    values = spec["include_values"]

    request = client.get_type("MutateGoogleAdsRequest")
    request.customer_id = customer_id
    request.mutate_operations.extend(ops)
    request.partial_failure = False
    request.validate_only = validate_only

    service = client.get_service("GoogleAdsService")
    try:
        response = service.mutate(request=request)
    except GoogleAdsException as ex:
        details = [f"{e.error_code}: {e.message}" for e in ex.failure.errors]
        raise ShoppingConfigError(
            f"Google Ads rejected the request (request_id={ex.request_id}): "
            + " | ".join(details[:5])
        )

    result = {
        "validate_only": validate_only,
        "campaign_operations": len(ops),
        "listing_group_plan": {
            "dimension": dimension,
            "included": list(values),
            "excluded": "catch-all (everything else)",
            "nodes": len(values) + 2,
        },
        "campaign_status": "PAUSED",
    }

    if validate_only:
        result["status"] = (
            "VALIDATED — nothing was created. The listing group tree is "
            "planned but not validated here: it needs a real ad group ID, "
            "which only exists after creation."
        )
        return result

    campaign_id = ad_group_id = None
    for res in response.mutate_operation_responses:
        rtype = res._pb.WhichOneof("response")
        if not rtype:
            continue
        rn = getattr(res, rtype).resource_name
        if rtype == "campaign_result":
            campaign_id = rn.split("/")[-1]
        elif rtype == "ad_group_result":
            ad_group_id = rn.split("/")[-1]

    # Second call: the listing group tree, now that the ad group exists.
    lg_ops = build_listing_group_ops(
        client, customer_id, ad_group_id, dimension, values,
        int(spec.get("bid_micros", DEFAULT_LISTING_BID_MICROS)))
    try:
        lg = client.get_service("AdGroupCriterionService").mutate_ad_group_criteria(
            customer_id=customer_id, operations=lg_ops)
        result["listing_group_nodes_created"] = len(lg.results)
    except GoogleAdsException as ex:
        details = [f"{e.error_code}: {e.message}" for e in ex.failure.errors]
        result["listing_group_error"] = (
            "Campaign was created but the listing group tree failed: "
            + " | ".join(details[:3])
            + ". The campaign is PAUSED and will not serve without it."
        )

    result["status"] = "CREATED — campaign and ad group are PAUSED"
    result["campaign_id"] = campaign_id
    result["ad_group_id"] = ad_group_id
    return result


# --------------------------------------------------------------------------- #
# Shared negative keyword lists
# --------------------------------------------------------------------------- #
def apply_negative_list(client, customer_id: str, list_name: str,
                        keywords: List[str], campaign_ids: List[str],
                        match_type: str = "PHRASE",
                        validate_only: bool = True) -> Dict[str, Any]:
    """Create or extend a shared negative keyword list and link it to campaigns.

    Idempotent by design: an existing list of the same name is reused, and only
    missing keywords and missing campaign links are added. Running it twice is
    a no-op.

    A shared list beats per-campaign negatives whenever the same exclusions
    apply to several campaigns — one edit then updates all of them.
    """
    from google.ads.googleads.errors import GoogleAdsException

    match_type = match_type.upper()
    if match_type not in ("EXACT", "PHRASE", "BROAD"):
        raise ShoppingConfigError("match_type must be EXACT, PHRASE, or BROAD.")

    cleaned = [k.strip().strip('[]"') for k in keywords if k and k.strip()]
    if not cleaned:
        raise ShoppingConfigError("No usable keywords supplied.")

    ga = client.get_service("GoogleAdsService")
    escaped = list_name.replace("'", "\\'")

    # Existing list?
    set_rn = None
    for row in ga.search(customer_id=customer_id, query=f"""
        SELECT shared_set.resource_name, shared_set.name, shared_set.member_count
        FROM shared_set
        WHERE shared_set.status = 'ENABLED' AND shared_set.name = '{escaped}'
    """):
        set_rn = row.shared_set.resource_name
        break

    existing_kw, existing_links = set(), set()
    if set_rn:
        for row in ga.search(customer_id=customer_id, query=f"""
            SELECT shared_criterion.keyword.text FROM shared_criterion
            WHERE shared_set.resource_name = '{set_rn}'
        """):
            existing_kw.add(row.shared_criterion.keyword.text.lower())
        for row in ga.search(customer_id=customer_id, query=f"""
            SELECT campaign.id FROM campaign_shared_set
            WHERE campaign_shared_set.shared_set = '{set_rn}'
        """):
            existing_links.add(str(row.campaign.id))

    ops = []
    created_list = False
    if not set_rn:
        set_rn = ga.shared_set_path(customer_id, "-1")
        op = client.get_type("MutateOperation")
        ss = op.shared_set_operation.create
        ss.resource_name = set_rn
        ss.name = list_name
        ss.type_ = client.enums.SharedSetTypeEnum.NEGATIVE_KEYWORDS
        ops.append(op)
        created_list = True

    to_add = [k for k in cleaned if k.lower() not in existing_kw]
    for kw in to_add:
        op = client.get_type("MutateOperation")
        sc = op.shared_criterion_operation.create
        sc.shared_set = set_rn
        sc.keyword.text = kw
        sc.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, match_type)
        ops.append(op)

    to_link = [c for c in campaign_ids if str(c) not in existing_links]
    for camp_id in to_link:
        op = client.get_type("MutateOperation")
        css = op.campaign_shared_set_operation.create
        css.campaign = ga.campaign_path(customer_id, str(camp_id))
        css.shared_set = set_rn
        ops.append(op)

    if not ops:
        return {
            "status": "NOTHING TO DO — list, keywords and links all exist already",
            "list_name": list_name,
            "already_present": sorted(existing_kw),
        }

    request = client.get_type("MutateGoogleAdsRequest")
    request.customer_id = customer_id
    request.mutate_operations.extend(ops)
    request.partial_failure = False
    request.validate_only = validate_only

    try:
        ga.mutate(request=request)
    except GoogleAdsException as ex:
        details = [f"{e.error_code}: {e.message}" for e in ex.failure.errors]
        raise ShoppingConfigError(
            f"Google Ads rejected the request (request_id={ex.request_id}): "
            + " | ".join(details[:5])
        )

    return {
        "status": ("VALIDATED — nothing was written" if validate_only
                   else "APPLIED"),
        "list_name": list_name,
        "list_created": created_list,
        "match_type": match_type,
        "keywords_added": to_add,
        "keywords_skipped_already_present": sorted(existing_kw & {k.lower() for k in cleaned}),
        "campaigns_linked": to_link,
        "operations": len(ops),
        "effect": "These terms stop triggering ads. Spend can only go down.",
    }
