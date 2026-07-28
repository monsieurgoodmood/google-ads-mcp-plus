#!/usr/bin/env python3
# Copyright 2026 Arthur Choisnet / ByteBerry Analytics LLC
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

"""Create a Google Ads Search campaign from a YAML config — safely.

This is the WRITE layer that the official (read-only) Google Ads MCP server does
not provide. It builds, in order:

    budget -> campaign -> campaign criteria (geo presence, language)
    -> ad group -> exact keywords (+ negatives) -> Responsive Search Ad
    -> assets (call, sitelinks, callouts, structured snippets)

Safety model (non-negotiable):
  * Everything is created PAUSED at the campaign level by default. Google's own
    guidance is to create campaigns PAUSED so ads do not serve immediately.
  * --dry-run validates text, checks the account currency, and resolves geo +
    language WITHOUT writing anything.
  * --live writes, still PAUSED. --enable (discouraged) creates ENABLED.
  * Nothing here can start spending money without an explicit human action
    (un-pausing the campaign in the Google Ads UI, or passing --enable).

Auth: Application Default Credentials (ADC) + a developer token from the
GOOGLE_ADS_DEVELOPER_TOKEN environment variable. No secret is ever read from,
or written to, this file. See docs/setup-oauth.md.

This is NOT an officially supported Google product. Use at your own risk.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

# Keep google-ads imports OUT of module top-level so that --validate-only and
# the unit tests run with no client library and no credentials.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader  # noqa: E402
import validators  # noqa: E402

logger = logging.getLogger("google-ads-mcp-plus")

# Shown once at startup. Apache-2.0 protects the source; this keeps the
# attribution visible at runtime too. Not an officially supported Google product.
BANNER = (
    "google-ads-mcp-plus — community tool, NOT an official Google product. "
    "Apache-2.0, by @monsieurgoodmood (ByteBerry Analytics). "
    "https://github.com/monsieurgoodmood/google-ads-mcp-plus"
)

# Google Ads API scope required by ADC for write operations.
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def build_client(cfg: Dict):
    """Build a GoogleAdsClient from ADC + the developer-token env var.

    Imports are local so the rest of this module (and the test suite) works
    without the google-ads package installed.
    """
    import google.auth
    from google.ads.googleads.client import GoogleAdsClient

    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not dev_token:
        raise SystemExit(
            "GOOGLE_ADS_DEVELOPER_TOKEN is not set. Export it (never commit it). "
            "See docs/setup-oauth.md."
        )

    # ADC created via:
    #   gcloud auth application-default login \
    #     --client-id-file=YOUR_CLIENT.json \
    #     --scopes=https://www.googleapis.com/auth/adwords,...cloud-platform
    credentials, _ = google.auth.default(scopes=[ADWORDS_SCOPE])

    login_customer_id = cfg["account"].get("login_customer_id") or None

    # use_proto_plus=True is the modern message style this script is written for.
    client = GoogleAdsClient(
        credentials=credentials,
        developer_token=dev_token,
        login_customer_id=login_customer_id,
        use_proto_plus=True,
    )
    return client


# --------------------------------------------------------------------------- #
# Read helpers (used by both --dry-run and --live)
# --------------------------------------------------------------------------- #
def check_account_currency(client, customer_id: str, expected: Optional[str]) -> str:
    """Read the account currency and status; abort on a currency mismatch.

    The account currency is fixed at creation and cannot be changed later, so a
    mismatch almost always means you are pointed at the wrong account.
    """
    ga = client.get_service("GoogleAdsService")
    rows = ga.search(
        customer_id=customer_id,
        query=(
            "SELECT customer.currency_code, customer.status, "
            "customer.descriptive_name FROM customer LIMIT 1"
        ),
    )
    currency = None
    for row in rows:
        currency = row.customer.currency_code
        status = row.customer.status.name
        name = row.customer.descriptive_name
        logger.info("Account %s (%s) currency=%s status=%s",
                    customer_id, name, currency, status)
    if expected and currency and currency.upper() != str(expected).upper():
        raise SystemExit(
            f"Currency guard: account currency is {currency} but config "
            f"currency_check is {expected}. Refusing to continue."
        )
    return currency or ""


def resolve_geo(client, target: str, country_code: Optional[str],
                language: str) -> str:
    """Resolve a location name to a geoTargetConstant resource name."""
    service = client.get_service("GeoTargetConstantService")
    request = client.get_type("SuggestGeoTargetConstantsRequest")
    request.locale = language or "en"
    if country_code:
        request.country_code = country_code
    request.location_names.names.append(target)

    response = service.suggest_geo_target_constants(request=request)
    suggestions = list(response.geo_target_constant_suggestions)
    if not suggestions:
        raise SystemExit(f"No geo target found for {target!r}.")

    best = suggestions[0].geo_target_constant
    logger.info("Geo: %r -> %s (%s, %s)", target, best.resource_name,
                best.name, best.country_code)
    return best.resource_name


def resolve_language(client, customer_id: str, code: str) -> str:
    """Resolve a language code (e.g. 'en') to a languageConstant resource name."""
    ga = client.get_service("GoogleAdsService")
    rows = ga.search(
        customer_id=customer_id,
        query=(
            "SELECT language_constant.resource_name, language_constant.code "
            f"FROM language_constant WHERE language_constant.code = '{code}'"
        ),
    )
    for row in rows:
        rn = row.language_constant.resource_name
        logger.info("Language: %r -> %s", code, rn)
        return rn
    raise SystemExit(f"No language constant found for code {code!r}.")


def find_existing_campaigns(client, customer_id: str, name: str) -> List[Dict]:
    """Return non-removed campaigns whose name matches ``name`` exactly."""
    ga = client.get_service("GoogleAdsService")
    escaped = name.replace("'", "\\'")
    rows = ga.search(
        customer_id=customer_id,
        query=(
            "SELECT campaign.resource_name, campaign.id, campaign.status, "
            "campaign.campaign_budget FROM campaign "
            f"WHERE campaign.name = '{escaped}' "
            "AND campaign.status != 'REMOVED'"
        ),
    )
    found = []
    for row in rows:
        found.append({
            "resource_name": row.campaign.resource_name,
            "budget": row.campaign.campaign_budget,
            "status": row.campaign.status.name,
        })
    return found


# --------------------------------------------------------------------------- #
# Policy-exemption handling (best-effort; verify against your API version)
# --------------------------------------------------------------------------- #
def _extract_exemptible_violation_keys(exception):
    """Pull exemptible PolicyViolationKey objects out of a GoogleAdsException.

    Used for AdGroupCriterion (keyword) operations. Returns a list of
    PolicyViolationKey protos to attach to ``operation.exempt_policy_violation_keys``.
    """
    keys = []
    for error in getattr(exception.failure, "errors", []):
        details = getattr(error, "details", None)
        pvd = getattr(details, "policy_violation_details", None) if details else None
        if pvd and getattr(pvd, "is_exemptible", False) and pvd.key:
            keys.append(pvd.key)
    return keys


def _extract_ignorable_policy_topics(exception):
    """Pull ignorable policy-topic names out of a GoogleAdsException.

    Used for AdGroupAd (RSA) operations. Returns topic-name strings to set on
    ``operation.policy_validation_parameter.ignorable_policy_topics``.
    """
    topics = []
    for error in getattr(exception.failure, "errors", []):
        details = getattr(error, "details", None)
        pfd = getattr(details, "policy_finding_details", None) if details else None
        if not pfd:
            continue
        for entry in getattr(pfd, "policy_topic_entries", []):
            # Topics of type PROHIBITED cannot be ignored; the rest can be tried.
            if entry.type_.name != "PROHIBITED" and entry.topic:
                topics.append(entry.topic)
    return topics


def mutate_with_exemptions(client, mutate_fn, operations, exemption_kind: str,
                           allow_exemptions: bool):
    """Run a mutate; on an exemptible policy violation, retry once with exemptions.

    ``exemption_kind`` is "criterion" (keywords) or "ad" (RSA). This is the path
    that handles restricted categories such as Local Services (locksmith,
    plumber, garage door, etc.). NOTE: an exemption lets the operation succeed,
    but Google may still require advertiser verification before the ad actually
    serves. See docs/policies.md. This never bypasses PROHIBITED content.
    """
    from google.ads.googleads.errors import GoogleAdsException

    try:
        return mutate_fn(operations)
    except GoogleAdsException as ex:
        if not allow_exemptions:
            raise

        if exemption_kind == "criterion":
            keys = _extract_exemptible_violation_keys(ex)
            if not keys:
                raise
            logger.warning("Retrying %d criterion op(s) with %d policy exemption(s).",
                           len(operations), len(keys))
            for op in operations:
                op.exempt_policy_violation_keys.extend(keys)
            return mutate_fn(operations)

        if exemption_kind == "ad":
            topics = _extract_ignorable_policy_topics(ex)
            if not topics:
                raise
            logger.warning("Retrying ad op(s), ignoring policy topics: %s", topics)
            for op in operations:
                op.policy_validation_parameter.ignorable_policy_topics.extend(topics)
            return mutate_fn(operations)

        raise


# --------------------------------------------------------------------------- #
# Write helpers
# --------------------------------------------------------------------------- #
def micros(amount) -> int:
    """Convert a currency amount to micros (1 unit = 1,000,000 micros)."""
    return int(round(float(amount) * 1_000_000))


def remove_campaigns(client, customer_id: str, existing: List[Dict]) -> None:
    """REMOVE homonym campaigns (and their budgets) for a clean re-run.

    Only called with --replace. REMOVE is a soft-delete and is permanent in
    Google Ads; this is why it is opt-in rather than the default.
    """
    camp_service = client.get_service("CampaignService")
    ops = []
    for c in existing:
        op = client.get_type("CampaignOperation")
        op.remove = c["resource_name"]
        ops.append(op)
    if ops:
        camp_service.mutate_campaigns(customer_id=customer_id, operations=ops)
        logger.info("Removed %d homonym campaign(s).", len(ops))

    budget_service = client.get_service("CampaignBudgetService")
    bops = []
    for c in existing:
        if c.get("budget"):
            bop = client.get_type("CampaignBudgetOperation")
            bop.remove = c["budget"]
            bops.append(bop)
    if bops:
        try:
            budget_service.mutate_campaign_budgets(customer_id=customer_id,
                                                   operations=bops)
            logger.info("Removed %d orphan budget(s).", len(bops))
        except Exception as exc:  # a shared/in-use budget cannot be removed
            logger.warning("Could not remove some budgets (likely shared): %s", exc)


def create_budget(client, customer_id: str, name: str, daily: float) -> str:
    service = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignBudgetOperation")
    budget = op.create
    budget.name = f"{name} - budget"
    budget.amount_micros = micros(daily)
    budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    budget.explicitly_shared = False
    resp = service.mutate_campaign_budgets(customer_id=customer_id, operations=[op])
    rn = resp.results[0].resource_name
    logger.info("Created budget %s", rn)
    return rn


def create_campaign(client, customer_id: str, cfg: Dict, budget_rn: str,
                    enable: bool) -> str:
    service = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    campaign = op.create
    c = cfg["campaign"]

    campaign.name = c["name"]
    campaign.status = (client.enums.CampaignStatusEnum.ENABLED if enable
                       else client.enums.CampaignStatusEnum.PAUSED)
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    campaign.campaign_budget = budget_rn

    # Network: Search only (no Search partners, no Display).
    network = "search_only" if c.get("network") in (None, "search_only") else c["network"]
    campaign.network_settings.target_google_search = True
    campaign.network_settings.target_search_network = (network != "search_only")
    campaign.network_settings.target_content_network = False
    campaign.network_settings.target_partner_search_network = False

    # Bidding.
    bidding = c.get("bidding", "maximize_clicks")
    if bidding == "manual_cpc":
        campaign.manual_cpc.enhanced_cpc_enabled = False
    else:
        # "Maximize clicks" == TargetSpend. Optional CPC ceiling.
        # If your API version rejects cpc_bid_ceiling_micros on TargetSpend,
        # set the ceiling via a portfolio strategy instead.
        if c.get("cpc_ceiling"):
            campaign.target_spend.cpc_bid_ceiling_micros = micros(c["cpc_ceiling"])
        else:
            _ = campaign.target_spend  # touch to instantiate Maximize Clicks

    # Geo targeting mode: PRESENCE (people physically in the location).
    geo_mode = (c.get("geo", {}) or {}).get("mode", "presence")
    if geo_mode == "presence":
        campaign.geo_target_type_setting.positive_geo_target_type = (
            client.enums.PositiveGeoTargetTypeEnum.PRESENCE
        )

    # REQUIRED since API v19.2/v20.1/v21: declare EU political advertising status.
    # Without this, MutateCampaigns fails with FieldError.REQUIRED. Since
    # 2026-04-01, an account with ANY undeclared campaign has all campaign
    # mutates blocked (MutateError.EU_POLITICAL_ADVERTISING_DECLARATION_REQUIRED).
    campaign.contains_eu_political_advertising = (
        client.enums.EuPoliticalAdvertisingStatusEnum
        .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )

    resp = service.mutate_campaigns(customer_id=customer_id, operations=[op])
    rn = resp.results[0].resource_name
    logger.info("Created campaign %s (status=%s)", rn,
                "ENABLED" if enable else "PAUSED")
    return rn


def create_campaign_criteria(client, customer_id: str, campaign_rn: str,
                             geo_rn: str, language_rn: str) -> None:
    service = client.get_service("CampaignCriterionService")
    ops = []

    geo_op = client.get_type("CampaignCriterionOperation")
    geo_op.create.campaign = campaign_rn
    geo_op.create.location.geo_target_constant = geo_rn
    ops.append(geo_op)

    lang_op = client.get_type("CampaignCriterionOperation")
    lang_op.create.campaign = campaign_rn
    lang_op.create.language.language_constant = language_rn
    ops.append(lang_op)

    service.mutate_campaign_criteria(customer_id=customer_id, operations=ops)
    logger.info("Added campaign criteria: geo (presence) + language.")


def create_ad_group(client, customer_id: str, campaign_rn: str, cfg: Dict,
                    enable: bool) -> str:
    service = client.get_service("AdGroupService")
    op = client.get_type("AdGroupOperation")
    ag = op.create
    ag.name = cfg["ad_group"]["name"]
    ag.campaign = campaign_rn
    ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
    ag.status = (client.enums.AdGroupStatusEnum.ENABLED if enable
                 else client.enums.AdGroupStatusEnum.ENABLED)
    # Optional default bid (used by manual_cpc).
    if cfg["campaign"].get("cpc_ceiling") and \
            cfg["campaign"].get("bidding") == "manual_cpc":
        ag.cpc_bid_micros = micros(cfg["campaign"]["cpc_ceiling"])
    resp = service.mutate_ad_groups(customer_id=customer_id, operations=[op])
    rn = resp.results[0].resource_name
    logger.info("Created ad group %s", rn)
    return rn


def _clean_keyword(text: str) -> str:
    """Strip the user's [exact]/\"phrase\" notation; we set match type explicitly."""
    return text.strip().strip("[]").strip('"').strip()


