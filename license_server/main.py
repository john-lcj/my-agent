"""Captain 授权服务器 — 极简 FastAPI，部署在一台小 VPS。

端点:
  POST /api/license/generate  管理员批量生成 key（需 ADMIN_TOKEN）
  POST /api/license/activate  激活 key（绑定机器码 + 邮箱）
  POST /api/license/check     本地 app 验证授权状态
  GET  /healthz               健康检查
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ── 配置 ─────────────────────────────────────────────────────────────────────
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me-admin-token")
DB_PATH     = os.environ.get("DB_PATH", "license.db")
# 每个 key 最多可以在几台机器上激活
MAX_DEVICES = int(os.environ.get("MAX_DEVICES", "2"))


# ── 数据库 ────────────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS license_keys (
            key          TEXT PRIMARY KEY,
            plan         TEXT NOT NULL DEFAULT 'pro',
            months       INTEGER NOT NULL DEFAULT 12,
            max_devices  INTEGER NOT NULL DEFAULT 2,
            created_at   REAL NOT NULL,
            expires_at   REAL,
            note         TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS activations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key  TEXT NOT NULL,
            machine_id   TEXT NOT NULL,
            email        TEXT NOT NULL DEFAULT '',
            activated_at REAL NOT NULL,
            last_check   REAL NOT NULL,
            UNIQUE(license_key, machine_id)
        );
    """)
    conn.commit()
    conn.close()


# ── 工具 ─────────────────────────────────────────────────────────────────────
def _gen_key(plan: str) -> str:
    prefix = "CAPT-PRO" if plan == "pro" else "CAPT-FREE"
    uid = uuid.uuid4().hex[:12].upper()
    return f"{prefix}-{uid[:4]}-{uid[4:8]}-{uid[8:]}"


def _require_admin(request: Request) -> bool:
    provided = request.headers.get("x-admin-token", "")
    return hmac.compare_digest(provided, ADMIN_TOKEN)


# ── 生命周期 ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    print(f"[license-server] DB={DB_PATH}, MAX_DEVICES={MAX_DEVICES}")
    yield


app = FastAPI(title="Captain License Server", lifespan=lifespan)


# ── 管理员：批量生成 key ───────────────────────────────────────────────────────
@app.post("/api/license/generate")
async def generate(request: Request) -> JSONResponse:
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "未授权"}, status_code=403)
    b = await request.json()
    plan    = b.get("plan", "pro")
    months  = int(b.get("months", 12))
    n       = int(b.get("n", 1))
    note    = b.get("note", "")
    max_dev = int(b.get("max_devices", MAX_DEVICES))
    now     = time.time()
    expires = now + months * 30 * 86400

    conn = get_conn()
    keys = []
    for _ in range(n):
        k = _gen_key(plan)
        conn.execute(
            "INSERT INTO license_keys(key,plan,months,max_devices,created_at,expires_at,note) "
            "VALUES(?,?,?,?,?,?,?)",
            (k, plan, months, max_dev, now, expires, note),
        )
        keys.append(k)
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "keys": keys, "expires_at": expires})


# ── 激活 ─────────────────────────────────────────────────────────────────────
@app.post("/api/license/activate")
async def activate(request: Request) -> JSONResponse:
    b          = await request.json()
    key        = (b.get("key") or "").strip().upper()
    machine_id = (b.get("machine_id") or "").strip()
    email      = (b.get("email") or "").strip().lower()

    if not key or not machine_id:
        return JSONResponse({"ok": False, "error": "缺少 key 或 machine_id"}, status_code=400)

    conn = get_conn()
    row = conn.execute("SELECT * FROM license_keys WHERE key=?", (key,)).fetchone()
    if not row:
        conn.close()
        return JSONResponse({"ok": False, "error": "授权码不存在"}, status_code=404)

    # 过期检查
    if row["expires_at"] and time.time() > row["expires_at"]:
        conn.close()
        return JSONResponse({"ok": False, "error": "授权码已过期", "expired": True}, status_code=403)

    # 机器数量检查
    acts = conn.execute(
        "SELECT machine_id FROM activations WHERE license_key=?", (key,)
    ).fetchall()
    machine_ids = {a["machine_id"] for a in acts}
    if machine_id not in machine_ids and len(machine_ids) >= row["max_devices"]:
        conn.close()
        return JSONResponse({
            "ok": False,
            "error": f"该授权码已在 {row['max_devices']} 台设备上激活，已达上限",
            "device_limit": True,
        }, status_code=403)

    now = time.time()
    conn.execute(
        "INSERT INTO activations(license_key,machine_id,email,activated_at,last_check) "
        "VALUES(?,?,?,?,?) ON CONFLICT(license_key,machine_id) "
        "DO UPDATE SET last_check=excluded.last_check, email=COALESCE(NULLIF(excluded.email,''),email)",
        (key, machine_id, email, now, now),
    )
    conn.commit()
    conn.close()

    return JSONResponse({
        "ok":         True,
        "plan":       row["plan"],
        "expires_at": row["expires_at"],
        "months":     row["months"],
    })


# ── 验证（本地 app 定期调用）────────────────────────────────────────────────────
@app.post("/api/license/check")
async def check(request: Request) -> JSONResponse:
    b          = await request.json()
    key        = (b.get("key") or "").strip().upper()
    machine_id = (b.get("machine_id") or "").strip()

    if not key or not machine_id:
        return JSONResponse({"ok": False, "valid": False, "error": "缺少参数"}, status_code=400)

    conn = get_conn()
    row = conn.execute("SELECT * FROM license_keys WHERE key=?", (key,)).fetchone()
    if not row:
        conn.close()
        return JSONResponse({"ok": True, "valid": False, "error": "授权码不存在"})

    if row["expires_at"] and time.time() > row["expires_at"]:
        conn.close()
        return JSONResponse({"ok": True, "valid": False, "expired": True,
                             "error": "授权码已过期，请续费"})

    act = conn.execute(
        "SELECT * FROM activations WHERE license_key=? AND machine_id=?",
        (key, machine_id),
    ).fetchone()
    if not act:
        conn.close()
        return JSONResponse({"ok": True, "valid": False, "error": "此设备未激活，请先激活"})

    # 更新最后验证时间
    conn.execute(
        "UPDATE activations SET last_check=? WHERE license_key=? AND machine_id=?",
        (time.time(), key, machine_id),
    )
    conn.commit()
    conn.close()

    return JSONResponse({
        "ok":         True,
        "valid":      True,
        "plan":       row["plan"],
        "expires_at": row["expires_at"],
    })


# ── 管理员：查看所有激活记录 ──────────────────────────────────────────────────
@app.get("/api/license/list")
async def list_keys(request: Request) -> JSONResponse:
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "未授权"}, status_code=403)
    conn = get_conn()
    keys = [dict(r) for r in conn.execute(
        "SELECT k.*, COUNT(a.id) as activations "
        "FROM license_keys k LEFT JOIN activations a ON a.license_key=k.key "
        "GROUP BY k.key ORDER BY k.created_at DESC"
    ).fetchall()]
    conn.close()
    return JSONResponse({"ok": True, "keys": keys})


# ── 健康检查 ──────────────────────────────────────────────────────────────────
@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "ts": time.time()})
