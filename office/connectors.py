"""Provider-neutral cloud connector contract with least-privilege defaults."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectorScope:
    read: bool = True
    draft: bool = False
    write: bool = False
    send: bool = False


@dataclass
class ConnectorResponse:
    ok: bool
    provider: str
    operation: str
    data: Any = None
    error: str = ""
    remote_id: str = ""


class OfficeConnector(Protocol):
    provider: str
    scopes: ConnectorScope

    def call(self, operation: str, **kwargs) -> ConnectorResponse: ...


@dataclass
class InMemoryConnector:
    """Deterministic adapter used for contract tests and local workflow rehearsal."""
    provider: str
    scopes: ConnectorScope = field(default_factory=ConnectorScope)
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def call(self, operation: str, **kwargs) -> ConnectorResponse:
        is_write = operation.endswith((".create", ".update", ".delete", ".send", ".invite"))
        is_send = operation.endswith((".send", ".invite"))
        if is_send and not self.scopes.send:
            return ConnectorResponse(False, self.provider, operation, error="send scope is not granted")
        if is_write and not self.scopes.write:
            return ConnectorResponse(False, self.provider, operation, error="write scope is not granted")
        if operation.endswith(".list") or operation.endswith(".search"):
            return ConnectorResponse(True, self.provider, operation, list(self.records.values()))
        remote_id = str(kwargs.get("remote_id") or len(self.records) + 1)
        if operation.endswith(".delete"):
            self.records.pop(remote_id, None)
        else:
            self.records[remote_id] = {"remote_id": remote_id, **kwargs}
        return ConnectorResponse(True, self.provider, operation, self.records.get(remote_id), remote_id)