def create_keywords(client, customer_id: str, ad_group_rn: str, cfg: Dict,
                    allow_exemptions: bool) -> None:
    service = client.get_service("AdGroupCriterionService")
    ops = []

    for kw in cfg["ad_group"].get("keywords_exact", []):
        op = client.get_type("AdGroupCriterionOperation")
        crit = op.create
        crit.ad_group = ad_group_rn
        crit.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        crit.keyword.text = _clean_keyword(kw)
        crit.keyword.match_type = client.enums.KeywordMatchTypeEnum.EXACT
        ops.append(op)

    for neg in cfg["ad_group"].get("negatives", []) or []:
        op = client.get_type("AdGroupCriterionOperation")
        crit = op.create
        crit.ad_group = ad_group_rn
        crit.negative = True
        crit.keyword.text = _clean_keyword(neg)
        crit.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
        ops.append(op)

    if not ops:
        return

    def _do(operations):
        return service.mutate_ad_group_criteria(customer_id=customer_id,
                                                 operations=operations)

    mutate_with_exemptions(client, _do, ops, "criterion", allow_exemptions)
    logger.info("Created %d keyword/negative criteria.", len(ops))


def create_rsa(client, customer_id: str, ad_group_rn: str, cfg: Dict,
               enable: bool, allow_exemptions: bool) -> None:
    service = client.get_service("AdGroupAdService")
    op = client.get_type("AdGroupAdOperation")
    aga = op.create
    aga.ad_group = ad_group_rn
    aga.status = (client.enums.AdGroupAdStatusEnum.ENABLED if enable
                  else client.enums.AdGroupAdStatusEnum.ENABLED)

    rsa = cfg["rsa"]
    aga.ad.final_urls.append(rsa["final_url"])
    if rsa.get("final_mobile_url"):
        aga.ad.final_mobile_urls.append(rsa["final_mobile_url"])

    for text in rsa.get("headlines", []):
        asset = client.get_type("AdTextAsset")
        asset.text = text
        aga.ad.responsive_search_ad.headlines.append(asset)
    for text in rsa.get("descriptions", []):
        asset = client.get_type("AdTextAsset")
        asset.text = text
        aga.ad.responsive_search_ad.descriptions.append(asset)
    if rsa.get("path1"):
        aga.ad.responsive_search_ad.path1 = rsa["path1"]
    if rsa.get("path2"):
        aga.ad.responsive_search_ad.path2 = rsa["path2"]

    def _do(operations):
        return service.mutate_ad_group_ads(customer_id=customer_id,
                                            operations=operations)

    mutate_with_exemptions(client, _do, [op], "ad", allow_exemptions)
    logger.info("Created Responsive Search Ad.")


