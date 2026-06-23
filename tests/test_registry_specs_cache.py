"""能力清单 specs() 缓存 —— 命中缓存 + register 后失效 + 浅拷贝隔离。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from core.types import CapabilityResult, Risk


class _Cap:
    def __init__(self, name):
        self.name = name
        self.description = "d"
        self.schema = {}
        self.risk = Risk.READ
    async def invoke(self, args, ctx):
        return CapabilityResult(ok=True, output="")


def test_specs_cached_same_object_contents():
    reg = CapabilityRegistry([_Cap("a"), _Cap("b")])
    s1 = reg.specs()
    s2 = reg.specs()
    assert s1 == s2 and len(s1) == 2
    # 返回浅拷贝:外部改了返回值不污染缓存
    s1.append({"name": "x"})
    assert len(reg.specs()) == 2


def test_register_invalidates_cache():
    reg = CapabilityRegistry([_Cap("a")])
    assert len(reg.specs()) == 1     # 建缓存
    reg.register(_Cap("c"))          # 应失效
    names = [s["name"] for s in reg.specs()]
    assert names == ["a", "c"]
