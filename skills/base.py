"""Skill plugin system.

Each skill is a directory under a skills root. Code-backed skills can ship only
an impl.py file; optional skill.json or SKILL.md metadata can provide a nicer
name, description, trigger, and risk. Markdown metadata is still accepted for
local/user skills, but built-in repository skills no longer require it.
"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from core.types import CapabilityResult, Risk


@dataclass
class SkillManifest:
    name: str
    description: str
    trigger: str
    risk: Risk
    path: str            # skill directory
    source_root: str = ""  # source skills root (built-in/user/extra)


class SkillCapability:
    """Adapt a loaded skill to the unified Capability interface."""

    def __init__(self, manifest: SkillManifest, run_fn, schema: dict) -> None:
        self.name = f"skill.{manifest.name}"
        self.risk = manifest.risk
        self.description = manifest.description
        self.schema = schema
        self._run = run_fn

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        return await self._run(args, ctx)


class SkillRegistry:
    def __init__(self, skills_dir: str | list[str] = "skills") -> None:
        if isinstance(skills_dir, str):
            self.skills_dirs = [skills_dir]
        else:
            self.skills_dirs = list(skills_dir)
        self._manifests: dict[str, SkillManifest] = {}

    def discover(self) -> None:
        self._manifests.clear()
        for root in self.skills_dirs:
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                if name.startswith((".", "_")):
                    continue
                sdir = os.path.join(root, name)
                if not os.path.isdir(sdir):
                    continue
                manifest = self._discover_manifest(name, sdir, root)
                if manifest and manifest.name not in self._manifests:
                    self._manifests[manifest.name] = manifest

    def available(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def load(self, name: str) -> SkillCapability:
        manifest = self._manifests.get(name)
        if manifest is None:
            raise ValueError(f"skill not found:{name}")
        impl_path = os.path.join(manifest.path, "impl.py")
        if os.path.isfile(impl_path):
            spec = importlib.util.spec_from_file_location(f"skill_{name}", impl_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            run_fn = getattr(module, "run", None)
            if run_fn is None:
                raise ValueError(f"skill {name} impl.py is missing run")
            schema = getattr(module, "SCHEMA", {
                "type": "object",
                "properties": {"input": {"type": "string"}},
            })
        else:
            run_fn, schema = self._make_guidance_runner(manifest)
        desc = manifest.description
        if manifest.trigger:
            desc = f"{desc} (trigger:{manifest.trigger})"
        cap = SkillCapability(manifest, run_fn, schema)
        cap.description = desc
        return cap

    @staticmethod
    def _make_guidance_runner(manifest: SkillManifest):
        """Load a guidance-only local skill from its documentation body."""
        skill_dir = manifest.path

        async def run(args: dict, ctx) -> CapabilityResult:
            from skills._guidance import cap, read_skill_body
            action = str(args.get("action") or "overview").strip().lower()
            body = read_skill_body(skill_dir)
            if action == "full":
                text = cap(body)
            else:
                text = cap(body[:6000])
            return CapabilityResult(ok=True, output=text)

        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["overview", "full"],
                    "description": "overview=summary, full=expanded body",
                },
            },
        }
        return run, schema

    def load_all_into(self, capability_registry) -> list[str]:
        """Discover and load every skill into the capability registry."""
        self.discover()
        loaded = []
        for manifest in self.available():
            try:
                capability_registry.register(self.load(manifest.name))
                loaded.append(manifest.name)
            except Exception as exc:
                import sys
                print(f"[skill] failed to load {manifest.name}: {exc}", file=sys.stderr)
        return loaded

    @staticmethod
    def _discover_manifest(dirname: str, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        json_path = os.path.join(sdir, "skill.json")
        if os.path.isfile(json_path):
            return SkillRegistry._parse_json_manifest(json_path, sdir, source_root)
        md_path = os.path.join(sdir, "SKILL.md")
        if os.path.isfile(md_path):
            return SkillRegistry._parse_manifest(md_path, sdir, source_root)
        impl_path = os.path.join(sdir, "impl.py")
        if os.path.isfile(impl_path):
            return SkillRegistry._manifest_from_impl(dirname, impl_path, sdir, source_root)
        return None

    @staticmethod
    def _parse_json_manifest(path: str, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return None
        return SkillRegistry._manifest_from_meta(meta, sdir, source_root)

    @staticmethod
    def _parse_manifest(md_path: str, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read()
        meta = _parse_frontmatter(text)
        desc = (meta.get("description") or "").strip()
        if not desc or desc == "|":
            from skills._guidance import read_skill_body
            body = read_skill_body(sdir).strip()
            desc = body.split("\n\n", 1)[0].replace("#", "").strip()[:200]
        meta["description"] = desc
        return SkillRegistry._manifest_from_meta(meta, sdir, source_root)

    @staticmethod
    def _manifest_from_impl(dirname: str, impl_path: str, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        spec = importlib.util.spec_from_file_location(f"skill_meta_{dirname}", impl_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        name = str(getattr(module, "NAME", "") or dirname).strip()
        desc = str(getattr(module, "DESCRIPTION", "") or "").strip()
        if not desc:
            doc = (getattr(module, "__doc__", "") or "").strip()
            desc = doc.splitlines()[0].strip() if doc else f"{name} skill"
        meta = {
            "name": name,
            "description": desc,
            "trigger": str(getattr(module, "TRIGGER", "") or ""),
            "risk": str(getattr(module, "RISK", "READ") or "READ"),
        }
        return SkillRegistry._manifest_from_meta(meta, sdir, source_root)

    @staticmethod
    def _manifest_from_meta(meta: dict, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        risk_name = (meta.get("risk", "READ") or "READ").upper()
        risk = Risk[risk_name] if risk_name in Risk.__members__ else Risk.READ
        name = str(meta.get("name") or os.path.basename(sdir)).strip()
        if not name:
            return None
        return SkillManifest(
            name=name,
            description=str(meta.get("description") or f"{name} skill").strip(),
            trigger=str(meta.get("trigger", "") or ""),
            risk=risk,
            path=sdir,
            source_root=source_root,
        )


def _parse_frontmatter(text: str) -> dict:
    """Parse --- wrapped key: value frontmatter without a YAML dependency."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta
