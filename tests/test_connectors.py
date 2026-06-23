"""声明式连接器回归 —— 规格转能力、风险分级、鉴权头从保险库取。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.connector_loader import build_connector_tools, _auth_headers, _ConnectorTool
from core.types import Risk


def _by_name(tools):
    return {t.name: t for t in tools}


def test_github_spec_builds_capabilities():
    tools = _by_name(build_connector_tools())
    assert "github.list_repos" in tools
    assert "github.create_issue" in tools
    # GET 只读;POST 写 → DESTRUCTIVE(Chat 必确认)
    assert tools["github.list_repos"].risk == Risk.READ
    assert tools["github.create_issue"].risk == Risk.DESTRUCTIVE


def test_path_params_become_required():
    tools = _by_name(build_connector_tools())
    schema = tools["github.get_repo"].schema
    assert set(schema.get("required", [])) == {"owner", "repo"}


def test_bearer_auth_header_from_vault():
    class FakeVault:
        def get(self, ref): return "tok-123" if ref == "github" else None
        def get_username(self, ref): return "u"

    class Ctx:
        vault = FakeVault()
    h, err = _auth_headers({"type": "bearer", "secret_ref": "github"}, Ctx())
    assert not err and h["Authorization"] == "Bearer tok-123"


def test_missing_credential_reports_error():
    class FakeVault:
        def get(self, ref): return None
        def get_username(self, ref): return ""

    class Ctx:
        vault = FakeVault()
    h, err = _auth_headers({"type": "bearer", "secret_ref": "nope"}, Ctx())
    assert err and "保险库" in err


def test_basic_auth_encodes_user_and_pass():
    import base64

    class FakeVault:
        def get(self, ref): return "pw"
        def get_username(self, ref): return "alice"

    class Ctx:
        vault = FakeVault()
    h, err = _auth_headers({"type": "basic", "secret_ref": "x"}, Ctx())
    assert not err
    decoded = base64.b64decode(h["Authorization"].split()[1]).decode()
    assert decoded == "alice:pw"
