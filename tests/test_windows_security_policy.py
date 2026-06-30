from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ListDir, ReadFile, WriteFile
from capabilities.tools.web import WebFetch, WebSearch
from core.types import CapabilityCall, Decision, Identity
from governance.engine import DeclarativePolicy


def _policy() -> DeclarativePolicy:
    reg = CapabilityRegistry([ReadFile(), WriteFile(), ListDir(), WebSearch(), WebFetch()])
    return DeclarativePolicy(reg, config_path="governance/policy.yaml")


def _shell(command: str) -> CapabilityCall:
    return CapabilityCall(name="shell.run", args={"command": command})


def test_windows_readonly_shell_commands_are_allowed():
    p = _policy()
    actor = Identity(roles=("executor",))
    for command in [
        "python scripts/check.py",
        "py -3 scripts/check.py",
        "dir",
        "type README.md",
        "where python",
        "Get-ChildItem .",
        "Get-Content README.md",
        "Select-String -Path README.md -Pattern Captain",
        "Test-Path .\\install.ps1",
    ]:
        r = p.review_detailed(_shell(command), actor, None)
        assert r.decision != Decision.BLOCK, f"{command}: {r.reason}"


def test_windows_destructive_commands_are_hard_blocked():
    p = _policy()
    actor = Identity(roles=("executor",))
    for command in [
        "Remove-Item C:\\data -Recurse -Force",
        "Remove-Item C:\\data -Force -Recurse",
        "del /s /q C:\\data\\*",
        "rmdir /s /q C:\\data",
        "rd /s /q C:\\data",
        "format C:",
        "diskpart",
        "bcdedit /set testsigning on",
        "reg delete HKCU\\Software\\Captain /f",
        "takeown /f C:\\ /r",
    ]:
        r = p.review_detailed(_shell(command), actor, None)
        assert r.decision == Decision.BLOCK, f"{command}: {r.decision} {r.reason}"


def test_windows_write_and_process_commands_require_confirmation():
    p = _policy()
    actor = Identity(roles=("executor",))
    for command in [
        "Set-Content out.txt hello",
        "Add-Content out.txt hello",
        "Out-File out.txt",
        "New-Item out.txt",
        "Copy-Item a.txt b.txt",
        "Move-Item a.txt b.txt",
        "Stop-Process -Name notepad",
        "Set-ExecutionPolicy RemoteSigned",
        "icacls out.txt /grant Users:F",
    ]:
        r = p.review_detailed(_shell(command), actor, None)
        assert r.decision == Decision.ASK, f"{command}: {r.decision} {r.reason}"
