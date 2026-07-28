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

"""Offline tests for src/audit/audit_account.py.

These cover the pure logic — money conversion, date windows, severity sorting,
report rendering, and the resilience of the runner when a check explodes. No
google-ads library, no network, no credentials.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audit import audit_account as aa  # noqa: E402


# --------------------------------------------------------------------------- #
# Money + percentage helpers
# --------------------------------------------------------------------------- #
def test_micros_to_units_converts():
    assert aa.micros_to_units(1_000_000) == 1.0
    assert aa.micros_to_units(2_500_000) == 2.5


def test_micros_to_units_handles_none_and_zero():
    assert aa.micros_to_units(None) == 0
    assert aa.micros_to_units(0) == 0


def test_pct_converts_ratio_to_percentage():
    assert aa.pct(0.256) == 25.6
    assert aa.pct(None) == 0
    assert aa.pct(1.0) == 100.0


# --------------------------------------------------------------------------- #
# Date window
# --------------------------------------------------------------------------- #
def test_date_range_ends_yesterday_not_today():
    """Today is partial and would make 'no conversions' checks fire wrongly."""
    _, end = aa.date_range(30)
    assert end == (dt.date.today() - dt.timedelta(days=1)).isoformat()


def test_date_range_spans_requested_days_inclusive():
    start, end = aa.date_range(7)
    delta = dt.date.fromisoformat(end) - dt.date.fromisoformat(start)
    assert delta.days == 6  # inclusive span of 7 days


def test_date_range_single_day():
    start, end = aa.date_range(1)
    assert start == end


# --------------------------------------------------------------------------- #
# Severity ordering + summary
# --------------------------------------------------------------------------- #
def _f(sev, name="x"):
    return aa.Finding(check=name, severity=sev, entity="e", message="m")


def test_sort_findings_puts_critical_first():
    findings = [_f(aa.INFO), _f(aa.CRITICAL), _f(aa.WARNING)]
    ordered = [f.severity for f in aa.sort_findings(findings)]
    assert ordered == [aa.CRITICAL, aa.WARNING, aa.INFO]


def test_sort_findings_is_stable_within_severity():
    findings = [_f(aa.WARNING, "first"), _f(aa.WARNING, "second")]
    assert [f.check for f in aa.sort_findings(findings)] == ["first", "second"]


def test_summarize_counts_each_severity():
    findings = [_f(aa.CRITICAL), _f(aa.CRITICAL), _f(aa.WARNING), _f(aa.INFO)]
    counts = aa.summarize(findings)
    assert counts[aa.CRITICAL] == 2
    assert counts[aa.WARNING] == 1
    assert counts[aa.INFO] == 1


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
def _ctx():
    return aa.AuditContext(date_from="2026-01-01", date_to="2026-01-30", days=30,
                           currency="EUR")


def test_render_text_mentions_counts_and_readonly():
    out = aa.render_text([_f(aa.CRITICAL)], "1234567890", _ctx())
    assert "1234567890" in out
    assert "1 critical" in out
    assert "nothing in your account was modified" in out.lower()


def test_render_markdown_groups_by_severity():
    findings = [_f(aa.CRITICAL), _f(aa.INFO)]
    out = aa.render_markdown(findings, "123", _ctx())
    assert "## Critical" in out
    assert "## Info" in out
    assert "## Warnings" not in out  # no warnings present


def test_render_json_is_parseable_and_complete():
    out = aa.render_json([_f(aa.WARNING)], "123", _ctx())
    payload = json.loads(out)
    assert payload["customer_id"] == "123"
    assert payload["days"] == 30
    assert payload["summary"][aa.WARNING] == 1
    assert len(payload["findings"]) == 1


def test_render_json_handles_no_findings():
    payload = json.loads(aa.render_json([], "123", _ctx()))
    assert payload["findings"] == []
    assert payload["summary"][aa.CRITICAL] == 0


# --------------------------------------------------------------------------- #
# Runner resilience — one broken check must not kill the audit
# --------------------------------------------------------------------------- #
def test_run_audit_survives_a_failing_check(monkeypatch):
    def good(client, cid, ctx):
        return [_f(aa.WARNING, "good")]

    def broken(client, cid, ctx):
        raise RuntimeError("API exploded")

    monkeypatch.setattr(aa, "CHECKS", [good, broken])
    findings = aa.run_audit(None, "123", _ctx())

    checks = {f.check for f in findings}
    assert "good" in checks          # the working check still reported
    assert "broken" in checks        # the failure was recorded, not swallowed
    assert any("API exploded" in f.message for f in findings)


def test_run_audit_returns_empty_when_no_checks(monkeypatch):
    monkeypatch.setattr(aa, "CHECKS", [])
    assert aa.run_audit(None, "123", _ctx()) == []


# --------------------------------------------------------------------------- #
# CLI argument handling
# --------------------------------------------------------------------------- #
def test_parse_args_defaults():
    args = aa.parse_args(["--customer-id", "123-456-7890"])
    assert args.days == 30
    assert args.format == "text"


def test_parse_args_requires_customer_id():
    with pytest.raises(SystemExit):
        aa.parse_args([])


def test_list_checks_exits_zero(capsys):
    assert aa.main(["--customer-id", "123", "--list-checks"]) == 0
    out = capsys.readouterr().out
    assert "check_conversion_tracking" in out


def test_every_registered_check_is_callable_and_documented():
    for check in aa.CHECKS:
        assert callable(check)
        assert check.__doc__, f"{check.__name__} has no docstring"
