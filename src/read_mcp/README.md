# `read_mcp/` — the official read-only MCP

There is no custom code in this directory on purpose. The **read** half of this
project is Google's official Google Ads MCP server, run unmodified. This folder
just tells you where it is and how to point it at your account.

## What to run

```bash
pipx run --spec git+https://github.com/googleads/google-ads-mcp.git google-ads-mcp
```

* Upstream: <https://github.com/googleads/google-ads-mcp>
* License: Apache-2.0
* Read-only: three tools — `list_accessible_customers`, `search` (GAQL), and
  `get_resource_metadata`. No mutate path.

## What it needs

The same credentials as the write layer:

* **ADC** scoped to `adwords` (Application Default Credentials).
* A **developer token** via `GOOGLE_ADS_DEVELOPER_TOKEN`.
* `GOOGLE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`), and
  `GOOGLE_ADS_LOGIN_CUSTOMER_ID` if you go through a manager (MCC) account.

Set these as environment variables in your MCP client config — never in this
repo.

## What it can and cannot do

* **Can:** list accounts you can reach, run GAQL queries, describe resources.
* **Cannot:** create, update, or remove anything.

To create campaigns, use the [write layer](../write_layer/) instead.

## Full instructions

Credentials: [`../../docs/setup-oauth.md`](../../docs/setup-oauth.md)
Using the MCP: [`../../docs/read-mcp.md`](../../docs/read-mcp.md)
