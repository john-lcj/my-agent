"""本地数据备份/恢复接口。

只导出客户可迁移的数据；密钥、令牌、邮箱授权码、保险库明文不进入备份。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config

BACKUP_VERSION = 1

_SQLITE_TABLES = {
    "sessions.db": ("sessions", "messages"),
    "feedback.db": ("message_feedback",),
    "tasks.db": ("tasks",),
    "templates.db": ("templates", "template_meta"),
}

_JSON_FILES = {
    "runtime": ("runtime.json",),
    "projects": ("projects.json",),
    "goals": ("goals.json",),
    "suggestions": ("suggestions.json",),
}


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _data_dir() -> str:
    return os.path.join(_root(), "data")


def _read_json(path: str, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _export_sqlite(db_name: str, tables: Iterable[str]) -> dict:
    path = os.path.join(Config.LOG_DIR, db_name)
    out: dict[str, list[dict]] = {}
    if not os.path.isfile(path):
        return out
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        existing = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in tables:
            if table in existing:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                out[table] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out


def _import_sqlite(db_name: str, tables: dict[str, list[dict]]) -> None:
    if not isinstance(tables, dict):
        return
    path = os.path.join(Config.LOG_DIR, db_name)
    if not os.path.isfile(path):
        return
    conn = sqlite3.connect(path, timeout=20)
    try:
        conn.execute("BEGIN")
        for table in _SQLITE_TABLES.get(db_name, ()):
            rows = tables.get(table)
            if not isinstance(rows, list) or not rows:
                continue
            cols = _table_columns(conn, table)
            if not cols:
                continue
            row_cols = [c for c in cols if c in rows[0]]
            if not row_cols:
                continue
            if table == "messages":
                sids = sorted({str(r.get("session_id") or "") for r in rows if r.get("session_id")})
                if sids:
                    marks = ",".join("?" for _ in sids)
                    conn.execute(f"DELETE FROM messages WHERE session_id IN ({marks})", sids)
            placeholders = ",".join("?" for _ in row_cols)
            col_sql = ",".join(row_cols)
            for row in rows:
                vals = [row.get(c) for c in row_cols]
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})",
                    vals,
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _export_payload() -> dict:
    payload = {
        "version": BACKUP_VERSION,
        "app": "captain",
        "generated_at": time.time(),
        "contains_sensitive": False,
        "data": {
            "sqlite": {},
            "json": {},
            "profile": _read_json(os.path.join(_data_dir(), "owner.json"), {}),
        },
    }
    for db_name, tables in _SQLITE_TABLES.items():
        payload["data"]["sqlite"][db_name] = _export_sqlite(db_name, tables)
    for key, parts in _JSON_FILES.items():
        payload["data"]["json"][key] = _read_json(os.path.join(Config.LOG_DIR, *parts), [] if key in {"goals", "suggestions"} else {})
    return payload


def _validate_backup(payload: dict) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "备份文件不是 JSON 对象"
    if payload.get("app") != "captain":
        return False, "不是 Captain 备份文件"
    if int(payload.get("version") or 0) != BACKUP_VERSION:
        return False, "备份版本不兼容"
    data = payload.get("data")
    if not isinstance(data, dict):
        return False, "备份缺少 data 字段"
    if not isinstance(data.get("sqlite", {}), dict) or not isinstance(data.get("json", {}), dict):
        return False, "备份结构不完整"
    return True, ""


def register_backup(app) -> None:
    @app.get("/api/backup/export")
    async def export_backup() -> JSONResponse:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return JSONResponse(
            _export_payload(),
            headers={"Content-Disposition": f'attachment; filename="captain-backup-{stamp}.json"'},
        )

    @app.post("/api/backup/import")
    async def import_backup(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "无法解析备份 JSON"}, status_code=400)
        ok, err = _validate_backup(payload)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        data = payload["data"]
        try:
            for db_name, tables in (data.get("sqlite") or {}).items():
                if db_name in _SQLITE_TABLES:
                    _import_sqlite(db_name, tables)
            profile = data.get("profile")
            if isinstance(profile, dict):
                _write_json(os.path.join(_data_dir(), "owner.json"), profile)
            for key, parts in _JSON_FILES.items():
                if key in (data.get("json") or {}):
                    _write_json(os.path.join(Config.LOG_DIR, *parts), data["json"][key])
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"导入失败:{exc}"}, status_code=400)
        return JSONResponse({"ok": True})
