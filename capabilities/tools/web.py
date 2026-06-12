"""联网搜索与网页抓取 —— 查资料、新闻、文档时的首选能力。

默认使用 DuckDuckGo HTML(无需 API Key)。可选配置:
  TAVILY_API_KEY / BRAVE_SEARCH_API_KEY / SERPER_API_KEY
"""
from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Optional

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_USER_AGENT = (
    "Mozilla/5.0 (compatible; my-agent/1.0; +https://github.com/local-agent)"
)
_MAX_FETCH_CHARS = 14_000
_MAX_SNIPPET = 400


def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_get(url: str, headers: Optional[dict] = None) -> str:
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "tr") and not self._skip:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        t = data.strip()
        if t:
            self._parts.append(t + " ")

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(page: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", page)
    return parser.text()


def parse_duckduckgo_html(page: str, limit: int) -> list[dict]:
    """从 DuckDuckGo HTML 结果页解析标题/链接/摘要。"""
    results: list[dict] = []
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        page,
        re.I | re.S,
    ):
        url = html_lib.unescape(m.group(1).strip())
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = html_lib.unescape(title).strip()
        if not title or url.startswith("//duckduckgo.com"):
            continue
        results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= limit:
            return results
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)',
        page,
        re.I | re.S,
    )
    for i, sn in enumerate(snippets):
        if i >= len(results):
            break
        text = re.sub(r"<[^>]+>", "", sn)
        results[i]["snippet"] = html_lib.unescape(text).strip()[:_MAX_SNIPPET]
    return results


def _search_tavily(query: str, k: int) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    data = _http_post_json(
        "https://api.tavily.com/search",
        {"api_key": key, "query": query, "max_results": k, "search_depth": "basic"},
    )
    out = []
    for item in data.get("results") or []:
        out.append({
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("content") or "")[:_MAX_SNIPPET],
        })
    return out[:k]


def _search_brave(query: str, k: int) -> list[dict]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    q = urllib.parse.urlencode({"q": query, "count": str(k)})
    data = json.loads(
        _http_get(
            f"https://api.search.brave.com/res/v1/web/search?{q}",
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
    )
    out = []
    for item in (data.get("web") or {}).get("results") or []:
        out.append({
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("description") or "")[:_MAX_SNIPPET],
        })
    return out[:k]


def _search_serper(query: str, k: int) -> list[dict]:
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        return []
    data = _http_post_json(
        "https://google.serper.dev/search",
        {"q": query, "num": k},
        headers={"X-API-KEY": key},
    )
    out = []
    for item in data.get("organic") or []:
        out.append({
            "title": str(item.get("title") or ""),
            "url": str(item.get("link") or ""),
            "snippet": str(item.get("snippet") or "")[:_MAX_SNIPPET],
        })
    return out[:k]


def _search_duckduckgo(query: str, k: int) -> list[dict]:
    body = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    return parse_duckduckgo_html(page, k)


def _search_wikipedia(query: str, k: int) -> list[dict]:
    """中文维基摘要,作为 DuckDuckGo 失败时的补充。"""
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": str(min(k, 5)),
        "format": "json",
        "utf8": 1,
    })
    url = f"https://zh.wikipedia.org/w/api.php?{params}"
    try:
        raw = _http_get(url)
        data = json.loads(raw)
    except Exception:
        return []
    out = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        page_url = "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        snip = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
        out.append({"title": title, "url": page_url, "snippet": snip[:_MAX_SNIPPET]})
    return out


def run_web_search(query: str, k: int = 8) -> tuple[list[dict], str]:
    """同步搜索入口,返回 (结果列表, 使用的后端名称)。"""
    query = query.strip()
    if not query:
        return [], "none"
    k = max(1, min(int(k), 15))

    for name, fn in (
        ("tavily", _search_tavily),
        ("brave", _search_brave),
        ("serper", _search_serper),
    ):
        try:
            hits = fn(query, k)
            if hits:
                return hits, name
        except Exception:
            continue

    try:
        hits = _search_duckduckgo(query, k)
        if hits:
            return hits, "duckduckgo"
    except Exception:
        pass

    try:
        hits = _search_wikipedia(query, k)
        if hits:
            return hits, "wikipedia"
    except Exception:
        pass

    return [], "none"


def _format_hits(hits: list[dict], backend: str) -> str:
    if not hits:
        return "(未找到相关结果,可换关键词或配置 TAVILY_API_KEY / SERPER_API_KEY)"
    lines = [f"(搜索引擎: {backend}, 共 {len(hits)} 条)"]
    for i, h in enumerate(hits, 1):
        title = h.get("title") or "(无标题)"
        url = h.get("url") or ""
        snip = h.get("snippet") or ""
        lines.append(f"{i}. {title}")
        if url:
            lines.append(f"   {url}")
        if snip:
            lines.append(f"   {snip}")
    return "\n".join(lines)


