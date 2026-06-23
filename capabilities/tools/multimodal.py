"""多模态广度 —— OCR(看图取字)+ 图像生成。

image.ocr      复用已配置的视觉模型(VISION_MODEL),把扫描件/截图/表格图转成文字,
               尽量保留版面与表格结构。无需额外 key。
image.generate 文生图:支持两种后端,由 IMAGE_PROVIDER 决定(不配则按线索自动判断):
               · runware —— Runware REST(任务数组/imageInference),IMAGE_MODEL 默认 runware:100@1;
               · openai  —— OpenAI 兼容的 images.generate 端点。
               公共配置:IMAGE_API_KEY(留空回退 OPENAI_API_KEY)/ IMAGE_MODEL / IMAGE_BASE_URL。
               产物保存到工作区 产物/ 目录。
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

from core.types import CapabilityResult, Risk


def _parse_size(s: str, default: int = 1024) -> tuple[int, int]:
    """'1024x768' → (1024, 768);各维取整到 64 的倍数并夹到 128~2048(Runware/SD 要求)。"""
    try:
        w, h = (int(x) for x in str(s).lower().split("x", 1))
    except Exception:
        w = h = default
    def _round64(v: int) -> int:
        v = max(128, min(2048, int(v)))
        return max(128, min(2048, round(v / 64) * 64))
    return _round64(w), _round64(h)


def _artifacts_dir() -> str:
    ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    d = os.path.join(ws, "产物")
    os.makedirs(d, exist_ok=True)
    return d


def _image_data_uri(path: str) -> tuple[str, str]:
    base = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    full = os.path.realpath(os.path.join(base, path)) if not os.path.isabs(path) else path
    if not os.path.isfile(full):
        return "", f"图片不存在:{path}"
    ext = os.path.splitext(full)[1].lstrip(".").lower() or "png"
    try:
        with open(full, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return "", str(e)
    return f"data:image/{ext};base64,{b64}", ""


class ImageOCR:
    name = "image.ocr"
    risk = Risk.READ
    description = ("把图片里的文字提取出来(扫描件/截图/表格图),尽量保留版面与表格结构。"
                  "复用视觉模型,需先配置 VISION_MODEL。")
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "工作区内图片路径(png/jpg/webp)"},
            "url": {"type": "string", "description": "或图片 URL(与 path 二选一)"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        if not os.environ.get("VISION_MODEL", "").strip():
            return CapabilityResult(ok=False, error="未配置 VISION_MODEL,无法 OCR(同视觉能力)")
        path = str(args.get("path", "")).strip()
        url = str(args.get("url", "")).strip()
        image_url = url
        if path:
            image_url, err = _image_data_uri(path)
            if err:
                return CapabilityResult(ok=False, error=err)
        if not image_url:
            return CapabilityResult(ok=False, error="需要 path 或 url")
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return CapabilityResult(ok=False, error="未安装 openai SDK")
        api_key = (os.environ.get("VISION_API_KEY", "").strip()
                   or os.environ.get("OPENAI_API_KEY", "").strip())
        if not api_key:
            return CapabilityResult(ok=False, error="未配置 VISION_API_KEY(或 OPENAI_API_KEY)")
        prompt = ("请逐字转写这张图片中的所有文字,保持原有阅读顺序;"
                  "若包含表格,用 Markdown 表格还原其行列结构。只输出转写内容,不要额外解释。")
        try:
            client = AsyncOpenAI(api_key=api_key,
                                 base_url=os.environ.get("VISION_BASE_URL", "").strip() or None)
            resp = await client.chat.completions.create(
                model=os.environ["VISION_MODEL"].strip(),
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]}],
            )
            return CapabilityResult(ok=True, output=resp.choices[0].message.content or "")
        except Exception as e:
            return CapabilityResult(ok=False, error=f"OCR 调用失败: {e}")


class ImageGenerate:
    name = "image.generate"
    risk = Risk.WRITE  # 产出文件
    description = ("按文字描述生成一张图片,保存到工作区 产物/。"
                  "需配置 IMAGE_MODEL(及 IMAGE_API_KEY 或 OPENAI_API_KEY)。")
    schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "图片内容描述"},
            "name": {"type": "string", "description": "保存文件名(可选,默认按时间)"},
            "size": {"type": "string", "description": "尺寸,如 1024x1024(可选)"},
        },
        "required": ["prompt"],
    }

    @staticmethod
    def _provider() -> str:
        """优先看 IMAGE_PROVIDER;没配则按线索猜(runware 模型id 或 base_url)。默认 openai。"""
        p = os.environ.get("IMAGE_PROVIDER", "").strip().lower()
        if p:
            return p
        model = os.environ.get("IMAGE_MODEL", "").strip().lower()
        base = os.environ.get("IMAGE_BASE_URL", "").strip().lower()
        if model.startswith("runware:") or "runware" in base:
            return "runware"
        return "openai"

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            return CapabilityResult(ok=False, error="缺少 prompt")
        api_key = (os.environ.get("IMAGE_API_KEY", "").strip()
                   or os.environ.get("OPENAI_API_KEY", "").strip())
        if not api_key:
            return CapabilityResult(ok=False, error="未配置 IMAGE_API_KEY(或 OPENAI_API_KEY)")

        provider = self._provider()
        try:
            if provider == "runware":
                raw, ext = await self._gen_runware(prompt, api_key, args)
            else:
                raw, ext = await self._gen_openai(prompt, api_key, args)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"图像生成失败({provider}): {e}")

        name = str(args.get("name", "")).strip() or f"image_{int(time.time())}.{ext}"
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            name += f".{ext}"
        path = os.path.join(_artifacts_dir(), name)
        try:
            with open(path, "wb") as f:
                f.write(raw)
        except OSError as e:
            return CapabilityResult(ok=False, error=str(e))
        return CapabilityResult(ok=True, output=f"已生成图片:{path}")

    async def _gen_openai(self, prompt: str, api_key: str, args: dict) -> tuple[bytes, str]:
        model = os.environ.get("IMAGE_MODEL", "").strip()
        if not model:
            raise RuntimeError("未配置 IMAGE_MODEL")
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key,
                             base_url=os.environ.get("IMAGE_BASE_URL", "").strip() or None)
        resp = await client.images.generate(
            model=model, prompt=prompt,
            size=str(args.get("size", "1024x1024")) or "1024x1024",
            response_format="b64_json", n=1)
        return base64.b64decode(resp.data[0].b64_json), "png"

    async def _gen_runware(self, prompt: str, api_key: str, args: dict) -> tuple[bytes, str]:
        """Runware REST:POST 任务数组到 /v1,要 base64 直接落盘(省二次下载、少出站)。"""
        import httpx
        base = os.environ.get("IMAGE_BASE_URL", "").strip() or "https://api.runware.ai/v1"
        model = os.environ.get("IMAGE_MODEL", "").strip() or "runware:100@1"
        w, h = _parse_size(args.get("size", "1024x1024"))
        task = {
            "taskType": "imageInference",
            "taskUUID": str(uuid.uuid4()),
            "positivePrompt": prompt,
            "width": w, "height": h,
            "model": model, "numberResults": 1,
            "outputType": "base64Data", "outputFormat": "PNG",
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(base, json=[task], headers=headers)
            j = r.json()
            if isinstance(j, dict) and j.get("errors"):
                msg = "; ".join(e.get("message", str(e)) for e in j["errors"])
                raise RuntimeError(msg or f"HTTP {r.status_code}")
            r.raise_for_status()
            data = (j or {}).get("data") or []
            if not data:
                raise RuntimeError(f"无返回数据:{str(j)[:200]}")
            item = data[0]
            b64 = item.get("imageBase64Data")
            if b64:
                return base64.b64decode(b64), "png"
            url = item.get("imageURL")
            if url:
                img = await client.get(url)
                img.raise_for_status()
                return img.content, "png"
            raise RuntimeError(f"返回里既无 base64 也无 URL:{str(item)[:200]}")
