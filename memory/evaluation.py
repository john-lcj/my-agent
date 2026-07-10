"""Small deterministic retrieval evaluation harness for owner-labeled cases."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    relevant: frozenset[str]
    private_scope: str | None = None


def evaluate_top3(memory, cases: list[RetrievalCase]) -> dict[str, float]:
    """Measure top-3 recall and privacy leakage for a labeled corpus."""
    if not cases:
        return {"top3_precision": 1.0, "privacy_leak_rate": 0.0}
    hits = 0
    returned = 0
    leaks = 0
    for case in cases:
        rows = memory.retrieve(case.query, k=3, scope=case.private_scope)
        contents = {row.content for row in rows}
        hits += len(contents & case.relevant)
        returned += len(contents)
        if case.private_scope is not None:
            leaks += sum(1 for row in rows if row.scope not in {"", case.private_scope})
    return {
        "top3_precision": hits / returned if returned else 1.0,
        "privacy_leak_rate": leaks / max(1, returned),
    }