def _coerce_host_to_ip(host: str) -> str:
    """把十进制/十六进制等非常规 IPv4 写法归一为点分形式;非此类原样返回。

    例:'2130706433' / '0x7f000001' -> '127.0.0.1'(常见 SSRF 绕过写法)。
    """
    try:
        if re.fullmatch(r"\d+", host):
            return str(ipaddress.ip_address(int(host)))
        if re.fullmatch(r"0x[0-9a-fA-F]+", host):
            return str(ipaddress.ip_address(int(host, 16)))
    except Exception:
        pass
    return host


def _ip_blocked_reason(ip_str: str) -> Optional[str]:
    """判断一个 IP 是否落在禁止网段(环回/私网/链路本地/保留/多播等)。"""
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])  # 去掉 IPv6 zone id
    except ValueError:
        return "无法识别的 IP 地址"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 这类映射地址按其 IPv4 判定
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return f"禁止访问内网/保留地址({ip})"
    return None


def _url_allowed(url: str) -> Optional[str]:
    """返回 None 表示允许,否则为拒绝原因。

    防 SSRF:不止看字面主机,而是把主机解析成 IP 后逐个判网段——这样
    指向内网的域名、IPv6、十进制/十六进制 IP 写法都拦得住。
    注:DNS rebinding(解析后到连接之间 IP 变化)是本层残留风险,需在网络层进一步收口。
    """
    raw = url.strip()
    if not raw:
        return "缺少 url"
    try:
        p = urllib.parse.urlparse(raw)
    except Exception:
        return "URL 无效"
    if p.scheme not in ("http", "https"):
        return "仅支持 http/https"
    host = (p.hostname or "").lower()
    if not host:
        return "URL 缺少主机名"
    if host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
        return "禁止访问本机地址"

    host = _coerce_host_to_ip(host)
    # 若已是 IP 字面量,直接判网段;否则解析所有 A/AAAA 记录,任一落入禁段即拒绝。
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except Exception:
            return "无法解析主机名"
        if not candidates:
            return "无法解析主机名"
    for ip in candidates:
        reason = _ip_blocked_reason(ip)
        if reason:
            return reason
    return None


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """跟随重定向前,对每一跳的目标地址重新做 SSRF 校验,拦截跳向内网的情况。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        deny = _url_allowed(newurl)
        if deny:
            raise urllib.error.HTTPError(
                newurl, code, f"重定向到受限地址被拦截:{deny}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_get(url: str, max_redirects: int = 5) -> str:
    """带 SSRF 防护的 GET:逐跳校验重定向目标。"""
    opener = urllib.request.build_opener(_ValidatingRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
    with opener.open(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


class WebSearch(Tool):
    name = "web.search"
    risk = Risk.READ
    description = (
        "在互联网上搜索关键词,返回标题、链接与摘要。"
        "查新闻、价格、文档、最新动态时优先使用;需要全文时再 web.fetch。"
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或自然语言问句"},
            "k": {"type": "integer", "description": "返回条数,默认 8,最大 15"},
        },
        "required": ["query"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return CapabilityResult(ok=False, error="缺少参数 query")
        try:
            k = int(args.get("k", 8))
        except (TypeError, ValueError):
            k = 8
        try:
            hits, backend = await asyncio.to_thread(run_web_search, query, k)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"搜索失败: {e}")
        return CapabilityResult(ok=True, output=_format_hits(hits, backend))


class WebFetch(Tool):
    name = "web.fetch"
    risk = Risk.READ
    description = (
        "抓取指定网页并提取正文文本(用于阅读搜索结果中的链接或已知 URL)。"
        "不支持登录页与内网地址。"
    )
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的 http(s) 地址"},
            "max_chars": {
                "type": "integer",
                "description": f"返回最大字符数,默认 {_MAX_FETCH_CHARS}",
            },
        },
        "required": ["url"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        url = str(args.get("url", "")).strip()
        deny = _url_allowed(url)
        if deny:
            return CapabilityResult(ok=False, error=deny)
        try:
            max_chars = int(args.get("max_chars", _MAX_FETCH_CHARS))
        except (TypeError, ValueError):
            max_chars = _MAX_FETCH_CHARS
        max_chars = max(500, min(max_chars, 30_000))

        def _fetch() -> str:
            page = _safe_get(url)   # 逐跳校验重定向,防 302 跳内网/云元数据
            text = html_to_text(page)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n…(已截断,原文约 {len(text)} 字)"
            return text or "(页面无可用正文)"

        try:
            body = await asyncio.to_thread(_fetch)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"抓取失败: {e}")
        return CapabilityResult(ok=True, output=body)
