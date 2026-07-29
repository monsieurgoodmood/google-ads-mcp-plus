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

"""Offline tests for the MCP server's safety layer.

These test the guards, not the Google Ads calls: the allowlist, the read-only
default, the two-phase confirmation tokens, and the mutation log. No mcp
package, no google-ads, no network, no credentials.
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from google_ads_mcp_plus import server as srv  # noqa: E402


@pytest.fixture(autouse=True)
def clean_pending():
    srv._PENDING.clear()
    yield
    srv._PENDING.clear()


# --------------------------------------------------------------------------- #
# Config parsing
# --------------------------------------------------------------------------- #
def test_allowlist_parsed_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_ALLOWED_CUSTOMERS", "123-456-7890, 9876543210")
    cfg = srv.ServerConfig.from_env()
    assert cfg.allowed_customers == ["1234567890", "9876543210"]


def test_writes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_ADS_MCP_ENABLE_WRITES", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_ALLOWED_CUSTOMERS", "123")
    assert srv.ServerConfig.from_env().writes_enabled is False


def test_writes_forced_off_when_allowlist_empty(monkeypatch):
    """Enabling writes without an allowlist must not grant blanket access."""
    monkeypatch.setenv("GOOGLE_ADS_MCP_ENABLE_WRITES", "true")
    monkeypatch.setenv("GOOGLE_ADS_ALLOWED_CUSTOMERS", "")
    assert srv.ServerConfig.from_env().writes_enabled is False


def test_writes_enabled_with_allowlist(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_MCP_ENABLE_WRITES", "true")
    monkeypatch.setenv("GOOGLE_ADS_ALLOWED_CUSTOMERS", "1234567890")
    assert srv.ServerConfig.from_env().writes_enabled is True


# --------------------------------------------------------------------------- #
# Allowlist enforcement
# --------------------------------------------------------------------------- #
def test_require_allowed_accepts_listed_account(monkeypatch):
    monkeypatch.setattr(srv.CONFIG, "allowed_customers", ["1234567890"])
    assert srv.require_allowed("123-456-7890") == "1234567890"


def test_require_allowed_rejects_unlisted_account(monkeypatch):
    monkeypatch.setattr(srv.CONFIG, "allowed_customers", ["1234567890"])
    with pytest.raises(ValueError, match="not in the allowlist"):
        srv.require_allowed("9999999999")


def test_require_allowed_rejects_when_no_allowlist(monkeypatch):
    monkeypatch.setattr(srv.CONFIG, "allowed_customers", [])
    with pytest.raises(ValueError, match="No accounts are allowlisted"):
        srv.require_allowed("1234567890")


def test_require_writes_blocks_in_readonly(monkeypatch):
    monkeypatch.setattr(srv.CONFIG, "writes_enabled", False)
    with pytest.raises(ValueError, match="READ-ONLY"):
        srv.require_writes()


# --------------------------------------------------------------------------- #
# Two-phase confirmation
# --------------------------------------------------------------------------- #
def test_stage_returns_token_and_registers_operation():
    token = srv.stage("update_budget", {"a": 1})
    assert token in srv._PENDING
    assert srv._PENDING[token]["operation"] == "update_budget"


def test_redeem_accepts_matching_token_and_payload():
    payload = {"campaign_id": "1", "new_daily_budget": 20.0}
    token = srv.stage("update_budget", payload)
    assert srv.redeem(token, "update_budget", payload) == payload


def test_redeem_is_single_use():
    payload = {"x": 1}
    token = srv.stage("update_budget", payload)
    srv.redeem(token, "update_budget", payload)
    with pytest.raises(ValueError, match="Unknown or expired"):
        srv.redeem(token, "update_budget", payload)


def test_redeem_rejects_unknown_token():
    with pytest.raises(ValueError, match="Unknown or expired"):
        srv.redeem("nope-1234", "update_budget", {})


def test_redeem_rejects_wrong_operation():
    payload = {"x": 1}
    token = srv.stage("update_budget", payload)
    with pytest.raises(ValueError, match="different operation"):
        srv.redeem(token, "set_status", payload)


def test_redeem_rejects_changed_payload():
    """A token issued for one change must not execute a different one."""
    token = srv.stage("update_budget", {"new_daily_budget": 20.0})
    with pytest.raises(ValueError, match="parameters changed"):
        srv.redeem(token, "update_budget", {"new_daily_budget": 2000.0})


def test_expired_tokens_are_pruned(monkeypatch):
    token = srv.stage("update_budget", {"x": 1})
    monkeypatch.setattr(srv, "_now", lambda: time.time() + srv._TOKEN_TTL_SECONDS + 60)
    with pytest.raises(ValueError, match="Unknown or expired"):
        srv.redeem(token, "update_budget", {"x": 1})


# --------------------------------------------------------------------------- #
# Mutation log
# --------------------------------------------------------------------------- #
def test_log_mutation_appends_jsonl(tmp_path, monkeypatch):
    log = tmp_path / "mutations.jsonl"
    monkeypatch.setattr(srv.CONFIG, "mutation_log", log)

    srv.log_mutation("update_campaign_budget", "123", 10.0, 20.0, {"c": "x"})
    srv.log_mutation("set_campaign_status", "123", "PAUSED", "ENABLED")

    lines = log.read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["operation"] == "update_campaign_budget"
    assert first["before"] == 10.0
    assert first["after"] == 20.0
    assert "timestamp" in first


def test_log_mutation_survives_unwritable_path(monkeypatch):
    """A logging failure must not crash a mutation that already succeeded."""
    monkeypatch.setattr(srv.CONFIG, "mutation_log",
                        Path("/nonexistent-dir-xyz/mutations.jsonl"))
    srv.log_mutation("op", "123", None, None)  # must not raise


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_digits_strips_formatting():
    assert srv.digits("123-456-7890") == "1234567890"
    assert srv.digits("  99 99  ") == "9999"


# --------------------------------------------------------------------------- #
# Numeric limits must not be silently disabled
# --------------------------------------------------------------------------- #
def test_nan_budget_limit_falls_back_to_default(monkeypatch):
    """float('nan') parses fine but defeats every comparison — must be refused."""
    monkeypatch.setenv("GOOGLE_ADS_MAX_DAILY_BUDGET", "nan")
    assert srv.ServerConfig.from_env().max_daily_budget == 100.0


def test_infinite_budget_limit_falls_back(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_MAX_DAILY_BUDGET", "inf")
    assert srv.ServerConfig.from_env().max_daily_budget == 100.0


def test_negative_budget_limit_falls_back(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_MAX_DAILY_BUDGET", "-5")
    assert srv.ServerConfig.from_env().max_daily_budget == 100.0


def test_garbage_budget_limit_falls_back(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_MAX_DAILY_BUDGET", "beaucoup")
    assert srv.ServerConfig.from_env().max_daily_budget == 100.0


def test_valid_budget_limit_is_used(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_MAX_DAILY_BUDGET", "250.5")
    assert srv.ServerConfig.from_env().max_daily_budget == 250.5
