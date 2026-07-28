# Write layer — creating campaigns safely

This is the part the official MCP cannot do. `create_campaign.py` reads a YAML
file you control and builds a complete Search campaign through the Google Ads
API: budget, campaign, geo/language criteria, ad group, exact keywords,
negatives, a Responsive Search Ad, and assets.

Two rules are baked in and cannot be turned off accidentally:

1. **Everything is created `PAUSED`.** Nothing spends until *you* enable it in
   the Google Ads UI. Going live in code requires the explicit, discouraged
   `--enable` flag (see below), and even that only flips the new campaign's
   status — it never touches billing.
2. **You must pick a mode.** The script refuses to run without exactly one of
   `--validate-only`, `--dry-run`, or `--live`. There is no "default" that
   writes.

---

## The workflow

Always walk the three steps in order. Each is a superset of the previous one.

```
--validate-only   →   --dry-run   →   --live
(offline, no auth)    (reads only)     (writes, PAUSED)
```

### 1. `--validate-only` (offline)

```bash
python src/write_layer/create_campaign.py \
  --config config.yaml --validate-only
```

* Parses your YAML and checks structure.
* Enforces every character limit (headlines ≤30, descriptions ≤90, callouts
  ≤25, etc.) and minimum counts (≥3 headlines, ≥2 descriptions).
* Validates structured-snippet headers against the allowed list.
* **Needs no credentials and no network.** This is what runs in CI and what you
  run constantly while editing copy.

If anything is too long or missing, it prints every problem at once and exits
non-zero. Fix them before moving on.

### 2. `--dry-run` (reads the account, writes nothing)

```bash
python src/write_layer/create_campaign.py \
  --config config.yaml --dry-run
```

Everything from validate-only, **plus** live read calls:

* Authenticates with your ADC + developer token.
* Confirms the account's currency matches `account.currency_check` and aborts on
  a mismatch (a wrong-currency budget is a costly mistake).
* Resolves your `geo.target` string to a real geo target constant.
* Resolves your `language` to a language constant.
* Reports whether a campaign of the same name already exists.

It does **not** create anything. This is the last checkpoint before writing.

### 3. `--live` (creates everything, PAUSED)

```bash
python src/write_layer/create_campaign.py \
  --config config.yaml --live
```

Builds, in order: budget → campaign → geo + language criteria → ad group →
keywords + negatives → RSA → assets (call, sitelinks, callouts, structured
snippets). The campaign and ad group come out **paused**. You review them in the
UI, attach conversions (see [conversions.md](conversions.md)), then enable when
ready.

---

## Every flag

| Flag | Mode | Effect |
|---|---|---|
| `--config PATH` | required | Path to your campaign YAML. |
| `--validate-only` | mode | Offline validation only. No auth, no network. |
| `--dry-run` | mode | Validate + read the account. Writes nothing. |
| `--live` | mode | Create the campaign and all children, paused. |
| `--enable` | modifier | **Discouraged.** With `--live`, create `ENABLED` instead of `PAUSED`. Still does not change billing, but the campaign can serve once the account is active. Prefer enabling manually in the UI. |
| `--replace` | modifier | With `--live`, REMOVE an existing campaign of the same name before creating. Opt-in only; without it, a name clash is reported, not overwritten. |
| `--allow-exemptions` | modifier | Permit best-effort policy-exemption retries for restricted categories. See [policies.md](policies.md). Never bypasses prohibited content. |
| `--verbose` | modifier | Debug logging. |

Exactly one mode is required. Modifiers are optional and only meaningful with
`--live` (except `--verbose`).

---

## The config file

Start from [`config.example.yaml`](../config.example.yaml) — it documents every
field inline. Copy it to a private `config.yaml` (which `.gitignore` keeps out
of the repo) and fill in your values.

Required sections, at a glance:

* `account.customer_id` and `account.currency_check`
* `campaign.name`, `daily_budget`, `bidding`, `network`, `geo.target`,
  `geo.mode`, `language`
* `ad_group.name`, `keywords_exact`
* `rsa.final_url`, `rsa.headlines` (≥3), `rsa.descriptions` (≥2)

`assets` (call, sitelinks, callouts, structured snippets) are optional; if
present they are validated and linked to the campaign.

A complete worked example lives in
[`examples/search-campaign.yaml`](../examples/search-campaign.yaml).

---

## Safety model in one paragraph

The script cannot start spend. It creates paused entities, and the only thing
that begins serving is a human clicking *Enable* in the UI on an account that is
already activated and billed. `--enable` exists for automation that genuinely
needs it, but it is documented as discouraged precisely because the safe path —
create paused, review, enable by hand — costs you nothing and catches mistakes.
The currency guard, the mandatory mode selection, and the no-silent-truncation
validators are all there to make the expensive errors impossible to make by
accident.

---

## Required recent API field

The Google Ads API now **requires** every new campaign to declare its EU
political-advertising status. The script sets
`contains_eu_political_advertising = DOES_NOT_CONTAIN` automatically. If you are
in fact running EU political ads, that is a regulated category with its own
verification process — see [policies.md](policies.md). Without this declaration,
recent API versions reject campaign creation outright.
