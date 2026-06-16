"""按权限档分模型:模型选择优先级回归(AGENT_<NAME>_MODEL > spec.llm > 默认)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.worker import resolve_worker_model


def test_env_override_wins():
    os.environ["AGENT_EXECUTOR_MODEL"] = "deepseek-v4-pro"
    try:
        assert resolve_worker_model("executor", "deepseek", "deepseek-v4-flash") == "deepseek-v4-pro"
    finally:
        del os.environ["AGENT_EXECUTOR_MODEL"]


def test_falls_back_to_spec_llm():
    os.environ.pop("AGENT_RESEARCHER_MODEL", None)
    assert resolve_worker_model("researcher", "deepseek", "deepseek-v4-flash") == "deepseek"


def test_falls_back_to_default():
    os.environ.pop("AGENT_EXECUTOR_MODEL", None)
    assert resolve_worker_model("executor", "", "deepseek-v4-flash") == "deepseek-v4-flash"


def test_per_profile_independent():
    os.environ["AGENT_EXECUTOR_MODEL"] = "deepseek-v4-pro"
    os.environ.pop("AGENT_RESEARCHER_MODEL", None)
    try:
        assert resolve_worker_model("executor", "deepseek", "m") == "deepseek-v4-pro"
        assert resolve_worker_model("researcher", "deepseek", "m") == "deepseek"  # 不受 executor 影响
    finally:
        del os.environ["AGENT_EXECUTOR_MODEL"]
