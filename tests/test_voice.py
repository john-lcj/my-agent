"""高音质语音回归 —— 配置解析 + 端点入参校验(离线:不发真实网络)。"""
from __future__ import annotations

import base64
import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_API_TOKEN"] = "t"
os.environ["AGENT_INBOX_WATCH"] = "0"
os.environ["AGENT_MONITOR_WATCH"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from server.app import app
import server.voice as voice

H = {"X-Agent-Token": "t"}


def _tok():
    os.environ["AGENT_API_TOKEN"] = "t"   # 其它测试可能改动,逐个请求前设回


def test_cfg_falls_back_to_vision(monkeypatch):
    monkeypatch.delenv("VOICE_API_KEY", raising=False)
    monkeypatch.setenv("VISION_API_KEY", "sk-vis")
    monkeypatch.delenv("VOICE_BASE_URL", raising=False)
    monkeypatch.delenv("VISION_BASE_URL", raising=False)
    key, base = voice._cfg()
    assert key == "sk-vis"
    assert base == "https://api.xiaomimimo.com/v1"   # 默认小米端点


def test_tts_missing_text_400():
    _tok()
    with TestClient(app) as c:
        r = c.post("/api/voice/tts", json={"text": "  "}, headers=H)
        assert r.status_code == 400


def test_asr_no_key_returns_502(monkeypatch):
    _tok()
    for k in ("VOICE_API_KEY", "VISION_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with TestClient(app) as c:
        payload = {"audio": base64.b64encode(b"RIFFxxxx").decode(), "format": "wav"}
        r = c.post("/api/voice/asr", json=payload, headers=H)
        assert r.status_code == 502
        assert "Key" in r.json().get("error", "")


def test_cfg_does_not_use_openai_for_voice(monkeypatch):
    monkeypatch.delenv("VOICE_API_KEY", raising=False)
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-be-used")
    key, _ = voice._cfg()
    assert key != "sk-openai-should-not-be-used"
    assert not key
