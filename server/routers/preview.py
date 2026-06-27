"""产物真实预览(/preview/<工作区相对路径>)—— 把工作区文件当真实 URL 服务。

用途:制作的网页(HTML)能作为真页面渲染——相对资源(./style.css、图片)能解析、
能在浏览器新标签打开看真效果,而不只是 iframe srcdoc 的自包含内嵌预览。

安全:路径走 resolve_in_workspace 校验(限工作区内、拦 .env 等);本地优先。
注:/preview 不在 /api 下,远程暴露(0.0.0.0)时不带控制面 token 校验——
它服务的是你自己的产物文件,等同于服务前端静态资源,按需自行评估。
"""
from __future__ import annotations

import os
from typing import Callable

from fastapi.responses import FileResponse, PlainTextResponse

_MEDIA = {
    "html": "text/html; charset=utf-8", "htm": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8", "js": "application/javascript; charset=utf-8",
    "json": "application/json; charset=utf-8", "svg": "image/svg+xml",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
}
_MAX = 25 * 1024 * 1024


def register_preview(app, resolve_in_workspace: Callable[[str], tuple]) -> None:
    @app.get("/preview/{subpath:path}")
    async def preview(subpath: str):
        ok, real, reason = resolve_in_workspace(subpath)
        if not ok:
            return PlainTextResponse(reason or "bad path", status_code=400)
        if not os.path.isfile(real):
            return PlainTextResponse("文件不存在", status_code=404)
        if os.path.getsize(real) > _MAX:
            return PlainTextResponse("文件过大(>25MB)", status_code=400)
        ext = os.path.splitext(real)[1].lower().lstrip(".")
        media = _MEDIA.get(ext, "application/octet-stream")
        return FileResponse(real, media_type=media)
