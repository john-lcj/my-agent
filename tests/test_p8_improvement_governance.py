import base64
import hashlib
import subprocess
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.improvement_governance import (
    CanaryStore, ImprovementStore, artifact_manifest, candidate_gate, can_promote,
    compare_repeated_runs, create_isolated_worktree, implementation_allowed,
    mine_failures, propose, record_signature, rollback_release, rollback_required, signed_payload,
)


def _keys():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def _signature(private, payload: bytes) -> str:
    return base64.b64encode(private.sign(payload)).decode()


def test_p8_external_approval_hash_chain_and_kernel_boundary(tmp_path):
    proposal = propose(title="Fix retry", root_cause="timeout", expected_benefit="fewer failures",
                       affected_paths=["core/loop.py"], risks=["regression"], tests=["pytest"], rollback="revert commit")
    store = ImprovementStore(str(tmp_path / "improvements.jsonl")); stored = store.add(proposal)
    assert implementation_allowed(stored)[0] is False
    private, public = _keys()
    with pytest.raises(PermissionError): store.approve(proposal.id, public, "invalid")
    approved = store.approve(proposal.id, public, _signature(private, signed_payload(proposal.id, "approve")))
    assert approved["owner_approved"] and store.verify_chain()
    assert implementation_allowed(approved)[0]
    review_key, review_public = _keys(); evidence_hash = "evidence"
    reviewed = store.record_review(proposal.id, evidence_hash, review_public,
                                   _signature(review_key, signed_payload(proposal.id, "review", evidence_hash)))
    assert reviewed["independent_reviewed"]
    released = store.approve_release(proposal.id, evidence_hash, public,
                                     _signature(private, signed_payload(proposal.id, "release", evidence_hash)))
    assert released["release_approved"]
    assert not implementation_allowed(dict(approved, affected_paths=["governance/policy.py"]))[0]
    with open(store.path, "a", encoding="utf-8") as handle: handle.write('{"tampered":true}\n')
    assert not store.verify_chain()


def test_p8_repeated_gate_signed_artifact_and_canary(tmp_path):
    comparison = compare_repeated_runs([.9, .91, .89], [.89, .9, .9])
    assert candidate_gate(comparison=comparison, critical_security_failures=0,
                          independent_reviewed=True, owner_approved=True)[0]
    assert not candidate_gate(comparison=compare_repeated_runs([.9]*3, [.87]*3), critical_security_failures=0,
                              independent_reviewed=True, owner_approved=True)[0]
    artifact = tmp_path / "app.py"; artifact.write_text("ok", encoding="utf-8")
    manifest = artifact_manifest(str(tmp_path), "abc", {"python": "3"}, ["app.py"])
    assert manifest == artifact_manifest(str(tmp_path), "abc", {"python": "3"}, ["app.py"])
    private, public = _keys(); signer = "release-authority"
    payload = ('{"manifest_hash":"' + manifest["manifest_hash"] + '","signer":"' + signer + '"}').encode()
    signed = record_signature(manifest, _signature(private, payload), signer, public)
    canary = CanaryStore(str(tmp_path / "canary.json")).start("p1", signed, ["read"], now=1000)
    evidence_hash = hashlib.sha256(__import__("json").dumps(canary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    promote_sig = _signature(private, signed_payload("p1", "promote", evidence_hash))
    assert not can_promote(canary, public_key_b64=public, signature_b64="invalid", now=1000 + 8*86400)[0]
    assert can_promote(canary, public_key_b64=public, signature_b64=promote_sig, now=1000 + 8*86400)[0]
    canary["duplicate_effects"] = 1
    assert not can_promote(canary, public_key_b64=public, signature_b64=promote_sig, now=1000 + 8*86400)[0]
    assert rollback_required(canary)[0]


def test_p8_isolated_worktree_and_rollback_under_five_minutes(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "app.py").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True)
    proposal = {"id": "candidate", "owner_approved": True, "affected_paths": ["app.py"]}
    path = create_isolated_worktree(str(repo), proposal)
    assert (tmp_path / ".captain-improvements" / "candidate" / "app.py").is_file()
    snapshot = tmp_path / "snapshot"; snapshot.mkdir(); (snapshot / "app.py").write_text("stable", encoding="utf-8")
    pairs = [("app.py", hashlib.sha256(b"stable").hexdigest())]
    expected = hashlib.sha256(('[[' + '"app.py","' + pairs[0][1] + '"]]').encode()).hexdigest()
    target = tmp_path / "runtime"; target.mkdir(); (target / "app.py").write_text("broken", encoding="utf-8")
    result = rollback_release(str(snapshot), str(target), expected, started_at=time.time())
    assert result["ok"] and (target / "app.py").read_text() == "stable"


def test_p8_failure_mining_is_clustered():
    rows = mine_failures([{"ok": False, "detail": "timeout", "impact": "high", "reproducible": True}] * 2)
    assert rows[0]["frequency"] == 2 and rows[0]["reproducible"]
