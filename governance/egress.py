"""出站域名管控 —— 细粒度限制 agent 能往哪些域名发请求。

覆盖 http.request / browser.open / 连接器的外发,降低被提示注入诱导"把数据发到陌生域名"
的风险,也便于合规(只许访问白名单内的内部系统/可信站点)。

配置(环境变量或 governance/policy.yaml 的 egress 段):
  AGENT_EGRESS_ALLOW="github.com,internal.corp"  设了就**只允许**这些域名(及其子域)。
  AGENT_EGRESS_BLOCK="evil.com,paste.ee"          黑名单,任何时候都拦(优先级高于白名单)。
不配置则不限制(默认放行),保持本地零配置体验。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def _domains(env_key: str, policy: dict | None, key: str) -> list[str]:
    raw = os.environ.get(env_key, "").strip()
    items = [d.strip().lower() for d in raw.split(",") if d.strip()]
    if not items and policy:
        items = [str(d).strip().lower() for d in (policy.get(key) or []) if str(d).strip()]
    return items


def _host_matches(host: str, domain: str) -> bool:
    host = (host or "").lower()
    return host == domain or host.endswith("." + domain)


def classify_data(*values: object) -> str:
    """A deliberately small, conservative classification for outbound data."""
    blob = " ".join(str(value).lower() for value in values if value is not None)
    if any(token in blob for token in ("authorization", "api_key", "token", "secret", "password", "cookie")):
        return "secret"
    if blob.strip():
        return "private"
    return "public"


def check_egress(
    url: str, policy: dict | None = None, *, method: str = "GET",
    data_classification: str = "public", destination: str = "http",
    allow_domains: list[str] | None = None,
) -> tuple[bool, str]:
    """Validate domain, method, and data class before an outbound operation.

    Public read-only navigation remains useful without configuration. Any write
    or non-public payload must target an explicit allowlisted destination.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False, "无法解析 URL 主机名"
    if not host:
        return False, "URL 缺少主机名"

    block = _domains("AGENT_EGRESS_BLOCK", policy, "block")
    if any(_host_matches(host, d) for d in block):
        return False, f"域名 {host} 在出站黑名单中,已拦截"

    allow = _domains("AGENT_EGRESS_ALLOW", policy, "allow")
    allow.extend(str(domain).lower() for domain in (allow_domains or []) if domain)
    if allow and not any(_host_matches(host, d) for d in allow):
        return False, f"域名 {host} 不在出站白名单内(仅允许:{', '.join(allow)})"

    write_or_private = method.upper() not in ("GET", "HEAD") or data_classification != "public"
    if write_or_private and not any(_host_matches(host, d) for d in allow):
        return False, (
            f"{destination} destination {host} is not explicitly approved for "
            f"{method.upper()} {data_classification} data"
        )

    return True, ""
