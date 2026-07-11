"""Security metadata for every capability exposed to an agent."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.types import Risk


@dataclass(frozen=True)
class CapabilityManifest:
    name: str
    risk: Risk
    data_scope: str
    side_effect: str
    reversible: bool
    authorization: str
    timeout_seconds: int
    verification: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "risk": int(self.risk),
            "data_scope": self.data_scope,
            "side_effect": self.side_effect,
            "reversible": self.reversible,
            "authorization": self.authorization,
            "timeout_seconds": self.timeout_seconds,
            "verification": self.verification,
            "source": self.source,
        }


_BUILTIN_NAMES = frozenset({
    "fs.read", "fs.list", "fs.write", "fs.search", "shell.run", "dev.run_tests",
    "web.search", "web.fetch", "exa.search", "http.request",
    "memory.remember", "memory.recall", "program.remember", "program.recall",
    "program.list", "schedule.create", "schedule.list", "schedule.delete",
    "schedule.update", "schedule.run", "plan.update", "browser.open",
    "browser.text", "browser.click", "browser.fill", "browser.wait",
    "browser.screenshot", "browser.upload", "browser.download",
    "browser.login_assist", "browser.close", "vision.see", "secret.save", "secret.list", "secret.issue_handle",
    "wechat.format", "skill.scaffold", "image.ocr", "image.generate",
    "monitor.create", "monitor.list", "monitor.delete", "goal.set", "goal.list",
    "goal.remove", "channel.status", "channel.configure", "model_key.save",
    "model_key.list", "model_key.clear", "suggest.add", "suggest.list",
    "notify.email",
    "git.read", "git.commit", "calendar.add", "calendar.list", "calendar.remove",
    "gui.control", "github.me", "github.list_repos", "github.get_repo",
    "github.list_issues", "github.create_issue", "skill.claude_design",
    "skill.csv_stats", "skill.date_calc", "skill.design_taste_frontend",
    "skill.docx_writer", "skill.file_append", "skill.file_edit",
    "skill.find_files", "skill.grep_text", "skill.http_request", "skill.json_tools",
    "skill.keyword_extract", "skill.markdown_toc", "skill.notify_dispatch",
    "skill.pdf_extract", "skill.personal_search", "skill.pptx_writer",
    "skill.readability_score", "skill.table_format", "skill.text_diff",
    "skill.text_stats", "skill.xlsx_writer",
})

_EXTERNAL_EFFECTS = frozenset({
    "http.request", "notify.email", "github.create_issue", "browser.click",
    "browser.fill", "browser.upload", "browser.download", "browser.login_assist",
    "channel.configure", "calendar.add", "calendar.remove",
})


def _builtin_manifest(cap: Any) -> CapabilityManifest | None:
    name = str(getattr(cap, "name", "") or "")
    if name not in _BUILTIN_NAMES:
        return None
    risk = getattr(cap, "risk", None)
    if not isinstance(risk, Risk):
        return None
    if name.startswith(("fs.", "git.", "skill.file_", "skill.docx_", "skill.pptx_", "skill.xlsx_")):
        data_scope = "workspace"
    elif name.startswith("browser."):
        data_scope = "browser-session"
    elif name.startswith(("memory.", "program.", "secret.", "model_key.", "schedule.", "monitor.", "goal.", "suggest.")):
        data_scope = "agent-state"
    elif name.startswith(("web.", "exa.", "http.", "github.")):
        data_scope = "network"
    else:
        data_scope = "task-input"
    external = name in _EXTERNAL_EFFECTS
    side_effect = "none" if risk == Risk.READ else ("external" if external else "local-write")
    return CapabilityManifest(
        name=name,
        risk=risk,
        data_scope=data_scope,
        side_effect=side_effect,
        reversible=risk == Risk.READ or (risk == Risk.WRITE and not external),
        authorization=(
            "auto-read" if risk == Risk.READ
            else "scoped-confirmation" if risk == Risk.WRITE
            else "explicit-confirmation"
        ),
        timeout_seconds=60,
        verification="provider-receipt" if external else (
            "readback" if risk != Risk.READ else "tool-result"
        ),
        source="builtin",
    )


def _explicit_manifest(cap: Any) -> tuple[CapabilityManifest | None, str]:
    raw = getattr(cap, "security_manifest", None)
    if raw is None:
        raw = getattr(cap, "manifest", None)
    if not isinstance(raw, dict):
        return None, "missing security manifest"
    required = {
        "name", "risk", "data_scope", "side_effect", "reversible",
        "authorization", "timeout_seconds", "verification", "source",
    }
    missing = sorted(key for key in required if key not in raw)
    if missing:
        return None, f"manifest missing: {', '.join(missing)}"
    try:
        raw_risk = raw["risk"]
        if isinstance(raw_risk, Risk):
            risk = raw_risk
        elif isinstance(raw_risk, str) and raw_risk.upper() in Risk.__members__:
            risk = Risk[raw_risk.upper()]
        else:
            risk = Risk(int(raw_risk))
        manifest = CapabilityManifest(
            name=str(raw["name"]), risk=risk,
            data_scope=str(raw["data_scope"]), side_effect=str(raw["side_effect"]),
            reversible=bool(raw["reversible"]), authorization=str(raw["authorization"]),
            timeout_seconds=int(raw["timeout_seconds"]),
            verification=str(raw["verification"]), source=str(raw["source"]),
        )
    except (TypeError, ValueError) as exc:
        return None, f"invalid manifest: {exc}"
    if manifest.name != getattr(cap, "name", ""):
        return None, "manifest name does not match capability"
    if manifest.risk != getattr(cap, "risk", None):
        return None, "manifest risk does not match capability"
    if manifest.timeout_seconds <= 0:
        return None, "manifest timeout must be positive"
    return manifest, ""


def resolve_manifest(cap: Any) -> tuple[CapabilityManifest | None, str]:
    """Return a complete manifest, or the reason this capability is blocked."""
    manifest, error = _explicit_manifest(cap)
    if manifest is not None:
        return manifest, ""
    builtin = _builtin_manifest(cap)
    if builtin is not None:
        return builtin, ""
    return None, error
