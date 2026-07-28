# Policies, restricted categories & exemptions

Google Ads enforces content and category policies at creation time and again at
serving time. This page explains how this tool interacts with that — and, just
as importantly, what it deliberately will not do.

> This project helps you run **legitimate** advertising correctly. It does not
> help with deceptive content, and its exemption handling never bypasses
> prohibited material. If your use case needs circumvention, this is the wrong
> tool.

---

## Restricted categories

Some perfectly legal businesses fall into **restricted categories** that need
extra verification before ads can serve. A common example is **Local Services**
— locksmiths, plumbers, garage-door, and similar trades. Ads in these
categories can be created but may be **limited** or **not eligible to serve**
until the advertiser completes verification.

Key point: **creating the campaign is not the same as being allowed to serve
it.** The API may accept your campaign while Google still requires
**advertiser verification** (identity and sometimes business/licensing checks)
before impressions are delivered. The tool can build the campaign; only Google's
verification process clears it to run.

If your category requires verification, complete it in the Google Ads UI. No API
flag substitutes for it.

---

## How policy exemptions work here

When you create keywords or ads, the API can return **policy findings**. Some
are **exemptible** (the system marks them as eligible for an exemption request);
others — genuinely **prohibited** content — are not.

This tool's behaviour:

* By default, a policy finding causes the operation to surface the problem.
* With the explicit `--allow-exemptions` flag, the script makes a
  **best-effort** retry:
  * For **keywords/criteria**, it re-submits with the exemptible policy
    violation keys the API reported.
  * For **ads (RSA)**, it re-submits marking the reported ignorable policy
    topics.
* It **never** attempts to exempt prohibited content. Exemptions apply only to
  findings the API itself flags as exemptible.

This exemption path is **API-version-dependent and best-effort** — the exact
fields and behaviour have shifted across Google Ads API versions, so treat it as
a convenience that may need adjustment, not a guarantee. When in doubt, resolve
the underlying policy issue rather than relying on an exemption.

`--allow-exemptions` is opt-in for a reason: requesting an exemption is a
statement that your ad legitimately fits an allowed use of a restricted area. Do
not use it to push content that does not.

---

## No deceptive content, no abusive circumvention

The validators in this repo stop silent truncation and malformed assets; they do
not, and cannot, vet your claims for honesty. That part is on you. Two lines this
project will not cross:

* **No deceptive content.** Misrepresenting who you are, what you sell, or what a
  click leads to violates Google policy and, often, the law.
* **No abusive circumvention.** Techniques designed to hide an ad's true content
  or destination from Google's review (cloaking, misleading redirects, and the
  like) are out of scope and unsupported.

Staying inside policy is not just compliance theatre — circumvention gets
accounts suspended, which is far more expensive than doing it correctly.

---

## EU political advertising (required declaration)

Recent Google Ads API versions **require** every new campaign to declare whether
it contains **EU political advertising**. This tool sets the declaration to
`DOES_NOT_CONTAIN` automatically, which is correct for ordinary commercial
campaigns.

Two things to know:

1. **If you genuinely run EU political ads**, that is a regulated category with
   its own transparency and verification requirements under EU rules. The
   automatic `DOES_NOT_CONTAIN` default would be inaccurate for you, and you must
   handle that category's specific obligations — this tool does not.
2. **Account-wide blocking.** Since this requirement took effect, an account
   that has *any* campaign without the declaration can have **all** campaign
   mutations blocked until the declaration is resolved. Setting it correctly on
   every campaign — which this tool does for the campaigns it creates — keeps you
   on the right side of that.

Reference:
<https://developers.google.com/google-ads/api/docs/campaigns/eu-political-ads>
