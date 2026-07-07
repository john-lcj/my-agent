"""产物预览、文件列表、文件上传端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

_IMAGE_RAW_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "gif", "svg"})
_IMAGE_RAW_MAX = 10 * 1024 * 1024


def register_artifacts(app, resolve_in_workspace) -> None:

    def _artifacts_dir() -> tuple:
        ws = os.path.realpath(os.path.expanduser(
            os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()))
        art = os.environ.get("AGENT_ARTIFACTS_DIR", "").strip()
        art = os.path.realpath(os.path.expanduser(art)) if art else os.path.join(ws, "产物")
        return (art, True) if os.path.isdir(art) else (ws, False)

    @app.get("/api/artifact/raw")
    async def read_artifact_raw(path: str = ""):
        ok, real, reason = resolve_in_workspace(path)
        if not ok:
            return JSONResponse({"ok": False, "error": reason}, status_code=400)
        if not os.path.isfile(real):
            return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=400)
        ext = os.path.splitext(real)[1].lower().lstrip(".")
        if ext not in _IMAGE_RAW_EXTS:
            return JSONResponse({"ok": False, "error": "非图片类型"}, status_code=400)
        if os.path.getsize(real) > _IMAGE_RAW_MAX:
            return JSONResponse({"ok": False, "error": "图片过大(>10MB)"}, status_code=400)
        media = f"image/{'jpeg' if ext == 'jpg' else ext}"
        return FileResponse(real, media_type=media, filename=os.path.basename(real))

    @app.get("/api/artifact")
    async def read_artifact(path: str = "") -> JSONResponse:
        ok, real, reason = resolve_in_workspace(path)
        if not ok:
            return JSONResponse({"ok": False, "error": reason}, status_code=400)
        if not os.path.isfile(real) or os.path.getsize(real) > 2 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "文件不存在或过大(>2MB)"}, status_code=400)
        ext = os.path.splitext(real)[1].lower().lstrip(".")
        if ext in _IMAGE_RAW_EXTS:
            return JSONResponse({"ok": True, "kind": "image", "ext": ext,
                                 "name": os.path.basename(real), "content": ""})
        kind = ("html" if ext in ("html", "htm") else
                "markdown" if ext == "md" else
                "code" if ext in ("py", "js", "ts", "css", "json", "sh", "yaml", "yml") else "text")
        try:
            with open(real, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return JSONResponse({"ok": True, "kind": kind, "ext": ext,
                             "name": os.path.basename(real), "content": content})

    @app.get("/api/files")
    async def list_files(dir: str = "") -> JSONResponse:
        base = (os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd())
        base = os.path.realpath(os.path.expanduser(base))
        target = base if not dir else os.path.realpath(os.path.join(base, dir))
        if target != base and not target.startswith(base + os.sep):
            return JSONResponse({"ok": False, "error": "越界"}, status_code=400)
        if not os.path.isdir(target):
            return JSONResponse({"ok": False, "error": "目录不存在"}, status_code=400)
        _SKIP = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache",
                 ".DS_Store", "my_agent.egg-info", ".cursor"}
        items = []
        try:
            for name in sorted(os.listdir(target)):
                if name in _SKIP or name.startswith("."):
                    continue
                full = os.path.join(target, name)
                rel = os.path.relpath(full, base)
                isdir = os.path.isdir(full)
                items.append({"name": name, "rel": rel, "type": "dir" if isdir else "file",
                              "ext": "" if isdir else os.path.splitext(name)[1].lstrip(".").lower()})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        items.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        return JSONResponse({"ok": True, "root": os.path.basename(base), "dir": dir, "items": items})

    @app.get("/api/artifacts")
    async def list_artifacts(q: str = "", limit: int = 200) -> JSONResponse:
        base, _ = _artifacts_dir()
        _EXTS = {"md", "html", "htm", "docx", "xlsx", "pptx", "pdf", "csv", "txt",
                 "json", "png", "jpg", "jpeg", "gif", "svg", "py", "js", "ipynb", "zip"}
        _SKIP = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache",
                 "my_agent.egg-info", ".cursor", "logs", "tests", "outputs_cache"}
        ql = (q or "").strip().lower()
        items = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lstrip(".").lower()
                if ext not in _EXTS or (ql and ql not in name.lower()):
                    continue
                full = os.path.join(root, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                items.append({"name": name, "rel": os.path.relpath(full, base),
                              "ext": ext, "size": st.st_size, "mtime": st.st_mtime})
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return JSONResponse({"ok": True, "root": os.path.basename(base), "dir": base,
                             "items": items[:max(1, min(int(limit or 200), 500))]})

    @app.post("/api/artifacts")
    async def save_artifact(request: Request) -> JSONResponse:
        b = await request.json()
        name = os.path.basename(str(b.get("filename") or b.get("name") or "").strip())
        name = name.replace("..", "_")
        if not name:
            return JSONResponse({"ok": False, "error": "缺少文件名"}, status_code=400)
        content = b.get("content", "")
        if not isinstance(content, str):
            return JSONResponse({"ok": False, "error": "content 必须是字符串"}, status_code=400)
        ws = os.path.realpath(os.path.expanduser(
            os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()))
        art = os.environ.get("AGENT_ARTIFACTS_DIR", "").strip()
        base = os.path.realpath(os.path.expanduser(art)) if art else os.path.join(ws, "产物")
        os.makedirs(base, exist_ok=True)
        dest = os.path.realpath(os.path.join(base, name))
        if dest != base and not dest.startswith(base + os.sep):
            return JSONResponse({"ok": False, "error": "越界"}, status_code=400)
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return JSONResponse({"ok": True, "name": name, "path": dest,
                             "rel": os.path.relpath(dest, base)})

    @app.post("/api/artifacts/reveal")
    async def reveal_artifacts() -> JSONResponse:
        import platform, subprocess
        ws = os.path.realpath(os.path.expanduser(
            os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()))
        art = os.environ.get("AGENT_ARTIFACTS_DIR", "").strip()
        art = os.path.realpath(os.path.expanduser(art)) if art else os.path.join(ws, "产物")
        os.makedirs(art, exist_ok=True)
        try:
            sysname = platform.system()
            if sysname == "Darwin":
                subprocess.Popen(["open", art])
            elif sysname == "Windows":
                subprocess.Popen(["explorer", art])
            else:
                subprocess.Popen(["xdg-open", art])
            return JSONResponse({"ok": True, "dir": art})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e), "dir": art})

    @app.post("/api/upload")
    async def upload_file(request: Request) -> JSONResponse:
        import base64
        b = await request.json()
        name = os.path.basename(str(b.get("name", "upload.bin"))).replace("..", "_") or "upload.bin"
        try:
            data = base64.b64decode(b.get("content_b64", ""))
        except Exception:
            return JSONResponse({"ok": False, "error": "content_b64 解码失败"}, status_code=400)
        if len(data) > 20 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "文件超过 20MB"}, status_code=400)
        base_dir = os.path.realpath(os.path.expanduser(
            os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()))
        rel_path = str(b.get("rel_path", "")).strip().replace("\\", "/").lstrip("/")
        if rel_path:
            parts = [p.replace("..", "_") for p in rel_path.split("/") if p and p not in (".", "..")]
            if not parts:
                return JSONResponse({"ok": False, "error": "无效路径"}, status_code=400)
            dest = os.path.realpath(os.path.join(base_dir, *parts))
            if dest != base_dir and not dest.startswith(base_dir + os.sep):
                return JSONResponse({"ok": False, "error": "越界"}, status_code=400)
        else:
            updir = os.path.join(base_dir, "uploads")
            os.makedirs(updir, exist_ok=True)
            dest = os.path.join(updir, name)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        rel = os.path.relpath(dest, base_dir)
        return JSONResponse({"ok": True, "path": dest, "name": name, "rel": rel})
