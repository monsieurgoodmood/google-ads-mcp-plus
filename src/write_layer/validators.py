# Copyright 2026 Arthur Choisnet / ByteBerry Analytics LLC
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

"""Offline validators for Google Ads campaign content.

This module is intentionally dependency-free (Python standard library only) so
that it can be unit-tested without the ``google-ads`` client library, without
network access, and without any credentials. It enforces the character limits
and the allowed structured-snippet headers documented by Google, and counts
double-width characters (CJK / full-width) as 2 the same way the Google Ads UI
does, so a string that "looks" short but is rejected by the API is caught here
first.

Nothing in this file ever calls the API or reads secrets.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


# --------------------------------------------------------------------------- #
# Limits (Google Ads). Verify against the current Help Center if Google changes
# them; they are stable but not guaranteed forever.
# --------------------------------------------------------------------------- #
MAX_HEADLINE = 30           # Responsive Search Ad headline
MAX_DESCRIPTION = 90        # Responsive Search Ad description
MAX_PATH = 15               # Display-URL path1 / path2
MAX_CALLOUT = 25            # Callout asset text
MAX_SITELINK_TEXT = 25      # Sitelink link text
MAX_SITELINK_DESC = 35      # Sitelink description line 1 / line 2
MAX_SNIPPET_VALUE = 25      # Structured-snippet value

# Minimum counts required for a Responsive Search Ad to be created/served.
MIN_HEADLINES = 3
MIN_DESCRIPTIONS = 2
MIN_SNIPPET_VALUES = 3      # Structured snippets need at least 3 values.

# Google's allowed structured-snippet headers (English locale). For other
# languages Google expects the localized header string; see docs/policies.md.
# NOTE: "Services" is NOT valid — the correct header is "Service catalog".
ALLOWED_SNIPPET_HEADERS = {
    "Amenities",
    "Brands",
    "Courses",
    "Degree programs",
    "Destinations",
    "Featured hotels",
    "Insurance coverage",
    "Models",
    "Neighborhoods",
    "Service catalog",
    "Shows",
    "Styles",
    "Types",
}


class ValidationError(Exception):
    """Raised when a configuration fails validation.

    Carries the full list of human-readable problems so the caller can print
    every issue at once instead of fixing them one re-run at a time.
    """

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(
            f"{len(errors)} validation error(s):\n  - "
            + "\n  - ".join(errors)
        )


@dataclass
class _Collector:
    """Accumulates error strings during a validation pass."""

    errors: List[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.errors.append(msg)


def glyph_length(text: str) -> int:
    """Return the Google-Ads "character" count for ``text``.

    Google counts East-Asian full-width and wide characters as 2. Everything
    else (including most Latin, Arabic and Cyrillic) counts as 1. This mirrors
    the counter shown in the Google Ads UI closely enough to avoid surprise
    rejections.
    """
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return total


def check_text(label: str, value: str, max_len: int, collector: _Collector) -> None:
    """Validate a single text field; record an error if it is empty or too long."""
    if value is None or str(value).strip() == "":
        collector.add(f"{label}: must not be empty")
        return
    length = glyph_length(str(value))
    if length > max_len:
        collector.add(
            f"{label}: {length} chars exceeds limit of {max_len} "
            f"-> {value!r}"
        )


def check_list(
    label: str,
    values: Iterable[str],
    max_len: int,
    collector: _Collector,
    min_count: Optional[int] = None,
    max_count: Optional[int] = None,
) -> None:
    """Validate a list of text fields and (optionally) its length."""
    items = list(values or [])
    if min_count is not None and len(items) < min_count:
        collector.add(f"{label}: needs at least {min_count} item(s), got {len(items)}")
    if max_count is not None and len(items) > max_count:
        collector.add(f"{label}: at most {max_count} item(s) allowed, got {len(items)}")
    for i, item in enumerate(items):
        check_text(f"{label}[{i}]", item, max_len, collector)


def check_snippet_header(header: str, collector: _Collector) -> None:
    """Validate a structured-snippet header against Google's allowed list."""
    if header not in ALLOWED_SNIPPET_HEADERS:
        collector.add(
            f"structured_snippet header {header!r} is not a valid Google header. "
            f"Use one of: {', '.join(sorted(ALLOWED_SNIPPET_HEADERS))}"
        )


def validate_campaign_content(cfg: dict) -> List[str]:
    """Validate the user-facing text content of a campaign config.

    Returns a list of problems (empty if the config is clean). This does NOT
    validate account/auth/geo — only the text that the API will reject if it is
    too long or malformed. Call this in ``--dry-run`` and again before going
    ``--live``.
    """
    c = _Collector()

    rsa = cfg.get("rsa", {}) or {}
    check_list("rsa.headlines", rsa.get("headlines", []), MAX_HEADLINE, c,
               min_count=MIN_HEADLINES, max_count=15)
    check_list("rsa.descriptions", rsa.get("descriptions", []), MAX_DESCRIPTION, c,
               min_count=MIN_DESCRIPTIONS, max_count=4)
    if rsa.get("path1"):
        check_text("rsa.path1", rsa["path1"], MAX_PATH, c)
    if rsa.get("path2"):
        check_text("rsa.path2", rsa["path2"], MAX_PATH, c)

    assets = cfg.get("assets", {}) or {}

    callouts = assets.get("callouts")
    if callouts:
        check_list("assets.callouts", callouts, MAX_CALLOUT, c, min_count=2)

    sitelinks = assets.get("sitelinks")
    if sitelinks:
        for i, sl in enumerate(sitelinks):
            if isinstance(sl, str):
                check_text(f"assets.sitelinks[{i}].text", sl, MAX_SITELINK_TEXT, c)
            elif isinstance(sl, dict):
                check_text(f"assets.sitelinks[{i}].text", sl.get("text", ""),
                           MAX_SITELINK_TEXT, c)
                for line in ("description1", "description2"):
                    if sl.get(line):
                        check_text(f"assets.sitelinks[{i}].{line}", sl[line],
                                   MAX_SITELINK_DESC, c)
            else:
                c.add(f"assets.sitelinks[{i}]: must be a string or a mapping")

    snippets = assets.get("structured_snippets")
    if snippets:
        for i, snip in enumerate(snippets):
            header = (snip or {}).get("header", "")
            check_snippet_header(header, c)
            check_list(f"assets.structured_snippets[{i}].values",
                       (snip or {}).get("values", []), MAX_SNIPPET_VALUE, c,
                       min_count=MIN_SNIPPET_VALUES)

    return c.errors


def assert_valid(cfg: dict) -> None:
    """Validate ``cfg`` and raise :class:`ValidationError` if anything is wrong."""
    errors = validate_campaign_content(cfg)
    if errors:
        raise ValidationError(errors)
