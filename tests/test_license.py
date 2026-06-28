"""授权服务器 + 本地客户端联动测试（纯 stdlib，不需要 FastAPI 运行时）。"""
from __future__ import annotations
import json, os, sys, tempfile, time, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 授权服务器数据层（直接操 SQLite，不启动 HTTP）────────────────────────────
class _ServerDB:
    """最小化复现 license_server/main.py 的数据逻辑，用于测试。"""
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS license_keys (
                key TEXT PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'pro',
                months INTEGER NOT NULL DEFAULT 12, max_devices INTEGER NOT NULL DEFAULT 2,
                created_at REAL NOT NULL, expires_at REAL, note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS activations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT NOT NULL, machine_id TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '', activated_at REAL NOT NULL, last_check REAL NOT NULL,
                UNIQUE(license_key, machine_id)
            );
        """)
        self.conn.commit()

    def gen_key(self, plan="pro", months=12, max_devices=2, expires_at=None):
        import uuid
        k = f"CAPT-PRO-{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}"
        now = time.time()
        exp = expires_at if expires_at is not None else now + months * 30 * 86400
        self.conn.execute(
            "INSERT INTO license_keys(key,plan,months,max_devices,created_at,expires_at,note) VALUES(?,?,?,?,?,?,'')",
            (k, plan, months, max_devices, now, exp))
        self.conn.commit()
        return k

    def activate(self, key, machine_id, email=""):
        row = self.conn.execute("SELECT * FROM license_keys WHERE key=?", (key,)).fetchone()
        if not row: return {"ok": False, "error": "授权码不存在"}
        if row["expires_at"] and time.time() > row["expires_at"]:
            return {"ok": False, "error": "授权码已过期"}
        acts = self.conn.execute("SELECT machine_id FROM activations WHERE license_key=?", (key,)).fetchall()
        mids = {a["machine_id"] for a in acts}
        if machine_id not in mids and len(mids) >= row["max_devices"]:
            return {"ok": False, "error": "设备数超限", "device_limit": True}
        now = time.time()
        self.conn.execute(
            "INSERT INTO activations(license_key,machine_id,email,activated_at,last_check) VALUES(?,?,?,?,?) "
            "ON CONFLICT(license_key,machine_id) DO UPDATE SET last_check=excluded.last_check",
            (key, machine_id, email, now, now))
        self.conn.commit()
        return {"ok": True, "plan": row["plan"], "expires_at": row["expires_at"]}

    def check(self, key, machine_id):
        row = self.conn.execute("SELECT * FROM license_keys WHERE key=?", (key,)).fetchone()
        if not row: return {"ok": True, "valid": False, "error": "授权码不存在"}
        if row["expires_at"] and time.time() > row["expires_at"]:
            return {"ok": True, "valid": False, "expired": True, "error": "已过期"}
        act = self.conn.execute(
            "SELECT * FROM activations WHERE license_key=? AND machine_id=?", (key, machine_id)).fetchone()
        if not act: return {"ok": True, "valid": False, "error": "未激活"}
        self.conn.execute("UPDATE activations SET last_check=? WHERE license_key=? AND machine_id=?",
                          (time.time(), key, machine_id))
        self.conn.commit()
        return {"ok": True, "valid": True, "plan": row["plan"], "expires_at": row["expires_at"]}


# ── 测试 ─────────────────────────────────────────────────────────────────────
class TestLicenseServer:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = _ServerDB(os.path.join(self.tmp.name, "license.db"))

    def teardown_method(self):
        self.tmp.cleanup()

    def test_generate_and_check_valid(self):
        key = self.db.gen_key("pro", 12)
        assert key.startswith("CAPT-PRO-")
        r = self.db.activate(key, "machine-001")
        assert r["ok"] is True and r["plan"] == "pro"
        r2 = self.db.check(key, "machine-001")
        assert r2["valid"] is True and r2["plan"] == "pro"

    def test_invalid_key(self):
        r = self.db.check("CAPT-PRO-FAKE-FAKE-FAKE", "m1")
        assert r["valid"] is False

    def test_unactivated_machine(self):
        key = self.db.gen_key()
        self.db.activate(key, "machine-A")
        r = self.db.check(key, "machine-B-not-activated")
        assert r["valid"] is False and "未激活" in r["error"]

    def test_device_limit(self):
        key = self.db.gen_key(max_devices=1)
        self.db.activate(key, "machine-1")
        r = self.db.activate(key, "machine-2")
        assert r["ok"] is False and r.get("device_limit") is True

    def test_same_device_reactivate_ok(self):
        key = self.db.gen_key(max_devices=1)
        self.db.activate(key, "machine-1")
        r = self.db.activate(key, "machine-1")
        assert r["ok"] is True

    def test_expired_key(self):
        key = self.db.gen_key(expires_at=time.time() - 1)
        r = self.db.activate(key, "m1")
        assert r["ok"] is False and "过期" in r["error"]

    def test_expired_check(self):
        key = self.db.gen_key(expires_at=time.time() + 10)
        self.db.activate(key, "m1")
        # 手动让 key 过期
        self.db.conn.execute("UPDATE license_keys SET expires_at=? WHERE key=?",
                             (time.time() - 1, key))
        self.db.conn.commit()
        r = self.db.check(key, "m1")
        assert r["valid"] is False and r.get("expired") is True


class TestLicenseClient:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tmp.name, ".license_cache")
        self.mid_dir    = os.path.join(self.tmp.name, ".captain")
        os.environ["CAPTAIN_LICENSE_CACHE"] = self.cache_path
        os.environ["CAPTAIN_LICENSE_SERVER"] = "http://localhost:19999"  # 不存在

    def teardown_method(self):
        self.tmp.cleanup()
        for k in ("CAPTAIN_LICENSE_CACHE", "CAPTAIN_LICENSE_SERVER", "CAPTAIN_LICENSE_KEY"):
            os.environ.pop(k, None)

    def _write_cache(self, data: dict):
        from license_client.client import _xor, _cache_path
        import pathlib
        p = _cache_path()   # 动态读取当前 env 设定的路径
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_xor(json.dumps(data).encode()))

    def _mid(self):
        from license_client.client import get_machine_id
        return get_machine_id()

    def test_no_key_no_cache_returns_free(self):
        os.environ.pop("CAPTAIN_LICENSE_KEY", None)
        from license_client.client import check_license
        s = check_license()
        assert s.valid is False and s.plan == "free"

    def test_valid_cache_not_expired(self):
        mid = self._mid()
        self._write_cache({"key": "CAPT-PRO-TEST", "plan": "pro",
                           "expires_at": time.time() + 86400 * 30,
                           "cached_at": time.time(), "machine_id": mid})
        from license_client.client import check_license
        s = check_license()
        assert s.valid is True and s.plan == "pro"

    def test_expired_cache_server_unreachable_grace_period(self):
        mid = self._mid()
        # cached_at 超过 TTL 但在 grace period 内（服务器不可达时应放行）
        from license_client.client import _cache_ttl
        self._write_cache({"key": "CAPT-PRO-TEST", "plan": "pro",
                           "expires_at": time.time() + 86400 * 30,
                           "cached_at": time.time() - _cache_ttl() - 60,
                           "machine_id": mid})
        from license_client.client import check_license
        s = check_license()
        assert s.valid is True and s.offline is True

    def test_cache_wrong_machine_id(self):
        self._write_cache({"key": "CAPT-PRO-TEST", "plan": "pro",
                           "expires_at": time.time() + 86400,
                           "cached_at": time.time(), "machine_id": "WRONG-MACHINE"})
        from license_client.client import check_license
        s = check_license()
        # 机器 ID 不匹配 → 当无缓存，联网失败 → invalid
        assert s.valid is False


class TestFeatureGates:
    def test_pro_all_allowed(self):
        from license_client.client import LicenseStatus
        from license_client.gates import make_gates
        s = LicenseStatus(valid=True, plan="pro")
        g = make_gates(s)
        assert g.allow_shell and g.allow_skill and g.allow_browser
        assert g.allow_schedule and g.allow_monitor
        assert g.daily_msg_limit is None
        assert g.check("shell.run") is True
        assert g.check("browser.click") is True

    def test_free_restricted(self):
        from license_client.client import LicenseStatus
        from license_client.gates import make_gates
        s = LicenseStatus(valid=False, plan="free")
        g = make_gates(s)
        assert not g.allow_shell
        assert not g.allow_skill
        assert not g.allow_browser
        assert g.daily_msg_limit == 100
        assert g.check("shell.run") is False
        assert g.check("fs.read") is True    # fs 对 free 可用

    def test_invalid_but_plan_pro_is_still_restricted(self):
        from license_client.client import LicenseStatus
        from license_client.gates import make_gates
        s = LicenseStatus(valid=False, plan="pro")  # 无效的 pro（过期）
        g = make_gates(s)
        assert g.is_pro is False
        assert not g.allow_shell