def create_assets(client, customer_id: str, campaign_rn: str, cfg: Dict) -> None:
    """Create call / sitelink / callout / structured-snippet assets and link them."""
    assets_cfg = cfg.get("assets", {}) or {}
    if not assets_cfg:
        return

    asset_service = client.get_service("AssetService")
    asset_ops = []
    plan = []  # (field_type_name,) per asset op, to link afterwards
    default_url = cfg["rsa"]["final_url"]

    # Call asset.
    if assets_cfg.get("call"):
        op = client.get_type("AssetOperation")
        op.create.call_asset.phone_number = assets_cfg["call"]
        op.create.call_asset.country_code = cfg["campaign"].get("call_country_code", "US")
        asset_ops.append(op)
        plan.append("CALL")

    # Sitelink assets (string -> text only; mapping -> text + url + descriptions).
    for sl in assets_cfg.get("sitelinks", []) or []:
        op = client.get_type("AssetOperation")
        sla = op.create.sitelink_asset
        if isinstance(sl, dict):
            sla.link_text = sl["text"]
            op.create.final_urls.append(sl.get("url", default_url))
            if sl.get("description1"):
                sla.description1 = sl["description1"]
            if sl.get("description2"):
                sla.description2 = sl["description2"]
        else:
            sla.link_text = sl
            op.create.final_urls.append(default_url)
        asset_ops.append(op)
        plan.append("SITELINK")

    # Callout assets.
    for co in assets_cfg.get("callouts", []) or []:
        op = client.get_type("AssetOperation")
        op.create.callout_asset.callout_text = co
        asset_ops.append(op)
        plan.append("CALLOUT")

    # Structured-snippet assets.
    for snip in assets_cfg.get("structured_snippets", []) or []:
        op = client.get_type("AssetOperation")
        ssa = op.create.structured_snippet_asset
        ssa.header = snip["header"]
        ssa.values.extend(snip.get("values", []))
        asset_ops.append(op)
        plan.append("STRUCTURED_SNIPPET")

    if not asset_ops:
        return

    resp = asset_service.mutate_assets(customer_id=customer_id, operations=asset_ops)
    asset_rns = [r.resource_name for r in resp.results]
    logger.info("Created %d asset(s).", len(asset_rns))

    # Link each asset to the campaign with the correct field type.
    ca_service = client.get_service("CampaignAssetService")
    link_ops = []
    field_enum = client.enums.AssetFieldTypeEnum
    for rn, field_name in zip(asset_rns, plan):
        op = client.get_type("CampaignAssetOperation")
        op.create.campaign = campaign_rn
        op.create.asset = rn
        op.create.field_type = getattr(field_enum, field_name)
        link_ops.append(op)
    ca_service.mutate_campaign_assets(customer_id=customer_id, operations=link_ops)
    logger.info("Linked %d asset(s) to the campaign.", len(link_ops))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_dry_run(client, cfg: Dict) -> None:
    customer_id = cfg["account"]["customer_id"]
    logger.info("DRY RUN — no data will be written.")
    check_account_currency(client, customer_id, cfg["account"].get("currency_check"))
    resolve_geo(client, cfg["campaign"]["geo"]["target"],
                cfg["campaign"]["geo"].get("country_code"),
                cfg["campaign"]["language"])
    resolve_language(client, customer_id, cfg["campaign"]["language"])
    existing = find_existing_campaigns(client, customer_id, cfg["campaign"]["name"])
    if existing:
        logger.warning("A campaign named %r already exists (%d). Use --replace to "
                       "recreate it on --live.", cfg["campaign"]["name"], len(existing))
    logger.info("Dry run OK. Content validated, account reachable, geo + language "
                "resolved. Re-run with --live to create everything (PAUSED).")


