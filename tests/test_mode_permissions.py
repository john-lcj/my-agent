"""Phase 1 permission defaults: Cowork still needs explicit scoped grants."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ReadFile, WriteFile
from core.context import Context
from core.types import CapabilityCall, Decision, Identity


def _policy():
    from governance.engine import DeclarativePolicy
    return DeclarativePolicy(CapabilityRegistry([ReadFile(), WriteFile()]), config_path=None)


def _ctx(coworker: bool) -> Context:
    c = Context()
    c.coworker = coworker
    return c


def test_write_confirms_in_both_modes_without_a_scoped_grant():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    c = CapabilityCall(name="fs.write", args={"path": "note.txt", "content": "x"})
    assert pol.review(c, Identity(), _ctx(True)) == Decision.ASK
    assert pol.review(c, Identity(), _ctx(False)) == Decision.ASK
    assert pol.review(c, Identity(), None) == Decision.ASK


def test_cowork_still_blocks_hard_boundaries():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    rmrf = CapabilityCall(name="shell.run", args={"command": "rm -rf /"})
    assert pol.review(rmrf, Identity(), _ctx(True)) == Decision.BLOCK   # 硬边界:Cowork 也拦
    dotenv = CapabilityCall(name="shell.run", args={"command": "cat .env"})
    assert pol.review(dotenv, Identity(), _ctx(True)) == Decision.BLOCK  # 泄密路径:仍拦
    keys = CapabilityCall(name="fs.read", args={"path": "logs/model_keys.json"})
    assert pol.review(keys, Identity(), _ctx(True)) == Decision.BLOCK
    force_push = CapabilityCall(name="shell.run", args={"command": "git push --force origin main"})
    assert pol.review(force_push, Identity(), _ctx(True)) == Decision.BLOCK


def test_explicit_capability_grant_can_allow_a_write():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    wr = CapabilityCall(name="fs.write", args={"path": "a.txt", "content": "x"})
    ctx = _ctx(True)
    assert pol.review(wr, Identity(), ctx) == Decision.ASK
    ctx.grant_capability("fs.write")
    assert pol.review(wr, Identity(), ctx) == Decision.ALLOW


def test_cowork_workspace_escape_still_guarded():
    """工作区越界(防提示注入读外部机密)是有意保留的边界,Cowork 也不自动放行。"""
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.environ["AGENT_WORKSPACE_ROOT"] = root
        os.environ.pop("AGENT_WORKSPACE_STRICT", None)
        try:
            pol = _policy()
            outside = CapabilityCall(name="fs.read", args={"path": "/etc/hosts"})
            # 即便 Cowork,越界读仍需确认(非自动放行)
            assert pol.review(outside, Identity(), _ctx(True)) == Decision.ASK
        finally:
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
