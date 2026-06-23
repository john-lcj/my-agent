"""多模态能力回归 —— 注册 + 未配置时给清晰提示(不发真实请求)。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Risk


def test_registered():
    os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    assert reg.get("image.ocr") is not None
    assert reg.get("image.generate") is not None
    assert reg.get("image.ocr").risk == Risk.READ
    assert reg.get("image.generate").risk == Risk.WRITE


def test_ocr_without_vision_model_clear_error(monkeypatch):
    monkeypatch.delenv("VISION_MODEL", raising=False)
    from capabilities.tools.multimodal import ImageOCR
    r = asyncio.run(ImageOCR().invoke({"url": "https://x/y.png"}, None))
    assert not r.ok and "VISION_MODEL" in r.error


def test_imagegen_without_model_clear_error(monkeypatch):
    # openai 路径:有 key 但没配模型 → 明确报缺 IMAGE_MODEL
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_API_KEY", "test-key")
    from capabilities.tools.multimodal import ImageGenerate
    r = asyncio.run(ImageGenerate().invoke({"prompt": "a cat"}, None))
    assert not r.ok and "IMAGE_MODEL" in r.error


def test_imagegen_without_key_clear_error(monkeypatch):
    # 没 key → 明确报缺 IMAGE_API_KEY(无论 provider)
    monkeypatch.delenv("IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from capabilities.tools.multimodal import ImageGenerate
    r = asyncio.run(ImageGenerate().invoke({"prompt": "a cat"}, None))
    assert not r.ok and "IMAGE_API_KEY" in r.error
