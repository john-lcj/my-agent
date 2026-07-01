"""前端静态服务(/、/styles.css、/app.js、/app.boot.js)—— 从 app.py 抽出。

前端已从单文件拆成 index.html + styles.css + app.js + app.boot.js(传统 script,
全局作用域不变)。这里用**显式路由**只服务这几个白名单资源,不开放整目录,
也不用通配路由(`/{x}` 会抢掉 /healthz、/manifest.json 等),避免误伤。
"""
from __future__ import annotations

import os

from fastapi.responses import FileResponse, HTMLResponse

_ASSETS = {
    "styles.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "app.boot.js": "application/javascript; charset=utf-8",
}


def register_frontend(app, frontend_dir: str) -> None:
    @app.get("/")
    async def index() -> HTMLResponse:
        index_path = os.path.join(frontend_dir, "index.html")
        if not os.path.isfile(index_path):
            return HTMLResponse(
                "<h1>前端文件缺失</h1>"
                f"<p>找不到 <code>{index_path}</code>。</p>"
                "<p>请在完整项目目录启动服务。</p>",
                status_code=503,
            )
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(
                f.read(),
                headers={"Cache-Control": "no-store, max-age=0"},
            )

    def _make_asset_route(fname: str, media: str):
        async def _serve():
            path = os.path.join(frontend_dir, fname)
            if not os.path.isfile(path):
                return HTMLResponse("Not Found", status_code=404)
            return FileResponse(
                path,
                media_type=media,
                headers={"Cache-Control": "no-store, max-age=0"},
            )
        return _serve

    for fname, media in _ASSETS.items():
        app.get(f"/{fname}")(_make_asset_route(fname, media))
