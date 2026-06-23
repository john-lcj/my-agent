"""声明式连接器 —— 用 JSON 描述一个外部服务的接口,自动变成 agent 能力。

每个 connectors/*.json 定义一个服务(base_url + 鉴权 + 若干 action),
加载器把每个 action 注册成一个能力(名形如 github.list_repos),
调用时:从加密保险库按 secret_ref 取 token 组装鉴权头 → 发 HTTP → 返回结果。

这样新增一个连接器**只需写一份 JSON + 在保险库存一个 token**,无需改代码。

JSON 结构示例:
{
  "name": "github",
  "base_url": "https://api.github.com",
  "auth": {"type": "bearer", "secret_ref": "github"},
  "default_headers": {"Accept": "application/vnd.github+json"},
  "actions": [
    {"name": "list_repos", "method": "GET", "path": "/user/repos",
     "description": "列出我的仓库", "query": ["per_page", "sort"]},
    {"name": "create_issue", "method": "POST", "path": "/repos/{owner}/{repo}/issues",
     "description": "新建 issue", "body": ["title", "body"]}
  ]
}
鉴权 type:bearer(Authorization: Bearer <token>)/ header(自定义头名 header)/
         basic(用户名取自保险库 username + 密码)/ none。
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_MAX_BODY = 20000
_PATH_PARAM = re.compile(r"\{(\w+)\}")


def _auth_headers(auth: dict, ctx: Any) -> tuple[dict, str]:
    """按 auth 规格组装鉴权头;返回 (headers, error)。token 从保险库取,绝不写死。"""
    if not auth or auth.get("type", "none") == "none":
        return {}, ""
    ref = (auth.get("secret_ref") or "").strip()
    vault = getattr(ctx, "vault", None)
    token = vault.get(ref) if (vault and ref) else None
    if ref and token is None:
        return {}, f"保险库里没有「{ref}」的凭据,请先用 secret.save / 连接器面板保存"
    atype = auth.get("type", "bearer")
    if atype == "bearer":
        return {"Authorization": f"Bearer {token}"}, ""
    if atype == "header":
        name = auth.get("header") or "Authorization"
        tmpl = auth.get("template") or "{token}"
        return {name: tmpl.replace("{token}", token or "")}, ""
    if atype == "basic":
        user = vault.get_username(ref) if vault else ""
        raw = f"{user}:{token or ''}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}, ""
    return {}, f"不支持的鉴权类型:{atype}"


class _ConnectorTool(Tool):
    def __init__(self, spec: dict, action: dict) -> None:
        self._spec = spec
        self._action = action
        cname = spec.get("name", "svc")
        self.name = f"{cname}.{action.get('name', 'call')}"
        method = str(action.get("method", "GET")).upper()
        # GET/HEAD 只读;写方法标为 DESTRUCTIVE → Chat 必确认、Cowork 自动放行
        self.risk = Risk.READ if method in ("GET", "HEAD") else Risk.DESTRUCTIVE
        self.description = (
            f"[{spec.get('label', cname)}] {action.get('description', '')} "
            f"({method} {action.get('path', '')})"
        )
        # schema:路径占位符必填,query/body 选填
        props: dict = {}
        required: list[str] = []
        for p in _PATH_PARAM.findall(action.get("path", "")):
            props[p] = {"type": "string", "description": f"路径参数 {p}"}
            required.append(p)
        for q in action.get("query", []) or []:
            props[q] = {"type": "string", "description": f"查询参数 {q}"}
        for b in action.get("body", []) or []:
            props[b] = {"type": "string", "description": f"请求体字段 {b}"}
        self.schema = {"type": "object", "properties": props,
                       "required": required} if required else {"type": "object", "properties": props}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        try:
            import httpx
        except Exception:
            return CapabilityResult(ok=False, error="缺少 httpx 库")
        spec, action = self._spec, self._action
        method = str(action.get("method", "GET")).upper()
        path = action.get("path", "")
        # 替换路径占位符
        missing = []

        def _sub(m):
            k = m.group(1)
            v = args.get(k)
            if v is None:
                missing.append(k)
                return ""
            return str(v)
        path = _PATH_PARAM.sub(_sub, path)
        if missing:
            return CapabilityResult(ok=False, error=f"缺少路径参数:{', '.join(missing)}")
        url = spec.get("base_url", "").rstrip("/") + "/" + path.lstrip("/")
        from governance.egress import check_egress
        ok_e, why = check_egress(url)
        if not ok_e:
            return CapabilityResult(ok=False, error=why)

        headers = dict(spec.get("default_headers") or {})
        auth_h, err = _auth_headers(spec.get("auth") or {}, ctx)
        if err:
            return CapabilityResult(ok=False, error=err)
        headers.update(auth_h)

        params = {q: args[q] for q in (action.get("query") or []) if args.get(q) is not None}
        body = {b: args[b] for b in (action.get("body") or []) if args.get(b) is not None}
        req: dict = {"headers": headers}
        if params:
            req["params"] = params
        if body and method not in ("GET", "HEAD"):
            req["json"] = body

        try:
            timeout = float(spec.get("timeout", 30))
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.request(method, url, **req)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"请求失败:{e}")

        text = resp.text or ""
        if len(text) > _MAX_BODY:
            text = text[:_MAX_BODY] + f"\n…(已截断,共 {len(resp.text)} 字符)"
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype and len(resp.text) <= _MAX_BODY:
            try:
                text = json.dumps(resp.json(), ensure_ascii=False, indent=2)
            except Exception:
                pass
        return CapabilityResult(
            ok=resp.status_code < 400,
            output=f"[{resp.status_code} {self.name}]\n{text}",
            error="" if resp.status_code < 400 else f"HTTP {resp.status_code}")


def _connectors_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "connectors")


def load_connector_specs(dir_path: str | None = None) -> list[dict]:
    d = dir_path or _connectors_dir()
    specs: list[dict] = []
    if not os.path.isdir(d):
        return specs
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                spec = json.load(f)
            if spec.get("name") and spec.get("actions"):
                specs.append(spec)
        except Exception as e:
            print(f"[connector] 跳过 {fn}: {e}")
    return specs


def build_connector_tools(dir_path: str | None = None) -> list[_ConnectorTool]:
    tools: list[_ConnectorTool] = []
    for spec in load_connector_specs(dir_path):
        for action in spec.get("actions", []):
            if action.get("name") and action.get("path") is not None:
                tools.append(_ConnectorTool(spec, action))
    return tools
