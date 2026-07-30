# google-ads-mcp-plus

**Run your Google Ads account from Claude Code. Find wasted spend, fix it, and
build campaigns — in plain language, on your own machine.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Tests](https://github.com/monsieurgoodmood/google-ads-mcp-plus/actions/workflows/tests.yml/badge.svg)](https://github.com/monsieurgoodmood/google-ads-mcp-plus/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

```bash
pipx install git+https://github.com/monsieurgoodmood/google-ads-mcp-plus.git

claude mcp add google-ads-plus \
  --env GOOGLE_ADS_DEVELOPER_TOKEN=your_token \
  --env GOOGLE_ADS_ALLOWED_CUSTOMERS=1234567890 \
  -- google-ads-mcp-plus
```

Then just ask.

---

## What it finds

Real output, first run, on a live account (figures redacted):

```
GOOGLE ADS AUDIT — account 123456****
Window: 30 days
Findings: 3 critical, 1 warning, 4 info

[CRITICAL] search terms
           32 search term(s) spent 874.50 EUR with no conversions.
           Review as negative keyword candidates.

[CRITICAL] FR | Search | <campaign>
           Losing 16.6% of impressions to BUDGET. Converting campaign —
           raising budget likely buys more conversions.

[WARNING]  responsive search ads
           1 RSA(s) are weak (fewer than 8 headlines / 3 descriptions).

[INFO]     change history
           12 change(s) in the last 30 days, by: <user>.
```

That took one command. **13 read-only checks**, no configuration.

---

## Then ask it to fix things

> *"add the wasteful search terms as negatives"*

Claude returns a **preview** — the exact list, and a confirmation token. Nothing
has changed. You read it. If it's right, you confirm, and only then is anything
written.

> *"which campaigns are budget-limited but converting?"*
> *"create a Performance Max campaign for this landing page, 20€/day"*
> *"who changed what in this account last month?"*
> *"pause the campaign that's spending with no conversions"*

---

## Why it's safe to point an LLM at a live ad account

A model driving real spend is riskier than a human typing a command: it can
misread intent, and account content (campaign names, **search terms written by
strangers**) enters its context as text. That's a prompt-injection surface.

So the server doesn't trust the model. Five layers, all enforced in code:

| Layer | Effect |
|---|---|
| **Account allowlist** | Any customer ID not in `GOOGLE_ADS_ALLOWED_CUSTOMERS` is refused. Empty list = nothing reachable. |
| **Writes off by default** | Mutations need an explicit opt-in. Setting it *without* an allowlist stays read-only. |
| **Two-phase commit** | Every write returns a preview + token first. The token is fingerprinted to the parameters, single-use, and expires in 10 minutes — a token issued to raise a budget to €22 cannot be replayed to set €2200. |
| **Hard numeric limits** | Budget ceiling and max change %, checked in code. `nan`, `inf` and negatives are refused rather than silently disabling the guard. |
| **Mutation log** | Every executed write appended to JSONL with before/after values. |

Campaigns are always created **PAUSED**.

These aren't claims — the safety layer was audited adversarially (12 bypass
attempts, all refused) and the failures found were fixed. Details in
[docs/mcp-server.md](docs/mcp-server.md).

> **This does not make an LLM safe to run unattended on a large account.** It
> makes mistakes bounded and reversible. Start read-only, on one account, with a
> ceiling you'd tolerate losing in a day.

---

## Nothing is hosted. Nothing is ours.

No server, no backend, no account to create, no usage limit — there's nothing to
limit. The code runs on your laptop with your credentials, and the only network
calls go straight from your machine to Google's API.

No telemetry, no phone-home, no analytics. **Nobody else sees your data,
including the author.** All ad spend, all API usage, and all consequences are
yours.

That's the difference from hosted third-party MCPs, which ask you to hand your
account keys to someone else's server — a real trust and data-residency
decision, and often a non-starter for client work.

---

