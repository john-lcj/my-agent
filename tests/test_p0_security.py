"""P0 安全加固回归 —— 工作区范围限制 + 外发收件人白名单。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ReadFile, WriteFile
from capabilities.tools.notify import SendEmail, _recipient_allowed
from core.types import CapabilityCall, Decision, Identity


def _policy():
    from governance.engine import DeclarativePolicy
    return DeclarativePolicy(CapabilityRegistry([ReadFile(), WriteFile()]), config_path=None)


def test_workspace_scope_ask_outside():
    with tempfile.TemporaryDirectory() as root:
        os.environ["AGENT_WORKSPACE_ROOT"] = root
        os.environ.pop("AGENT_WORKSPACE_STRICT", None)
        try:
            pol = _policy()
            inside = CapabilityCall(name="fs.read", args={"path": os.path.join(root, "a.txt")})
            outside = CapabilityCall(name="fs.read", args={"path": "/etc/hosts"})
            assert pol.review(inside, Identity(), None) == Decision.ALLOW
            assert pol.review(outside, Identity(), None) == Decision.ASK
        finally:
            del os.environ["AGENT_WORKSPACE_ROOT"]


def test_workspace_scope_strict_blocks():
    with tempfile.TemporaryDirectory() as root:
        os.environ["AGENT_WORKSPACE_ROOT"] = root
        os.environ["AGENT_WORKSPACE_STRICT"] = "1"
        try:
            pol = _policy()
            outside = CapabilityCall(name="fs.write", args={"path": "/tmp/evil.txt", "content": "x"})
            assert pol.review(outside, Identity(), None) == Decision.BLOCK
        finally:
            del os.environ["AGENT_WORKSPACE_ROOT"]
            del os.environ["AGENT_WORKSPACE_STRICT"]


def test_workspace_unset_no_restriction():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    # 未配置工作区:越界读不被范围逻辑拦(回到原有规则,READ 自动放行)
    c = CapabilityCall(name="fs.read", args={"path": "/etc/hosts"})
    assert pol.review(c, Identity(), None) == Decision.ALLOW


def test_workspace_blocks_dotdot_escape():
    with tempfile.TemporaryDirectory() as root:
        os.environ["AGENT_WORKSPACE_ROOT"] = root
        os.environ.pop("AGENT_WORKSPACE_STRICT", None)
        try:
            pol = _policy()
            sneaky = CapabilityCall(name="fs.read", args={"path": os.path.join(root, "../../etc/hosts")})
            assert pol.review(sneaky, Identity(), None) == Decision.ASK
        finally:
            del os.environ["AGENT_WORKSPACE_ROOT"]


def test_recipient_allowlist_default_self():
    # 隔离 env:其它测试 import server.app 会触发 _channel_cfg 读取真实
    # logs/channels.json 并把真实 EMAIL_ALLOWED_RECIPIENTS 灌入 os.environ。
    os.environ.pop("EMAIL_ALLOWED_RECIPIENTS", None)
    assert _recipient_allowed("me@x.com", "me@x.com") is True
    assert _recipient_allowed("stranger@evil.com", "me@x.com") is False


def test_recipient_allowlist_env():
    os.environ["EMAIL_ALLOWED_RECIPIENTS"] = "a@x.com, Boss@Y.com"
    try:
        assert _recipient_allowed("boss@y.com", "me@x.com") is True
        assert _recipient_allowed("me@x.com", "me@x.com") is False  # 白名单覆盖默认
    finally:
        del os.environ["EMAIL_ALLOWED_RECIPIENTS"]


def test_send_email_rejects_non_allowlisted():
    os.environ.pop("EMAIL_ALLOWED_RECIPIENTS", None)
    os.environ["EMAIL_SMTP_HOST"] = "smtp.x.com"
    os.environ["EMAIL_USER"] = "me@x.com"
    os.environ["EMAIL_PASS"] = "p"
    try:
        r = asyncio.run(SendEmail().invoke(
            {"to": "stranger@evil.com", "subject": "s", "body": "b"}, None))
        assert r.ok is False and "白名单" in (r.error or "")
    finally:
        for k in ("EMAIL_SMTP_HOST", "EMAIL_USER", "EMAIL_PASS"):
            os.environ.pop(k, None)
