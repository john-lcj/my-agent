"""Fake-IP DNS(Shadowrocket/Clash 等)环境下的 SSRF 判定。"""
from __future__ import annotations

from capabilities.tools import web


def test_fakeip_range_allowed_when_fakeip_dns_active(monkeypatch):
    monkeypatch.setattr(web, "_fakeip_dns_active", lambda: True)
    assert web._ip_blocked_reason("198.18.0.15", allow_proxy_fakeip=True) is None
    assert web._ip_blocked_reason("198.19.255.1", allow_proxy_fakeip=True) is None


def test_fakeip_range_blocked_without_fakeip_dns(monkeypatch):
    monkeypatch.setattr(web, "_fakeip_dns_active", lambda: False)
    assert "禁止访问" in (web._ip_blocked_reason("198.18.0.15") or "")


def test_fakeip_literal_url_remains_blocked(monkeypatch):
    monkeypatch.setattr(web, "_fakeip_dns_active", lambda: True)
    assert "禁止访问" in (web._url_allowed("http://198.18.0.15/private") or "")


def test_public_hostname_can_use_fakeip_dns(monkeypatch):
    monkeypatch.setattr(web, "_fakeip_dns_active", lambda: True)
    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("198.18.0.15", 0))],
    )
    assert web._url_allowed("https://example.com") is None


def test_private_and_loopback_still_blocked_with_fakeip_dns(monkeypatch):
    monkeypatch.setattr(web, "_fakeip_dns_active", lambda: True)
    for ip in ("127.0.0.1", "10.0.0.1", "192.168.0.1", "169.254.1.1", "::1"):
        assert "禁止访问" in (web._ip_blocked_reason(ip) or ""), ip


def test_fakeip_probe_caches(monkeypatch):
    calls = []

    def fake_getaddrinfo(*a, **k):
        calls.append(1)
        return [(2, 1, 6, "", ("198.18.0.99", 0))]

    monkeypatch.setattr(web.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(web, "_fakeip_probe", (0.0, False))
    assert web._fakeip_dns_active() is True
    assert web._fakeip_dns_active() is True
    assert len(calls) == 1