## The 13 tools

**Read — always available**

| Tool | What it does |
|---|---|
| `server_status` | Current mode, allowlist, limits. Ask for this first. |
| `list_accounts` | Accounts your credentials reach, marking which are allowlisted. |
| `run_audit` | The 13 checks, as JSON. |
| `list_campaigns` | Campaigns with budget, status, spend, conversions. |
| `gaql_query` | Any read-only GAQL SELECT. Non-SELECT refused. |
| `validate_ad_copy` / `validate_pmax_assets` | Character limits, offline — no account needed. |

**Write — opt-in, two-phase**

| Tool | Notes |
|---|---|
| `update_campaign_budget` | Bounded by ceiling and max-change %. |
| `set_campaign_status` | Pause or enable. Enabling warns that spend starts. |
| `add_negative_keywords` | Per-campaign negatives. Safest write: spend can only go down. |
| `apply_negative_keyword_list` | **Shared** negative list — one edit updates every linked campaign. Idempotent. |
| `create_shopping_campaign` | Standard Shopping: budget, campaign, ad group, product ad, and an exhaustive listing group tree. Created PAUSED. |
| `create_performance_max_campaign` | One atomic mutate. The preview runs the API's own `validate_only`, so real API errors surface before anything exists. Created PAUSED. |

### The 13 audit checks

Conversion tracking (goal-based **and** legacy) · campaigns spending with zero
conversions · budget-lost impression share · rank-lost impression share ·
wasteful search terms · low Quality Score keywords · weak RSAs · disapproved ads
· missing negatives · missing sitelinks · single-ad ad groups · auto-tagging
disabled · recent change history.

Text, Markdown or JSON output. **Exit code 1 on critical findings**, so it works
as a cron monitor. Full reference: [docs/audit.md](docs/audit.md).

---

## Scope — what it does and doesn't do

**Read is unlimited.** GAQL reaches every readable resource: campaigns, keywords,
ads, assets, audiences, conversions, search terms, Quality Score, change
history. If you can write the query, you can read it.

**Write is deliberately narrow.** Every additional path multiplies the surface
for expensive mistakes in a tool that spends real money.

| Area | Supported | Not yet |
|---|---|---|
| Campaign type | **Search** (CLI), **Performance Max** and **Standard Shopping** (MCP tools) | Display, Video, Demand Gen, App |
| Operation | Create; update budgets, pause/enable, add negatives | Editing existing ads, bulk restructuring |
| Bidding | Search: max clicks, manual CPC. PMax: max conversions / conversion value, optional tCPA or tROAS | Changing an existing campaign's strategy, portfolio strategies |
| Targeting | Geo, language, ad schedule, negatives | Audiences, remarketing, Customer Match, demographics, devices |
| Assets | Sitelinks, callouts, structured snippets, call, price, promotion (reused by ID) | Uploading new images |

