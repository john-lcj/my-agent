"""高音质语音代理 —— 用小米 MiMo 的 ASR/TTS(复用已配的视觉 key,服务端调,key 不出浏览器)。

TTS:POST {base}/chat/completions,model=mimo-v2-tts,body 带 audio{format,voice};
     返回 choices[0].message.audio.data(base64 音频)。
ASR:同 chat 接口,把音频(WAV/MP3,base64)作为输入,返回识别文本。
配置(默认复用小米视觉那套):
  VOICE_API_KEY  / VISION_API_KEY / 设置页「小米视觉」model_keys
  VOICE_BASE_URL / VISION_BASE_URL(默认 https://api.xiaomimimo.com/v1)
  VOICE_TTS_MODEL(默认 mimo-v2-tts) / VOICE_TTS_VOICE(默认 mimo_default)
  VOICE_ASR_MODEL(默认 mimo-v2.5-asr)
"""
from __future__ import annotations

import base64
import os


def _xiaomi_store_key() -> tuple[str, str]:
    """从 model_keys 读取小米视觉(语音与视觉共用)配置。"""
    try:
        from config import Config
        from server.model_keys import ModelKeyStore, is_real_key
        cfg = ModelKeyStore(path=f"{Config.LOG_DIR}/model_keys.json").get_config("xiaomi_vision")
        key = (cfg.get("key") or "").strip()
        base = (cfg.get("base_url") or "").strip().rstrip("/")
        return (key if is_real_key(key) else ""), base
    except Exception:
        return "", ""


def _cfg() -> tuple[str, str]:
    store_key, store_base = _xiaomi_store_key()
    key = (os.environ.get("VOICE_API_KEY", "").strip()
           or os.environ.get("VISION_API_KEY", "").strip()
           or store_key)
    base = (os.environ.get("VOICE_BASE_URL", "").strip()
            or os.environ.get("VISION_BASE_URL", "").strip()
            or store_base
            or "https://api.xiaomimimo.com/v1").rstrip("/")
    return key, base


def _headers(key: str) -> dict:
    # 小米示例用 api-key 头;同时带 Authorization 以兼容标准 OpenAI 协议。
    return {"Content-Type": "application/json",
            "Authorization": f"Bearer {key}", "api-key": key}


async def tts(text: str, voice: str = "", style: str = "", fmt: str = "wav") -> tuple[bytes, str]:
    key, base = _cfg()
    if not key:
        raise RuntimeError("未配置语音 API Key(VOICE_API_KEY 或 VISION_API_KEY)")
    import httpx
    model = os.environ.get("VOICE_TTS_MODEL", "mimo-v2-tts")
    voice = voice or os.environ.get("VOICE_TTS_VOICE", "mimo_default")
    content = (f"<style>{style}</style>" if style else "") + (text or "")
    payload = {"model": model,
               "messages": [{"role": "assistant", "content": content}],
               "audio": {"format": fmt, "voice": voice}}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(base + "/chat/completions", json=payload, headers=_headers(key))
    r.raise_for_status()
    audio = r.json()["choices"][0]["message"]["audio"]
    return base64.b64decode(audio["data"]), audio.get("format", fmt)


async def asr(audio_bytes: bytes, fmt: str = "wav") -> str:
    key, base = _cfg()
    if not key:
        raise RuntimeError("未配置语音 API Key(VOICE_API_KEY 或 VISION_API_KEY)")
    import httpx
    model = os.environ.get("VOICE_ASR_MODEL", "mimo-v2.5-asr")
    b64 = base64.b64encode(audio_bytes).decode()
    payload = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}},
    ]}]}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(base + "/chat/completions", json=payload, headers=_headers(key))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""
