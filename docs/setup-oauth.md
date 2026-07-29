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

### What actually happens in the terminal

This is the part that confuses everyone, because `--no-browser` does **not**
print a link for you to open. It prints **a second gcloud command** that you
must run on a machine that *has* a browser. The exchange looks like this:

**1. Your headless/WSL terminal prints:**

```
You are authorizing client libraries without access to a web browser.
Please run the following command on a machine with a web browser and copy
its output back here:

    gcloud auth application-default login --remote-bootstrap="https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=...&scope=...&state=..."
```

**2. Copy that entire command** and run it on a machine with a browser
(Windows PowerShell, your Mac, anywhere with gcloud installed). It opens the
Google consent screen. Approve it.

**3. That second machine then prints a long URL** starting with
`https://localhost:8085/?state=...&code=4/0A...`

**4. Copy that whole `localhost` URL** and paste it back into the first
terminal, at the prompt:

```
Enter the output of the above command:
```

Press Enter. You should see `Credentials saved to file: [...]`.

> The URL you paste back **contains your authorization code**. Never share it,
> never commit it. It is single-use and expires quickly, but treat it as a
> secret.

### On WSL specifically

If gcloud is installed **inside** WSL, the Windows browser will often open
automatically and the flow completes by itself — no copy-paste needed. If you
have gcloud on both Windows and WSL, the simplest path is to run the whole
`gcloud auth application-default login` command **in WSL** and let it hand off
to the Windows browser.

### Other traps

* ⚠️ With `--client-id-file`, the correct flag is **`--no-browser`**, *not*
  `--no-launch-browser`. (Different gcloud code paths; the latter errors out
  with a custom client.)
* ⚠️ Run this in a **real interactive terminal**. In a non-interactive or agent
  shell you cannot paste the code back and you get `EOFError`.
* ⚠️ If you see `Error 400: redirect_uri_mismatch`, your OAuth client is not of
  type **Desktop app** (step 1). Recreate it with the right type.

This writes `application_default_credentials.json` to the standard gcloud
location (`~/.config/gcloud/` on Linux/WSL). The client library will find it on
its own — you do not need to set `GOOGLE_APPLICATION_CREDENTIALS`.

Verify it worked:

```bash
gcloud auth application-default print-access-token
```

If a token prints, ADC is in place.

## 5. Set the quota project

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

If prompted, enable the Cloud Resource Manager API
(`cloudresourcemanager.googleapis.com`) and re-run.

## 6. Get a developer token from Google Ads

### 6a. You need a MANAGER (MCC) account — this is the hidden prerequisite

**The API Center only exists on manager accounts.** If you look for it in a
regular Google Ads account, you will not find it, and nothing you do will make
it appear. This blocks a lot of people who assume any Ads account will do.

If you do not already have one, create a manager account at
<https://ads.google.com/home/tools/manager-accounts/>. It is free, takes a few
minutes, and does not require its own billing. You can then link your existing
ad account to it (Manager account → **Accounts → + → Link existing account**),
or simply use the manager account purely to hold the token.

### 6b. Find the API Center and apply

1. Sign in to your **manager** account at ads.google.com.
2. Go to **Admin → API Center** (in some UI versions: **Tools & Settings → Setup
   → API Center**).
3. You will be asked to complete an **API access application form**. Expect
   questions about:
   * your company name, website, and contact email,
   * how you intend to use the API (be specific and truthful — e.g. "managing
     Search campaigns for my own/clients' accounts via the Google Ads API"),
   * whether the tool is for internal use or distributed to third parties,
   * acceptance of the Google Ads API Terms.
4. Submit. Your token string is issued immediately, but its **access level** is
   what determines whether it actually works.

### 6c. Access levels — the thing that decides if it works

| Level | What it can do |
|---|---|
| **Test** | Only **test accounts**. Querying a real account returns `"The developer token is only approved for use with test accounts"`. |
| **Basic** | Real production accounts, with a daily operations cap. **This is what you need.** |
| **Standard** | Real accounts, higher limits. Apply later if you outgrow Basic. |

A newly issued token typically starts at **Test** level. You must apply for
**Basic** access from the same API Center page. **Approval is a manual review by
Google and can take several business days** — sometimes with follow-up questions
by email. Apply early; it is the long pole of this whole setup.

While you wait, you can develop against a **test account** (a special Google Ads
account that never spends real money). Create one from your manager account.

### 6d. Export it — never commit it

```bash
export GOOGLE_ADS_DEVELOPER_TOKEN=YOUR_DEVELOPER_TOKEN
```

To make it persistent, add that line to `~/.bashrc` or `~/.zshrc`. Do **not**
put it in any file inside this repository.

> If you reach the ad account **through a manager (MCC)**, also set the manager
> ID — `login_customer_id` in `config.yaml` (digits only, no dashes). The login
> customer is the account you act *through*; the customer ID in your config is
> the account you act *on*. Without it the API cannot resolve accounts under the
> manager.

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
google-ads-plus-campaign --config config.yaml --dry-run
```

A successful dry run means: content validated, account reachable, currency
matches, and geo + language resolved — without writing anything.

## Common errors → cause

| Symptom | Likely cause |
| --- | --- |
| Refused on the `adwords` scope | Using the default gcloud client — create your own Desktop client (step 1). |
| `access blocked` / consent denied | Your email is not a **test user** (step 3). |
| `EOFError` during login | Non-interactive shell — run in a real terminal (step 4). |
| `redirect_uri_mismatch` | OAuth client is not type **Desktop app** (step 1). |
| **Cannot find API Center anywhere** | You are in a regular Ads account. The API Center only exists on a **manager (MCC)** account (step 6a). |
| Login seems stuck after `--no-browser` | It is waiting for you to paste back the `localhost` URL produced by the second command (step 4). |
| `developer token only approved for test accounts` | Token lacks Basic/Explorer access (step 6). |
| `customer not enabled` | Google Ads account not activated yet (step 7). |
| Wrong/empty results under an MCC | `login_customer_id` not set (step 6). |
| `The required field was not present` on campaign create | EU political advertising declaration missing — handled by this script; see [`policies.md`](policies.md). |
