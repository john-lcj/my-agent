"""pytest 回归 —— 复用 tests/harness 核心用例。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

# 项目根目录入 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests import harness as h


def test_bootstrap_gui_registry():
    ok, _ = h._bootstrap_gui_registry_check()
    assert ok


@pytest.mark.skipif(sys.platform != "darwin", reason="screencapture 仅 macOS 可用")
def test_gui_screenshot():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, _ = asyncio.run(h._gui_screenshot_check(tmp_dir))
        assert ok


def test_hybrid_memory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, _ = h._hybrid_memory_check(tmp_dir)
        assert ok


def test_vector_memory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, _ = h._vector_memory_check(tmp_dir)
        assert ok


def test_governance_reason():
    ok, _ = asyncio.run(h._governance_reason_check())
    assert ok


def test_memory_governance():
    ok, _ = asyncio.run(h._memory_governance_check())
    assert ok


def test_authz():
    ok, _ = h._authz_check()
    assert ok


def test_coordinator():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, _ = asyncio.run(h._coordinator_check(tmp_dir))
        assert ok


def test_streaming_tokens():
    ok, _ = asyncio.run(h._streaming_token_check())
    assert ok


def test_external_profile_registry():
    ok, _ = h._external_profile_registry_check()
    assert ok


def test_harness_full_suite():
    with tempfile.TemporaryDirectory() as tmp_dir:
        passed, total = asyncio.run(h.run_all_checks(tmp_dir, verbose=False))
        assert passed == total
