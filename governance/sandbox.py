"""Fail-closed local execution sandbox for residual code paths.

On macOS this uses the built-in Seatbelt runtime (``sandbox-exec``).  The
profile permits only the selected workspace for user data, denies networking
and process forking by default, and starts children with a scrubbed environment.
Unsupported hosts fail closed until a platform backend is added.
"""
from __future__ import annotations

import asyncio
import os
import platform
import site
import subprocess
from typing import Sequence

_MAX_OUTPUT = 256_000
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _limit_resources(timeout: float) -> None:
    """Inherited by sandbox-exec and its child; Seatbelt denies forks separately."""
    try:
        import resource
        cpu = max(1, min(int(timeout), 120))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError):
        pass


def _seatbelt_profile(workspace: str) -> str:
    root = os.path.realpath(workspace).replace('"', "")
    runtime_paths = []
    runtime_site_paths = site.getsitepackages()
    if os.environ.get("AGENT_SANDBOX_ALLOW_USER_SITE") == "1":
        runtime_site_paths.append(site.getusersitepackages())
    for path in runtime_site_paths:
        real = os.path.realpath(path)
        if real and os.path.isdir(real):
            runtime_paths.append(f'(allow file-read* (subpath "{real.replace(chr(34), "")}"))')
    runtime_rules = "\n".join(runtime_paths)
    # System runtimes remain readable, but host/user data does not. Explicit
    # workspace rules override the broad home-directory deny for its subtree.
    return f'''(version 1)
(deny default)
(allow process-exec)
(allow file-read*)
(deny file-read* (subpath "/Users"))
(deny file-read* (subpath "/etc"))
(deny file-read* (subpath "/private"))
(deny file-read* (subpath "/var"))
(deny file-read* (subpath "/Library"))
(deny file-read* (subpath "/Volumes"))
(deny file-read* (subpath "/Network"))
{runtime_rules}
(allow file-read* (literal "/dev/null"))
(allow file-write* (literal "/dev/null"))
(allow file-read* (subpath "{root}"))
(allow file-write* (subpath "{root}"))
'''


def sandbox_argv(argv: Sequence[str], workspace: str) -> tuple[list[str], str]:
    """Wrap an argv list in the available OS sandbox, or raise fail-closed."""
    if platform.system() != "Darwin" or not os.path.isfile(_SANDBOX_EXEC):
        raise RuntimeError("no supported OS sandbox is available on this host")
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("sandbox argv must contain non-empty strings")
    root = os.path.realpath(workspace)
    if not os.path.isdir(root):
        raise ValueError("sandbox workspace is not a directory")
    return [_SANDBOX_EXEC, "-p", _seatbelt_profile(root), *argv], root


def sandbox_env(workspace: str) -> dict[str, str]:
    """Do not pass API keys, tokens, or the real home directory to sandboxed code."""
    home = os.path.join(workspace, ".sandbox-home")
    os.makedirs(home, exist_ok=True)
    env = {
        "HOME": home,
        "TMPDIR": workspace,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    python_paths = [workspace]
    user_site = site.getusersitepackages()
    if os.environ.get("AGENT_SANDBOX_ALLOW_USER_SITE") == "1" and os.path.isdir(user_site):
        python_paths.append(user_site)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env


def _trim(data: bytes) -> str:
    text = data.decode("utf-8", "replace")
    return text[-_MAX_OUTPUT:] + ("\n[output truncated]" if len(text) > _MAX_OUTPUT else "")


async def run_async(
    argv: Sequence[str], *, workspace: str, timeout: float, input_data: str = "",
) -> tuple[bool, str, str]:
    command, root = sandbox_argv(argv, workspace)
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=root,
        env=sandbox_env(root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=lambda: _limit_resources(timeout),
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(input_data.encode("utf-8")), timeout=max(1.0, timeout))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return False, "", f"sandboxed process timed out after {timeout}s"
    body = _trim(out) + (f"\n[stderr]\n{_trim(err)}" if err else "")
    return proc.returncode == 0, body, "" if proc.returncode == 0 else f"sandboxed process exited {proc.returncode}"


def run_sync(argv: Sequence[str], *, workspace: str, timeout: float) -> tuple[bool, str, str]:
    command, root = sandbox_argv(argv, workspace)
    try:
        result = subprocess.run(
            command, cwd=root, env=sandbox_env(root), capture_output=True,
            timeout=max(1.0, timeout), check=False,
            preexec_fn=lambda: _limit_resources(timeout),
        )
    except subprocess.TimeoutExpired:
        return False, "", f"sandboxed process timed out after {timeout}s"
    body = _trim(result.stdout) + (f"\n[stderr]\n{_trim(result.stderr)}" if result.stderr else "")
    return result.returncode == 0, body, "" if result.returncode == 0 else f"sandboxed process exited {result.returncode}"
