#!/usr/bin/env python3
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

"""Audit a Google Ads account — strictly read-only.

This module NEVER mutates anything. It only issues GAQL `search` queries and
reports findings. It is safe to run against any production account.

Each audit is an independent "check" function registered in ``CHECKS``. A check
receives ``(client, customer_id, ctx)`` and returns a list of ``Finding``.
Adding a new audit means writing one function and registering it — no other
part of this file needs to change.

Usage::

    python src/audit/audit_account.py --customer-id 1234567890
    python src/audit/audit_account.py --customer-id 1234567890 --days 90
    python src/audit/audit_account.py --customer-id 1234567890 --format markdown \\
        --output audit.md

Findings carry a severity:

* ``critical`` — costing money right now, or hiding the data you need.
* ``warning``  — meaningful inefficiency worth fixing.
* ``info``     — context, or a smaller optimisation.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional

ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"

logger = logging.getLogger("google-ads-mcp-plus.audit")

BANNER = (
    "google-ads-mcp-plus (audit) — community tool, NOT an official Google "
    "product. Read-only: this command never modifies your account. "
    "Apache-2.0, by @monsieurgoodmood (ByteBerry Analytics)."
)

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    """A single audit result."""

    check: str
    severity: str
    entity: str
    message: str
    detail: Dict = field(default_factory=dict)


@dataclass
class AuditContext:
    """Everything a check needs beyond the client."""

    date_from: str
    date_to: str
    days: int
    currency: str = ""
    # Spend below this (account currency units) is treated as noise.
    min_spend: float = 10.0


def micros_to_units(micros: Optional[int]) -> float:
    """Google Ads reports money in micros (1 unit = 1_000_000 micros)."""
    return round((micros or 0) / 1_000_000, 2)


def pct(value: Optional[float]) -> float:
    """Impression-share style ratios come back as 0..1 floats."""
    return round((value or 0) * 100, 1)


# --------------------------------------------------------------------------- #
# Client + query helpers
# --------------------------------------------------------------------------- #
def build_client(login_customer_id: Optional[str] = None):
    """Build a GoogleAdsClient from ADC + the developer-token env var.

    Imports are local so this module can be imported (and unit-tested) without
    the google-ads package installed.
    """
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not dev_token:
        raise SystemExit(
            "GOOGLE_ADS_DEVELOPER_TOKEN is not set. Export it (never commit it). "
            "See docs/setup-oauth.md."
        )

    try:
        import google.auth
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError as exc:
        raise SystemExit(
            f"Missing dependency ({exc}). Install the client library first:\n"
            "    pip install -r requirements.txt\n"
            "Note: --list-checks works without it."
        )

    credentials, _ = google.auth.default(scopes=[ADWORDS_SCOPE])
    return GoogleAdsClient(
        credentials=credentials,
        developer_token=dev_token,
        login_customer_id=login_customer_id or None,
        use_proto_plus=True,
    )


def run_query(client, customer_id: str, query: str):
    """Run one GAQL query and yield rows. Read-only by construction."""
    ga = client.get_service("GoogleAdsService")
    return ga.search(customer_id=customer_id, query=query)


def date_range(days: int) -> (str, str):
    """Return (from, to) as YYYY-MM-DD, ending yesterday.

    Today is excluded because the current day is always partial and would make
    every 'no conversions' check fire spuriously.
    """
    end = _dt.date.today() - _dt.timedelta(days=1)
    start = end - _dt.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


# --------------------------------------------------------------------------- #
# Checks — each returns List[Finding] and never mutates anything
# --------------------------------------------------------------------------- #
def check_account_overview(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Account-level context: name, currency, spend, conversions."""
    q = f"""
        SELECT customer.descriptive_name, customer.currency_code,
               customer.time_zone, customer.auto_tagging_enabled,
               metrics.cost_micros, metrics.conversions, metrics.clicks,
               metrics.impressions
        FROM customer
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
    """
    out: List[Finding] = []
    for row in run_query(client, customer_id, q):
        ctx.currency = row.customer.currency_code
        cost = micros_to_units(row.metrics.cost_micros)
        convs = round(row.metrics.conversions or 0, 1)
        out.append(Finding(
            check="account_overview",
            severity=INFO,
            entity=row.customer.descriptive_name or customer_id,
            message=(
                f"{ctx.days}d: {cost} {ctx.currency} spend, {convs} conversions, "
                f"{row.metrics.clicks} clicks, {row.metrics.impressions} impressions."
            ),
            detail={
                "currency": row.customer.currency_code,
                "time_zone": row.customer.time_zone,
                "cost": cost,
                "conversions": convs,
                "clicks": row.metrics.clicks,
                "impressions": row.metrics.impressions,
            },
        ))
        # Auto-tagging off breaks conversion attribution from GA4.
        if not row.customer.auto_tagging_enabled:
            out.append(Finding(
                check="auto_tagging",
                severity=CRITICAL,
                entity="account",
                message=(
                    "Auto-tagging is DISABLED. GCLID is not appended to your "
                    "click URLs, so imported GA4 conversions may not attribute "
                    "correctly. Enable it in Admin > Account settings."
                ),
            ))
    return out


