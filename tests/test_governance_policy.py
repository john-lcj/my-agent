"""治理策略 API。"""
from __future__ import annotations

from governance.policy_summary import load_policy_summary


def test_load_policy_summary_has_sections():
    data = load_policy_summary()
    assert "block" in data and "confirm" in data and "auto" in data
    assert len(data["confirm"]) >= 3
