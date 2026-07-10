"""http_request skill:通用 HTTP API 调用(带 SSRF 防护)。"""
from __future__ import annotations

import json as _json

from core.types import CapabilityResult

RISK = "WRITE"

SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Request URL, http or https"},
        "method": {"type": "string", "description": "GET/POST/PUT/DELETE; defaults to GET"},
        "headers": {"type": "object", "description": "Request headers, such as Authorization"},
        "params": {"type": "object", "description": "URL query parameters"},
        "json": {"type": "object", "description": "JSON body for POST/PUT"},
        "timeout": {"type": "number", "description": "Timeout in seconds; defaults to 20"},
    },
    "required": ["url"],
}


def _ssrf_blocked(url: str) -> str:
    """复用项目 web 工具的 URL 白名单(拒绝内网/本地);不可用时退回基础校验。"""
    try:
        from capabilities.tools.web import _url_allowed
        return _url_allowed(url) or ""
    except Exception:
        import ipaddress
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "")
        if host in ("localhost", "metadata.google.internal"):
            return "拒绝访问本地/元数据地址"
        try:
            if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
                return "拒绝访问内网/环回地址"
        except ValueError:
            pass
        return ""


async def run(args: dict, ctx) -> CapabilityResult:
    url = str(args.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return CapabilityResult(ok=False, error="url 必须以 http:// 或 https:// 开头")
    blocked = _ssrf_blocked(url)
    if blocked:
        return CapabilityResult(ok=False, error=f"已拦截:{blocked}")

    method = str(args.get("method", "GET")).strip().upper() or "GET"
    headers = args.get("headers") or {}
    params = args.get("params") or {}
    body = args.get("json")
    try:
        timeout = float(args.get("timeout", 20))
    except (TypeError, ValueError):
        timeout = 20.0

    import asyncio

    def _do():
        import requests
        resp = requests.request(method, url, headers=headers, params=params,
                                json=body if body is not None else None, timeout=timeout)
        ct = resp.headers.get("Content-Type", "")
        try:
            data = resp.json()
            text = _json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            text = resp.text
        return resp.status_code, ct, text

    try:
        code, ct, text = await asyncio.get_event_loop().run_in_executor(None, _do)
    except Exception as e:
        return CapabilityResult(ok=False, error=f"请求失败:{e}")

    if len(text) > 6000:
        text = text[:6000] + "\n…(已截断)"
    ok = 200 <= code < 400
    return CapabilityResult(ok=ok, output=f"HTTP {code} · {ct}\n\n{text}",
                            error="" if ok else f"HTTP {code}")