Extensions welcome — see [Contributing](#contributing) — provided they keep the
safety model intact.

---

## Setup

**Prerequisites:** Python 3.10+, a Google Cloud project with the Google Ads API
enabled, **your own OAuth Desktop client** (the default gcloud client is blocked
for the `adwords` scope), and a developer token with **Basic** access (a
test-only token cannot touch production accounts).

The OAuth setup has real, non-obvious traps: the API Center only exists on
**manager (MCC)** accounts, `--no-browser` prints a *second command* rather than
a link, and — the one that bites everyone — an OAuth consent screen left in
**Testing** expires your refresh token **every 7 days**. All of it is documented
step by step in
**[docs/setup-oauth.md](docs/setup-oauth.md)**. Read that first; it will save you
an afternoon.

```bash
gcloud auth application-default login \
  --client-id-file=CLIENT.json \
  --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform \
  --no-browser

export GOOGLE_ADS_DEVELOPER_TOKEN=YOUR_DEVELOPER_TOKEN
```

### Configuration

| Variable | Required | Purpose |
|---|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | yes | Your developer token. |
| `GOOGLE_ADS_ALLOWED_CUSTOMERS` | yes | Comma-separated IDs this server may touch. |
| `GOOGLE_ADS_MCP_ENABLE_WRITES` | no | `true` to allow mutations. Default: read-only. |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | if MCC | Manager account ID. |
| `GOOGLE_ADS_MAX_DAILY_BUDGET` | no | Ceiling for any budget set here. Default 100. |
| `GOOGLE_ADS_MAX_BUDGET_CHANGE_PCT` | no | Largest single change. Default 50. |
| `GOOGLE_ADS_MUTATION_LOG` | no | JSONL log path. Default `mutations.jsonl`. |

Set the ceiling **above** your existing budgets — below them, this server can
never adjust those campaigns.

### Other MCP clients

Works with any MCP client (Claude Desktop, Cursor, Gemini CLI). Config examples
in [docs/mcp-server.md](docs/mcp-server.md).

### Command line

Three commands ship with the package, for people who prefer a terminal:

```bash
google-ads-plus-audit --customer-id 1234567890 --days 90 --format markdown --output audit.md
google-ads-plus-campaign --config config.yaml --validate-only   # then --dry-run, then --live
google-ads-mcp-plus                                             # the MCP server
```

⚠️ The Search-campaign CLI does **not** share the server's safety model: no
allowlist, no ceiling, no confirmation token, no log. See
[docs/write-layer.md](docs/write-layer.md).

---

## Before you enable anything

**Never put a campaign live without conversion tracking** — that's blind spend.
Link GA4 to Google Ads, import your key events, make the real goal biddable, and
turn on auto-tagging: [docs/conversions.md](docs/conversions.md).

Some categories are restricted (Local Services, etc.) and need advertiser
verification before serving: [docs/policies.md](docs/policies.md). This project
does not help with deceptive content or policy circumvention.

---

## Tests

90 tests, fully offline — no API, no credentials:

```bash
pip install -e ".[dev]" && pytest -q
```

---

## Documentation

| Guide | Contents |
|---|---|
| [setup-oauth.md](docs/setup-oauth.md) | Credentials, end to end, with the real traps |
| [mcp-server.md](docs/mcp-server.md) | Tools, safety model, client config |
| [audit.md](docs/audit.md) | The 13 checks, thresholds, adding your own |
| [write-layer.md](docs/write-layer.md) | Search campaign CLI, every flag |
| [conversions.md](docs/conversions.md) | GA4 linking, auto-tagging |
| [policies.md](docs/policies.md) | Restricted categories, exemptions, EU political ads |
| [read-mcp.md](docs/read-mcp.md) | Google's official read-only MCP |
| [CLAUDE.md](CLAUDE.md) | Operating guide the agent reads before acting |

---

## Disclaimer

**This is NOT an officially supported Google product.** It is a community
project. It complements Google's official read-only
[`googleads/google-ads-mcp`](https://github.com/googleads/google-ads-mcp) and
uses the Google Ads API Python client library — both Google's work, Apache-2.0.
This project is independent and not affiliated with or endorsed by Google.

Use at your own risk. You are responsible for every campaign, every euro spent,
and for complying with Google Ads policies and applicable law.

## License & attribution

Apache-2.0 — use, modify, distribute, and sell products built on this, including
commercially and closed-source. The one obligation: keep the copyright headers
and include the [NOTICE](./NOTICE) file when redistributing.

Copyright 2026 ByteBerry Analytics LLC — [@monsieurgoodmood](https://github.com/monsieurgoodmood).
A ⭐ is appreciated, never required.

## Contributing

Issues and PRs welcome. Most useful: more campaign types (Shopping, Display),
bidding-strategy tools, additional audit checks, doc translations.

Two ground rules: **never commit credentials**, and **keep the safety model
intact** — no PR that makes writing easier at the cost of the guardrails.
