"""P1-07 through P1-11: egress, handles, authority, audit, and modes."""
from __future__ import annotations

import json

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ReadFile, WriteFile
from core.context import Context
from core.types import CapabilityCall, Decision, Identity
from governance.egress import check_egress
from governance.secret_broker import SecretBroker


class _Vault:
    def get(self, name):
        return "secret-value" if name == "api" else ""


def test_private_egress_requires_explicit_destination(monkeypatch):
    monkeypatch.delenv("AGENT_EGRESS_ALLOW", raising=False)
    assert not check_egress("https://example.com", method="POST", data_classification="private")[0]
    monkeypatch.setenv("AGENT_EGRESS_ALLOW", "example.com")
    assert check_egress("https://example.com", method="POST", data_classification="private")[0]


def test_secret_handle_is_single_use_and_destination_bound():
    broker = SecretBroker(_Vault())
    handle = broker.issue("api", capability="http.request", destination="api.example.com")
    assert broker.resolve(handle, capability="http.request", destination="wrong.example.com") == ""
    handle = broker.issue("api", capability="http.request", destination="api.example.com")
    assert broker.resolve(handle, capability="http.request", destination="api.example.com") == "secret-value"
    assert broker.resolve(handle, capability="http.request", destination="api.example.com") == ""


def test_external_authority_cannot_authorize_write():
    from governance.engine import DeclarativePolicy
    policy = DeclarativePolicy(CapabilityRegistry([ReadFile(), WriteFile()]))
    ctx = Context(authority="email")
    call = CapabilityCall(name="fs.write", args={"path": "a.txt", "content": "x"})
    review = policy.review_detailed(call, Identity(), ctx)
    assert review.decision == Decision.BLOCK
    assert review.rule == "authority:untrusted-side-effect"


def test_governance_modes_are_behaviorally_distinct():
    from capabilities.tools.web import WebFetch
    from governance.engine import DeclarativePolicy
    reg = CapabilityRegistry([ReadFile(), WriteFile(), WebFetch()])
    read = CapabilityCall(name="web.fetch", args={"url": "https://example.com"})
    write = CapabilityCall(name="fs.write", args={"path": "a.txt", "content": "x"})
    assert DeclarativePolicy(reg, mode="conservative").review(read, Identity(), Context()) == Decision.ASK
    assert DeclarativePolicy(reg, mode="balanced").review(read, Identity(), Context()) == Decision.ALLOW
    ctx = Context(task_auto_approve=True)
    assert DeclarativePolicy(reg, mode="aggressive").review(write, Identity(), ctx) == Decision.ALLOW


def test_audit_hash_chain_detects_tampering(tmp_path, monkeypatch):
    import observability.audit as audit_mod
    path = tmp_path / "audit.log"
    monkeypatch.setattr(audit_mod, "_audit_path", lambda: str(path))
    audit_mod.audit(capability="fs.write", args={"path": "a.txt"}, decision="ask", ok=True, authority="owner")
    audit_mod.audit(capability="fs.write", args={"path": "b.txt"}, decision="allow", ok=True, authority="owner")
    assert audit_mod.verify_chain(str(path))
    rows = path.read_text(encoding="utf-8").splitlines()
    damaged = json.loads(rows[-1]); damaged["decision"] = "block"
    rows[-1] = json.dumps(damaged)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert not audit_mod.verify_chain(str(path))
