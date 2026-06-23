"""评测打分 + 长任务断点续跑 回归。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.scoring import score_case, summarize
from memory.checkpoint_store import CheckpointStore


# ── 评测打分 ──
def test_contains_and_not_contains():
    ok, fails = score_case("结果是 96", [], {"contains": ["96"], "not_contains": ["错误"]})
    assert ok and not fails
    ok2, f2 = score_case("出错了", [], {"contains": ["96"]})
    assert not ok2 and f2


def test_any_and_capabilities():
    ok, _ = score_case("无法查到", [], {"any": ["无法", "不能"]})
    assert ok
    ok2, f2 = score_case("done", ["wechat.format"], {"capabilities": ["wechat.format"]})
    assert ok2
    ok3, f3 = score_case("done", [], {"capabilities": ["wechat.format"]})
    assert not ok3 and "wechat.format" in f3[0]


def test_summarize_pass_rate():
    s = summarize([{"passed": True}, {"passed": False}, {"passed": True}])
    assert s["total"] == 3 and s["passed"] == 2 and s["pass_rate"] == round(2/3, 3)


# ── 断点续跑 ──
def test_checkpoint_unfinished(tmp_path):
    st = CheckpointStore(base_dir=str(tmp_path))
    st.save("sess-1", [
        {"text": "拉数据", "status": "done"},
        {"text": "写报告", "status": "doing"},
        {"text": "发邮件", "status": "pending"},
    ])
    un = st.unfinished("sess-1")
    assert un == ["写报告", "发邮件"]   # done 的不算


def test_checkpoint_clear(tmp_path):
    st = CheckpointStore(base_dir=str(tmp_path))
    st.save("s", [{"text": "x", "status": "pending"}])
    assert st.unfinished("s") == ["x"]
    st.clear("s")
    assert st.unfinished("s") == []


def test_checkpoint_missing_session(tmp_path):
    st = CheckpointStore(base_dir=str(tmp_path))
    assert st.load("nope") is None and st.unfinished("nope") == []
