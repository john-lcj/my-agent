"""Evidence package for office deliveries."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidencePackage:
    task_id: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_source(self, source: str, sha256: str = "", trusted: bool = False, **meta) -> None:
        self.sources.append({"path": source, "sha256": sha256, "trusted": trusted, **meta})

    def add_output(self, path: str, sha256: str = "", **meta) -> None:
        self.outputs.append({"path": path, "sha256": sha256, **meta})

    def add_validation(self, check: dict[str, Any]) -> None:
        self.validations.append(check)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, directory: str) -> str:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"evidence-{self.task_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
        return path


def evidence_ready(package: EvidencePackage) -> bool:
    return bool(package.outputs) and bool(package.validations) and all(
        check.get("ok") is True for check in package.validations
    )
