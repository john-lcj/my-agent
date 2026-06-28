"""凭据保险库能力 —— 让 agent 安全地"记住"登录信息。

设计要点(安全):
  · 只提供 secret.save(存) 与 secret.list(列元信息),**故意不提供 secret.get**——
    密码明文绝不通过工具输出回到模型上下文。
  · 登录时:用户名正常填;密码用 browser.fill 的 value="secret:<name>" 引用,
    由 browser.fill 内部向保险库解引用,明文不经过模型、不写文件、不进日志。
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _vault(ctx: Any):
    return getattr(ctx, "vault", None)


class SecretSave(Tool):
    name = "secret.save"
    risk = Risk.WRITE   # 写入凭据,Chat 需确认;Cowork 全自动放行
    description = (
        "把一条登录凭据或 API Key 安全存入加密保险库:密码/密钥加密落盘,用户名等非密信息明文存。"
        "存好后用 secret:<name> 在 browser.fill 里引用密码,明文绝不外露。"
        "建议同时填写 description(用途说明)和 scope(权限范围),下次执行相关任务时 agent 会自动提示可用此凭据。"
    )
    schema = {
        "type": "object",
        "properties": {
            "name":        {"type": "string", "description": "凭据名(如 tencent_cloud、github_token),用于后续引用"},
            "secret":      {"type": "string", "description": "密码或 API 密钥(加密存储,不会明文展示)"},
            "username":    {"type": "string", "description": "用户名/账号(非密,明文存,可选)"},
            "url":         {"type": "string", "description": "登录页或 API 地址(可选)"},
            "description": {"type": "string", "description": "用途说明,如「腾讯云主账号」「GitHub 个人 token」"},
            "scope":       {"type": "string", "description": "权限范围,如「CVM 管理、COS 读写」「repo 读写、workflow」"},
            "note":        {"type": "string", "description": "其他备注(可选)"},
        },
        "required": ["name"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        v = _vault(ctx)
        if v is None:
            return CapabilityResult(ok=False, error="未配置凭据保险库")
        name = str(args.get("name", "")).strip()
        if not name:
            return CapabilityResult(ok=False, error="缺少参数 name")
        try:
            v.save(
                name=name,
                secret=str(args.get("secret", "")),
                username=str(args.get("username", "")),
                url=str(args.get("url", "")),
                note=str(args.get("note", "")),
                description=str(args.get("description", "")),
                scope=str(args.get("scope", "")),
            )
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        has_pw = "已加密保存密钥" if args.get("secret") else "(未含密钥)"
        desc_hint = ""
        if args.get("description"):
            desc_hint = f"；用途：{args['description']}"
        if args.get("scope"):
            desc_hint += f"；权限：{args['scope']}"
        return CapabilityResult(
            ok=True,
            output=(f"已安全保存凭据「{name}」{has_pw}{desc_hint}。"
                    f"下次执行相关任务时将自动提示此凭据可用。"),
        )


class SecretList(Tool):
    name = "secret.list"
    risk = Risk.READ
    description = "列出已保存的凭据(含用途说明/权限范围/用户名/登录页,绝不含密码)。执行部署/API 操作前先调用此工具确认可用凭据。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        v = _vault(ctx)
        if v is None:
            return CapabilityResult(ok=False, error="未配置凭据保险库")
        try:
            rows = v.list()
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        if not rows:
            return CapabilityResult(ok=True, output="(保险库为空，尚未保存任何凭据)")
        lines = []
        for r in rows:
            pw = "🔑" if r.get("has_secret") else "—"
            parts = [f"- [{r['name']}]"]
            if r.get("description"):
                parts.append(r["description"])
            if r.get("scope"):
                parts.append(f"权限:{r['scope']}")
            if r.get("username"):
                parts.append(f"用户名:{r['username']}")
            parts.append(f"密钥:{pw}")
            if r.get("url"):
                parts.append(r["url"])
            lines.append(" | ".join(parts))
        return CapabilityResult(ok=True, output="\n".join(lines))