def run_live(client, cfg: Dict, enable: bool, replace: bool,
             allow_exemptions: bool) -> None:
    customer_id = cfg["account"]["customer_id"]
    if enable:
        logger.warning("--enable set: the campaign will be created ENABLED and may "
                       "start spending immediately. This is discouraged.")

    check_account_currency(client, customer_id, cfg["account"].get("currency_check"))
    geo_rn = resolve_geo(client, cfg["campaign"]["geo"]["target"],
                         cfg["campaign"]["geo"].get("country_code"),
                         cfg["campaign"]["language"])
    language_rn = resolve_language(client, customer_id, cfg["campaign"]["language"])

    existing = find_existing_campaigns(client, customer_id, cfg["campaign"]["name"])
    if existing:
        if not replace:
            raise SystemExit(
                f"A campaign named {cfg['campaign']['name']!r} already exists. "
                "Pass --replace to remove and recreate it, or rename the campaign "
                "in your config."
            )
        remove_campaigns(client, customer_id, existing)

    budget_rn = create_budget(client, customer_id, cfg["campaign"]["name"],
                              cfg["campaign"]["daily_budget"])
    campaign_rn = create_campaign(client, customer_id, cfg, budget_rn, enable)
    create_campaign_criteria(client, customer_id, campaign_rn, geo_rn, language_rn)
    ad_group_rn = create_ad_group(client, customer_id, campaign_rn, cfg, enable)
    create_keywords(client, customer_id, ad_group_rn, cfg, allow_exemptions)
    create_rsa(client, customer_id, ad_group_rn, cfg, enable, allow_exemptions)
    create_assets(client, customer_id, campaign_rn, cfg)

    logger.info("DONE. Campaign created %s. Review it in the Google Ads UI; it is "
                "%s.", campaign_rn, "ENABLED" if enable else "PAUSED — un-pause "
                "manually when you are ready to serve.")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create a Google Ads Search campaign from a YAML config "
                    "(paused-by-default).")
    p.add_argument("--config", required=True, help="Path to your campaign YAML.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true",
                      help="Offline: validate the config only. No API, no creds.")
    mode.add_argument("--dry-run", action="store_true",
                      help="Validate + check account + resolve geo/language. "
                           "Writes nothing.")
    mode.add_argument("--live", action="store_true",
                      help="Create everything (PAUSED by default).")
    p.add_argument("--enable", action="store_true",
                   help="(discouraged) Create ENABLED instead of PAUSED. --live only.")
    p.add_argument("--replace", action="store_true",
                   help="On --live, REMOVE an existing homonym campaign first.")
    p.add_argument("--allow-exemptions", action="store_true",
                   help="Retry exemptible policy violations with exemptions "
                        "(e.g. Local Services). Never bypasses prohibited content.")
    p.add_argument("--verbose", action="store_true", help="Debug logging.")
    args = p.parse_args(argv)
    if args.enable and not args.live:
        p.error("--enable can only be used together with --live.")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logger.info("%s", BANNER)

    # Load + validate the config (offline). Raises with a full error list.
    try:
        cfg = config_loader.load_and_validate(args.config)
    except (config_loader.ConfigError, validators.ValidationError) as exc:
        logger.error("Config invalid:\n%s", exc)
        return 2

    logger.info("Config OK: campaign %r on account %s.",
                cfg["campaign"]["name"], cfg["account"]["customer_id"])

    if args.validate_only:
        logger.info("Validate-only: nothing else to do.")
        return 0

    client = build_client(cfg)

    if args.dry_run:
        run_dry_run(client, cfg)
    else:
        run_live(client, cfg, args.enable, args.replace, args.allow_exemptions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
