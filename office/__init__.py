"""Provider-neutral office automation primitives."""

from office.kernel import OfficeKernel, OfficeOperation, OperationResult
from office.runner import OfficeWorkflowRunner

__all__ = ["OfficeKernel", "OfficeOperation", "OperationResult", "OfficeWorkflowRunner"]
