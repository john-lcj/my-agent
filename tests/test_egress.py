"""出站域名管控回归 —— 黑名单优先、白名单仅放行名单内、默认不限制。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governance.egress import check_egress


def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_EGRESS_ALLOW", raising=False)
    monkeypatch.delenv("AGENT_EGRESS_BLOCK", raising=False)


def test_default_allows_all(monkeypatch):
    _clear(monkeypatch)
    ok, _ = check_egress("https://anything.example.com/x")
    assert ok


def test_blocklist_blocks_domain_and_subdomain(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_EGRESS_BLOCK", "evil.com")
    assert not check_egress("https://evil.com/p")[0]
    assert not check_egress("https://api.evil.com/p")[0]   # 子域也拦
    assert check_egress("https://good.com/p")[0]


def test_allowlist_only_permits_listed(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_EGRESS_ALLOW", "github.com,internal.corp")
    assert check_egress("https://api.github.com/user")[0]   # 子域放行
    assert check_egress("https://internal.corp/api")[0]
    assert not check_egress("https://random.io/x")[0]       # 名单外拦


def test_block_wins_over_allow(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_EGRESS_ALLOW", "github.com")
    monkeypatch.setenv("AGENT_EGRESS_BLOCK", "github.com")
    assert not check_egress("https://github.com/x")[0]      # 黑名单优先


def test_rejects_malformed(monkeypatch):
    _clear(monkeypatch)
    assert not check_egress("notaurl")[0]
