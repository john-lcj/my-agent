"""文生图 Runware 后端 —— mock httpx,验证 provider 判定 + 落盘(不打真网络)。"""
from __future__ import annotations

import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.multimodal import ImageGenerate, _parse_size

# 1x1 透明 PNG
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYGAAAAAEAAH"
            "2FzhVAAAAAElFTkSuQmCC")


def test_parse_size_rounds_to_64():
    assert _parse_size("1024x768") == (1024, 768)
    assert _parse_size("1000x1000") == (1024, 1024)   # 取整到 64 倍数
    assert _parse_size("乱写") == (1024, 1024)          # 容错
    w, h = _parse_size("5000x10")
    assert w == 2048 and h == 128                       # 夹边界


def test_provider_detection(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    monkeypatch.setenv("IMAGE_MODEL", "runware:100@1")
    assert ImageGenerate._provider() == "runware"      # 按模型id猜
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    assert ImageGenerate._provider() == "openai"       # 显式优先


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
    def json(self):
        return self._p
    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, json=None, headers=None):
        # 校验确实带了 Bearer 和 imageInference 任务
        assert headers and headers["Authorization"].startswith("Bearer ")
        assert json and json[0]["taskType"] == "imageInference"
        return _FakeResp({"data": [{"imageBase64Data": _PNG_B64}]})


def test_runware_generate_saves_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IMAGE_PROVIDER", "runware")
    monkeypatch.setenv("IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("IMAGE_MODEL", "runware:100@1")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    cap = ImageGenerate()
    res = asyncio.run(cap.invoke({"prompt": "日出", "name": "日出.png"}, ctx=None))
    assert res.ok, res.error
    out = tmp_path / "产物" / "日出.png"
    assert out.is_file()
    assert out.read_bytes() == base64.b64decode(_PNG_B64)


def test_runware_surfaces_api_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IMAGE_PROVIDER", "runware")
    monkeypatch.setenv("IMAGE_API_KEY", "bad-key")

    class _ErrClient(_FakeClient):
        async def post(self, url, json=None, headers=None):
            return _FakeResp({"errors": [{"message": "Invalid API key"}]})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _ErrClient)

    res = asyncio.run(ImageGenerate().invoke({"prompt": "x"}, ctx=None))
    assert not res.ok and "Invalid API key" in res.error


def test_missing_key_is_honest(monkeypatch):
    monkeypatch.delenv("IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = asyncio.run(ImageGenerate().invoke({"prompt": "x"}, ctx=None))
    assert not res.ok and "API_KEY" in res.error


def test_provider_detection_zhipu(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    monkeypatch.setenv("IMAGE_MODEL", "cogview-3-flash")
    assert ImageGenerate._provider() == "zhipu"      # 按模型id猜


class _ImgResp:
    content = base64.b64decode(_PNG_B64)
    def raise_for_status(self):
        pass


class _ZhipuClient(_FakeClient):
    async def post(self, url, json=None, headers=None):
        assert headers["Authorization"].startswith("Bearer ")
        assert json["model"].startswith("cogview")
        return _FakeResp({"data": [{"url": "https://img.example/abc.png"}]})
    async def get(self, url):
        return _ImgResp()


def test_zhipu_generate_saves_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IMAGE_PROVIDER", "zhipu")
    monkeypatch.setenv("IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("IMAGE_MODEL", "cogview-3-flash")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _ZhipuClient)
    res = asyncio.run(ImageGenerate().invoke({"prompt": "日出", "name": "日出.png"}, ctx=None))
    assert res.ok, res.error
    out = tmp_path / "产物" / "日出.png"
    assert out.is_file() and out.read_bytes() == base64.b64decode(_PNG_B64)
