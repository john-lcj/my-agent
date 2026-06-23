"""多模态视觉能力 —— 让 agent「看」图片/截图/图表(DeepSeek 纯文本看不了)。

可配置任意 OpenAI 兼容的视觉端点(小米 MiMo / OpenAI / 通义 等),不必改代码:
  VISION_MODEL      视觉模型 id(如小米 mimo-v2-omni、或 gpt-4o)
  VISION_BASE_URL   端点(如小米 https://api.xiaomimimo.com/v1;留空=用 OpenAI 默认)
  VISION_API_KEY    该端点的 key(留空则回退 OPENAI_API_KEY)
配了 VISION_MODEL 即启用;否则明确提示未配置。
"""
from __future__ import annotations

import base64
import os
from typing import Any

from core.types import CapabilityResult, Risk


def vision_configured() -> bool:
    return bool(os.environ.get("VISION_MODEL", "").strip())


class VisionSee:
    name = "vision.see"
    risk = Risk.READ
    description = ("看一张图片/截图/图表并回答关于它的问题(理解视觉内容)。"
                  "需先配置 VISION_MODEL;未配置会提示。")
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "工作区内图片文件路径(png/jpg/webp 等)"},
            "url": {"type": "string", "description": "或:图片 URL(与 path 二选一)"},
            "question": {"type": "string", "description": "想问关于这张图的什么"},
        },
        "required": ["question"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        if not vision_configured():
            return CapabilityResult(
                ok=False,
                error="未配置视觉模型。请在 .env 设置 VISION_MODEL=<支持图像的模型id> "
                      "并配好对应 provider 的 key(OPENAI_API_KEY / ANTHROPIC_API_KEY),即可启用。",
            )
        question = str(args.get("question", "")).strip()
        path = str(args.get("path", "")).strip()
        url = str(args.get("url", "")).strip()
        if not path and not url:
            return CapabilityResult(ok=False, error="需要 path 或 url 指定图片")

        # 组装图像输入(OpenAI 兼容的 image_url 形式;data URI 走 base64)。
        image_url = url
        if path:
            base = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
            full = os.path.realpath(os.path.join(base, path)) if not os.path.isabs(path) else path
            if not os.path.isfile(full):
                return CapabilityResult(ok=False, error=f"图片不存在:{path}")
            ext = os.path.splitext(full)[1].lstrip(".").lower() or "png"
            try:
                with open(full, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
            except OSError as e:
                return CapabilityResult(ok=False, error=str(e))
            image_url = f"data:image/{ext};base64,{b64}"

        try:
            from openai import AsyncOpenAI
        except ImportError:
            return CapabilityResult(ok=False, error="未安装 openai SDK")
        model_id = os.environ["VISION_MODEL"].strip()
        base_url = os.environ.get("VISION_BASE_URL", "").strip() or None
        api_key = (os.environ.get("VISION_API_KEY", "").strip()
                   or os.environ.get("OPENAI_API_KEY", "").strip())
        if not api_key:
            return CapabilityResult(ok=False, error="未配置 VISION_API_KEY(或 OPENAI_API_KEY)")
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            )
            return CapabilityResult(ok=True, output=resp.choices[0].message.content or "")
        except Exception as e:
            return CapabilityResult(ok=False, error=f"视觉模型调用失败: {e}")
