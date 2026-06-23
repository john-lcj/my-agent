"""HTTP 连接器回归 —— 输入校验 + 风险等级(WRITE,需确认)。

只测纯逻辑(不发真实网络):非法 url/method 被挡;风险等级正确,确保治理会拦。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.http_request import HttpRequest
from core.types import Risk


def test_risk_is_write():
    assert HttpRequest.risk == Risk.WRITE
    assert HttpRequest.name == "http.request"


def test_rejects_non_http_url():
    r = asyncio.run(
        HttpRequest().invoke({"url": "file:///etc/passwd"}, ctx=None))
    assert not r.ok and "http" in r.error


def test_rejects_bad_method():
    r = asyncio.run(
        HttpRequest().invoke({"url": "https://example.com", "method": "CONNECT"}, ctx=None))
    assert not r.ok and "方法" in r.error


def test_rejects_bad_headers():
    r = asyncio.run(
        HttpRequest().invoke({"url": "https://example.com", "headers": "oops"}, ctx=None))
    assert not r.ok
