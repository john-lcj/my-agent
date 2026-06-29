"""Captain 授权服务器 — 极简 FastAPI，部署在一台小 VPS。

端点:
  POST /api/license/generate        管理员批量生成 key（需 ADMIN_TOKEN）
  POST /api/license/activate        激活 key（绑定机器码 + 邮箱）
  POST /api/license/check           本地 app 验证授权状态
  GET  /api/license/list            管理员查看所有 key
  POST /api/payment/hupi_callback   虎皮椒支付回调（自动发码）
  POST /api/payment/mzf_callback    码支付回调（自动发码）
  POST /api/payment/manual_issue    管理员手动补发（需 ADMIN_TOKEN）
  GET  /healthz                     健康检查
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
    total = len(keys)
    active = sum(1 for k in keys if k.get("activations", 0) > 0)
    conn.close()
    return JSONResponse({"ok": True, "keys": keys, "stats": {"total": total, "activated": active}})


# ── 健康检查 ──────────────────────────────────────────────────────────────────
@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "ts": time.time()})


# ══════════════════════════════════════════════════════════════════════════════
#  支付回调 — 自动发码
# ══════════════════════════════════════════════════════════════════════════════

# 支付金额 → 套餐映射（单位：元）
_AMOUNT_MAP: dict[str, tuple[str, int]] = {
    "29":  ("pro", 1),    # ¥29  → Pro 月付
    "199": ("pro", 12),   # ¥199 → Pro 年付
}
# 允许误差（支付平台有时会多/少几分）
_AMOUNT_TOLERANCE = 0.5


def _match_plan(amount_str: str) -> Optional[tuple[str, int]]:
    """根据金额字符串返回 (plan, months) 或 None。"""
    try:
        paid = float(amount_str)
    except (ValueError, TypeError):
        return None
    for k, v in _AMOUNT_MAP.items():
        if abs(paid - float(k)) <= _AMOUNT_TOLERANCE:
            return v
    return None


def _auto_issue(email: str, plan: str, months: int, note: str = "") -> Optional[str]:
    """生成 key、写库、发邮件，返回 key 或 None（失败）。"""
    now    = time.time()
    key    = _gen_key(plan)
    exp    = now + months * 30 * 86400
    conn   = get_conn()
    try:
        conn.execute(
            "INSERT INTO license_keys(key,plan,months,max_devices,created_at,expires_at,note) "
            "VALUES(?,?,?,?,?,?,?)",
            (key, plan, months, MAX_DEVICES, now, exp, note),
        )
        conn.commit()
    finally:
        conn.close()

    # 异步发邮件（放后台线程，不阻塞响应）
    import threading
    def _send():
        try:
            from mailer import send, render_key_email
            subj, html, text = render_key_email(key, plan, months, exp)
            send(email, subj, html, text)
        except Exception as e:
            print(f"[payment] 邮件发送失败: {e}")
    threading.Thread(target=_send, daemon=True).start()

    print(f"[payment] 自动发码 → {email} | {key} | {plan}/{months}mo")
    return key


def _hupi_verify(params: dict, key: str) -> bool:
    """验证虎皮椒签名。
    签名算法：将参数按 key 升序排列拼接后加 key，MD5。
    """
    sign = params.pop("sign", "")
    sign_type = params.pop("sign_type", "MD5")
    sorted_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v != "")
    raw = sorted_str + key
    expected = hashlib.md5(raw.encode()).hexdigest()
    return hmac.compare_digest(sign.lower(), expected.lower())


# ── 虎皮椒回调 ────────────────────────────────────────────────────────────────
# 文档：https://www.xunhupay.com/doc/api/notify.html
@app.post("/api/payment/hupi_callback")
async def hupi_callback(request: Request) -> str:
    """虎皮椒支付成功回调。需在虎皮椒后台配置回调地址。"""
    hupi_key = os.environ.get("HUPI_KEY", "")
    try:
        form = dict(await request.form())
    except Exception:
        form = await request.json()

    # 验签（配置了 HUPI_KEY 才验）
    if hupi_key:
        params_copy = dict(form)
        if not _hupi_verify(params_copy, hupi_key):
            print(f"[hupi] 签名验证失败: {form}")
            return "fail"

    trade_status = form.get("trade_status", "")
    if trade_status != "TRADE_SUCCESS":
        return "success"   # 其他状态直接返回 success，告诉虎皮椒不要重发

    email      = str(form.get("email") or form.get("buyer_email") or "").strip().lower()
    amount_str = str(form.get("total_fee") or form.get("money") or "0")
    out_trade_no = str(form.get("out_trade_no") or "")

    # 幂等：同一 out_trade_no 不重复发码
    conn = get_conn()
    dup = conn.execute(
        "SELECT key FROM license_keys WHERE note=?", (f"hupi:{out_trade_no}",)
    ).fetchone()
    conn.close()
    if dup:
        print(f"[hupi] 重复回调，跳过: {out_trade_no}")
        return "success"

    plan_info = _match_plan(amount_str)
    if not plan_info:
        print(f"[hupi] 未匹配到套餐，金额={amount_str}")
        return "success"

    plan, months = plan_info
    if not email:
        print(f"[hupi] 无买家邮箱，out_trade_no={out_trade_no}")
        return "success"

    _auto_issue(email, plan, months, note=f"hupi:{out_trade_no}")
    return "success"


# ── 码支付回调 ────────────────────────────────────────────────────────────────
# 文档：https://codepay.fateqq.com/
@app.post("/api/payment/mzf_callback")
async def mzf_callback(request: Request) -> str:
    """码支付（FateQQ/码支付）回调。"""
    mzf_key = os.environ.get("MZF_KEY", "")
    try:
        form = dict(await request.form())
    except Exception:
        form = await request.json()

    # 码支付签名：price+istype+tradeno+key → MD5
    sign      = form.get("sign", "")
    price     = str(form.get("price", ""))
    istype    = str(form.get("istype", ""))
    tradeno   = str(form.get("tradeno", ""))
    if mzf_key:
        raw      = f"{price}{istype}{tradeno}{mzf_key}"
        expected = hashlib.md5(raw.encode()).hexdigest()
        if not hmac.compare_digest(sign.lower(), expected.lower()):
            print(f"[mzf] 签名验证失败")
            return "fail"

    email      = str(form.get("param") or "").strip().lower()   # 买家在备注填邮箱
    amount_str = price

    # 幂等
    conn = get_conn()
    dup = conn.execute(
        "SELECT key FROM license_keys WHERE note=?", (f"mzf:{tradeno}",)
    ).fetchone()
    conn.close()
    if dup:
        return "success"

    plan_info = _match_plan(amount_str)
    if not plan_info or not email:
        print(f"[mzf] 跳过: amount={amount_str} email={email}")
        return "success"

    plan, months = plan_info
    _auto_issue(email, plan, months, note=f"mzf:{tradeno}")
    return "success"


# ── 管理员手动补发 ────────────────────────────────────────────────────────────
@app.post("/api/payment/manual_issue")
async def manual_issue(request: Request) -> JSONResponse:
    """管理员手动向指定邮箱补发授权码。"""
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "未授权"}, status_code=403)
    b      = await request.json()
    email  = (b.get("email") or "").strip().lower()
    plan   = b.get("plan", "pro")
    months = int(b.get("months", 12))
    note   = b.get("note", "manual")

    if not email:
        return JSONResponse({"ok": False, "error": "缺少 email"}, status_code=400)

    key = _auto_issue(email, plan, months, note=note)
    return JSONResponse({"ok": True, "key": key, "email": email})
