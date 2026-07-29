# Examples

## `search-campaign.yaml`

A complete, generic worked example: an English-language Search campaign for a
plumber in Austin, Texas. It is **placeholder data** — the phone number is fake
and the final URL points at `example.com`. It exists to show every section of a
valid config filled in correctly, including:

* a realistic geo + language setup (`presence` mode),
* an exact-match ad group with negatives,
* a Responsive Search Ad with enough headlines and descriptions to pass
  validation,
* sitelinks shown in **both** supported forms (plain string and
  `text`/`description`/`url` object),
* a structured-snippet header drawn from Google's allowed list,
* a restricted-category note (the plumbing trade falls under **Local Services**,
  which may require advertiser verification before serving — see
  [`../docs/policies.md`](../docs/policies.md)).

### Try it offline

You can validate it right now, with no credentials and no network:

```bash
google-ads-plus-campaign --config search-campaign.yaml --validate-only
```

It should report that the config is OK.

### Use it as a starting point

1. Copy it to a private config outside the examples folder:

   ```bash
   cp search-campaign.yaml ../config.yaml
   ```

   (`.gitignore` keeps a top-level `config.yaml` out of the repo; the
   `examples/*.yaml` files are intentionally tracked.)
2. Replace the placeholders — `account.customer_id`, the geo target, all ad
   copy, the real final URL, phone, and sitelink URLs.
3. Walk the workflow: `--validate-only` → `--dry-run` → `--live`, as described in
   [`../docs/write-layer.md`](../docs/write-layer.md).

Everything is created **paused**. Attach conversions
([`../docs/conversions.md`](../docs/conversions.md)) before you enable it.
