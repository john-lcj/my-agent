import json

import pytest

from browser_runtime.fixtures import fixture_contract
from browser_runtime.kernel import (
    BrowserContextKey,
    BrowserKernel,
    BrowserOperation,
    BrowserTrace,
    RemoteStateAssertion,
)


def test_context_identity_is_stable_and_path_safe():
    left = BrowserContextKey("owner", "account-a", "project", "task-1")
    right = BrowserContextKey("owner", "account-a", "project", "task-1")
    assert left.value == right.value and len(left.value) == 64
    with pytest.raises(ValueError):
        BrowserContextKey("owner", "../account", "project", "task")


def test_browser_kernel_leases_and_idempotent_operations(tmp_path):
    kernel = BrowserKernel(str(tmp_path / "browser.db"), str(tmp_path / "trace.jsonl"))
    context = BrowserContextKey("owner", "account", "project", "task")
    lease = kernel.acquire(context)
    with pytest.raises(RuntimeError):
        kernel.acquire(context)
    op = BrowserOperation("form.submit", "fixture", selector="#fixture-form", high_impact=True)
    first = kernel.execute(context, op, lambda: {"saved": True})
    second = kernel.execute(context, op, lambda: {"saved": False})
    assert first["ok"] and second["status"] == "deduplicated" and second["result"] == {"saved": True}
    assert kernel.release(lease)


def test_trace_redacts_secret_and_preserves_hash_chain(tmp_path):
    kernel = BrowserKernel(str(tmp_path / "browser.db"), str(tmp_path / "trace.jsonl"))
    first = BrowserTrace("t1", "ctx", "op", "fill", "fixture",
                         accessibility={"secret": "super-secret", "role": "textbox"})
    second = BrowserTrace("t2", "ctx", "op2", "click", "fixture", result="ok")
    h1 = kernel.append_trace(first)
    h2 = kernel.append_trace(second)
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert rows[0]["accessibility"]["secret"] == "[REDACTED]"
    assert rows[1]["previous_hash"] == h1 and rows[1]["hash"] == h2


def test_remote_state_assertion_requires_explicit_evidence():
    assertion = RemoteStateAssertion("saved", expected_url="http://fixture/saved",
                                     required_text=("Saved successfully",), forbidden_text=("Error",))
    assert assertion.verify(url="http://fixture/saved", text="Saved successfully")[0]
    assert not assertion.verify(url="http://fixture/form", text="Saved successfully")[0]
    assert not assertion.verify(url="http://fixture/saved", text="Error")[0]


def test_local_fixture_declares_accessible_and_secret_fields():
    fixture = fixture_contract()
    assert fixture["required_roles"] == ["heading", "textbox", "button"]
    assert fixture["secret_fields"] == ["secret"]


def test_playwright_context_state_paths_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path))
    from capabilities.tools.browser import BrowserOpen, _state_file
    first = BrowserContextKey("owner", "account-a", "project", "task")
    second = BrowserContextKey("owner", "account-b", "project", "task")
    assert _state_file(first) != _state_file(second)
    assert "account_id" in BrowserOpen.schema["properties"]
