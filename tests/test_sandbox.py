"""P1-05 Seatbelt coverage for residual commands and generated skills."""
from __future__ import annotations

import asyncio
import json
import platform
import sys

import pytest

from governance.sandbox import run_sync

pytestmark = pytest.mark.skipif(platform.system() != "Darwin", reason="macOS Seatbelt backend")


def test_sandbox_allows_workspace_write_but_blocks_host_file_and_network(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SANDBOX_ALLOW_USER_SITE", "1")
    write = "from pathlib import Path; Path('proof.txt').write_text('ok')"
    ok, _, error = run_sync([sys.executable, "-c", write], workspace=str(tmp_path), timeout=10)
    assert ok, error
    assert (tmp_path / "proof.txt").read_text(encoding="utf-8") == "ok"

    read_host = "open('/etc/hosts', encoding='utf-8').read()"
    ok, output, _ = run_sync([sys.executable, "-c", read_host], workspace=str(tmp_path), timeout=10)
    assert not ok
    assert "Operation not permitted" in output

    fork = "import subprocess; subprocess.run(['/bin/echo', 'child'], check=True)"
    ok, output, _ = run_sync([sys.executable, "-c", fork], workspace=str(tmp_path), timeout=10)
    assert not ok
    assert "Operation not permitted" in output

    network = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=1)"
    ok, output, _ = run_sync([sys.executable, "-c", network], workspace=str(tmp_path), timeout=10)
    assert not ok
    assert "Operation not permitted" in output


def test_generated_workspace_skill_runs_inside_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_SANDBOX_ALLOW_USER_SITE", "1")
    root = tmp_path / ".agent" / "skills"
    skill_dir = root / "probe"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(json.dumps({
        "name": "probe", "description": "sandbox probe", "risk": "READ",
        "security_manifest": {
            "data_scope": "workspace", "side_effect": "none", "reversible": True,
            "authorization": "auto-read", "timeout_seconds": 30,
            "verification": "tool-result", "source": "generated-workspace-skill",
        },
    }), encoding="utf-8")
    (skill_dir / "impl.py").write_text(
        "class R:\n"
        "    def __init__(self, ok, output='', error=None): self.ok, self.output, self.error = ok, output, error\n"
        "async def run(args, ctx):\n"
        "    try:\n"
        "        open('/etc/hosts').read()\n"
        "        return R(False, error='host read unexpectedly succeeded')\n"
        "    except PermissionError:\n"
        "        return R(True, output='host read blocked')\n",
        encoding="utf-8",
    )
    from skills.base import SkillRegistry
    registry = SkillRegistry(str(root))
    registry.discover()
    result = asyncio.run(registry.load("probe").invoke({}, None))
    assert result.ok, result.error
    assert result.output == "host read blocked"
