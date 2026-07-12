"""新增通用能力:fs.search / browser / vision + 分模式 prompt + 治理。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import CapabilityCall, Decision, Identity


# ── ④ fs.search ───────────────────────────────────────────────────────────
def test_fs_search_finds_content():
    from capabilities.tools.fs_search import FsSearch
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "sub"))
    open(os.path.join(d, "a.py"), "w").write("def hello():\n    return 42\n")
    open(os.path.join(d, "sub", "b.md"), "w").write("# 标题\nhello world\n")
    os.environ["AGENT_WORKSPACE_ROOT"] = d
    try:
        r = asyncio.run(FsSearch().invoke({"query": "hello"}, None))
        assert r.ok and "a.py" in r.output and "b.md" in r.output
        r2 = asyncio.run(FsSearch().invoke({"query": "hello", "glob": "*.py"}, None))
        assert "a.py" in r2.output and "b.md" not in r2.output
        r3 = asyncio.run(FsSearch().invoke({"query": "不存在的词xyz"}, None))
        assert r3.ok and "没找到" in r3.output
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)


# ── ② browser:未装 Playwright 时优雅报错 ────────────────────────────────────
def test_browser_graceful_without_playwright():
    from capabilities.tools.browser import BrowserOpen, BrowserText
    try:
        import playwright  # noqa: F401
        return  # 装了就跳过(不在沙箱里真开浏览器)
    except Exception:
        pass
    r = asyncio.run(BrowserOpen().invoke({"url": "https://example.com"}, None))
    assert not r.ok and "Playwright" in (r.error or "")
    r2 = asyncio.run(BrowserText().invoke({}, None))
    assert not r2.ok  # 没开页面


# ── ① vision:未配置 VISION_MODEL 时明确提示 ─────────────────────────────────
def test_vision_unconfigured():
    from capabilities.tools.vision import VisionSee, vision_configured
    os.environ.pop("VISION_MODEL", None)
    assert not vision_configured()
    r = asyncio.run(VisionSee().invoke({"question": "这是什么", "url": "http://x/y.png"}, None))
    assert not r.ok and "VISION_MODEL" in (r.error or "")


# ── 注册 ────────────────────────────────────────────────────────────────────
def test_new_caps_registered():
    from core.bootstrap import build_registry
    names = {s.get("name") for s in build_registry("interactive").specs()}
    for n in ("fs.search", "browser.open", "browser.click", "browser.fill", "vision.see", "gui.observe", "gui.control"):
        assert n in names, f"{n} 未注册"


# ── 治理:浏览器写操作默认确认，Cowork 也需要显式授权 ───────────────────────
class _Ctx:
    def __init__(self, coworker): self.coworker = coworker


def test_browser_click_confirm_by_mode():
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.browser import BrowserClick
    from governance.engine import DeclarativePolicy
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = DeclarativePolicy(CapabilityRegistry([BrowserClick()]), config_path="governance/policy.yaml")
    c = CapabilityCall(name="browser.click", args={"selector": "#btn"})
    assert pol.review(c, Identity(), _Ctx(False)) == Decision.ASK
    assert pol.review(c, Identity(), _Ctx(True)) == Decision.ASK


# ── 分模式 prompt ───────────────────────────────────────────────────────────
def test_mode_prompt_differs():
    from core.prompts import mode_prompt
    assert "Cowork 执行" in mode_prompt(True) and "preflight" in mode_prompt(True)
    assert "Chat 顾问" in mode_prompt(False) and "不主动写入" in mode_prompt(False)
