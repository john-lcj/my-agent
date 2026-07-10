"""Phase 1: capability metadata and default-deny policy contracts."""
from __future__ import annotations

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ReadFile, WriteFile
from core.context import Context
from core.types import CapabilityCall, CapabilityResult, Decision, Identity, Risk
from governance.engine import DeclarativePolicy
from governance.gateway import invoke_governed


class _IncompleteCapability:
    name = "test.incomplete"
    risk = Risk.READ
    description = "missing manifest"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args, ctx):
        return CapabilityResult(ok=True, output="should not run")


def test_builtin_registry_has_complete_manifests():
    from core.bootstrap import build_registry

    registry = build_registry("interactive")
    errors = registry.manifest_audit()
    assert all(name.startswith("skill.") for name in errors)
    assert all(registry.manifest_for(spec["name"]) is not None for spec in registry.specs())


def test_incomplete_capability_is_not_exposed_and_is_default_denied():
    registry = CapabilityRegistry([_IncompleteCapability()])
    assert registry.specs() == []
    policy = DeclarativePolicy(registry, config_path=None)
    call = CapabilityCall(name="test.incomplete", declared_risk=Risk.READ)
    review = policy.review_detailed(call, Identity(), Context())
    assert review.decision == Decision.BLOCK
    assert review.rule == "manifest:default-deny"


def test_write_defaults_to_confirmation_without_an_explicit_grant():
    registry = CapabilityRegistry([ReadFile(), WriteFile()])
    policy = DeclarativePolicy(registry, config_path=None)
    call = CapabilityCall(name="fs.write", args={"path": "note.txt", "content": "x"})
    assert policy.review(call, Identity(), Context()) == Decision.ASK


def test_governed_gateway_requires_approval_before_a_write():
    registry = CapabilityRegistry([WriteFile()])
    policy = DeclarativePolicy(registry, config_path=None)
    call = CapabilityCall(name="fs.write", args={"path": "note.txt", "content": "x"})

    async def deny(*_args):
        return False

    import asyncio

    result = asyncio.run(invoke_governed(registry, policy, call, Identity(), Context(), deny))
    assert result.ok is False
    assert "approval" in (result.error or "")


def test_explicit_user_skill_manifest_is_exposed():
    from skills.base import SkillCapability, SkillManifest

    async def run(_args, _ctx):
        return CapabilityResult(ok=True, output="ok")

    manifest = SkillManifest(
        name="approved_user_skill",
        description="test",
        trigger="",
        risk=Risk.READ,
        path="/tmp/approved_user_skill",
        source_root="/tmp/user-skills",
        security_manifest={
            "name": "skill.approved_user_skill",
            "risk": "READ",
            "data_scope": "task-input",
            "side_effect": "none",
            "reversible": True,
            "authorization": "auto-read",
            "timeout_seconds": 5,
            "verification": "tool-result",
            "source": "user-reviewed",
        },
    )
    registry = CapabilityRegistry([SkillCapability(manifest, run, {"type": "object"})])
    assert registry.manifest_audit() == {}
    assert registry.specs()[0]["name"] == "skill.approved_user_skill"
