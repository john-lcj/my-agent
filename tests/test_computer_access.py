from __future__ import annotations

import asyncio
import os

import pytest

from capabilities.base import CapabilityRegistry
from capabilities.gui import GUIControl, GUIObserve, _screenshot
from core.computer_access import FULL_ACCESS, WORKSPACE_ACCESS, apply_computer_access_mode
from core.types import CapabilityCall, Decision, Identity
from governance.engine import DeclarativePolicy
from governance.workspace import resolve_path


class _Ctx:
    authority = "owner"
    task_auto_approve = False
    capability_grants = set()
    grants = set()


def test_interactive_registry_has_observe_and_control():
    from core.bootstrap import build_registry

    names = {spec["name"] for spec in build_registry("interactive").specs()}
    assert {"gui.observe", "gui.control"}.issubset(names)


def test_full_access_expands_paths_but_keeps_relative_base(tmp_path, monkeypatch):
    import core.computer_access as access

    monkeypatch.setattr(access, "_BASE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    apply_computer_access_mode(WORKSPACE_ACCESS)
    _, error = resolve_path("/etc/hosts", require_exists=True)
    assert "outside" in error

    apply_computer_access_mode(FULL_ACCESS)
    path, error = resolve_path("/etc/hosts", require_exists=True)
    assert path == os.path.realpath("/etc/hosts") and not error
    assert os.environ["AGENT_WORKSPACE_ROOT"] == str(tmp_path)

    apply_computer_access_mode(WORKSPACE_ACCESS)
    assert "CAPTAIN_FULL_COMPUTER_ACCESS" not in os.environ


def test_full_access_auto_allows_owner_gui_but_default_asks(monkeypatch):
    registry = CapabilityRegistry([GUIObserve(), GUIControl()])
    policy = DeclarativePolicy(registry, config_path="governance/policy.yaml")
    call = CapabilityCall(name="gui.control", args={"action": "open_app", "app_name": "Finder"})
    monkeypatch.delenv("CAPTAIN_FULL_COMPUTER_ACCESS", raising=False)
    assert policy.review(call, Identity(), _Ctx()) == Decision.ASK
    monkeypatch.setenv("CAPTAIN_FULL_COMPUTER_ACCESS", "1")
    assert policy.review(call, Identity(), _Ctx()) == Decision.ALLOW


def test_screenshot_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    class _FailedProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"screen recording denied"

    async def fake_subprocess(*_args, **_kwargs):
        return _FailedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    with pytest.raises(RuntimeError, match="screen recording denied"):
        asyncio.run(_screenshot(str(tmp_path / "screen.png")))


def test_permission_status_uses_non_prompting_preflight(monkeypatch):
    import core.computer_access as access

    monkeypatch.setattr(access.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(access, "_macos_accessibility_trusted", lambda: True)
    monkeypatch.setattr(access, "_macos_screen_capture_trusted", lambda: False)
    monkeypatch.setattr(
        access.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("protected command executed")),
    )
    assert access.computer_permission_status() == {
        "platform": "darwin",
        "supported": True,
        "accessibility": True,
        "screen_recording": False,
    }


def test_open_settings_does_not_trigger_protected_operation(monkeypatch):
    import core.computer_access as access

    calls = []
    monkeypatch.setattr(access.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(access.subprocess, "Popen", lambda argv: calls.append(argv))
    monkeypatch.setattr(
        access.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("protected command executed")),
    )
    access.open_macos_privacy_settings("screen_recording")
    assert len(calls) == 1
    assert calls[0][0] == "open"


def test_local_desktop_can_toggle_full_access_with_explicit_confirmation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import server.app as appmod

    original_path = appmod._runtime_cfg.path
    original_mode = appmod._runtime_cfg.get_computer_access_mode()
    appmod._runtime_cfg.path = str(tmp_path / "runtime.json")
    monkeypatch.setenv("CAPTAIN_DESKTOP", "1")
    client = TestClient(appmod.app, client=("127.0.0.1", 50000))
    try:
        denied = client.post("/api/system/computer-access", json={"mode": "full"})
        assert denied.status_code == 400
        enabled = client.post(
            "/api/system/computer-access",
            json={"mode": "full", "confirmation": "FULL COMPUTER ACCESS"},
        )
        assert enabled.status_code == 200
        assert enabled.json()["full_access_active"] is True
        restored = client.post("/api/system/computer-access", json={"mode": "workspace"})
        assert restored.status_code == 200
        assert restored.json()["full_access_active"] is False
    finally:
        appmod._runtime_cfg.path = original_path
        apply_computer_access_mode(original_mode)
