"""语音 TTS/ASR 代理端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def register_voice(app) -> None:
    @app.post("/api/voice/tts")
    async def voice_tts(request: Request):
        from starlette.responses import Response as _Resp
        b = await request.json()
        text = str(b.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "缺少 text"}, status_code=400)
        try:
            from server.voice import tts
            audio, fmt = await tts(text, voice=b.get("voice", ""), style=b.get("style", ""))
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=502)
        media = "audio/mpeg" if fmt == "mp3" else "audio/wav"
        return _Resp(content=audio, media_type=media)

    @app.post("/api/voice/asr")
    async def voice_asr(request: Request) -> JSONResponse:
        import base64 as _b64
        ct = request.headers.get("content-type", "")
        try:
            if "application/json" in ct:
                b = await request.json()
                raw = _b64.b64decode(b.get("audio", ""))
                fmt = b.get("format", "wav")
            else:
                form = await request.form()
                up = form["audio"]
                raw = await up.read()
                fmt = "wav"
            from server.voice import asr
            text = await asr(raw, fmt)
            return JSONResponse({"ok": True, "text": text})
        except Exception as e:
            msg = str(e)[:300]
            if "401" in msg or "Unauthorized" in msg:
                msg = "语音 Key 无效或未配置,请到 设置→模型→小米视觉 填写 API Key"
            elif "未配置语音 API Key" in msg:
                msg = "未配置语音 Key,请到 设置→模型→小米视觉 填写 API Key"
            return JSONResponse({"ok": False, "error": msg}, status_code=502)
