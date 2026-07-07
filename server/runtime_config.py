"""运行时配置 —— Web 设置页写入,重启连接后仍生效。"""
from __future__ import annotations

import json
import os
from typing import Any

from config import Config


class RuntimeConfigStore:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        current.update(data)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return current

    def get_model(self, fallback: str | None = None) -> str:
        from llm.model_registry import default_model_id, get_model, normalize_model_id

        cfg = self.load()
        if cfg.get("model"):
            mid = normalize_model_id(str(cfg["model"]))
            if mid:
                return mid
        if cfg.get("provider"):
            mid = normalize_model_id(str(cfg["provider"]))
            if mid:
                return mid
        return fallback or default_model_id()

    def get_provider(self, fallback: str | None = None) -> str:
        from llm.model_registry import get_model

        return get_model(self.get_model(fallback)).provider

    def get_max_cost_usd(self) -> float | None:
        raw = self.load().get("max_cost_usd")
        if raw is None or raw == "":
            return Config.MAX_COST_USD
        try:
            v = float(raw)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return Config.MAX_COST_USD

    def get_governance_mode(self, fallback: str | None = None) -> str:
        return self.load().get("governance_mode") or fallback or Config.GOVERNANCE_MODE

    def get_max_steps(self) -> int:
        """返回最大步数;0 表示无限制。未设置则用 Config.MAX_STEPS。"""
        raw = self.load().get("max_steps")
        if raw is None or raw == "":
            return Config.MAX_STEPS
        try:
            v = int(raw)
            return v if v > 0 else 0   # 0 = 无限制
        except (TypeError, ValueError):
            return Config.MAX_STEPS

    def get_proactive(self) -> bool:
        raw = self.load().get("proactive")
        if raw is not None:
            return bool(raw)
        return os.environ.get("AGENT_PROACTIVE", "0") != "0"

    def get_briefing_enabled(self) -> bool:
        raw = self.load().get("briefing_enabled")
        if raw is not None:
            return bool(raw)
        return True

    def get_briefing_at(self) -> str:
        raw = self.load().get("briefing_at")
        if raw:
            return str(raw).strip()
        return os.environ.get("AGENT_BRIEFING_AT", "08:00")
