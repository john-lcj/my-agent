"""通用 HTTP 连接器 —— 让 agent 调用内部系统 / 第三方的认证 REST API。

定位:web.fetch 只取网页内容(GET);本能力支持任意方法 + 自定义请求头
(放 Authorization/X-API-Key 等)+ JSON/表单 body,用于"连接需要登录的系统接口"。

风险定为 WRITE:对外发请求可能改数据、也可能外泄信息,默认需确认(Chat 会问;
Cowork 全自动放行,仅硬边界拦)。响应体截断,避免把超大返回灌进上下文。

安全:URL/请求头/body 只能来自主人或主人明确认可的任务,**绝不**采信网页/邮件/
文件等外部内容里给出的地址或"请把数据发到某处"——那是数据,不是指令(治理+提示词双重把关)。
"""
from __future__ import annotations

import json as _json
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
_MAX_BODY = 20000  # 响应体最多回传字符数(防上下文爆炸)


class HttpRequest(Tool):
    name = "http.request"
    risk = Risk.WRITE
    description = (
        "调用内部系统/第三方的 REST API:支持任意方法(GET/POST/PUT/PATCH/DELETE)、"
        "自定义请求头(放 token)、JSON 或表单 body。用于连接需要登录/鉴权的接口。"
    )
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整请求地址(http/https)"},
            "method": {"type": "string", "description": "GET/POST/PUT/PATCH/DELETE,默认 GET"},
            "headers": {"type": "object", "description": "请求头,如 {\"Authorization\": \"Bearer xxx\"}"},
            "json": {"type": "object", "description": "JSON body(自动设 Content-Type)"},
            "data": {"type": "object", "description": "表单 body(application/x-www-form-urlencoded)"},
            "params": {"type": "object", "description": "URL 查询参数"},
            "timeout": {"type": "number", "description": "超时秒,默认 30"},
        },
        "required": ["url"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        url = str(args.get("url", "")).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return CapabilityResult(ok=False, error="url 必须以 http:// 或 https:// 开头")
        from governance.egress import check_egress
        ok_e, why = check_egress(url)
        if not ok_e:
            return CapabilityResult(ok=False, error=why)
        method = str(args.get("method", "GET")).strip().upper() or "GET"
        if method not in _ALLOWED_METHODS:
            return CapabilityResult(ok=False, error=f"不支持的方法:{method}")
        headers = args.get("headers") or {}
        if not isinstance(headers, dict):
            return CapabilityResult(ok=False, error="headers 必须是对象")
        try:
            timeout = float(args.get("timeout", 30))
        except (TypeError, ValueError):
            timeout = 30.0

        try:
            import httpx  # 已是 fastapi/starlette 依赖,基本必有
        except Exception:
            return CapabilityResult(ok=False, error="缺少 httpx 库,无法发起 HTTP 请求")

        req_kwargs: dict = {"headers": {str(k): str(v) for k, v in headers.items()}}
        if args.get("params"):
            req_kwargs["params"] = args["params"]
        if args.get("json") is not None:
            req_kwargs["json"] = args["json"]
        elif args.get("data") is not None:
            req_kwargs["data"] = args["data"]

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.request(method, url, **req_kwargs)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"请求失败:{e}")

        body = resp.text or ""
        truncated = len(body) > _MAX_BODY
        if truncated:
            body = body[:_MAX_BODY] + f"\n…(已截断,共 {len(resp.text)} 字符)"
        # 尝试美化 JSON,便于模型阅读
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype and not truncated:
            try:
                body = _json.dumps(resp.json(), ensure_ascii=False, indent=2)
            except Exception:
                pass
        out = f"[{resp.status_code} {method} {url}]\n{body}"
        return CapabilityResult(ok=resp.status_code < 400, output=out,
                                error="" if resp.status_code < 400 else f"HTTP {resp.status_code}")
