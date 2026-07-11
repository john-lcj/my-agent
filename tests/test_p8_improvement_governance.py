import subprocess

from core.improvement_governance import (
    ImprovementStore, artifact_manifest, candidate_gate, can_promote, create_isolated_worktree, implementation_allowed, record_signature,
    mine_failures, propose,
)


def test_p8_proposal_requires_scope_and_protects_kernel(tmp_path):
    proposal = propose(title="Fix retry", root_cause="timeout", expected_benefit="fewer failures",
                       affected_paths=["core/loop.py"], risks=["regression"], tests=["pytest"], rollback="revert commit")
    store = ImprovementStore(str(tmp_path / "improvements.json"))
    stored = store.add(proposal)
    assert implementation_allowed(stored)[0] is False
    stored = store.update(proposal.id, owner_approved=True)
    assert implementation_allowed(stored)[0] is True
    protected = dict(stored, affected_paths=["governance/policy.py"])
    assert implementation_allowed(protected)[0] is False


def test_p8_failure_gate_canary_and_artifact_contract():
    clusters = mine_failures([{"ok": False, "detail": "timeout", "impact": "high", "reproducible": True}] * 2)
    assert clusters[0]["frequency"] == 2 and clusters[0]["reproducible"]
    assert candidate_gate(baseline_success=.9, candidate_success=.89, critical_security_failures=0,
                          independent_reviewed=True, owner_approved=True)[0]
    assert not candidate_gate(baseline_success=.9, candidate_success=.87, critical_security_failures=0,
                              independent_reviewed=True, owner_approved=True)[0]
    manifest = artifact_manifest(".", "abc", {"python": "3"})
    assert record_signature(manifest, "external-signature", "release-authority")["signer"] == "release-authority"
    assert can_promote({"started_at": 0, "task_volume": 0})[0]
    assert not can_promote({"started_at": 0, "crashes": 1})[0]


def test_p8_creates_isolated_worktree_only_for_approved_scope(tmp_path):
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
    assert path.endswith("candidate")
