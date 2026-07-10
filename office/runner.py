"""Execute an office workflow with artifact validation and evidence delivery."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from office.artifacts import inspect_artifact
from office.evidence import EvidencePackage, evidence_ready
from office.kernel import OfficeKernel, OfficeOperation, OperationResult
from office.workflows import OfficeWorkflow


class OfficeWorkflowRunner:
    def __init__(self, kernel: OfficeKernel, evidence_dir: str) -> None:
        self.kernel = kernel
        self.evidence_dir = evidence_dir

    def run(self, workflow: OfficeWorkflow, target: str, payload: dict[str, Any],
            produce: Callable[[], str], dry_run: bool = False) -> OperationResult:
        operation = OfficeOperation(
            operation=f"workflow.{workflow.slug}", target=target, payload=payload,
            authority="write" if not dry_run else "read", dry_run=dry_run,
        )
        package = EvidencePackage(operation.key())

        def handler() -> dict[str, Any]:
            output_path = produce()
            check = inspect_artifact(output_path, render=True)
            package.add_validation(check.as_dict())
            package.add_output(output_path, check.sha256, kind=check.kind)
            evidence_path = package.write(self.evidence_dir)
            if not evidence_ready(package):
                raise RuntimeError("artifact validation failed; delivery withheld")
            return {"workflow": workflow.slug, "output": output_path,
                    "evidence": evidence_path, "validation": check.as_dict()}

        return self.kernel.execute(operation, handler)
