# Auditing an account (read-only)

`audit_account.py` inspects a Google Ads account and reports what is costing you
money or hiding your data. It issues **only** GAQL `search` queries — it has no
mutate path at all, so it is safe to point at any production account.

```bash
google-ads-plus-audit --customer-id 1234567890
```

---

## What it checks

List them at any time, no credentials required:

```bash
google-ads-plus-audit --customer-id 0 --list-checks
```

| Check | Severity | What it catches |
|---|---|---|
| `account_overview` | info | Spend, conversions, clicks for the window. Flags **auto-tagging disabled** as critical. |
| `conversion_tracking` | critical | No enabled conversion action, or no biddable goal. Checks **goal-based** conversions (`customer_conversion_goal.biddability`) first and only falls back to the legacy `primary_for_goal` flag — checking only the legacy flag reports a false alarm on modern accounts. |
| `recent_changes` | info | Who changed what in the last 30 days, and from which interface. Usually the first question when performance moves. |
| `campaign_no_conversions` | critical | Enabled campaigns spending real money with zero conversions. |
| `budget_limited` | critical/warning | Impression share lost to budget ≥10%. Critical when the campaign converts. |
| `rank_lost` | warning | Impression share lost to ad rank ≥35% — bids or quality too low. |
| `wasteful_search_terms` | critical/warning | Search terms with spend and no conversions — negative keyword candidates. |
| `low_quality_keywords` | warning | Keywords with Quality Score ≤4 that are actually spending. |
| `ad_strength` | warning | RSAs rated Poor/Average, or with <8 headlines / <3 descriptions. |
| `disapproved_ads` | critical | Enabled ads that are disapproved or limited, silently not serving. |
| `missing_negatives` | warning | Search campaigns with no campaign-level negative keywords. |
| `missing_sitelinks` | info | Search campaigns with no sitelink assets. |
| `single_ad_group` | info | Ad groups running a single ad — nothing to rotate or compare. |

---

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--customer-id` | required | Account to audit. Dashes are stripped automatically. |
| `--login-customer-id` | — | Manager (MCC) ID, if you access the account through one. |
| `--days` | 30 | Lookback window. The window **ends yesterday** — today is partial and would make "no conversions" fire wrongly. |
| `--min-spend` | 10 | Ignore entities below this spend, in account currency. Raise it on large accounts to cut noise. |
| `--format` | text | `text`, `markdown`, or `json`. |
| `--output` | stdout | Write the report to a file. |
| `--list-checks` | — | List registered checks and exit. Works offline. |
| `--verbose` | — | Debug logging. |

### Examples

A client-ready Markdown report over 90 days:

```bash
google-ads-plus-audit \
  --customer-id 1234567890 --days 90 \
  --format markdown --output audit-client.md
```

Machine-readable output for your own tooling:

```bash
google-ads-plus-audit \
  --customer-id 1234567890 --format json --output audit.json
```

Through a manager account:

```bash
google-ads-plus-audit \
  --customer-id 1234567890 --login-customer-id 9876543210
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Ran successfully, no critical findings. |
| `1` | Ran successfully, **at least one critical finding**. |
| `2` | Bad arguments / missing credentials. |

Exit code 1 makes this usable in cron or CI as a monitor: run it nightly and
alert when it returns non-zero.

---

## Adding your own check

The design goal is that a new audit is one function, nothing else.

```python
def check_my_thing(client, customer_id, ctx) -> List[Finding]:
    """One-line docstring — this shows up in --list-checks."""
    q = f"""
        SELECT campaign.name, metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{ctx.date_from}' AND '{ctx.date_to}'
    """
    out = []
    for row in run_query(client, customer_id, q):
        if some_condition:
            out.append(Finding(
                check="my_thing",
                severity=WARNING,
                entity=row.campaign.name,
                message="What is wrong and what to do about it.",
                detail={"anything": "useful"},
            ))
    return out
```

Then add it to the `CHECKS` list. That is the whole integration.

Two conventions worth keeping:

* **Never mutate.** Only `run_query`. A check that writes breaks the guarantee
  this whole module rests on.
* **A failing check must not kill the audit.** The runner already catches
  exceptions per check and turns them into an `info` finding, so a GAQL typo
  degrades one result instead of the whole report.

---

## Interpreting results honestly

The thresholds (10% budget loss, QS ≤4, 35% rank loss) are **defaults, not
verdicts**. A campaign losing impression share to budget is only a problem if it
converts profitably. A Quality Score of 4 on a genuinely competitive commercial
term may be unavoidable. Read the findings as questions worth investigating, not
as instructions.

The one exception is `conversion_tracking`: if nothing is Primary, that is not a
matter of interpretation — bidding truly has nothing to optimise toward.
