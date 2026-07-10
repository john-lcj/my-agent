"""Short-lived secret handles; secret values never become model tool output."""
from __future__ import annotations

import secrets
import time


class SecretBroker:
    def __init__(self, vault, *, ttl_seconds: int = 120) -> None:
        self._vault = vault
        self._ttl = ttl_seconds
        self._handles: dict[str, tuple[str, str, str, float]] = {}

    def issue(self, name: str, *, capability: str, destination: str) -> str:
        if not self._vault or not self._vault.get(name):
            return ""
        handle = "sh_" + secrets.token_urlsafe(18)
        self._handles[handle] = (name, capability, destination.lower(), time.monotonic() + self._ttl)
        return handle

    def resolve(self, handle: str, *, capability: str, destination: str) -> str:
        item = self._handles.pop(handle, None)  # single use by design
        if not item:
            return ""
        name, allowed_capability, allowed_destination, expires = item
        if time.monotonic() > expires or capability != allowed_capability:
            return ""
        host = (destination or "").lower()
        if allowed_destination and host != allowed_destination:
            return ""
        return self._vault.get(name) if self._vault else ""

    def resolve_named(self, name: str) -> str:
        """Connector configuration can use a vault name internally, never via model output."""
        return self._vault.get(name) if self._vault else ""
