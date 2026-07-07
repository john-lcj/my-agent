"""eval 失败经验优先注入。"""
from __future__ import annotations

from memory.base import MemoryItem
from memory.experience_miner import format_experience_block
from memory.hybrid import HybridMemory
from memory.longterm_sqlite import SQLiteMemory


class _Mem:
    def __init__(self, items):
        self._items = items

    def retrieve(self, query, k=8):
        return self._items[:k]


def test_eval_failure_experience_sorted_first():
    items = [
        MemoryItem(kind="experience", content="普通经验 A"),
        MemoryItem(kind="experience", content="[eval_failure] case_x: 缺证据"),
        MemoryItem(kind="experience", content="普通经验 B"),
    ]
    block = format_experience_block(_Mem(items), "case_x 证据")
    assert block.index("[eval_failure]") < block.index("普通经验 A")


def test_inject_budget_truncates():
    from memory.policy import inject_with_budget
    blocks = [f"块{i}" * 40 for i in range(100)]
    out = inject_with_budget(blocks, max_chars=1200)
    assert len(out) <= 1200
