"""Regression coverage for the single workspace path boundary."""
from __future__ import annotations

import asyncio

import pytest
from core.verification import Verification, run_verification
from governance.workspace import resolve_path


def test_resolver_rejects_traversal_and_outside_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    path, error = resolve_path("../outside.txt")
    assert path == ""
    assert "outside" in error
    path, error = resolve_path("/etc/passwd", require_exists=True)
    assert path == ""
    assert "outside" in error


def test_resolver_rejects_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    path, error = resolve_path("link.txt", require_exists=True)
    assert path == ""
    assert "outside" in error


def test_file_tools_enforce_workspace_for_read_and_write(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    from capabilities.tools.fs import ReadFile, WriteFile
    result = asyncio.run(WriteFile().invoke({"path": "../escape.txt", "content": "no"}, None))
    assert not result.ok and "outside" in (result.error or "")
    result = asyncio.run(ReadFile().invoke({"path": "/etc/passwd"}, None))
    assert not result.ok and "outside" in (result.error or "")


def test_verification_cannot_read_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    v = Verification(kind="read_file", target="/etc/passwd")
    run_verification(v)
    assert v.status == "fail"
