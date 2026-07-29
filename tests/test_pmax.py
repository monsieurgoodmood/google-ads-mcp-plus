# Copyright 2026 ByteBerry Analytics LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline tests for Performance Max validation. No API, no credentials."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from google_ads_mcp_plus import pmax  # noqa: E402


def _spec(**over):
    base = {
        "marketing_image_asset_ids": [111],
        "square_marketing_image_asset_ids": [222],
        "logo_asset_ids": [333],
        "campaign_name": "PMax | Test",
        "daily_budget": 50,
        "final_url": "https://example.com/lp",
        "business_name": "Example Co",
        "headlines": ["Fast Service", "Book Today", "Top Rated"],
        "long_headlines": ["The most reliable way to book your service online."],
        "descriptions": ["Reliable local help, available now.",
                         "Free quote in minutes."],
    }
    base.update(over)
    return base


def test_valid_spec_has_no_errors():
    assert pmax.validate_pmax_content(_spec()) == []


def test_too_few_headlines():
    errs = pmax.validate_pmax_content(_spec(headlines=["One", "Two"]))
    assert any("at least 3" in e for e in errs)


def test_missing_long_headline():
    errs = pmax.validate_pmax_content(_spec(long_headlines=[]))
    assert any("long_headlines" in e for e in errs)


def test_long_headline_over_90_chars():
    errs = pmax.validate_pmax_content(_spec(long_headlines=["x" * 91]))
    assert any("long_headlines[0]" in e for e in errs)


def test_long_headline_at_limit_passes():
    assert pmax.validate_pmax_content(_spec(long_headlines=["x" * 90])) == []


def test_too_few_descriptions():
    errs = pmax.validate_pmax_content(_spec(descriptions=["only one"]))
    assert any("descriptions" in e for e in errs)


def test_headline_over_30_chars_caught():
    errs = pmax.validate_pmax_content(
        _spec(headlines=["x" * 31, "Book Today", "Top Rated"]))
    assert any("headlines[0]" in e for e in errs)


def test_business_name_required():
    errs = pmax.validate_pmax_content(_spec(business_name="  "))
    assert any("business_name" in e for e in errs)


def test_business_name_over_25_chars():
    errs = pmax.validate_pmax_content(_spec(business_name="x" * 26))
    assert any("business_name" in e for e in errs)


def test_final_url_required():
    errs = pmax.validate_pmax_content(_spec(final_url=""))
    assert any("final_url" in e for e in errs)


def test_daily_budget_required():
    errs = pmax.validate_pmax_content(_spec(daily_budget=0))
    assert any("daily_budget" in e for e in errs)


def test_callout_cap_enforced():
    """Google caps campaign-level callouts at 20."""
    errs = pmax.validate_pmax_content(_spec(callout_asset_ids=list(range(21))))
    assert any("callout_asset_ids" in e for e in errs)


def test_callouts_at_cap_pass():
    assert pmax.validate_pmax_content(
        _spec(callout_asset_ids=list(range(20)))) == []


def test_multiple_errors_all_reported():
    errs = pmax.validate_pmax_content(
        _spec(headlines=["One"], descriptions=[], business_name=""))
    assert len(errs) >= 3


def test_cjk_counted_as_double_width():
    """15 wide chars == 30 width (ok); 16 == 32 (too long)."""
    assert pmax.validate_pmax_content(
        _spec(headlines=["東" * 15, "Book Today", "Top Rated"])) == []
    errs = pmax.validate_pmax_content(
        _spec(headlines=["東" * 16, "Book Today", "Top Rated"]))
    assert any("headlines[0]" in e for e in errs)


def test_execute_refuses_invalid_spec_before_any_api_call():
    """Validation must fail offline — client=None proves no API call happened."""
    with pytest.raises(pmax.PMaxConfigError):
        pmax.execute(None, "1234567890", _spec(headlines=[]), validate_only=True)


def test_missing_marketing_image_rejected():
    """Google requires all three image types on a PMax asset group."""
    errs = pmax.validate_pmax_content(_spec(marketing_image_asset_ids=[]))
    assert any("marketing_image_asset_ids" in e for e in errs)


def test_missing_square_image_rejected():
    errs = pmax.validate_pmax_content(_spec(square_marketing_image_asset_ids=[]))
    assert any("square_marketing_image_asset_ids" in e for e in errs)


def test_missing_logo_rejected():
    errs = pmax.validate_pmax_content(_spec(logo_asset_ids=[]))
    assert any("logo_asset_ids" in e for e in errs)


def test_require_images_false_allows_text_only_validation():
    """The drafting path must be able to return valid with no image IDs."""
    spec = _spec()
    for k in ("marketing_image_asset_ids", "square_marketing_image_asset_ids",
              "logo_asset_ids"):
        spec[k] = []
    assert pmax.validate_pmax_content(spec, require_images=False) == []


def test_require_images_false_still_checks_text():
    spec = _spec(headlines=["One"])
    assert pmax.validate_pmax_content(spec, require_images=False) != []


# --------------------------------------------------------------------------- #
# Shopping — offline spec validation
# --------------------------------------------------------------------------- #
from google_ads_mcp_plus import shopping  # noqa: E402


def _shop(**over):
    base = {
        "campaign_name": "Shopping | Pans",
        "daily_budget": 20,
        "merchant_id": 123456,
        "feed_label": "EUR_1234",
        "include_values": ["pan"],
        "dimension": "product_type_level1",
    }
    base.update(over)
    return base


def test_valid_shopping_spec():
    assert shopping.validate_shopping_spec(_shop()) == []


def test_merchant_id_required():
    errs = shopping.validate_shopping_spec(_shop(merchant_id=None))
    assert any("merchant_id" in e for e in errs)


def test_feed_label_required():
    """feed_label replaced sales_country and must match Merchant Center."""
    errs = shopping.validate_shopping_spec(_shop(feed_label=""))
    assert any("feed_label" in e for e in errs)


def test_include_values_required():
    errs = shopping.validate_shopping_spec(_shop(include_values=[]))
    assert any("include_values" in e for e in errs)


def test_bad_priority_rejected():
    errs = shopping.validate_shopping_spec(_shop(campaign_priority=5))
    assert any("campaign_priority" in e for e in errs)


def test_all_priorities_accepted():
    for p in (0, 1, 2):
        assert shopping.validate_shopping_spec(_shop(campaign_priority=p)) == []


def test_unknown_dimension_rejected():
    errs = shopping.validate_shopping_spec(_shop(dimension="colour"))
    assert any("dimension" in e for e in errs)


def test_every_documented_dimension_is_supported():
    for dim in shopping.PRODUCT_DIMENSIONS:
        assert shopping.validate_shopping_spec(_shop(dimension=dim)) == []


def test_create_refuses_invalid_spec_before_any_api_call():
    """client=None proves validation happened offline."""
    with pytest.raises(shopping.ShoppingConfigError):
        shopping.create_shopping_campaign(None, "123", _shop(feed_label=""),
                                          validate_only=True)
