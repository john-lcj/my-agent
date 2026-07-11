"""Per-domain browser policy; unknown domains are read-only by default."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from urllib.parse import urlparse


@dataclass(frozen=True)
class SitePolicy:
    domain: str
    actions: tuple[str, ...] = ("read",)
    data_classifications: tuple[str, ...] = ("public",)
    account_id: str = ""
    require_confirmation: bool = True


class SitePolicyStore:
    def __init__(self, path: str = "logs/browser_site_policies.json") -> None:
        self.path = path

    def _load(self) -> list[SitePolicy]:
        try:
            data = json.loads(open(self.path, encoding="utf-8").read())
            return [SitePolicy(str(item["domain"]), tuple(item.get("actions", ["read"])),
                               tuple(item.get("data_classifications", ["public"])),
                               str(item.get("account_id", "")), bool(item.get("require_confirmation", True)))
                    for item in data if isinstance(item, dict) and item.get("domain")]
        except Exception:
            return []

    def save(self, policy: SitePolicy) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        policies = [item for item in self._load() if item.domain != policy.domain]
        policies.append(policy)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump([asdict(item) for item in policies], handle, ensure_ascii=False, indent=2)

    def allows(self, url: str, action: str, data_classification: str = "public", account_id: str = "") -> tuple[bool, str]:
        domain = (urlparse(url).hostname or "").lower()
        policy = next((item for item in self._load() if item.domain.lower() == domain), None)
        if policy is None:
            return (action == "read", "unknown browser domain is read-only")
        if action not in policy.actions:
            return False, f"browser action is not allowed by site policy: {action}"
        if data_classification not in policy.data_classifications:
            return False, "data classification is not allowed by site policy"
        if policy.account_id and account_id and policy.account_id != account_id:
            return False, "browser account is not allowed for this site policy"
        return True, "site policy allows action"
