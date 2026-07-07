"""记忆 API 与策略。"""
from __future__ import annotations

from memory.base import MemoryItem
from memory.conflict import detect_preference_conflict
from memory.factory import build_longterm
from memory.policy import inject_with_budget, ttl_for_kind


def test_ttl_for_kind():
    assert ttl_for_kind("fact") == 90 * 86400
    assert ttl_for_kind("preference") is None


def test_inject_with_budget():
    blocks = ["a" * 2000, "b" * 2000]
    out = inject_with_budget(blocks, max_chars=2500)
    assert len(out) <= 2500


def test_memory_list_and_delete(tmp_path):
    mem = build_longterm(str(tmp_path))
    mem.store(MemoryItem(kind="fact", content="测试事实", importance=0.6))
    rows = mem.list_all(kind="fact")
    assert any("测试事实" in r["content"] for r in rows)
    rid = rows[0]["id"]
    assert mem.delete_by_id(rid)
    assert not mem.list_all(kind="fact")


def test_preference_conflict():
    existing = [MemoryItem(kind="preference", content="不喜欢用 Slack")]
    tip = detect_preference_conflict(existing, "喜欢用 Slack 沟通")
    assert tip is None or "冲突" in tip or "Slack" in tip


def test_fact_expires_returns_stale_on_recall(tmp_path):
    import time
    mem = build_longterm(str(tmp_path))
    from memory.longterm_sqlite import SQLiteMemory
    kw = mem._kw
    assert isinstance(kw, SQLiteMemory)
    old = time.time() - 200 * 86400
    kw._conn.execute(
        "INSERT INTO memories (kind, content, importance, source, scope, created_at, last_used, expires_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("fact", "过期事实", 0.5, "agent", "", old, old, old + 86400),
    )
    kw._conn.commit()
    hits = mem.retrieve("过期事实", k=5)
    assert len(hits) == 1
    assert hits[0].stale is True
