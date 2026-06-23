"""额外端点(小米/自定义)能进模型下拉 + 能被 build_llm 解析。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_xiaomi_surfaces_when_vision_configured(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "mimo-v2-omni")
    monkeypatch.setenv("VISION_API_KEY", "sk-xm")
    from llm.model_registry import extra_models
    ids = {m["id"] for m in extra_models()}
    assert "ext:xiaomi" in ids
    em = next(m for m in extra_models() if m["id"] == "ext:xiaomi")
    assert "mimo-v2-omni" in em["label"]


def test_xiaomi_absent_without_vision(monkeypatch):
    monkeypatch.delenv("VISION_MODEL", raising=False)
    from llm.model_registry import extra_models
    assert "ext:xiaomi" not in {m["id"] for m in extra_models()}


def test_normalize_passes_ext_through():
    from llm.model_registry import normalize_model_id
    assert normalize_model_id("ext:xiaomi") == "ext:xiaomi"
    assert normalize_model_id("ext:kimi") == "ext:kimi"


def test_build_llm_resolves_xiaomi(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "mimo-v2-omni")
    monkeypatch.setenv("VISION_API_KEY", "sk-xm")
    monkeypatch.setenv("VISION_BASE_URL", "https://api.xiaomimimo.com/v1")
    from llm.factory import build_llm
    llm = build_llm(model="ext:xiaomi", with_fallback=False)
    # 应构建出一个指向小米端点的 OpenAI 兼容 LLM
    assert getattr(llm, "name", "") == "ext:xiaomi"
    assert getattr(llm, "model", "") == "mimo-v2-omni"


def test_build_llm_ext_incomplete_raises(monkeypatch):
    for k in ("VISION_MODEL", "VISION_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from llm.factory import build_llm
    try:
        build_llm(model="ext:xiaomi", with_fallback=False)
        assert False, "应因缺 key/模型名报错"
    except ValueError as e:
        assert "不完整" in str(e)
