"""DAG 计划图 —— L1 纯函数测试(无 LLM、无 worker)。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.plan_graph import PlanGraph, PlanNode, from_dispatch_plan


def _node(nid, agent="w", task="t", deps=None):
    return PlanNode(id=nid, agent=agent, sub_task=task, depends_on=deps or [])


def test_validate_ok():
    g = PlanGraph(nodes=[_node("a"), _node("b", deps=["a"])])
    ok, err = g.validate()
    assert ok, err


def test_validate_duplicate_id():
    g = PlanGraph(nodes=[_node("a"), _node("a")])
    ok, err = g.validate()
    assert not ok
    assert "重复" in err


def test_validate_missing_dep():
    g = PlanGraph(nodes=[_node("a", deps=["missing"])])
    ok, err = g.validate()
    assert not ok
    assert "不存在" in err


def test_validate_self_dep():
    g = PlanGraph(nodes=[_node("a", deps=["a"])])
    ok, err = g.validate()
    assert not ok


def test_validate_cycle():
    g = PlanGraph(nodes=[
        _node("a", deps=["b"]),
        _node("b", deps=["a"]),
    ])
    ok, err = g.validate()
    assert not ok
    assert "环" in err


def test_layers_diamond():
    g = PlanGraph(nodes=[
        _node("a"),
        _node("b"),
        _node("c", deps=["a", "b"]),
    ])
    assert g.validate()[0]
    layers = g.layers()
    assert len(layers) == 2
    assert {n.id for n in layers[0]} == {"a", "b"}
    assert [n.id for n in layers[1]] == ["c"]


def test_layers_chain():
    g = PlanGraph(nodes=[
        _node("n1"),
        _node("n2", deps=["n1"]),
        _node("n3", deps=["n2"]),
    ])
    layers = g.layers()
    assert len(layers) == 3
    assert [[n.id for n in layer] for layer in layers] == [["n1"], ["n2"], ["n3"]]


def test_from_dispatch_plan_parallel():
    class A:
        def __init__(self, name, sub_task):
            self.agent_name = name
            self.sub_task = sub_task

    class P:
        parallel = True
        assignments = [A("w1", "t1"), A("w2", "t2")]
        reason = "parallel test"

    g = from_dispatch_plan(P())
    assert g.validate()[0]
    assert len(g.layers()) == 1
    assert len(g.layers()[0]) == 2
    assert all(not n.depends_on for n in g.nodes)


def test_from_dispatch_plan_serial():
    class A:
        def __init__(self, name, sub_task):
            self.agent_name = name
            self.sub_task = sub_task

    class P:
        parallel = False
        assignments = [A("w1", "t1"), A("w2", "t2")]
        reason = "serial test"

    g = from_dispatch_plan(P())
    assert g.validate()[0]
    assert g.nodes[0].depends_on == []
    assert g.nodes[1].depends_on == ["n1"]
