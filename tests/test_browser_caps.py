"""浏览器能力回归 —— 注册齐全 + 风险分级 + 上传路径限工作区(不依赖 Playwright)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Risk


def test_new_browser_caps_registered():
    os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    for n in ("browser.wait", "browser.screenshot", "browser.upload", "browser.download"):
        assert reg.get(n) is not None, f"{n} 未注册"
    # 读/写分级
    assert reg.get("browser.wait").risk == Risk.READ
    assert reg.get("browser.screenshot").risk == Risk.READ
    assert reg.get("browser.upload").risk == Risk.WRITE
    assert reg.get("browser.download").risk == Risk.WRITE


def test_upload_path_confined_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    from capabilities.tools.browser import _safe_ws_path
    # 工作区内的文件 → 放行
    inside = tmp_path / "ok.txt"
    inside.write_text("x")
    assert _safe_ws_path("ok.txt") == str(inside)
    # 越界 → 拒绝
    assert _safe_ws_path("/etc/passwd") is None
    assert _safe_ws_path("../../etc/passwd") is None
