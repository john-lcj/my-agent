"""系统管理端点：update + stats (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import asyncio
import json
import os
import re
import time as _time
import urllib.error
import zipfile

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

from config import Config
from core.runtime_identity import runtime_diagnostics
from server.keychain_store import secret_ref, set_secret, should_use_for_path


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _env_path() -> str:
    return os.path.join(_project_root(), ".env")


def _app_support_root() -> str:
    return os.path.dirname(_project_root())


def _write_env_value(key: str, value: str) -> None:
    path = _env_path()
    lines: list[str] = []
    if os.path.isfile(path):
      with open(path, "r", encoding="utf-8") as f:
          lines = f.readlines()
    found = False
    out: list[str] = []
    for line in lines:
        raw = line.lstrip()
        if raw.startswith(f"{key}="):
            out.append(f"{key}={value}\n")
            found = True
        else:
            out.append(line)
    if not found:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


def _current_version() -> str:
    try:
        import re
        text = open(os.path.join(_project_root(), "pyproject.toml"), encoding="utf-8").read()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "0.1.0"


def _latest_update_manifest() -> dict:
    import urllib.request

    url = os.environ.get(
        "CAPTAIN_UPDATE_MANIFEST",
        "https://github.com/john-lcj/my-agent/releases/latest/download/latest.json",
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        value = json.loads(resp.read().decode("utf-8"))
    if not isinstance(value, dict) or not value.get("version"):
        raise ValueError("invalid Captain update manifest")
    return value


def _version_tuple(raw: str) -> tuple[int, int, int]:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(raw or "").strip())
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0)


def _manifest_platform_entry(manifest: dict) -> dict:
    machine = os.uname().machine if hasattr(os, "uname") else "x86_64"
    if os.name == "nt":
        candidates = ("windows-x86_64", "windows-x86_64-nsis")
    elif hasattr(os, "uname") and os.uname().sysname == "Darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        candidates = (f"darwin-{arch}", f"macos-{arch}")
    else:
        candidates = (f"linux-{machine}",)
    platforms = manifest.get("platforms") or {}
    for key in candidates:
        entry = platforms.get(key)
        if isinstance(entry, dict):
            return entry
    return {}


def _release_page_from_asset(url: str) -> str:
    match = re.match(r"^(https://github\.com/[^/]+/[^/]+)/releases/download/([^/]+)/", url or "")
    return f"{match.group(1)}/releases/tag/{match.group(2)}" if match else (
        "https://github.com/john-lcj/my-agent/releases"
    )


_SECRET_REPLACEMENTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"ghp_[A-Za-z0-9_]{20,}"), "ghp_<redacted>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "github_pat_<redacted>"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-<redacted>"),
    (re.compile(r"CAPT-PRO-[A-Z0-9]{4}(?:-[A-Z0-9]{4}){1,}", re.I), "CAPT-PRO-<redacted>"),
    (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 <redacted>"),
    (re.compile(r"(?i)\b(X-Agent-Token\s*:?)\s*[A-Za-z0-9._~+/=\-]{4,}"), r"\1 <redacted>"),
    (re.compile(
        r"(?im)^([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASS|LICENSE_KEY)[A-Z0-9_]*\s*=\s*).+$"
    ), r"\1<redacted>"),
    (re.compile(
        r'(?i)("?(?:api[_-]?key|access[_-]?token|auth[_-]?secret|license[_-]?key|password|secret)"?\s*:\s*)"[^"]+"'
    ), r'\1"<redacted>"'),
)


def _redact_text(text: str) -> str:
    out = text or ""
    for pattern, replacement in _SECRET_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    return out


def _read_text_tail(path: str, limit: int = 200_000) -> str:
    with open(path, "rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > limit:
                f.seek(size - limit)
                prefix = f"[captain diagnostics] 文件较大，仅包含最后 {limit} bytes。\n"
            else:
                f.seek(0)
                prefix = ""
            data = f.read()
        except OSError:
            f.seek(0)
            prefix = ""
            data = f.read(limit)
    return prefix + data.decode("utf-8", errors="replace")


def _write_redacted_member(z: zipfile.ZipFile, source: str, arcname: str,
                           limit: int = 200_000) -> None:
    if not os.path.isfile(source):
        return
    z.writestr(arcname, _redact_text(_read_text_tail(source, limit=limit)))


def register_system(app, task_store, template_store, vault, ext_channels,
                    scheduler_holder, daemon_results, start_ts,
                    leader_state=None) -> None:
    """scheduler_holder = [Scheduler|None]；start_ts = 进程启动时刻（float）。"""

    @app.get("/api/stats")
    async def stats() -> JSONResponse:
        try:
            from memory.monitor_store import MonitorStore
            n_monitors = len(MonitorStore(path=f"{Config.LOG_DIR}/monitors.json").list())
        except Exception:
            n_monitors = 0
        try:
            n_conn = len(__import__("capabilities.connector_loader",
                                    fromlist=["load_connector_specs"]).load_connector_specs())
        except Exception:
            n_conn = 0
        daemon = {
            "queued_or_running": sum(1 for r in daemon_results.values()
                                     if r.get("status") in ("queued", "running")),
            "total": len(daemon_results),
        }
        token = os.environ.get("AGENT_API_TOKEN", "").strip()
        auth_secret = os.environ.get("AUTH_SECRET", "").strip()
        security = {
            "workspace_root": bool(os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()),
            "api_token": bool(token and token != "change-me-to-random-string"),
            "auth_secret": bool(auth_secret and auth_secret != "captain-dev-secret-change-me-in-prod"),
            "email_allowlist": bool(
                os.environ.get("EMAIL_ALLOWED_SENDERS", "").strip()
                or os.environ.get("EMAIL_ALLOWED_RECIPIENTS", "").strip()
            ),
            "web_host": os.environ.get("AGENT_WEB_HOST", "127.0.0.1"),
            "web_port": os.environ.get("AGENT_WEB_PORT", "8000"),
        }
        return JSONResponse({
            "uptime_sec":       round(_time.time() - start_ts, 1),
            "sessions":         0,  # 避免循环引用；前端不展示此字段
            "scheduled_tasks":  len(task_store.list()),
            "monitors":         n_monitors,
            "connectors":       n_conn,
            "templates":        len(template_store.list()),
            "secrets":          len(vault.list()) if vault else 0,
            "channels":         list(ext_channels.keys()),
            "daemon":           daemon,
            "scheduler_running": bool(
                scheduler_holder[0] is not None
                and getattr(scheduler_holder[0], "_running", False)
            ),
            "leader": dict(leader_state or {}),
            "security":         security,
        })

    @app.post("/api/system/security/access-token")
    async def set_access_token(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = str(body.get("access_token") or "").strip()
        if not token:
            return JSONResponse({"ok": False, "error": "访问码不能为空"}, status_code=400)
        if len(token) < 4:
            return JSONResponse({"ok": False, "error": "访问码至少 4 位"}, status_code=400)
        if len(token) > 128 or any(ch.isspace() for ch in token):
            return JSONResponse({"ok": False, "error": "访问码不能包含空白，且长度不能超过 128"}, status_code=400)
        _write_env_value("AGENT_API_TOKEN", token)
        if should_use_for_path(_project_root()):
            set_secret(secret_ref("env", "AGENT_API_TOKEN"), token)
        os.environ["AGENT_API_TOKEN"] = token
        return JSONResponse({"ok": True, "configured": True})

    @app.get("/api/system/update/check")
    async def system_update_check() -> JSONResponse:
        current = _current_version()
        try:
            manifest = _latest_update_manifest()
            latest = str(manifest.get("version") or "").lstrip("v")
            entry = _manifest_platform_entry(manifest)
            if not entry or not entry.get("signature"):
                raise ValueError("the update manifest has no signed artifact for this platform")
            url = str(entry.get("url") or "")
            return JSONResponse({
                "ok": True,
                "current": current,
                "latest": latest or current,
                "already_latest": bool(
                    latest and _version_tuple(latest) <= _version_tuple(current)
                ),
                "download_url": url,
                "release_url": _release_page_from_asset(url),
                "signed": bool(entry.get("signature")),
                "contract_version": 1,
            })
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return JSONResponse({
                    "ok": True,
                    "current": current,
                    "latest": current,
                    "already_latest": True,
                    "release_missing": True,
                    "message": "当前 GitHub 仓库还没有发布安装包。请先在 GitHub 创建 Release 并上传 DMG 后再使用自动更新。",
                    "release_url": "https://github.com/john-lcj/my-agent/releases",
                })
            return JSONResponse({"ok": False, "current": current, "error": f"GitHub 返回 HTTP {e.code}"}, status_code=502)
        except Exception as e:
            return JSONResponse({"ok": False, "current": current, "error": str(e)}, status_code=500)

    @app.get("/api/system/diagnostics")
    async def diagnostics_status() -> JSONResponse:
        root = _project_root()
        identity = runtime_diagnostics(root, Config.LOG_DIR)
        return JSONResponse({
            "ok": True,
            "project_root": root,
            "log_dir": Config.LOG_DIR,
            "desktop": os.environ.get("CAPTAIN_DESKTOP", "") == "1",
            "keychain": should_use_for_path(root),
            "python": os.sys.executable,
            "web_host": os.environ.get("AGENT_WEB_HOST", "127.0.0.1"),
            "web_port": os.environ.get("AGENT_WEB_PORT", "8000"),
            "pid": os.getpid(),
            "leader": dict(leader_state or {}),
            **identity,
        })

    @app.post("/api/system/logs/open")
    async def open_logs() -> JSONResponse:
        path = Config.LOG_DIR
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif os.uname().sysname == "Darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
            return JSONResponse({"ok": True, "path": path})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e), "path": path}, status_code=500)

    @app.get("/api/system/diagnostics/export")
    async def export_diagnostics():
        import tempfile
        root = _project_root()
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        out_dir = os.path.join(tempfile.gettempdir(), "captain-diagnostics")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"captain-diagnostics-{stamp}.zip")
        summary = {
            "generated_at": stamp,
            "project_root": root,
            "log_dir": Config.LOG_DIR,
            "desktop": os.environ.get("CAPTAIN_DESKTOP", "") == "1",
            "keychain": should_use_for_path(root),
            "python": os.sys.executable,
            "web_host": os.environ.get("AGENT_WEB_HOST", "127.0.0.1"),
            "web_port": os.environ.get("AGENT_WEB_PORT", "8000"),
        }
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("summary.json", __import__("json").dumps(summary, ensure_ascii=False, indent=2))
            redacted_files = [
                (os.path.join(Config.LOG_DIR, "trace.jsonl"), "logs/trace.tail.jsonl"),
                (os.path.join(Config.LOG_DIR, "audit.log"), "logs/audit.tail.log"),
                (os.path.join(Config.LOG_DIR, "journal.md"), "logs/journal.tail.md"),
                (os.path.join(Config.LOG_DIR, "runtime.json"), "config/runtime.json"),
                (os.path.join(Config.LOG_DIR, "task_patterns.json"), "config/task_patterns.json"),
                (os.path.join(root, "desktop", "src-tauri", "tauri.conf.json"), "desktop/tauri.conf.json"),
            ]
            for path, arcname in redacted_files:
                _write_redacted_member(z, path, arcname)
            for name in ("backend.out.log", "backend.err.log"):
                path = os.path.join(_app_support_root(), name)
                _write_redacted_member(z, path, f"desktop/{name}")
        return FileResponse(
            out_path,
            media_type="application/zip",
            filename=os.path.basename(out_path),
        )

    @app.post("/api/system/update")
    async def system_update() -> JSONResponse:
        import subprocess
        import sys

        root = _project_root()
        if os.environ.get("CAPTAIN_DESKTOP", "") == "1" or not os.path.isdir(
            os.path.join(root, ".git")
        ):
            try:
                manifest = _latest_update_manifest()
                entry = _manifest_platform_entry(manifest)
                if not entry or not entry.get("signature"):
                    raise ValueError("the update manifest has no signed artifact for this platform")
                return JSONResponse({
                    "ok": True,
                    "desktop_updater": True,
                    "latest": str(manifest.get("version") or ""),
                    "signed": bool(entry.get("signature")),
                    "message": "请使用 Captain 桌面更新器安装并重启；更新包会先验证签名。",
                })
            except Exception as e:
                return JSONResponse(
                    {"ok": False, "error": f"检查签名更新清单失败:{e}"},
                    status_code=502,
                )

        script = os.path.join(root, "scripts", "update.sh")
        if os.name == "nt" or not os.path.isfile(script):
            return JSONResponse(
                {"ok": False, "error": "当前开发环境没有可用的安全更新脚本"},
                status_code=501,
            )
        try:
            result = subprocess.run(
                ["bash", script],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=420,
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "update failed").strip()
            return JSONResponse({"ok": False, "error": error}, status_code=409)

        already_latest = "Already current" in result.stdout
        if not already_latest:
            async def _restart():
                await asyncio.sleep(1)
                port = int(os.environ.get("AGENT_WEB_PORT", "8000"))
                os.chdir(root)
                os.execve(
                    sys.executable,
                    [sys.executable, "-m", "uvicorn", "server.app:app",
                     "--host", "127.0.0.1", "--port", str(port)],
                    {**os.environ, "AGENT_WEB_PORT": str(port)},
                )

            asyncio.create_task(_restart())
        return JSONResponse({
            "ok": True,
            "already_latest": already_latest,
            "log": result.stdout[-4000:],
        })
