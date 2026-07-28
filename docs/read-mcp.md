# Read access — the official Google Ads MCP

The **read** half of this project is not our code. It is Google's official
Google Ads MCP server, which you run as-is. This page explains how to install
it, point it at your account, and what it can and cannot do.

> The official server is read-only by design. It cannot create, update, or
> remove anything. That is exactly why the [write layer](write-layer.md) in this
> repo exists alongside it.

---

## What it is

* Repo: `https://github.com/googleads/google-ads-mcp`
* License: Apache-2.0
* Language: Python, distributed as a runnable package
* Built on the Google Ads API (v21 at time of writing)
* Exposes **three tools**, all read-only:
  * `list_accessible_customers` — the accounts your credentials can reach
  * `search` — run a GAQL query against an account
  * `get_resource_metadata` — describe resources/fields available to GAQL

Because everything is a query, the worst an MCP client can do through this
server is read your data. No mutate path exists.

---

## Prerequisites

You need the same two credentials the write layer uses:

1. **ADC** (Application Default Credentials) scoped to `adwords`.
2. A **developer token** from the Google Ads API Center.

Both are covered step by step in **[setup-oauth.md](setup-oauth.md)**. Do that
page first; the MCP will not authenticate without it.

You also need [`pipx`](https://pipx.pypa.io/) to run the server without a
manual clone:

```bash
python -m pip install --user pipx
python -m pipx ensurepath
```

---

## Run it

The official server can be launched directly from its Git repo with `pipx`:

```bash
pipx run --spec git+https://github.com/googleads/google-ads-mcp.git google-ads-mcp
```

It reads configuration from environment variables:

| Variable | Required | Purpose |
|---|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | yes | Your developer token. |
| `GOOGLE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`) | yes | The Cloud project that owns your OAuth client. |
| `GOOGLE_APPLICATION_CREDENTIALS` | usually | Path to your ADC JSON, if it is not in the default location. |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | if using an MCC | Manager (MCC) account ID, digits only, no dashes. |

If you generated ADC with `gcloud auth application-default login`, the file
already sits in the gcloud default path and the library finds it without
`GOOGLE_APPLICATION_CREDENTIALS`. Set the variable only when you store the file
elsewhere.

---

## Wire it into an MCP client

Any MCP-capable client (Claude Desktop, etc.) launches the server the same way:
as a command with environment variables. A typical client config entry looks
like this:

```json
{
  "mcpServers": {
    "google-ads": {
      "command": "pipx",
      "args": [
        "run",
        "--spec",
        "git+https://github.com/googleads/google-ads-mcp.git",
        "google-ads-mcp"
      ],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "YOUR_DEVELOPER_TOKEN",
        "GOOGLE_PROJECT_ID": "your-cloud-project-id",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890"
      }
    }
  }
}
```

Put **real** values only in your local client config, never in this repo.

---

## Using the three tools

A normal first session:

1. Call `list_accessible_customers` to confirm which accounts your credentials
   reach. If your account is missing here, the problem is access/linking, not
   the MCP.
2. Use `search` with a GAQL query against a specific customer ID. For example,
   to list enabled campaigns:

   ```sql
   SELECT campaign.id, campaign.name, campaign.status
   FROM campaign
   WHERE campaign.status = 'ENABLED'
   ORDER BY campaign.name
   ```

3. Use `get_resource_metadata` when you are unsure which fields or resources a
   GAQL query can select.

GAQL reference: <https://developers.google.com/google-ads/api/docs/query/overview>

---

## Manager (MCC) accounts

If you authenticate through a manager account, set
`GOOGLE_ADS_LOGIN_CUSTOMER_ID` to the **manager** ID and pass the **child**
account's ID as the customer you query. The login customer is the account you
act *through*; the queried customer is the account you act *on*.

---

## What read access cannot do

* It cannot create or change campaigns, budgets, ads, keywords, or assets.
* It cannot import conversions or change account settings.

For any of that, switch to the [write layer](write-layer.md) — a separate,
explicit, paused-by-default Python script, not an MCP tool.
