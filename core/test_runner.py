"""Typed test execution shared by the agent and delivery verification."""
from __future__ import annotations

import os
import re
import sys

from governance.sandbox import run_sync
from governance.workspace import resolve_path, workspace_root

_PYTEST_PREFIX = re.compile(r"^(?:(?:python3?|py\s+-3)\s+-m\s+)?pytest(?:\s+-q)?\s*")
_TARGET = re.compile(r"^tests(?:/[A-Za-z0-9_.-]+)*(?:::[A-Za-z_][A-Za-z0-9_]*)*$")


def normalize_test_target(value: str) -> tuple[str, str]:
    """Accept a test path or legacy pytest spelling, never a shell program."""
    raw = (value or "").strip()
    if not raw:
        return "", "test target is required"
    target = _PYTEST_PREFIX.sub("", raw).strip() if _PYTEST_PREFIX.match(raw) else raw
    if not _TARGET.fullmatch(target):
        return "", "test target must be a path below tests/"
    path_part = target.split("::", 1)[0]
    path, error = resolve_path(path_part, require_exists=True)
    if error:
        return "", error
    if not os.path.isfile(path):
        return "", "test target is not a file"
    return target, ""


def run_pytest(target: str, *, timeout: int = 120) -> tuple[bool, str, str]:
    normalized, error = normalize_test_target(target)
    if error:
        return False, "", error
    ok, output, error = run_sync(
        [sys.executable, "-m", "pytest", "-q", normalized],
        workspace=workspace_root(), timeout=timeout,
    )
    return ok, output[-1500:], error
