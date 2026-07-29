# google-ads-mcp-plus

**Drive Google Ads from Claude: an MCP server with read, audit, and guarded
write tools — allowlisted accounts, two-phase confirmation, paused-by-default,
full docs and examples.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Status: experimental](https://img.shields.io/badge/status-experimental-orange)

> ⚠️ **Disclaimer.** This is **NOT** an officially supported Google product. It
> is a community, experimental project. It wraps Google's official, read-only
> Google Ads MCP server and adds an independent Python write layer that calls
> the Google Ads API directly. **Use at your own risk.** You are responsible for
> every campaign, every euro/dollar spent, and for complying with Google Ads
> policies and applicable law.

---

## 1. The problem this solves

Google's **official Google Ads MCP server** (`googleads/google-ads-mcp`,
released April 2026) is **strictly read-only**. It exposes three tools —
`list_accessible_customers`, `search` (GAQL), and `get_resource_metadata` — and
"cannot modify bids, pause campaigns, or create new assets." Great for
reporting and diagnostics; useless the moment you want an agent to actually
*create* a campaign.

The hosted, third-party MCPs that *do* offer write access ask you to hand your
account keys to someone else's server. That is a real trust and data-residency
decision, not always acceptable for client work.

**`google-ads-mcp-plus`** keeps the two concerns separate and local:

* **Read** → use the official read-only MCP (this repo documents and points to
  it; see [`docs/read-mcp.md`](docs/read-mcp.md)).
* **Write** → a small, auditable, config-driven Python script that runs on
  *your* machine with *your* credentials and creates campaigns **paused by
  default** ([`docs/write-layer.md`](docs/write-layer.md)).

## 2. Features

**Read (official MCP):** GAQL queries, account discovery, resource metadata —
all read-only, credentials stay on your machine.

**MCP server (this repo) — the main interface:**
* Connect Claude Code (or any MCP client) and work in plain language: audit an
  account, list campaigns, run GAQL, change budgets, pause/enable, add negatives.
* **Writes are off by default** and require an explicit account allowlist.
* **Two-phase commit:** every write returns a preview and a token first —
  nothing changes until you confirm. Tokens are fingerprinted, single-use, and
  expire in 10 minutes.
* Hard budget ceilings enforced in code, plus an append-only mutation log.
* Setup and the full tool list: [`docs/mcp-server.md`](docs/mcp-server.md).

**Audit (this repo, read-only):**
* `audit_account.py` runs 12 checks over any account and reports what is
  costing you money: missing/secondary conversion actions, campaigns spending
  with zero conversions, budget- and rank-lost impression share, wasteful
  search terms, low Quality Score keywords, weak RSAs, disapproved ads, missing
  negatives and sitelinks.
* Text, Markdown, or JSON output. Exit code 1 on critical findings, so it works
  as a cron/CI monitor.
* **Never mutates anything** — GAQL queries only. See [`docs/audit.md`](docs/audit.md).

**Write (this repo):**
* One YAML config → budget → campaign → criteria (geo *presence* + language) →
  ad group → exact keywords (+ negatives) → Responsive Search Ad → assets
  (call, sitelinks, callouts, structured snippets).
* **Paused-by-default.** Nothing serves until you un-pause it by hand (or pass
  the discouraged `--enable`).
* **`--validate-only`** (offline, no credentials) and **`--dry-run`** (checks
  the account, resolves geo + language, writes nothing) before any **`--live`**.
* **Strict text validation** — no headline/description/asset is ever silently
  truncated; the run stops and tells you the exact field and overflow.
* Handles the **EU political advertising declaration** the API now requires.
* Best-effort **policy-exemption** handling for restricted categories
  (e.g. Local Services).
* Idempotent re-runs via an opt-in `--replace` (never destructive by surprise).

## 2b. Scope — what this does and does not do

Be clear about this before you invest time.

**Audit is packaged.** This repo ships an audit module with 12 read-only
checks (see [`docs/audit.md`](docs/audit.md)), extensible by adding one
function. Beyond those, write your own GAQL.

**Read is unlimited.** The official MCP exposes GAQL, so every readable
resource is reachable: campaigns, ad groups, keywords, ads, assets, audiences,
conversions, search terms, Quality Score, change history, recommendations. If
you can write the query, you can read it.

