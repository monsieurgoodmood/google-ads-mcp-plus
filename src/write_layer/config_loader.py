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

"""Load and validate a campaign config (YAML).

This module depends only on PyYAML and the dependency-free ``validators``
module. It never imports the ``google-ads`` client and never touches the
network, so a config can be validated in CI with no credentials.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validators  # noqa: E402  (sibling module)


class ConfigError(Exception):
    """Raised when the config file is missing required structure."""


def _digits_only(value: Any) -> str:
    """Strip dashes/spaces from a customer ID. ``123-456-7890`` -> ``1234567890``."""
    return re.sub(r"\D", "", str(value or ""))


def _require(cfg: Dict, dotted: str, problems: List[str]) -> Any:
    """Fetch a nested key like ``campaign.geo.target``; record if missing/empty."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            problems.append(f"missing required key: {dotted}")
            return None
        node = node[part]
    if node in (None, "", [], {}):
        problems.append(f"required key is empty: {dotted}")
        return None
    return node


def load_and_validate(path: str) -> Dict:
    """Load ``path`` (YAML), validate structure + text limits, and return the dict.

    Raises ``ConfigError`` for structural problems and
    ``validators.ValidationError`` for content (character-limit) problems.
    """
    if not os.path.exists(path):
        raise ConfigError(f"config file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a YAML mapping")

    problems: List[str] = []

    # Required structure (the API needs all of these to build a Search campaign).
    _require(cfg, "account.customer_id", problems)
    _require(cfg, "campaign.name", problems)
    _require(cfg, "campaign.daily_budget", problems)
    _require(cfg, "campaign.geo.target", problems)
    _require(cfg, "campaign.language", problems)
    _require(cfg, "ad_group.name", problems)
    _require(cfg, "ad_group.keywords_exact", problems)
    _require(cfg, "rsa.headlines", problems)
    _require(cfg, "rsa.descriptions", problems)
    _require(cfg, "rsa.final_url", problems)  # ads cannot be created without it

    if problems:
        raise ConfigError(
            f"{len(problems)} structural problem(s):\n  - " + "\n  - ".join(problems)
        )

    # Normalise account IDs to digits only.
    cfg["account"]["customer_id"] = _digits_only(cfg["account"]["customer_id"])
    if cfg["account"].get("login_customer_id"):
        cfg["account"]["login_customer_id"] = _digits_only(
            cfg["account"]["login_customer_id"]
        )

    # Content validation (character limits, headers, minimum counts). Raises
    # validators.ValidationError with the full list of problems if anything fails.
    validators.assert_valid(cfg)

    return cfg
