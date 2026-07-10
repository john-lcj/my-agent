"""P1-04: routine tests are typed; residual shell has no raw command surface."""
from __future__ import annotations

import asyncio
import json

from capabilities.base import CapabilityRegistry
from capabilities.tools.shell import RunShell
from capabilities.tools.dev import RunTests
from core.context import Context
from core.types import CapabilityCall, Decision, Identity
from core.verification import Verification, run_verification


def test_residual_shell_rejects_raw_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    result = asyncio.run(RunShell().invoke({"command": "echo unsafe"}, None))
    assert not result.ok
    assert "raw shell commands" in (result.error or "")


def test_residual_shell_only_runs_configured_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_APPROVED_SHELL_COMMANDS_JSON", json.dumps({"echo-proof": ["/bin/echo", "proof"]}))
    result = asyncio.run(RunShell().invoke({"command_id": "echo-proof"}, None))
    assert result.ok
    assert result.output.strip() == "proof"


def test_residual_shell_rejects_unknown_command_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    result = asyncio.run(RunShell().invoke({"command_id": "anything"}, None))
    assert not result.ok
    assert "not approved" in (result.error or "")


def test_residual_shell_needs_a_fresh_confirmation_even_after_capability_grant():
    from governance.engine import DeclarativePolicy
    policy = DeclarativePolicy(CapabilityRegistry([RunShell()]))
    ctx = Context()
    ctx.grant_capability("shell.run")
    call = CapabilityCall(name="shell.run", args={"command_id": "echo-proof"})
    assert policy.review(call, Identity(), ctx) == Decision.ASK


def test_verification_rejects_shell_syntax_in_test_target(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    marker = tmp_path / "escaped"
    verification = Verification(kind="run_test", target=f"pytest -q; touch {marker}")
    run_verification(verification)
    assert verification.status == "fail"
    assert "test target" in verification.evidence
    assert not marker.exists()


def test_typed_runner_executes_only_a_workspace_test_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_SANDBOX_ALLOW_USER_SITE", "1")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    result = asyncio.run(RunTests().invoke({"target": "tests/test_ok.py"}, None))
    assert result.ok, result.error
    assert "1 passed" in result.output
