# OAuth & credentials setup (the guide that was missing)

This is the part that actually blocks people. Follow it in order. Every step
here corresponds to a real failure people hit.

> None of these steps put a secret into this repository. ADC files, OAuth client
> JSON, and your developer token all live **outside** the repo and are covered
> by `.gitignore` if they ever land in the working directory.

---

## 0. What you are building

For **write** access (the script in this repo) you authenticate with
**Application Default Credentials (ADC)** plus a **developer token**:

* **ADC** = a user OAuth credential stored locally by gcloud, scoped to the
  Google Ads API. The client library finds it automatically.
* **Developer token** = a 22-character string from the Google Ads API Center,
  passed via the `GOOGLE_ADS_DEVELOPER_TOKEN` environment variable.

Service accounts do **not** work for plain Google Ads access — they cannot be
added as users on a Google Ads account, so they have zero access to campaigns.
Use user OAuth with your own client (below).

---

## 1. Create your OWN OAuth Client ID (this is the #1 blocker)

The default OAuth client that ships with `gcloud` is **blocked for the
`adwords` scope**. If you try to generate ADC for Google Ads with the built-in
client you will be refused. You must create your own client:

1. Go to **Google Cloud Console → APIs & Services → Credentials**.
2. **Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Download the JSON. Call it e.g. `CLIENT.json` (keep it out of the repo).

You will pass this with `--client-id-file=CLIENT.json` later.

## 2. Enable the Google Ads API on the project

**APIs & Services → Library →** search "Google Ads API" → **Enable**. (Direct:
`https://console.cloud.google.com/apis/library/googleads.googleapis.com`.)

## 3. Configure the OAuth consent screen + add yourself as a test user

In **APIs & Services → OAuth consent screen**:

* Fill in the minimum app info.
* Under **Test users**, add the Google account email you will authenticate with.

If you skip this you get **"app blocked / access denied"** at the consent step,
because an app in "Testing" only allows listed test users.

## 4. Generate ADC with the right scopes

Download your `CLIENT.json` first, then:

```bash
gcloud auth application-default login \
  --client-id-file=CLIENT.json \
  --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform \
  --no-browser
```

Two traps here:

* ⚠️ With `--client-id-file`, the correct flag is **`--no-browser`**, *not*
  `--no-launch-browser`. (Different gcloud code paths; the latter errors out
  with a custom client.)
* ⚠️ **WSL / headless / agent shells.** Run this in a **real interactive
  terminal** so you can paste the returned authorization code back. In a
  non-interactive shell you get `EOFError`. If a Windows browser opens, the
  local server on a random port often captures the code automatically and you
  do not need to paste anything.

This writes `application_default_credentials.json` to the standard gcloud
location. The client library will find it on its own.

## 5. Set the quota project

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

If prompted, enable the Cloud Resource Manager API
(`cloudresourcemanager.googleapis.com`) and re-run.

## 6. Get a developer token (and the right access level)

* Get it from the **Google Ads API Center** under your **manager (MCC)
  account**: `Tools → API Center`.
* **Access levels matter.** A token approved for **test accounts only** returns
  `"The developer token is only approved for use with test accounts"` when you
  query a production account. You need at least **Basic** (or **Explorer**)
  access. New tokens are sometimes auto-upgraded to Explorer; if not, apply in
  the API Center. Approval can take a few business days — use a **test account**
  while you wait.
* Export it (never commit it):

```bash
export GOOGLE_ADS_DEVELOPER_TOKEN=YOUR_DEVELOPER_TOKEN
```

> If you reach the ad account **through a manager (MCC)**, also set the manager
> ID — `login_customer_id` in `config.yaml` (digits only, no dashes). Without
> it the API cannot resolve accounts under the manager.

## 7. The Google Ads account itself must be ready

* A brand-new account must be **activated** (billing / onboarding complete).
  Until then the API returns errors like *"account not yet enabled / customer
  not enabled."*
* ⚠️ **Currency is fixed at account creation and can never be changed.** Choose
  it correctly up front. This repo's `currency_check` guard refuses to run if
  the account currency differs from what your config expects — a cheap way to
  catch "wrong account" mistakes.

---

## Quick verification

Once the above is done, confirm read access end-to-end with the official MCP
(see [`read-mcp.md`](read-mcp.md)) or with a one-line GAQL call, then run this
repo's dry run:

```bash
python src/write_layer/create_campaign.py --config config.yaml --dry-run
```

A successful dry run means: content validated, account reachable, currency
matches, and geo + language resolved — without writing anything.

## Common errors → cause

| Symptom | Likely cause |
| --- | --- |
| Refused on the `adwords` scope | Using the default gcloud client — create your own Desktop client (step 1). |
| `access blocked` / consent denied | Your email is not a **test user** (step 3). |
| `EOFError` during login | Non-interactive shell — run in a real terminal (step 4). |
| `developer token only approved for test accounts` | Token lacks Basic/Explorer access (step 6). |
| `customer not enabled` | Google Ads account not activated yet (step 7). |
| Wrong/empty results under an MCC | `login_customer_id` not set (step 6). |
| `The required field was not present` on campaign create | EU political advertising declaration missing — handled by this script; see [`policies.md`](policies.md). |
