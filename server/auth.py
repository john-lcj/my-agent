"""JWT 鉴权 —— 纯 stdlib 实现，零外部依赖。

用 HMAC-SHA256 签名，格式与标准 JWT 兼容（header.payload.signature）。
颁发 access token（7天），前端存 localStorage，
每次请求带 Authorization: Bearer <token> 或 X-Auth-Token: <token>。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import HTTPException, Request, status

# ── 密钥：生产部署时务必设置 AUTH_SECRET 环境变量 ──────────────────────────
_SECRET = os.environ.get("AUTH_SECRET", "captain-dev-secret-change-me-in-prod").encode()
_TTL    = 86400 * 7   # 7 天


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_decode(s: str) -> bytes:
    # 补 padding
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def create_token(user_id: str, email: str, plan: str = "free") -> str:
    header  = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64_encode(json.dumps({
        "sub":   user_id,
        "email": email,
        "plan":  plan,
        "iat":   int(time.time()),
        "exp":   int(time.time()) + _TTL,
    }).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64_encode(hmac.new(_SECRET, sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> dict:
    """解码并验证 token，失败抛 HTTPException 401。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("invalid format")
        header_b64, payload_b64, sig_b64 = parts
        # 验签
        expected = _b64_encode(
            hmac.new(_SECRET, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected, sig_b64):
            raise ValueError("invalid signature")
        payload = json.loads(_b64_decode(payload_b64))
        # 检查过期
        if payload.get("exp", 0) < time.time():
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    xt = request.headers.get("x-auth-token", "").strip()
    if xt:
        return xt
    return request.query_params.get("token")


# ── FastAPI 依赖 ─────────────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    """FastAPI Depends：返回当前用户 payload dict（含 sub/email/plan）。"""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(token)


def get_current_user_optional(request: Request) -> Optional[dict]:
    """可选鉴权：未登录时返回 None（兼容单机模式）。"""
    token = _extract_token(request)
    if not token:
        return None
    try:
        return decode_token(token)
    except HTTPException:
        return None


def current_user_id(request: Request) -> str:
    return get_current_user(request)["sub"]