def _biddable_goals(client, customer_id: str) -> Optional[List[str]]:
    """Return biddable goal categories, or None if the account is not goal-based.

    Google Ads has TWO mechanisms for deciding what bidding optimises toward:

    * the legacy per-action flag ``conversion_action.primary_for_goal``, and
    * account-level goals (``customer_conversion_goal``) with a ``biddability``
      field, which is what modern accounts and Performance Max actually use.

    Checking only the legacy flag reports "nothing is primary" on a perfectly
    well-configured goal-based account. So we check goals first.

    The ``biddability`` field is not selectable in every API version, hence the
    fallback query.
    """
    q_with = """
        SELECT customer_conversion_goal.category, customer_conversion_goal.origin,
               customer_conversion_goal.biddability
        FROM customer_conversion_goal
    """
    q_without = """
        SELECT customer_conversion_goal.category, customer_conversion_goal.origin
        FROM customer_conversion_goal
    """
    try:
        rows = list(run_query(client, customer_id, q_with))
    except Exception:  # noqa: BLE001 - field unavailable in this API version
        try:
            rows = list(run_query(client, customer_id, q_without))
        except Exception:  # noqa: BLE001 - account is not goal-based at all
            return None
        # Without the biddability field we cannot tell which goals are biddable.
        return [] if not rows else ["<biddability not selectable in this API version>"]

    if not rows:
        return None
    return [
        row.customer_conversion_goal.category.name
        for row in rows
        if getattr(row.customer_conversion_goal, "biddability", False)
    ]


