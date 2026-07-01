"""本地授权验证客户端 — 纯 stdlib，零依赖。

流程：
  1. 读本地缓存（~/.captain/.license_cache），未超期直接返回，不联网
  2. 超期 → 联网调用 /api/license/check 刷新
  3. 联网失败 → grace period（3天）内继续放行，避免网络抖动中断使用
  4. 完全未激活 → 返回 free 状态，app 根据此决定是否限制功能
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    from server.keychain_store import get_secret, secret_ref, set_secret, should_use_for_path
except Exception:  # pragma: no cover - license client must remain standalone-friendly
    get_secret = None
    set_secret = None
    secret_ref = None
    should_use_for_path = None

# ── 配置默认值（全部动态读取，测试时可随时覆盖 env）────────────────────────
_DEFAULT_SERVER     = "https://license.irestart-your-life.club"
_DEFAULT_CACHE_TTL  = 7 * 86400
_DEFAULT_GRACE      = 3 * 86400
_DEFAULT_CACHE      = os.path.expanduser("~/.captain/.license_cache")
LICENSE_KEY_ENV     = "CAPTAIN_LICENSE_KEY"
_XOR_KEY            = b"captain-xor-2024"


def _cache_path() -> Path:
    return Path(os.environ.get("CAPTAIN_LICENSE_CACHE", _DEFAULT_CACHE))

def _license_server() -> str:
    return os.environ.get("CAPTAIN_LICENSE_SERVER", _DEFAULT_SERVER)

def _cache_ttl() -> int:
    return int(os.environ.get("CAPTAIN_LICENSE_CACHE_TTL", str(_DEFAULT_CACHE_TTL)))

def _grace_period() -> int:
    return int(os.environ.get("CAPTAIN_LICENSE_GRACE", str(_DEFAULT_GRACE)))


def _keychain_license_key() -> str:
    if not (get_secret and secret_ref and should_use_for_path):
        return ""
    try:
        if should_use_for_path(os.getcwd()):
            return get_secret(secret_ref("env", LICENSE_KEY_ENV))
    except Exception:
        return ""
    return ""


def _store_license_key(key: str) -> None:
    if not (set_secret and secret_ref and should_use_for_path):
        return
    try:
        if should_use_for_path(os.getcwd()):
            set_secret(secret_ref("env", LICENSE_KEY_ENV), key)
    except Exception:
        pass


# ── 机器唯一 ID ───────────────────────────────────────────────────────────────
def get_machine_id() -> str:
    """生成/读取本机唯一 ID，持久化到 ~/.captain/machine_id。"""
    mid_file = Path(os.path.expanduser("~/.captain/machine_id"))
    mid_file.parent.mkdir(parents=True, exist_ok=True)
    if mid_file.exists():
        return mid_file.read_text().strip()
    raw = f"{platform.node()}|{platform.machine()}|{uuid.getnode()}|{uuid.uuid4()}"
    mid = hashlib.sha256(raw.encode()).hexdigest()[:32]
    mid_file.write_text(mid)
    return mid


# ── 缓存混淆（XOR，防止普通用户直接篡改）────────────────────────────────────
def _xor(data: bytes) -> bytes:
    k = _XOR_KEY
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))

def _write_cache(payload: dict) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_xor(json.dumps(payload).encode()))

def _read_cache() -> Optional[dict]:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        return json.loads(_xor(p.read_bytes()))
    except Exception:
        return None


# ── 联网请求（urllib，零依赖）────────────────────────────────────────────────
def _post(path: str, body: dict, timeout: int = 8) -> Optional[dict]:
    try:
        import urllib.request
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            f"{_license_server()}{path}", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── 返回值 ────────────────────────────────────────────────────────────────────
class LicenseStatus:
    def __init__(self, valid: bool, plan: str = "free",
                 expires_at: Optional[float] = None,
                 offline: bool = False, error: str = ""):
        self.valid      = valid
        self.plan       = plan          # "free" | "pro"
        self.expires_at = expires_at
        self.offline    = offline       # True = 本次离线，用缓存放行
        self.error      = error

    @property
    def is_pro(self) -> bool:
        return self.valid and self.plan == "pro"

    def days_left(self) -> Optional[int]:
        if not self.expires_at:
            return None
        return max(0, int((self.expires_at - time.time()) / 86400))

    def to_dict(self) -> dict:
        return {
            "valid":      self.valid,
            "plan":       self.plan,
            "expires_at": self.expires_at,
            "days_left":  self.days_left(),
            "offline":    self.offline,
            "error":      self.error,
        }

    def __repr__(self) -> str:
        return (f"LicenseStatus(valid={self.valid}, plan={self.plan}, "
                f"days_left={self.days_left()}, offline={self.offline})")


# ── 主入口 ────────────────────────────────────────────────────────────────────
def check_license(key: Optional[str] = None) -> LicenseStatus:
    """
    检查授权状态。key 优先级：参数 > 环境变量 > 缓存中的 key。

    开发模式：设置 CAPTAIN_DEV_PRO=1 直接返回 Pro，无需授权服务器。
    """
    # 开发/自用绕过：本地不需要授权服务器
    testing_license_paths = (
        os.environ.get("CAPTAIN_LICENSE_CACHE")
        or os.environ.get("CAPTAIN_LICENSE_SERVER", "").startswith("http://localhost:")
    )
    if os.environ.get("CAPTAIN_DEV_PRO", "").strip() == "1" and not testing_license_paths:
        return LicenseStatus(valid=True, plan="pro",
                             expires_at=time.time() + 365 * 86400)

    key = (key or os.environ.get(LICENSE_KEY_ENV, "") or _keychain_license_key()).strip().upper() or None
    mid = get_machine_id()
    cache = _read_cache()

    # ── 有缓存 ──────────────────────────────────────────────────────────────
    if cache and cache.get("machine_id") == mid:
        active_key = key or cache.get("key", "")
        plan       = cache.get("plan", "free")
        expires_at = cache.get("expires_at")
        cached_at  = cache.get("cached_at", 0)

        if not active_key:
            return LicenseStatus(valid=False, plan="free",
                                 error="未激活，请运行 captain activate <授权码>")

        # 缓存仍在 TTL 内 → 直接信任，省去网络
        if time.time() - cached_at < _cache_ttl():
            return LicenseStatus(valid=True, plan=plan, expires_at=expires_at)

        # 缓存过期 → 联网刷新
        result = _post("/api/license/check", {"key": active_key, "machine_id": mid})
        if result and result.get("valid"):
            _write_cache({"key": active_key, "plan": result["plan"],
                          "expires_at": result.get("expires_at"),
                          "cached_at": time.time(), "machine_id": mid})
            return LicenseStatus(valid=True, plan=result["plan"],
                                 expires_at=result.get("expires_at"))

        # 联网失败 → grace period
        if time.time() - cached_at < _cache_ttl() + _grace_period():
            return LicenseStatus(valid=True, plan=plan, expires_at=expires_at, offline=True)

        # grace 也过了
        return LicenseStatus(valid=False, plan="free", offline=True,
                             error="授权验证超时，请联网后重启")

    # ── 无缓存，用 key 首次验证 ─────────────────────────────────────────────
    if not key:
        return LicenseStatus(valid=False, plan="free",
                             error="未激活，请运行 captain activate <授权码>")

    result = _post("/api/license/check", {"key": key, "machine_id": mid})
    if result is None:
        return LicenseStatus(valid=False, plan="free", offline=True,
                             error="无法连接授权服务器，请检查网络")
    if not result.get("valid"):
        return LicenseStatus(valid=False, plan="free",
                             error=result.get("error", "授权验证失败"))

    _write_cache({"key": key, "plan": result["plan"],
                  "expires_at": result.get("expires_at"),
                  "cached_at": time.time(), "machine_id": mid})
    _store_license_key(key)
    return LicenseStatus(valid=True, plan=result["plan"],
                         expires_at=result.get("expires_at"))


def activate(key: str, email: str = "") -> LicenseStatus:
    """激活授权码（首次使用时调用）。"""
    key = key.strip().upper()
    mid = get_machine_id()
    result = _post("/api/license/activate", {"key": key, "machine_id": mid, "email": email})
    if result is None:
        return LicenseStatus(valid=False, offline=True, error="无法连接授权服务器")
    if not result.get("ok"):
        return LicenseStatus(valid=False, error=result.get("error", "激活失败"))
    _write_cache({"key": key, "plan": result["plan"],
                  "expires_at": result.get("expires_at"),
                  "cached_at": time.time(), "machine_id": mid})
    _store_license_key(key)
    return LicenseStatus(valid=True, plan=result["plan"],
                         expires_at=result.get("expires_at"))
