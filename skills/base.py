"""Skill 插件系统 —— 可热插拔的能力扩展。

约定:每个 skill 是一个目录 skills/<name>/,内含:
- SKILL.md:带 frontmatter 元信息(name/description/trigger/risk),Body text是给模型/人看的说明。
- impl.py:定义 `async def run(args: dict, ctx) -> CapabilityResult`,可选 `SCHEMA` 字典。

渐进式披露:discover() 只解析轻量清单(省 token);load() 在真正要用时才导入 impl。
加载后通过 SkillCapability 包装成统一 Capability,纳入同一治理管线。
"""
from __future__ import annotations

import importlib.util
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
    path: str            # skill 目录
    source_root: str = ""  # 来自哪个 skills 根目录(内置/用户)


class SkillCapability:
    """把一个已加载的 skill 适配成统一 Capability。"""

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
                md = os.path.join(sdir, "SKILL.md")
                if os.path.isdir(sdir) and os.path.isfile(md):
                    manifest = self._parse_manifest(md, sdir, root)
                    if manifest and manifest.name not in self._manifests:
                        self._manifests[manifest.name] = manifest

    def available(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def load(self, name: str) -> SkillCapability:
        manifest = self._manifests.get(name)
        if manifest is None:
            raise ValueError(f"未发现 skill:{name}")
        impl_path = os.path.join(manifest.path, "impl.py")
        if os.path.isfile(impl_path):
            spec = importlib.util.spec_from_file_location(f"skill_{name}", impl_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            run_fn = getattr(module, "run", None)
            if run_fn is None:
                raise ValueError(f"skill {name} 的 impl.py 缺少 run 函数")
            schema = getattr(module, "SCHEMA", {
                "type": "object",
                "properties": {"input": {"type": "string"}},
            })
        else:
            run_fn, schema = self._make_guidance_runner(manifest)
        desc = manifest.description
        if manifest.trigger:
            desc = f"{desc}（触发:{manifest.trigger}）"
        cap = SkillCapability(manifest, run_fn, schema)
        cap.description = desc
        return cap

    @staticmethod
    def _make_guidance_runner(manifest: SkillManifest):
        """无 impl.py 的 skill 按指导文档加载(SKILL.md Body text可读/可调用)。"""
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
        """发现并加载全部 skill,注册进统一能力注册表。返回已加载的 skill 名。"""
        self.discover()
        loaded = []
        for manifest in self.available():
            try:
                capability_registry.register(self.load(manifest.name))
                loaded.append(manifest.name)
            except Exception as exc:
                import sys
                print(f"[skill] 加载 {manifest.name} 失败: {exc}", file=sys.stderr)
        return loaded

    @staticmethod
    def _parse_manifest(md_path: str, sdir: str, source_root: str = "") -> Optional[SkillManifest]:
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read()
        meta = _parse_frontmatter(text)
        if "name" not in meta:
            return None
        desc = (meta.get("description") or "").strip()
        if not desc or desc == "|":
            from skills._guidance import read_skill_body
            body = read_skill_body(sdir).strip()
            desc = body.split("\n\n", 1)[0].replace("#", "").strip()[:200]
        risk_name = (meta.get("risk", "READ") or "READ").upper()
        risk = Risk[risk_name] if risk_name in Risk.__members__ else Risk.READ
        return SkillManifest(
            name=meta["name"],
            description=desc,
            trigger=meta.get("trigger", ""),
            risk=risk,
            path=sdir,
            source_root=source_root,
        )


def _parse_frontmatter(text: str) -> dict:
    """解析以 --- 包裹的 key: value frontmatter(零依赖,不需要 PyYAML)。"""
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
