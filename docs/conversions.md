# Conversions & auto-tagging

A campaign without conversion tracking is blind spend. Before you enable
anything this tool creates, make sure Google Ads can actually see what success
looks like. This page is the short, correct checklist.

> The write layer never enables a campaign for you. This page is the work you do
> in the Google Ads and GA4 interfaces *before* you flip a paused campaign on.

---

## 1. Link GA4 to Google Ads

In **GA4 → Admin → Product links → Google Ads links**, link the GA4 property to
your Google Ads account. You need edit access on both sides.

This link is what lets you pull GA4 events into Google Ads as conversions, and
what lets GA4 attribute sessions to your ad clicks.

---

## 2. Import GA4 key events as conversions — and make them Primary

1. In GA4, mark the events that matter (purchase, lead submit, call, etc.) as
   **key events**.
2. In **Google Ads → Goals → Conversions → Summary**, import those GA4 key
   events as conversion actions.
3. Set the ones you want to optimise toward to **Primary**, not Secondary.

This is the step people get wrong: an imported conversion left as **Secondary**
(sometimes shown as "hidden" / not in "Conversions") is *not* used by bidding.
If your smart bidding has nothing Primary to optimise, it cannot optimise. Make
the real goal Primary.

---

## 3. Turn on auto-tagging (GCLID)

In **Google Ads → Admin → Account settings → Auto-tagging**, enable it. This
appends the **GCLID** to your click URLs, which is how Google Ads ties clicks
back to conversions and powers accurate attribution.

Without auto-tagging, imported GA4 conversions can fail to attribute to the
right campaign, and you lose the data the whole setup depends on.

---

## 4. (Optional) Enhanced Conversions for Leads

For lead-gen accounts, **Enhanced Conversions for Leads** improves match quality
by sending hashed first-party data (e.g. email) with conversions, recovering
conversions that would otherwise go unattributed. It is opt-in and has its own
data-handling requirements — set it up only if you understand and accept those
terms for your account.

---

## 5. Do not enable a campaign with no conversions

Two hard rules:

* **Never enable a campaign before conversions are importing.** Spending money
  with no conversion signal is paying for clicks you cannot evaluate.
* **Do not jump straight to a conversion-based bid strategy with no data.**
  Strategies like "Maximize conversions" need a baseline of conversion history
  to work. On a brand-new account, start with the click-based strategy the
  config uses (`maximize_clicks`), let real conversions accumulate, then switch.

The campaigns this tool creates are paused on purpose so you can complete this
checklist first. Verify conversions are recording, then enable.
