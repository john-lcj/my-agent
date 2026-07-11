"""Phase 8 controlled self-improvement contracts.

This module deliberately manages evidence and authorization, not autonomous
production deployment.  The release authority remains outside the agent.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


PROTECTED_PATH_PREFIXES = (
    "governance/", "observability/audit", "governance/secret", "core/runtime_identity",
    "scripts/release", "desktop/scripts/prepare", "server/keychain",
)
TERMINAL = {"rejected", "promoted", "rolled_back"}


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
    evidence: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ImprovementStore:
    def __init__(self, path: str = "logs/improvements.json") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _read(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _write(self, rows: list[dict]) -> None:
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)

    def list(self) -> list[dict]:
        return self._read()

    def get(self, proposal_id: str) -> dict | None:
        return next((row for row in self._read() if row.get("id") == proposal_id), None)

    def add(self, proposal: ImprovementProposal) -> dict:
        rows = self._read(); rows.append(asdict(proposal)); self._write(rows)
        return rows[-1]

    def update(self, proposal_id: str, **changes) -> dict | None:
        rows = self._read()
        for row in rows:
            if row.get("id") == proposal_id:
                row.update(changes); row["updated_at"] = time.time(); self._write(rows); return row
        return None


def protected_path(path: str) -> bool:
    normalized = (path or "").replace("\\", "/").lstrip("./")
    return any(normalized.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def mine_failures(events: list[dict]) -> list[dict]:
    clusters: dict[tuple[str, str], dict] = {}
    for event in events:
        if event.get("ok", True):
            continue
        root = str(event.get("root_cause") or event.get("detail") or "unknown")[:160]
        impact = str(event.get("impact") or "low")
        key = (root, impact)
        cluster = clusters.setdefault(key, {"root_cause": root, "impact": impact, "frequency": 0, "reproducible": False})
        cluster["frequency"] += 1
        cluster["reproducible"] = cluster["reproducible"] or bool(event.get("reproducible"))
    return sorted(clusters.values(), key=lambda item: (item["impact"] == "critical", item["frequency"]), reverse=True)


def propose(*, title: str, root_cause: str, expected_benefit: str, affected_paths: list[str],
            risks: list[str], tests: list[str], rollback: str) -> ImprovementProposal:
    if not all([title.strip(), root_cause.strip(), expected_benefit.strip(), affected_paths, risks, tests, rollback.strip()]):
        raise ValueError("proposal requires benefit, scope, risks, tests, and rollback")
    return ImprovementProposal(uuid.uuid4().hex[:12], title.strip(), root_cause.strip(), expected_benefit.strip(),
                               [path.strip() for path in affected_paths if path.strip()], risks, tests, rollback.strip())


def implementation_allowed(proposal: dict) -> tuple[bool, str]:
    if not proposal.get("owner_approved"):
        return False, "owner approval is required before implementation"
    if any(protected_path(path) for path in proposal.get("affected_paths", [])):
        return False, "proposal touches the protected kernel"
    return True, "approved isolated implementation"


def candidate_gate(*, baseline_success: float, candidate_success: float, critical_security_failures: int,
                   independent_reviewed: bool, owner_approved: bool) -> tuple[bool, str]:
    if critical_security_failures:
        return False, "critical security finding"
    if candidate_success < baseline_success - 0.02:
        return False, "task success regressed by more than 2 percent"
    if not independent_reviewed:
        return False, "independent review is required"
    if not owner_approved:
        return False, "release authority approval is required"
    return True, "candidate passed release gate"


def artifact_manifest(root: str, commit: str, dependencies: dict[str, str]) -> dict:
    payload = {"commit": commit, "dependencies": dependencies, "built_at": int(time.time())}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "manifest_hash": hashlib.sha256(encoded).hexdigest(), "root": str(Path(root).resolve())}


def create_isolated_worktree(root: str, proposal: dict, *, base_ref: str = "HEAD") -> str:
    """Create a detached worktree only after explicit owner approval.

    The worktree is intentionally outside the runtime data directory and no
    credentials are copied into it.  This creates a candidate workspace, not a
    permission to merge or deploy it.
    """
    allowed, reason = implementation_allowed(proposal)
    if not allowed:
        raise PermissionError(reason)
    root_path = Path(root).resolve()
    target = root_path.parent / ".captain-improvements" / str(proposal["id"])
    if target.exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "-C", str(root_path), "worktree", "add", "--detach", str(target), base_ref],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "could not create isolated worktree")
    for filename in (".env", "logs", "data"):
        candidate = target / filename
        if candidate.is_file():
            candidate.unlink()
    return str(target)


def record_signature(manifest: dict, signature: str, signer: str) -> dict:
    if not signature.strip() or not signer.strip():
        raise ValueError("external signature and signer are required")
    return {**manifest, "signature": signature.strip(), "signer": signer.strip(), "signed_at": int(time.time())}


def can_promote(canary: dict, *, now: float | None = None, minimum_days: int = 7, minimum_tasks: int = 0) -> tuple[bool, str]:
    now = now or time.time()
    if canary.get("crashes") or canary.get("security_regression") or canary.get("duplicate_effects") or canary.get("migration_failure"):
        return False, "canary recorded a rollback trigger"
    if now - float(canary.get("started_at", now)) >= minimum_days * 86400:
        return True, "minimum canary duration met"
    if minimum_tasks and int(canary.get("task_volume", 0)) >= minimum_tasks:
        return True, "minimum canary task volume met"
    return False, "canary window is still active"
