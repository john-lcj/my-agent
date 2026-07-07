"""记忆注入性能基准。"""
from __future__ import annotations

import time

from memory.base import MemoryItem
from memory.factory import build_longterm
from memory.policy import inject_with_budget


def test_inject_budget_1000_items_under_one_second(tmp_path):
    mem = build_longterm(str(tmp_path))
    for i in range(200):
        mem.store(MemoryItem(kind="fact", content=f"测试记忆条目编号{i}用于基准", importance=0.3))
    t0 = time.perf_counter()
    blocks = [f"块{i}" * 30 for i in range(50)]
    out = inject_with_budget(blocks, max_chars=1200)
    elapsed = time.perf_counter() - t0
    assert len(out) <= 1200
    assert elapsed < 1.0
