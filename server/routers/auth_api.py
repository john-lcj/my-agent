"""注册 / 登录 / 兑换码 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from memory.user_store import UserStore
from server.auth import create_token, get_current_user, current_user_id

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_user_store(request: Request) -> UserStore:
    return request.app.state.user_store


# ── 注册 ────────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(request: Request) -> JSONResponse:
    b = await request.json()
    email    = (b.get("email") or "").strip()
    password = b.get("password") or ""
    us: UserStore = _get_user_store(request)
    try:
        user  = us.register(email, password)
        token = create_token(user["id"], user["email"], user["plan"])
        return JSONResponse({"ok": True, "token": token, "user": _safe(user)})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ── 登录 ────────────────────────────────────────────────────────────────────

@router.post("/login")
async def login(request: Request) -> JSONResponse:
    b = await request.json()
    email    = (b.get("email") or "").strip()
    password = b.get("password") or ""
    us: UserStore = _get_user_store(request)
    user = us.login(email, password)
    if not user:
        return JSONResponse({"ok": False, "error": "邮箱或密码错误"}, status_code=401)
    token = create_token(user["id"], user["email"], user["plan"])
    return JSONResponse({"ok": True, "token": token, "user": _safe(user)})


# ── 当前用户信息 ─────────────────────────────────────────────────────────────

@router.get("/me")
async def me(request: Request) -> JSONResponse:
    payload = get_current_user(request)
    us: UserStore = _get_user_store(request)
    user = us.get_by_id(payload["sub"])
    if not user:
        return JSONResponse({"ok": False, "error": "用户不存在"}, status_code=404)
    used   = us.tokens_today(user["id"])
    quota  = user["quota_daily"]
    return JSONResponse({
        "ok":    True,
        "user":  _safe(user),
        "usage": {"tokens_today": used, "quota_daily": quota,
                  "pct": round(used / quota * 100, 1) if quota else 0},
    })


# ── 兑换码 ─────────────────────────────────────────────────────────────────

@router.post("/redeem")
async def redeem(request: Request) -> JSONResponse:
    payload = get_current_user(request)
    b = await request.json()
    code = (b.get("code") or "").strip()
    us: UserStore = _get_user_store(request)
    try:
        user  = us.redeem(payload["sub"], code)
        token = create_token(user["id"], user["email"], user["plan"])
        return JSONResponse({"ok": True, "token": token, "user": _safe(user)})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ── 管理员：生成兑换码（需 AGENT_API_TOKEN）─────────────────────────────────

@router.post("/admin/codes")
async def create_code(request: Request) -> JSONResponse:
    import hmac, os
    token  = os.environ.get("AGENT_API_TOKEN", "")
    provided = request.headers.get("x-agent-token", "")
    if not token or not hmac.compare_digest(provided, token):
        return JSONResponse({"ok": False, "error": "未授权"}, status_code=403)
    b     = await request.json()
    plan  = b.get("plan", "pro")
    months = int(b.get("months", 1))
    n     = int(b.get("n", 1))
    us: UserStore = _get_user_store(request)
    codes = [us.create_redeem_code(plan, months) for _ in range(n)]
    return JSONResponse({"ok": True, "codes": codes})


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _safe(user: dict) -> dict:
    """去掉密码哈希再返回。"""
    return {k: v for k, v in user.items() if k != "password_hash"}