**Write is deliberately narrow.** The write layer creates **one new Search
campaign** from a config file. That is its entire job.

| Area | Supported | Not supported |
|---|---|---|
| Campaign type | **Search** (CLI) and **Performance Max** (MCP tool) | Display, Shopping, Video, Demand Gen, App |
| Operation | Create; via MCP: update budgets, pause/enable, add negatives | Editing existing ads, bulk restructuring |
| Bidding | Search: `maximize_clicks`, `manual_cpc`. PMax: maximize conversions / conversion value, with optional tCPA or tROAS | Changing the strategy of an existing campaign, portfolio strategies |
| Keywords | Exact match + negatives | Phrase, positive broad, shared sets |
| Structure | One ad group, one RSA | Multiple ad groups or ads per run |
| Targeting | Geo + language | Audiences, remarketing, Customer Match, demographics, devices, ad schedule |
| Assets | Call, sitelinks, callouts, structured snippets | Images, logos, promotions, prices, lead forms, PMax asset groups |
| Other | — | Creating conversion actions, drafts/experiments, labels, bid adjustments |

This narrowness is a design choice, not an oversight. Every additional campaign
type multiplies the surface area for expensive mistakes in a tool that spends
real money. A small, well-tested write path beats a broad, shaky one.

Contributions extending this are welcome — see
[Contributing](#12-contributing) — provided they keep the safety model intact.

## 2c. Connect it to Claude Code

```bash
pipx install git+https://github.com/monsieurgoodmood/google-ads-mcp-plus.git

claude mcp add google-ads-plus \
  --env GOOGLE_ADS_DEVELOPER_TOKEN=your_token \
  --env GOOGLE_ADS_ALLOWED_CUSTOMERS=1234567890 \
  -- google-ads-mcp-plus
```

Then just ask: *"audit account 1234567890 over the last 60 days"*. Writes stay
disabled until you set `GOOGLE_ADS_MCP_ENABLE_WRITES=true`. Full guide: [`docs/mcp-server.md`](docs/mcp-server.md).

The repo ships a [`CLAUDE.md`](CLAUDE.md) that Claude Code reads automatically —
it explains every tool, the two-phase write flow, audit interpretation, and a
GAQL cookbook, so the agent knows how to drive the account safely without being
told each time.

## 2d. Audit an account from the CLI

Once credentials are set up ([`docs/setup-oauth.md`](docs/setup-oauth.md)):

```bash
google-ads-plus-audit --customer-id 1234567890
```

Client-ready Markdown report over 90 days:

```bash
google-ads-plus-audit --customer-id 1234567890 \
  --days 90 --format markdown --output audit.md
```

Full reference: [`docs/audit.md`](docs/audit.md).

## 3. Quick start

### Prerequisites
* Python 3.10+
* A Google Cloud project with the **Google Ads API enabled**
* Your **own** OAuth Client ID (Desktop type) — the default gcloud client is
  blocked for the `adwords` scope
* A **developer token** with at least Basic/Explorer access (a test-only token
  cannot touch production accounts)
* An **activated** Google Ads account (billing/onboarding complete)

The OAuth setup has real, non-obvious pitfalls. They are documented step by step
in **[`docs/setup-oauth.md`](docs/setup-oauth.md)** — read that first.

### Install
```bash
git clone https://github.com/monsieurgoodmood/google-ads-mcp-plus.git
cd google-ads-mcp-plus
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # write layer
pip install -r requirements-dev.txt      # to run the offline tests
```

### Credentials (summary — full guide in docs/setup-oauth.md)
```bash
# 1) Create your own OAuth Desktop client in Google Cloud, download CLIENT.json
# 2) Generate ADC with the adwords scope using YOUR client:
gcloud auth application-default login \
  --client-id-file=CLIENT.json \
  --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform \
  --no-browser
# 3) Export your developer token (never commit it):
export GOOGLE_ADS_DEVELOPER_TOKEN=YOUR_DEVELOPER_TOKEN
```

## 4. Read with the official MCP

Point your MCP host (Claude Code, Cursor, Gemini CLI, …) at Google's server:
```bash
claude mcp add google-ads-mcp -- \
  pipx run --spec git+https://github.com/googleads/google-ads-mcp.git google-ads-mcp
```
Full configuration (env vars, manager accounts) in
[`docs/read-mcp.md`](docs/read-mcp.md).

## 5. Write a campaign (paused-by-default)

```bash
cp config.example.yaml config.yaml        # config.yaml is gitignored
# edit config.yaml with YOUR account, budget, keywords, ad copy…

# offline content check (no credentials):
google-ads-plus-campaign --config config.yaml --validate-only

# dry run (reads the account, resolves geo + language, writes nothing):
google-ads-plus-campaign --config config.yaml --dry-run

# create everything, PAUSED:
google-ads-plus-campaign --config config.yaml --live
```
Then open the Google Ads UI, review, and **un-pause when you are ready**. See
[`docs/write-layer.md`](docs/write-layer.md) for every flag.

## 6. Conversions & auto-tagging

Do not put a campaign live without conversion tracking — it is blind spend. Link
GA4 ↔ Google Ads, import your GA4 key events as **primary** conversions, and
enable auto-tagging: [`docs/conversions.md`](docs/conversions.md).

## 7. Policies & exemptions

Some categories are restricted (e.g. **Local Services** for locksmiths,
plumbers, garage-door, etc.) and may require **advertiser verification** before
serving. How exemptions work, and what this tool does and does not do, is in
[`docs/policies.md`](docs/policies.md). This project does not help with
deceptive content or abusive policy circumvention.

## 8. Security

* **No secrets in the repo.** Everything is a placeholder.
* A strict [`.gitignore`](.gitignore) excludes `.env`, ADC files, `*credentials*.json`,
  `client_secret*.json`, `google-ads.yaml`, and your private `config.yaml`.
* The developer token is read from an environment variable, never from a file in
  the repo.
* **Verify `.gitignore` before every `git add`.** When in doubt,
  `git status --ignored`.

## 9. Tests

The character-limit validators run fully offline (no API, no credentials):
```bash
pytest -q
```

## 10. Who pays for what

**Nothing here is a hosted service.** There is no server, no backend, no
account to create with us, and no usage limit — because there is nothing to
limit. You clone the repo and run the code on your own machine.

That means:

| Thing | Who provides it |
|---|---|
| This code | Free, Apache-2.0, forever. Clone, fork, use commercially. |
| Google Cloud project + OAuth client | **You** (free tier is sufficient). |
| Google Ads developer token | **You** (free, requested from your account). |
| Google Ads account + ad spend | **You**. Every euro/dollar is yours. |
| Infrastructure to run this | **You** — your laptop. |

The author hosts nothing and receives nothing. There is no telemetry, no
phone-home, no analytics: the only network calls this code makes are directly
from your machine to Google's API, with your credentials. Nobody else can see
your data, including the author.

---

## 11. License & attribution

Licensed under **[Apache-2.0](./LICENSE)** — one of the most permissive licenses
there is. You may use, modify, distribute, and sell products built on this,
including commercially and in closed-source work.

The one thing Apache-2.0 asks in return is **attribution**: if you redistribute
this code or a derivative of it, keep the copyright headers and include a copy
of the **[NOTICE](./NOTICE)** file. That is the whole obligation.

> **Author:** ByteBerry Analytics LLC —
> [@monsieurgoodmood](https://github.com/monsieurgoodmood)
> Copyright 2026. Originally published at
> `https://github.com/monsieurgoodmood/google-ads-mcp-plus`.

If this saved you time, a ⭐ on the repo or a link back is appreciated but never
required.

### Third-party components

This project runs alongside, and depends on, Google's official read-only
[`googleads/google-ads-mcp`](https://github.com/googleads/google-ads-mcp) and
the [Google Ads API Python client library](https://github.com/googleads/google-ads-python).
Those are Google's work, licensed Apache-2.0. This write layer is independent
and is **not** affiliated with or endorsed by Google. See [NOTICE](./NOTICE) for
the full list.

---

## 12. Contributing

Issues and pull requests welcome. Useful contributions: support for other
campaign types (Performance Max, Display), additional asset types, more
validators, translations of the docs.

Two ground rules: never commit credentials (check `git status` against
`.gitignore` before every commit), and keep paused-by-default intact — no PR
that makes writing easier at the cost of the safety model will be merged.