def check_conversion_tracking(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """No biddable conversion goal = smart bidding has nothing to optimise."""
    q = """
        SELECT conversion_action.name, conversion_action.status,
               conversion_action.type, conversion_action.primary_for_goal,
               conversion_action.category
        FROM conversion_action
        WHERE conversion_action.status = 'ENABLED'
    """
    enabled, primary = [], []
    for row in run_query(client, customer_id, q):
        name = row.conversion_action.name
        enabled.append(name)
        if row.conversion_action.primary_for_goal:
            primary.append(name)

    out: List[Finding] = []
    if not enabled:
        out.append(Finding(
            check="conversion_tracking",
            severity=CRITICAL,
            entity="account",
            message=(
                "No ENABLED conversion action exists. You are spending blind. "
                "Import your GA4 key events before running any campaign."
            ),
        ))
        return out

    goals = _biddable_goals(client, customer_id)

    # Goal-based account: the goals decide, not the legacy per-action flag.
    if goals is not None:
        if goals:
            out.append(Finding(
                check="conversion_tracking",
                severity=INFO,
                entity="account",
                message=(
                    f"Goal-based conversions: {len(goals)} biddable goal(s) "
                    f"({', '.join(goals[:5])}), across {len(enabled)} enabled "
                    "conversion action(s)."
                ),
                detail={"biddable_goals": goals, "enabled_actions": enabled},
            ))
        else:
            out.append(Finding(
                check="conversion_tracking",
                severity=CRITICAL,
                entity="account",
                message=(
                    "This account uses goal-based conversions but NO goal is "
                    "biddable. Smart bidding has nothing to optimise toward. "
                    "Set at least one goal biddable in Goals > Conversions."
                ),
                detail={"enabled_actions": enabled},
            ))
        return out

    # Legacy account: fall back to the per-action primary flag.
    if not primary:
        out.append(Finding(
            check="conversion_tracking",
            severity=CRITICAL,
            entity="account",
            message=(
                f"{len(enabled)} conversion action(s) enabled but NONE is marked "
                "Primary. Secondary conversions are not used by bidding — "
                "smart bidding has no goal to optimise toward."
            ),
            detail={"enabled": enabled},
        ))
    else:
        out.append(Finding(
            check="conversion_tracking",
            severity=INFO,
            entity="account",
            message=f"{len(primary)} primary conversion action(s): {', '.join(primary[:5])}.",
            detail={"primary": primary, "enabled": enabled},
        ))
    return out


def check_recent_changes(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Who changed what recently — the first question when performance moves.

    The change_event resource is limited to the last 30 days by the API,
    regardless of the audit window.
    """
    end = _dt.date.today()
    start = end - _dt.timedelta(days=29)
    q = f"""
        SELECT change_event.change_date_time, change_event.change_resource_type,
               change_event.changed_fields, change_event.user_email,
               change_event.client_type, campaign.name
        FROM change_event
        WHERE change_event.change_date_time
              BETWEEN '{start} 00:00:00' AND '{end} 23:59:59'
          AND change_event.change_resource_type IN
              ('CAMPAIGN', 'CAMPAIGN_BUDGET', 'CAMPAIGN_CRITERION', 'AD_GROUP')
        ORDER BY change_event.change_date_time DESC
        LIMIT 200
    """
    changes = []
    for row in run_query(client, customer_id, q):
        ev = row.change_event
        changes.append({
            "when": str(ev.change_date_time),
            "resource": ev.change_resource_type.name,
            "campaign": row.campaign.name,
            "by": ev.user_email,
            "via": ev.client_type.name,
        })
    if not changes:
        return [Finding(
            check="recent_changes",
            severity=INFO,
            entity="account",
            message="No campaign-level changes recorded in the last 30 days.",
        )]

    who = sorted({c["by"] for c in changes if c["by"]})
    return [Finding(
        check="recent_changes",
        severity=INFO,
        entity="change history",
        message=(
            f"{len(changes)} change(s) in the last 30 days"
            + (f", by: {', '.join(who[:5])}" if who else "")
            + f". Most recent: {changes[0]['resource']} on "
              f"'{changes[0]['campaign']}' ({changes[0]['when']})."
        ),
        detail={"changes": changes[:50]},
    )]


def check_campaigns_without_conversions(client, customer_id: str,
                                        ctx: AuditContext) -> List[Finding]:
    """Campaigns spending real money with zero conversions over the window."""
    q = f"""
        SELECT campaign.id, campaign.name, campaign.status,
               campaign.advertising_channel_type,
               metrics.cost_micros, metrics.conversions, metrics.clicks
        FROM campaign
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
          AND campaign.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
    """
    out: List[Finding] = []
    for row in run_query(client, customer_id, q):
        cost = micros_to_units(row.metrics.cost_micros)
        convs = row.metrics.conversions or 0
        if cost >= ctx.min_spend and convs == 0:
            out.append(Finding(
                check="campaign_no_conversions",
                severity=CRITICAL,
                entity=row.campaign.name,
                message=(
                    f"Spent {cost} {ctx.currency} over {ctx.days}d with ZERO "
                    f"conversions ({row.metrics.clicks} clicks)."
                ),
                detail={"campaign_id": row.campaign.id, "cost": cost,
                        "clicks": row.metrics.clicks},
            ))
    return out


def check_budget_limited(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Impression share lost to budget = demand you are paying to ignore."""
    q = f"""
        SELECT campaign.name, metrics.search_budget_lost_impression_share,
               metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
          AND campaign.status = 'ENABLED'
          AND campaign.advertising_channel_type = 'SEARCH'
    """
    out: List[Finding] = []
    for row in run_query(client, customer_id, q):
        lost = row.metrics.search_budget_lost_impression_share or 0
        convs = row.metrics.conversions or 0
        if lost >= 0.10:
            sev = WARNING if convs == 0 else CRITICAL
            out.append(Finding(
                check="budget_limited",
                severity=sev,
                entity=row.campaign.name,
                message=(
                    f"Losing {pct(lost)}% of impressions to BUDGET. "
                    + ("Converting campaign — raising budget likely buys more "
                       "conversions." if convs > 0 else
                       "But it has no conversions, so fix relevance before "
                       "raising budget.")
                ),
                detail={"budget_lost_is": pct(lost), "conversions": round(convs, 1)},
            ))
    return out


def check_rank_lost(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Impression share lost to rank = bids or quality are too low."""
    q = f"""
        SELECT campaign.name, metrics.search_rank_lost_impression_share,
               metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
          AND campaign.status = 'ENABLED'
          AND campaign.advertising_channel_type = 'SEARCH'
    """
    out: List[Finding] = []
    for row in run_query(client, customer_id, q):
        lost = row.metrics.search_rank_lost_impression_share or 0
        cost = micros_to_units(row.metrics.cost_micros)
        if lost >= 0.35 and cost >= ctx.min_spend:
            out.append(Finding(
                check="rank_lost",
                severity=WARNING,
                entity=row.campaign.name,
                message=(
                    f"Losing {pct(lost)}% of impressions to AD RANK — bids or "
                    "ad/landing-page quality are holding it back."
                ),
                detail={"rank_lost_is": pct(lost), "cost": cost},
            ))
    return out


def check_wasteful_search_terms(client, customer_id: str,
                                ctx: AuditContext) -> List[Finding]:
    """Search terms burning money with no conversion — negative keyword candidates."""
    q = f"""
        SELECT search_term_view.search_term, campaign.name,
               metrics.cost_micros, metrics.clicks, metrics.conversions
        FROM search_term_view
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """
    out: List[Finding] = []
    wasted = 0.0
    terms = []
    for row in run_query(client, customer_id, q):
        cost = micros_to_units(row.metrics.cost_micros)
        if cost >= ctx.min_spend and (row.metrics.conversions or 0) == 0:
            wasted += cost
            terms.append({
                "term": row.search_term_view.search_term,
                "campaign": row.campaign.name,
                "cost": cost,
                "clicks": row.metrics.clicks,
            })
    if terms:
        top = ", ".join(f"'{t['term']}' ({t['cost']})" for t in terms[:5])
        out.append(Finding(
            check="wasteful_search_terms",
            severity=CRITICAL if wasted >= ctx.min_spend * 10 else WARNING,
            entity="search terms",
            message=(
                f"{len(terms)} search term(s) spent {round(wasted, 2)} "
                f"{ctx.currency} with no conversions. Top: {top}. "
                "Review as negative keyword candidates."
            ),
            detail={"total_wasted": round(wasted, 2), "terms": terms[:50]},
        ))
    return out


def check_low_quality_keywords(client, customer_id: str,
                               ctx: AuditContext) -> List[Finding]:
    """Quality Score <= 4 means you pay a premium for every click."""
    q = f"""
        SELECT ad_group_criterion.keyword.text,
               ad_group_criterion.quality_info.quality_score,
               campaign.name, ad_group.name, metrics.cost_micros
        FROM keyword_view
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
          AND ad_group_criterion.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """
    poor = []
    for row in run_query(client, customer_id, q):
        qs = row.ad_group_criterion.quality_info.quality_score
        cost = micros_to_units(row.metrics.cost_micros)
        if qs and qs <= 4 and cost >= ctx.min_spend:
            poor.append({
                "keyword": row.ad_group_criterion.keyword.text,
                "quality_score": qs,
                "campaign": row.campaign.name,
                "cost": cost,
            })
    if not poor:
        return []
    total = round(sum(k["cost"] for k in poor), 2)
    top = ", ".join(f"'{k['keyword']}' QS={k['quality_score']}" for k in poor[:5])
    return [Finding(
        check="low_quality_keywords",
        severity=WARNING,
        entity="keywords",
        message=(
            f"{len(poor)} keyword(s) with Quality Score <= 4 consumed {total} "
            f"{ctx.currency}. Top: {top}. Low QS inflates your CPC."
        ),
        detail={"keywords": poor[:50], "total_cost": total},
    )]


def check_ad_strength(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """RSAs with few headlines or poor Ad Strength underperform."""
    q = """
        SELECT ad_group_ad.ad.id, ad_group_ad.ad_strength,
               ad_group_ad.ad.responsive_search_ad.headlines,
               ad_group_ad.ad.responsive_search_ad.descriptions,
               campaign.name, ad_group.name
        FROM ad_group_ad
        WHERE ad_group_ad.status = 'ENABLED'
          AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
        LIMIT 200
    """
    weak = []
    for row in run_query(client, customer_id, q):
        rsa = row.ad_group_ad.ad.responsive_search_ad
        n_head = len(rsa.headlines)
        n_desc = len(rsa.descriptions)
        strength = row.ad_group_ad.ad_strength.name if row.ad_group_ad.ad_strength else "UNKNOWN"
        if strength in ("POOR", "AVERAGE") or n_head < 8 or n_desc < 3:
            weak.append({
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "ad_strength": strength,
                "headlines": n_head,
                "descriptions": n_desc,
            })
    if not weak:
        return []
    return [Finding(
        check="ad_strength",
        severity=WARNING,
        entity="responsive search ads",
        message=(
            f"{len(weak)} RSA(s) are weak (Poor/Average strength, or fewer than "
            "8 headlines / 3 descriptions). More distinct assets give the "
            "system more combinations to optimise."
        ),
        detail={"ads": weak[:50]},
    )]


def check_disapproved_ads(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Disapproved ads are silently not serving."""
    q = """
        SELECT ad_group_ad.ad.id, ad_group_ad.policy_summary.approval_status,
               campaign.name, ad_group.name
        FROM ad_group_ad
        WHERE ad_group_ad.status = 'ENABLED'
          AND ad_group_ad.policy_summary.approval_status IN ('DISAPPROVED', 'AREA_OF_INTEREST_ONLY')
        LIMIT 100
    """
    bad = []
    for row in run_query(client, customer_id, q):
        bad.append({
            "campaign": row.campaign.name,
            "ad_group": row.ad_group.name,
            "status": row.ad_group_ad.policy_summary.approval_status.name,
        })
    if not bad:
        return []
    return [Finding(
        check="disapproved_ads",
        severity=CRITICAL,
        entity="ads",
        message=(
            f"{len(bad)} enabled ad(s) are disapproved or limited and are not "
            "serving normally. Check the policy details in the UI."
        ),
        detail={"ads": bad[:50]},
    )]


def check_missing_negatives(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """A Search campaign with no negative keywords wastes budget by default."""
    campaigns = {}
    q1 = """
        SELECT campaign.id, campaign.name
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND campaign.advertising_channel_type = 'SEARCH'
    """
    for row in run_query(client, customer_id, q1):
        campaigns[row.campaign.id] = row.campaign.name

    if not campaigns:
        return []

    q2 = """
        SELECT campaign.id, campaign_criterion.keyword.text
        FROM campaign_criterion
        WHERE campaign_criterion.negative = TRUE
          AND campaign_criterion.type = 'KEYWORD'
    """
    with_negatives = set()
    for row in run_query(client, customer_id, q2):
        with_negatives.add(row.campaign.id)

    missing = [n for cid, n in campaigns.items() if cid not in with_negatives]
    if not missing:
        return []
    return [Finding(
        check="missing_negatives",
        severity=WARNING,
        entity="campaigns",
        message=(
            f"{len(missing)} Search campaign(s) have NO negative keywords at the "
            f"campaign level: {', '.join(missing[:5])}."
        ),
        detail={"campaigns": missing[:50]},
    )]


def check_missing_sitelinks(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Sitelinks are free real estate; missing them lowers CTR."""
    campaigns = {}
    q1 = """
        SELECT campaign.id, campaign.name
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND campaign.advertising_channel_type = 'SEARCH'
    """
    for row in run_query(client, customer_id, q1):
        campaigns[row.campaign.id] = row.campaign.name
    if not campaigns:
        return []

    q2 = """
        SELECT campaign.id, campaign_asset.field_type
        FROM campaign_asset
        WHERE campaign_asset.field_type = 'SITELINK'
          AND campaign_asset.status = 'ENABLED'
    """
    with_sitelinks = set()
    for row in run_query(client, customer_id, q2):
        with_sitelinks.add(row.campaign.id)

    missing = [n for cid, n in campaigns.items() if cid not in with_sitelinks]
    if not missing:
        return []
    return [Finding(
        check="missing_sitelinks",
        severity=INFO,
        entity="campaigns",
        message=(
            f"{len(missing)} Search campaign(s) have no sitelink assets: "
            f"{', '.join(missing[:5])}."
        ),
        detail={"campaigns": missing[:50]},
    )]


def check_single_ad_groups(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Ad groups with a single ad cannot be tested against anything."""
    q = """
        SELECT ad_group.id, ad_group.name, campaign.name
        FROM ad_group_ad
        WHERE ad_group_ad.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
        LIMIT 500
    """
    counts: Dict[int, Dict] = {}
    for row in run_query(client, customer_id, q):
        gid = row.ad_group.id
        entry = counts.setdefault(gid, {"n": 0, "name": row.ad_group.name,
                                        "campaign": row.campaign.name})
        entry["n"] += 1

    singles = [v for v in counts.values() if v["n"] < 2]
    if not singles:
        return []
    return [Finding(
        check="single_ad_group",
        severity=INFO,
        entity="ad groups",
        message=(
            f"{len(singles)} enabled ad group(s) run a single ad. Two or three "
            "RSAs give the system something to rotate and compare."
        ),
        detail={"ad_groups": singles[:50]},
    )]


# Registry — add a function here and it runs. Order defines report order.
CHECKS: List[Callable] = [
    check_account_overview,
    check_conversion_tracking,
    check_recent_changes,
    check_campaigns_without_conversions,
    check_budget_limited,
    check_rank_lost,
    check_wasteful_search_terms,
    check_low_quality_keywords,
    check_ad_strength,
    check_disapproved_ads,
    check_missing_negatives,
    check_missing_sitelinks,
    check_single_ad_groups,
]


# --------------------------------------------------------------------------- #
# Runner + reporters
# --------------------------------------------------------------------------- #
def run_audit(client, customer_id: str, ctx: AuditContext) -> List[Finding]:
    """Execute every registered check. One failing check never aborts the rest."""
    findings: List[Finding] = []
    for check in CHECKS:
        name = check.__name__
        try:
            logger.debug("Running %s", name)
            findings.extend(check(client, customer_id, ctx))
        except Exception as exc:  # noqa: BLE001 - a broken check must not kill the audit
            logger.warning("Check %s failed: %s", name, exc)
            findings.append(Finding(
                check=name,
                severity=INFO,
                entity="audit",
                message=f"This check could not run: {exc}",
            ))
    return findings


def sort_findings(findings: List[Finding]) -> List[Finding]:
    """Critical first, then warnings, then info. Stable within a severity."""
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))


def summarize(findings: List[Finding]) -> Dict[str, int]:
    out = {CRITICAL: 0, WARNING: 0, INFO: 0}
    for f in findings:
        if f.severity in out:
            out[f.severity] += 1
    return out


def render_text(findings: List[Finding], customer_id: str, ctx: AuditContext) -> str:
    counts = summarize(findings)
    lines = [
        "=" * 72,
        f"GOOGLE ADS AUDIT — account {customer_id}",
        f"Window: {ctx.date_from} to {ctx.date_to} ({ctx.days} days)",
        f"Findings: {counts[CRITICAL]} critical, {counts[WARNING]} warning, "
        f"{counts[INFO]} info",
        "=" * 72,
        "",
    ]
    icons = {CRITICAL: "[CRITICAL]", WARNING: "[WARNING] ", INFO: "[INFO]    "}
    for f in sort_findings(findings):
        lines.append(f"{icons.get(f.severity, '[?]')} {f.entity}")
        lines.append(f"           {f.message}")
        lines.append("")
    lines.append("Read-only audit — nothing in your account was modified.")
    return "\n".join(lines)


def render_markdown(findings: List[Finding], customer_id: str,
                    ctx: AuditContext) -> str:
    counts = summarize(findings)
    lines = [
        f"# Google Ads audit — account {customer_id}",
        "",
        f"**Window:** {ctx.date_from} → {ctx.date_to} ({ctx.days} days)  ",
        f"**Findings:** {counts[CRITICAL]} critical · {counts[WARNING]} warning "
        f"· {counts[INFO]} info",
        "",
    ]
    for sev, title in ((CRITICAL, "Critical"), (WARNING, "Warnings"), (INFO, "Info")):
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for f in group:
            lines.append(f"- **{f.entity}** — {f.message}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by [google-ads-mcp-plus]"
        "(https://github.com/monsieurgoodmood/google-ads-mcp-plus) — read-only "
        "audit, nothing was modified._"
    )
    return "\n".join(lines)


def render_json(findings: List[Finding], customer_id: str,
                ctx: AuditContext) -> str:
    payload = {
        "customer_id": customer_id,
        "date_from": ctx.date_from,
        "date_to": ctx.date_to,
        "days": ctx.days,
        "currency": ctx.currency,
        "summary": summarize(findings),
        "findings": [asdict(f) for f in sort_findings(findings)],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Audit a Google Ads account. Read-only: never modifies anything.",
    )
    p.add_argument("--customer-id", required=True,
                   help="Account to audit, digits only (dashes are stripped).")
    p.add_argument("--login-customer-id", default=None,
                   help="Manager (MCC) account ID, if you access through one.")
    p.add_argument("--days", type=int, default=30,
                   help="Lookback window in days (default 30).")
    p.add_argument("--min-spend", type=float, default=10.0,
                   help="Ignore entities below this spend, in account currency "
                        "(default 10).")
    p.add_argument("--format", choices=["text", "markdown", "json"], default="text",
                   help="Report format (default text).")
    p.add_argument("--output", default=None,
                   help="Write the report to this file instead of stdout.")
    p.add_argument("--list-checks", action="store_true",
                   help="List the registered checks and exit.")
    p.add_argument("--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.list_checks:
        for c in CHECKS:
            first_line = (c.__doc__ or "").strip().split("\n")[0]
            print(f"{c.__name__:38s} {first_line}")
        return 0

    logger.info("%s", BANNER)

    customer_id = "".join(ch for ch in str(args.customer_id) if ch.isdigit())
    if not customer_id:
        raise SystemExit("--customer-id must contain digits.")

    if args.days < 1:
        raise SystemExit("--days must be >= 1.")

    date_from, date_to = date_range(args.days)
    ctx = AuditContext(date_from=date_from, date_to=date_to, days=args.days,
                       min_spend=args.min_spend)

    client = build_client(args.login_customer_id)
    findings = run_audit(client, customer_id, ctx)

    if args.format == "markdown":
        report = render_markdown(sort_findings(findings), customer_id, ctx)
    elif args.format == "json":
        report = render_json(findings, customer_id, ctx)
    else:
        report = render_text(findings, customer_id, ctx)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        logger.info("Report written to %s", args.output)
    else:
        print(report)

    # Exit 1 when something critical was found — useful in CI / cron.
    return 1 if summarize(findings)[CRITICAL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
