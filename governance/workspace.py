"""Canonical filesystem boundary for agent-visible workspaces.

Every path supplied to a capability is resolved from the configured workspace
root and checked *after* symlinks are resolved.  Keeping this here avoids the
usual split-brain security bug where one API rejects ``../`` while another
quietly accepts it.
"""
from __future__ import annotations

import os


def workspace_root() -> str:
    raw = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    return os.path.realpath(os.path.expanduser(raw))


def resolve_path(raw_path: str, *, default: str = "", require_exists: bool = False) -> tuple[str, str]:
    """Return an absolute in-workspace path, or ``('', reason)``.

    ``realpath`` deliberately runs before the containment check, including for
    a not-yet-created output file, so a symlinked parent cannot escape the root.
    """
    raw = (raw_path or default or "").strip()
    if not raw:
        return "", "missing path"
    root = workspace_root()
    candidate = os.path.expanduser(raw)
    if not os.path.isabs(candidate):
        candidate = os.path.join(root, candidate)
    resolved = os.path.realpath(candidate)
    if resolved != root and not resolved.startswith(root + os.sep):
        return "", "path is outside the authorized workspace"
    if require_exists and not os.path.exists(resolved):
        return "", "path does not exist"
    return resolved, ""


def artifacts_dir() -> str:
    path, error = resolve_path("产物")
    if error:  # workspace_root is always a valid base, retained as a guard.
        raise RuntimeError(error)
    os.makedirs(path, exist_ok=True)
    return path
