"""系统管理端点：update + stats (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import asyncio
import os
import time as _time

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _env_path() -> str:
    return os.path.join(_project_root(), ".env")


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


def register_system(app, task_store, template_store, vault, ext_channels,
                    scheduler_holder, daemon_results, start_ts) -> None:
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
            "email_allowlist": bool(os.environ.get("EMAIL_ALLOWED_RECIPIENTS", "").strip()),
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
            "scheduler_running": scheduler_holder[0] is not None,
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
        os.environ["AGENT_API_TOKEN"] = token
        return JSONResponse({"ok": True, "configured": True})

    @app.post("/api/system/update")
    async def system_update() -> JSONResponse:
        import subprocess, sys
        root = _project_root()

        import shutil
        portable_git = os.path.join(root, "runtime", "git", "bin", "git.exe")
        if os.path.exists(portable_git):
            git_cmd = portable_git
        elif shutil.which("git"):
            git_cmd = "git"
        else:
            return JSONResponse({"ok": False, "error": "未找到 git"}, status_code=500)

        portable_pip = os.path.join(root, "runtime", "python", "Scripts", "pip.exe")
        venv_pip_win = os.path.join(root, ".venv", "Scripts", "pip.exe")
        venv_pip_unix = os.path.join(root, ".venv", "bin", "pip")
        if os.path.exists(portable_pip):
            pip_cmd = [portable_pip]
        elif os.path.exists(venv_pip_win):
            pip_cmd = [venv_pip_win]
        elif os.path.exists(venv_pip_unix):
            pip_cmd = [venv_pip_unix]
        else:
            pip_cmd = [sys.executable, "-m", "pip"]

        git_env = os.environ.copy()
        git_bin_dir = os.path.dirname(git_cmd)
        git_env["PATH"] = git_bin_dir + os.pathsep + git_env.get("PATH", "")

        try:
            fetch = subprocess.run(
                [git_cmd, "-C", root, "fetch", "origin", "main"],
                capture_output=True, text=True, timeout=60, env=git_env,
            )
            if fetch.returncode != 0:
                return JSONResponse({"ok": False, "error": fetch.stderr.strip()}, status_code=500)
            local = subprocess.run(
                [git_cmd, "-C", root, "rev-parse", "HEAD"],
                capture_output=True, text=True, env=git_env,
            ).stdout.strip()
            remote = subprocess.run(
                [git_cmd, "-C", root, "rev-parse", "FETCH_HEAD"],
                capture_output=True, text=True, env=git_env,
            ).stdout.strip()
            already_latest = (local == remote)
            if not already_latest:
                dirty = subprocess.run(
                    [git_cmd, "-C", root, "status", "--porcelain"],
                    capture_output=True, text=True, timeout=15, env=git_env,
                )
                had_stash = bool((dirty.stdout or "").strip())
                if had_stash:
                    stash = subprocess.run(
                        [git_cmd, "-C", root, "stash", "push", "--include-untracked",
                         "--message", "captain-auto-update-backup"],
                        capture_output=True, text=True, timeout=15, env=git_env,
                    )
                    if stash.returncode != 0:
                        return JSONResponse({"ok": False, "error": stash.stderr.strip()}, status_code=500)
                reset = subprocess.run(
                    [git_cmd, "-C", root, "reset", "--hard", "FETCH_HEAD"],
                    capture_output=True, text=True, timeout=30, env=git_env,
                )
                if reset.returncode != 0:
                    if had_stash:
                        subprocess.run([git_cmd, "-C", root, "stash", "pop", "--quiet"],
                                       capture_output=True, timeout=10, env=git_env)
                    return JSONResponse({"ok": False, "error": reset.stderr.strip()}, status_code=500)
                if had_stash:
                    subprocess.run([git_cmd, "-C", root, "stash", "pop", "--quiet"],
                                   capture_output=True, timeout=10, env=git_env)

            req_lock = os.path.join(root, "requirements.lock.txt")
            req_base = os.path.join(root, "requirements-base.txt")
            req_full = os.path.join(root, "requirements.txt")
            req = req_lock if os.path.exists(req_lock) else (req_base if os.path.exists(req_base) else req_full)
            if os.path.exists(req) and not already_latest:
                primary = os.environ.get("PIP_INDEX_URL", "").strip() or "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
                extra = os.environ.get("PIP_EXTRA_INDEX_URL", "").strip() or "https://mirrors.aliyun.com/pypi/simple"
                pip_result = subprocess.run(
                    pip_cmd + ["install", "-q", "-r", req,
                                "-i", primary, "--extra-index-url", extra],
                    capture_output=True, timeout=180,
                )
                if pip_result.returncode != 0:
                    err = (pip_result.stderr or b"").decode(errors="replace").strip()
                    return JSONResponse({"ok": False, "error": f"pip install 失败: {err}"}, status_code=500)
            if not already_latest:
                async def _restart():
                    await asyncio.sleep(1)
                    port = int(os.environ.get("AGENT_WEB_PORT", "8000"))
                    try:
                        subprocess.Popen(
                            [sys.executable, "-m", "uvicorn", "server.app:app",
                             "--host", "127.0.0.1", "--port", str(port)],
                            cwd=root, start_new_session=True,
                        )
                    except Exception:
                        pass
                    os._exit(0)
                asyncio.create_task(_restart())
            return JSONResponse({"ok": True, "already_latest": already_latest,
                                 "log": fetch.stderr.strip()})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
