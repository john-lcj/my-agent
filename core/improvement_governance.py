"""Controlled self-improvement with externally signed release authority."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


PROTECTED_PATH_PREFIXES = (
    "governance/", "observability/audit", "governance/secret", "core/runtime_identity",
    "core/improvement_governance", "scripts/release", "desktop/scripts/prepare",
    "server/keychain", "server/routers/misc", "scripts/sync-all",
)


@dataclass
class ImprovementProposal:
    id: str
    title: str
    root_cause: str
    expected_benefit: str
    affected_paths: list[str]
    risks: list[str]
    tests: list[str]
    rollback: str
    status: str = "proposed"
    owner_approved: bool = False
    independent_reviewed: bool = False
    evidence: list[dict[str, Any]] = field(default_factory=list)
    learning: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def signed_payload(proposal_id: str, action: str, evidence_hash: str = "") -> bytes:
    return _canonical({"proposal_id": proposal_id, "action": action, "evidence_hash": evidence_hash}).encode()


def verify_external_signature(public_key_b64: str, payload: bytes, signature_b64: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.b64decode(signature_b64, validate=True), payload)
        return True
    except (ValueError, InvalidSignature):
        return False


class ImprovementStore:
    """Hash-chained event store; approval/evidence cannot use a generic update API."""

    def __init__(self, path: str = "logs/improvements.jsonl") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _events(self) -> list[dict]:
        if not os.path.isfile(self.path):
            return []
        rows = []
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def verify_chain(self) -> bool:
        previous = ""
        try:
            for event in self._events():
                digest = event.get("hash", "")
                unsigned = {key: value for key, value in event.items() if key != "hash"}
                if unsigned.get("prev_hash") != previous or digest != hashlib.sha256((previous + _canonical(unsigned)).encode()).hexdigest():
                    return False
                previous = digest
        except Exception:
            return False
        return True

    def _append(self, kind: str, proposal_id: str, data: dict) -> dict:
        if not self.verify_chain():
            raise RuntimeError("improvement evidence chain is invalid")
        events = self._events(); previous = events[-1]["hash"] if events else ""
        event = {"id": uuid.uuid4().hex, "ts": time.time(), "kind": kind,
                 "proposal_id": proposal_id, "data": data, "prev_hash": previous}
        event["hash"] = hashlib.sha256((previous + _canonical(event)).encode()).hexdigest()
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(_canonical(event) + "\n")
            handle.flush(); os.fsync(handle.fileno())
        return event

    def list(self) -> list[dict]:
        if not self.verify_chain():
            raise RuntimeError("improvement evidence chain is invalid")
        states: dict[str, dict] = {}
        for event in self._events():
            pid, kind, data = event["proposal_id"], event["kind"], event["data"]
            if kind == "proposal_created":
                states[pid] = dict(data)
            elif pid in states:
                if kind == "owner_approved":
                    states[pid].update(owner_approved=True, status="approved")
                elif kind == "independent_reviewed":
                    states[pid].update(independent_reviewed=True, status="reviewed")
                elif kind == "release_approved":
                    states[pid].update(release_approved=True, status="release_approved")
                elif kind == "evidence_recorded":
                    states[pid].setdefault("evidence", []).append(data)
                elif kind == "learning_recorded":
                    states[pid].setdefault("learning", []).append(data)
                elif kind == "status_changed":
                    states[pid]["status"] = data["status"]
                states[pid]["updated_at"] = event["ts"]
        return list(states.values())

    def get(self, proposal_id: str) -> dict | None:
        return next((row for row in self.list() if row.get("id") == proposal_id), None)

    def add(self, proposal: ImprovementProposal) -> dict:
        self._append("proposal_created", proposal.id, asdict(proposal))
        return self.get(proposal.id) or {}

    def approve(self, proposal_id: str, public_key_b64: str, signature_b64: str) -> dict:
        if not self.get(proposal_id):
            raise KeyError(proposal_id)
        if not verify_external_signature(public_key_b64, signed_payload(proposal_id, "approve"), signature_b64):
            raise PermissionError("invalid release-authority signature")
        self._append("owner_approved", proposal_id, {"signature": signature_b64, "public_key_hash": hashlib.sha256(public_key_b64.encode()).hexdigest()})
        return self.get(proposal_id) or {}

    def record_review(self, proposal_id: str, evidence_hash: str, public_key_b64: str, signature_b64: str) -> dict:
        if not self.get(proposal_id):
            raise KeyError(proposal_id)
        if not verify_external_signature(public_key_b64, signed_payload(proposal_id, "review", evidence_hash), signature_b64):
            raise PermissionError("invalid independent-review signature")
        self._append("independent_reviewed", proposal_id, {"evidence_hash": evidence_hash, "signature": signature_b64})
        return self.get(proposal_id) or {}

    def approve_release(self, proposal_id: str, evidence_hash: str, public_key_b64: str, signature_b64: str) -> dict:
        proposal = self.get(proposal_id)
        if not proposal or not proposal.get("independent_reviewed"):
            raise PermissionError("independent signed review is required before release approval")
        if not verify_external_signature(public_key_b64, signed_payload(proposal_id, "release", evidence_hash), signature_b64):
            raise PermissionError("invalid release-approval signature")
        self._append("release_approved", proposal_id, {"evidence_hash": evidence_hash, "signature": signature_b64})
        return self.get(proposal_id) or {}

    def add_evidence(self, proposal_id: str, kind: str, value: dict) -> dict:
        if not self.get(proposal_id):
            raise KeyError(proposal_id)
        payload = {"kind": kind, "value": value, "evidence_hash": _digest(value)}
        self._append("evidence_recorded", proposal_id, payload)
        return payload

    def record_learning(self, proposal_id: str, decision: str, expected: str, observed: str) -> None:
        if not self.get(proposal_id):
            raise KeyError(proposal_id)
        self._append("learning_recorded", proposal_id, {"decision": decision, "expected": expected, "observed": observed})


def protected_path(path: str) -> bool:
    normalized = os.path.normpath((path or "").replace("\\", "/")).lstrip("./")
    return normalized.startswith("../") or any(normalized.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def mine_failures(events: list[dict]) -> list[dict]:
    clusters: dict[tuple[str, str], dict] = {}
    for event in events:
        if event.get("ok", True):
            continue
        root = str(event.get("root_cause") or event.get("detail") or "unknown")[:160]
        impact = str(event.get("impact") or "low")
        row = clusters.setdefault((root, impact), {"root_cause": root, "impact": impact, "frequency": 0, "reproducible": False})
        row["frequency"] += 1; row["reproducible"] |= bool(event.get("reproducible"))
    return sorted(clusters.values(), key=lambda item: (item["impact"] == "critical", item["frequency"]), reverse=True)


def mine_failure_files(paths: list[str]) -> list[dict]:
    events = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line); events.append(row)
        except Exception:
            continue
    return mine_failures(events)


def propose(*, title: str, root_cause: str, expected_benefit: str, affected_paths: list[str],
            risks: list[str], tests: list[str], rollback: str) -> ImprovementProposal:
    if not all([title.strip(), root_cause.strip(), expected_benefit.strip(), affected_paths, risks, tests, rollback.strip()]):
        raise ValueError("proposal requires benefit, scope, risks, tests, and rollback")
    return ImprovementProposal(uuid.uuid4().hex[:12], title.strip(), root_cause.strip(), expected_benefit.strip(),
                               [path.strip() for path in affected_paths if path.strip()], risks, tests, rollback.strip())


def implementation_allowed(proposal: dict) -> tuple[bool, str]:
    if not proposal.get("owner_approved"):
        return False, "externally signed owner approval is required"
    if any(protected_path(path) for path in proposal.get("affected_paths", [])):
        return False, "proposal touches the protected kernel"
    return True, "approved isolated implementation"


def create_isolated_worktree(root: str, proposal: dict, *, base_ref: str = "HEAD") -> str:
    allowed, reason = implementation_allowed(proposal)
    if not allowed:
        raise PermissionError(reason)
    root_path = Path(root).resolve(); target = root_path.parent / ".captain-improvements" / str(proposal["id"])
    if target.exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "-C", str(root_path), "worktree", "add", "--detach", str(target), base_ref], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "could not create isolated worktree")
    for filename in (".env", "logs", "data"):
        candidate = target / filename
        if candidate.is_file(): candidate.unlink()
        elif candidate.is_dir(): shutil.rmtree(candidate)
    return str(target)


def validate_candidate_scope(worktree: str, proposal: dict) -> tuple[bool, list[str]]:
    result = subprocess.run(["git", "-C", worktree, "diff", "--name-only", "HEAD"], capture_output=True, text=True, timeout=10)
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    allowed = set(proposal.get("affected_paths", []))
    invalid = [path for path in changed if protected_path(path) or not any(path == item or path.startswith(item.rstrip("/") + "/") for item in allowed)]
    return not invalid, invalid


def run_verification_pipeline(root: str, suites: tuple[str, ...] = ("compile", "unit", "eval")) -> dict:
    commands = {
        "compile": ["python3", "-m", "compileall", "-q", "core", "memory", "server", "governance"],
        "unit": ["python3", "-m", "pytest", "-q", "tests"],
        "eval": ["python3", "scripts/run_evals.py", "--mock", "--repeat", "3", "--no-gate"],
    }
    results = []
    for suite in suites:
        if suite not in commands: raise ValueError(f"unknown verification suite: {suite}")
        started = time.time(); proc = subprocess.run(commands[suite], cwd=root, capture_output=True, text=True, timeout=600)
        results.append({"suite": suite, "ok": proc.returncode == 0, "seconds": round(time.time() - started, 3),
                        "output_hash": hashlib.sha256((proc.stdout + proc.stderr).encode()).hexdigest()})
    return {"ok": all(row["ok"] for row in results), "results": results, "evidence_hash": _digest(results)}


def compare_repeated_runs(baseline: list[float], candidate: list[float]) -> dict:
    if len(baseline) < 3 or len(candidate) < 3:
        raise ValueError("comparative evaluation requires at least three runs per version")
    base, cand = sum(baseline) / len(baseline), sum(candidate) / len(candidate)
    regression = base - cand
    return {"baseline_mean": base, "candidate_mean": cand, "regression": regression, "passed": regression <= 0.02}


def candidate_gate(*, comparison: dict, critical_security_failures: int, independent_reviewed: bool,
                   owner_approved: bool, verification_ok: bool = True) -> tuple[bool, str]:
    if critical_security_failures: return False, "critical security finding"
    if not verification_ok: return False, "verification pipeline failed"
    if not comparison.get("passed"): return False, "task success regressed by more than 2 percent"
    if not independent_reviewed: return False, "independent signed review is required"
    if not owner_approved: return False, "signed release-authority approval is required"
    return True, "candidate passed release gate"


def artifact_manifest(root: str, commit: str, dependencies: dict[str, str], files: list[str]) -> dict:
    base = Path(root).resolve(); hashes = {}
    for rel in sorted(set(files)):
        path = (base / rel).resolve()
        if path.is_file() and (path == base or str(path).startswith(str(base) + os.sep)):
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {"commit": commit, "dependencies": dict(sorted(dependencies.items())), "files": hashes}
    return {**payload, "manifest_hash": _digest(payload)}


def record_signature(manifest: dict, signature_b64: str, signer: str, public_key_b64: str) -> dict:
    payload = _canonical({"manifest_hash": manifest.get("manifest_hash", ""), "signer": signer}).encode()
    if not verify_external_signature(public_key_b64, payload, signature_b64):
        raise PermissionError("artifact signature verification failed")
    return {**manifest, "signature": signature_b64, "signer": signer, "signature_verified": True}


class CanaryStore:
    def __init__(self, path: str):
        self.path = path; os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def start(self, proposal_id: str, signed_artifact: dict, authority_scope: list[str], *, now: float | None = None) -> dict:
        if not signed_artifact.get("signature_verified"):
            raise PermissionError("verified signed artifact required")
        record = {"proposal_id": proposal_id, "manifest_hash": signed_artifact["manifest_hash"],
                  "started_at": now or time.time(), "authority_scope": authority_scope, "shadow": True,
                  "signature_verified": True,
                  "task_volume": 0, "crashes": 0, "security_regression": False,
                  "duplicate_effects": 0, "migration_failure": False}
        Path(self.path).write_text(_canonical(record), encoding="utf-8"); return record

    def load(self) -> dict:
        return json.loads(Path(self.path).read_text(encoding="utf-8"))

    def observe(self, **metrics) -> dict:
        record = self.load()
        for key in ("task_volume", "crashes", "security_regression", "duplicate_effects", "migration_failure"):
            if key in metrics: record[key] = metrics[key]
        Path(self.path).write_text(_canonical(record), encoding="utf-8"); return record


def can_promote(canary: dict, *, public_key_b64: str, signature_b64: str, now: float | None = None,
                minimum_days: int = 7, minimum_tasks: int = 0) -> tuple[bool, str]:
    now = now or time.time()
    evidence_hash = _digest(canary)
    if not verify_external_signature(
        public_key_b64,
        signed_payload(str(canary.get("proposal_id", "")), "promote", evidence_hash),
        signature_b64,
    ):
        return False, "valid signed promotion approval is required for current canary evidence"
    if canary.get("signature_verified") is not True: return False, "artifact signature is not verified"
    if any((canary.get("crashes"), canary.get("security_regression"), canary.get("duplicate_effects"), canary.get("migration_failure"))):
        return False, "canary recorded a rollback trigger"
    started = float(canary.get("started_at") or 0)
    if started <= 0 or started > now or not canary.get("authority_scope") or not canary.get("shadow"):
        return False, "invalid or unrestricted canary record"
    if now - started >= minimum_days * 86400: return True, "minimum canary duration met"
    if minimum_tasks > 0 and int(canary.get("task_volume", 0)) >= minimum_tasks: return True, "minimum task volume met"
    return False, "canary window is still active"


def rollback_required(canary: dict, *, baseline_success: float | None = None,
                      candidate_success: float | None = None) -> tuple[bool, str]:
    if canary.get("crashes"): return True, "candidate crashed"
    if canary.get("security_regression"): return True, "security regression"
    if canary.get("duplicate_effects"): return True, "duplicate external effect"
    if canary.get("migration_failure"): return True, "data migration failure"
    if baseline_success is not None and candidate_success is not None and baseline_success - candidate_success > 0.02:
        return True, "task success regressed by more than 2 percent"
    return False, "no rollback trigger"


def rollback_release(snapshot: str, target: str, expected_hash: str, *, started_at: float | None = None) -> dict:
    started = started_at or time.time(); source = Path(snapshot); destination = Path(target)
    if not source.is_dir(): raise FileNotFoundError(snapshot)
    actual_hash = _digest(sorted((str(path.relative_to(source)), hashlib.sha256(path.read_bytes()).hexdigest())
                                 for path in source.rglob("*") if path.is_file()))
    if actual_hash != expected_hash: raise ValueError("rollback snapshot hash mismatch")
    temporary = destination.with_name(destination.name + ".rollback-tmp")
    if temporary.exists(): shutil.rmtree(temporary)
    shutil.copytree(source, temporary)
    previous = destination.with_name(destination.name + ".rollback-old")
    if previous.exists(): shutil.rmtree(previous)
    if destination.exists(): os.replace(destination, previous)
    os.replace(temporary, destination)
    elapsed = time.time() - started
    return {"ok": elapsed < 300, "seconds": elapsed, "snapshot_hash": actual_hash}
