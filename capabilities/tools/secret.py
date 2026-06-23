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
        "把一条登录凭据安全存入加密保险库:密码/密钥加密落盘,用户名等非密信息明文存。"
        "存好后用 secret:<name> 在 browser.fill 里引用密码,明文绝不外露。"
    )
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "凭据名(如 gmail、公司OA),用于后续引用"},
            "secret": {"type": "string", "description": "密码或 API 密钥(加密存储)"},
            "username": {"type": "string", "description": "用户名/账号(非密,明文存)"},
            "url": {"type": "string", "description": "登录页地址(可选)"},
            "note": {"type": "string", "description": "备注(可选)"},
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
            )
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        has_pw = "已加密保存密码" if args.get("secret") else "(未含密码)"
        return CapabilityResult(
            ok=True,
            output=f"已安全保存凭据「{name}」{has_pw};登录时用 secret:{name} 引用密码,不会明文展示。",
        )


class SecretList(Tool):
    name = "secret.list"
    risk = Risk.READ
    description = "列出已保存的凭据(只含名称/用户名/登录页/备注,绝不含密码)。"
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
            return CapabilityResult(ok=True, output="(保险库为空)")
        lines = []
        for r in rows:
            pw = "🔑" if r.get("has_secret") else "—"
            lines.append(f"- {r['name']} | 用户名:{r.get('username') or '(无)'} | "
                         f"密码:{pw} | {r.get('url') or ''}")
        return CapabilityResult(ok=True, output="\n".join(lines))
