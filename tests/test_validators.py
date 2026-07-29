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
#
# Project: https://github.com/monsieurgoodmood/google-ads-mcp-plus

"""Offline tests for src/write_layer/validators.py.

These run with nothing but pytest installed: no google-ads library, no network,
no credentials. They prove the character-limit gate works before anyone touches
a real account.

Run from the repo root:  pytest -q
"""

import os
import sys

# Make ``src`` importable without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from google_ads_mcp_plus import validators as v  # noqa: E402


# --------------------------------------------------------------------------- #
# glyph_length
# --------------------------------------------------------------------------- #
def test_glyph_length_latin():
    assert v.glyph_length("hello") == 5


def test_glyph_length_counts_cjk_as_two():
    # Each CJK ideograph counts as 2, matching the Google Ads counter.
    assert v.glyph_length("東京") == 4


def test_glyph_length_arabic_counts_as_one():
    # Arabic letters are single-width for Google's counter.
    assert v.glyph_length("قفل") == 3


# --------------------------------------------------------------------------- #
# headline / description boundaries
# --------------------------------------------------------------------------- #
def test_headline_at_limit_passes():
    cfg = _min_cfg(headlines=["x" * 30, "abc", "def"])
    assert v.validate_campaign_content(cfg) == []


def test_headline_over_limit_fails():
    cfg = _min_cfg(headlines=["x" * 31, "abc", "def"])
    errors = v.validate_campaign_content(cfg)
    assert any("headlines[0]" in e for e in errors)


def test_cjk_headline_width_boundary():
    # 15 wide chars == 30 width -> ok; 16 wide chars == 32 width -> too long.
    ok = _min_cfg(headlines=["東" * 15, "abc", "def"])
    assert v.validate_campaign_content(ok) == []
    bad = _min_cfg(headlines=["東" * 16, "abc", "def"])
    assert any("headlines[0]" in e for e in v.validate_campaign_content(bad))


def test_description_boundary():
    ok = _min_cfg(descriptions=["d" * 90, "d2"])
    assert v.validate_campaign_content(ok) == []
    bad = _min_cfg(descriptions=["d" * 91, "d2"])
    assert any("descriptions[0]" in e for e in v.validate_campaign_content(bad))


# --------------------------------------------------------------------------- #
# minimum counts
# --------------------------------------------------------------------------- #
def test_too_few_headlines_fails():
    cfg = _min_cfg(headlines=["only", "two"])
    assert any("at least 3" in e for e in v.validate_campaign_content(cfg))


def test_too_few_descriptions_fails():
    cfg = _min_cfg(descriptions=["only one"])
    assert any("at least 2" in e for e in v.validate_campaign_content(cfg))


# --------------------------------------------------------------------------- #
# callouts / sitelinks / structured snippets
# --------------------------------------------------------------------------- #
def test_callout_over_limit_fails():
    cfg = _min_cfg()
    cfg["assets"] = {"callouts": ["x" * 26, "ok callout"]}
    assert any("callouts[0]" in e for e in v.validate_campaign_content(cfg))


def test_sitelink_text_over_limit_fails():
    cfg = _min_cfg()
    cfg["assets"] = {"sitelinks": ["x" * 26]}
    assert any("sitelinks[0]" in e for e in v.validate_campaign_content(cfg))


def test_sitelink_object_description_over_limit_fails():
    cfg = _min_cfg()
    cfg["assets"] = {"sitelinks": [{"text": "Pricing", "description1": "y" * 36}]}
    assert any("description1" in e for e in v.validate_campaign_content(cfg))


def test_localised_snippet_header_is_not_blocked():
    """Google localises snippet headers: French accounts use 'Modeles',
    'Services'. Hard-failing on the English list would break every
    non-English advertiser on perfectly valid content."""
    for header in ("Services", "Modeles", "Dienstleistungen"):
        cfg = _min_cfg()
        cfg["assets"] = {
            "structured_snippets": [{"header": header, "values": ["A", "B", "C"]}]
        }
        errors = v.validate_campaign_content(cfg)
        assert not any("header" in e for e in errors), f"{header} was blocked"


def test_snippet_still_requires_enough_values():
    cfg = _min_cfg()
    cfg["assets"] = {
        "structured_snippets": [{"header": "Services", "values": ["A", "B"]}]
    }
    assert v.validate_campaign_content(cfg)


def test_valid_snippet_header_passes():
    cfg = _min_cfg()
    cfg["assets"] = {
        "structured_snippets": [
            {"header": "Service catalog", "values": ["A", "B", "C"]}
        ]
    }
    assert v.validate_campaign_content(cfg) == []


def test_snippet_too_few_values_fails():
    cfg = _min_cfg()
    cfg["assets"] = {
        "structured_snippets": [
            {"header": "Types", "values": ["only", "two"]}
        ]
    }
    assert any("at least 3" in e for e in v.validate_campaign_content(cfg))


# --------------------------------------------------------------------------- #
# assert_valid raises with the full list
# --------------------------------------------------------------------------- #
def test_assert_valid_raises_on_multiple_errors():
    cfg = _min_cfg(headlines=["x" * 31, "y" * 31, "ok"],
                   descriptions=["d" * 91, "d2"])
    with pytest.raises(v.ValidationError) as exc:
        v.assert_valid(cfg)
    assert len(exc.value.errors) >= 2


def test_assert_valid_passes_on_clean_config():
    v.assert_valid(_min_cfg())  # should not raise


# --------------------------------------------------------------------------- #
# helper
# --------------------------------------------------------------------------- #
def _min_cfg(headlines=None, descriptions=None):
    return {
        "rsa": {
            "headlines": headlines or ["Fast Service", "Call Today", "Top Rated"],
            "descriptions": descriptions or [
                "Reliable local help, available now.",
                "Free quote in minutes.",
            ],
            "path1": "service",
            "path2": "city",
        }
    }
