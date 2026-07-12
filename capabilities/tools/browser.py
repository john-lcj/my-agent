"""浏览器交互能力 —— 补上 web.fetch 的短板:渲染 JS、点击、填表、等待、截图、上传下载。

基于 Playwright(可选依赖)。未安装时优雅报错并给出安装命令,不影响其它能力。
会话级:一个持久 context + page 在多次调用间保留(open→fill→click→text 串起来用)。
**登录态跨会话保持**:context 的 storage_state(cookie/localStorage)落盘,重启后自动载入,
登录过的网站下次不必重登。

  browser.open        READ   打开/跳转 URL,返回渲染后正文(执行 JS)
  browser.text        READ   读当前页渲染后正文
  browser.wait        READ   等待某元素出现 / 等待固定毫秒(应对慢加载 SPA)
  browser.screenshot  READ   截图当前页 → 存到 产物/,返回路径(可喂 vision.see 看)
  browser.click       WRITE  点击元素(可能触发提交/跳转)
  browser.fill        WRITE  往输入框填值(密码用 secret:<名> 引用保险库)
  browser.upload      WRITE  给文件输入框设置要上传的文件
  browser.download    WRITE  点击触发下载,把文件存到 产物/
"""
from __future__ import annotations

import os
import sys
from typing import Any

from core.types import CapabilityResult, Risk
from governance.workspace import artifacts_dir, resolve_path
from browser_runtime.kernel import (
    BrowserActionPreview, BrowserContextKey, BrowserKernel, BrowserLease,
    RemoteStateAssertion,
)
from browser_runtime.accessibility import normalize_nodes, select_unique
from browser_runtime.policy import SitePolicyStore

_PW = None      # one Playwright engine; contexts remain isolated
_SESSIONS: dict[str, dict] = {}
_LEASE_KERNEL: BrowserKernel | None = None
_LEASES: dict[str, BrowserLease] = {}
_SITE_POLICIES: SitePolicyStore | None = None


def _default_headless() -> bool:
    return os.environ.get("AGENT_BROWSER_HEADLESS", "1").strip() != "0"


def _configure_bundled_browser_path() -> None:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip():
        return
    executable = os.path.realpath(sys.executable)
    runtime = os.path.dirname(os.path.dirname(os.path.dirname(executable)))
    candidate = os.path.join(runtime, "ms-playwright")
    if os.path.isdir(candidate):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate


def _state_file(context: BrowserContextKey) -> str:
    base = (os.environ.get("AGENT_LOG_DIR", "").strip() or "logs")
    return os.path.join(base, "browser_contexts", f"{context.value}.json")


def _context_key(ctx: Any, args: dict | None = None) -> BrowserContextKey:
    args = args or {}
    identity = getattr(ctx, "identity", None)
    task_frame = getattr(ctx, "task_frame", None)
    owner = str(args.get("owner_id") or getattr(identity, "subject_id", "local-user") or "local-user")
    account = str(args.get("account_id") or getattr(ctx, "browser_account_id", "")
                  or getattr(identity, "channel", "cli") or "default-account")
    project = str(args.get("project_id") or getattr(ctx, "browser_project_id", "")
                  or getattr(ctx, "session_id", "") or "default-project")
    task = str(args.get("task_id") or getattr(ctx, "durable_job_id", "")
               or getattr(task_frame, "task_id", "") or "interactive")
    return BrowserContextKey(owner, account, project, task)


def _artifacts_dir() -> str:
    return artifacts_dir()


def _lease_kernel() -> BrowserKernel:
    global _LEASE_KERNEL
    if _LEASE_KERNEL is None:
        base = (os.environ.get("AGENT_LOG_DIR", "").strip() or "logs")
        _LEASE_KERNEL = BrowserKernel(os.path.join(base, "browser_runtime.db"),
                                      os.path.join(base, "browser_traces.jsonl"))
    return _LEASE_KERNEL


def _site_policies() -> SitePolicyStore:
    global _SITE_POLICIES
    if _SITE_POLICIES is None:
        base = (os.environ.get("AGENT_LOG_DIR", "").strip() or "logs")
        _SITE_POLICIES = SitePolicyStore(os.path.join(base, "browser_site_policies.json"))
    return _SITE_POLICIES


async def _ensure_page(context: BrowserContextKey, headless: bool | None = None):
    """Lazily create one isolated Playwright context for a task identity.

    headless=None 用默认(env AGENT_BROWSER_HEADLESS,默认无头);
    显式传 True/False 时,若与当前模式不同则**重启浏览器**切换(供登录助手开可见窗口)。
    """
    global _PW
    _configure_bundled_browser_path()
    want = _default_headless() if headless is None else headless
    session = _SESSIONS.get(context.value)
    if session and session["headless"] == want:
        if not _lease_kernel().renew(_LEASES[context.value]):
            raise RuntimeError("browser context lease was lost; reopen the context")
        return session["page"]
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "未安装 Playwright。请先:pip install playwright && python -m playwright install chromium"
        ) from e
    # Mode changes are scoped to this context and never close another account.
    if session:
        await _save_state(context)
        try:
            await session["context"].close()
        except Exception:
            pass
    lease = _LEASE_KERNEL and _LEASES.get(context.value)
    if lease is None:
        lease = _lease_kernel().acquire(context)
    if _PW is None:
        _PW = await async_playwright().start()
    try:
        browser = await _PW.chromium.launch(headless=want)
    except Exception:
        _lease_kernel().release(lease)
        raise
    state = _state_file(context)
    kwargs = {"accept_downloads": True}
    if os.path.isfile(state):
        kwargs["storage_state"] = state          # 复用上次登录态
    browser_context = await browser.new_context(**kwargs)
    page = await browser_context.new_page()
    _SESSIONS[context.value] = {
        "browser": browser, "context": browser_context, "page": page,
        "headless": want, "identity": context,
    }
    _LEASES[context.value] = lease
    return page


async def _save_state(context: BrowserContextKey) -> None:
    """Persist only the selected task context's cookie/localStorage."""
    session = _SESSIONS.get(context.value)
    if session is None:
        return
    try:
        lease = _LEASES.get(context.value)
        if lease is not None and not _lease_kernel().renew(lease):
            return
        path = _state_file(context)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        await session["context"].storage_state(path=path)
    except Exception:
        pass


async def _close_context(context: BrowserContextKey) -> bool:
    session = _SESSIONS.get(context.value)
    lease = _LEASES.get(context.value)
    if session:
        await _save_state(context)
        try:
            await session["context"].close()
            await session["browser"].close()
        except Exception:
            pass
    _SESSIONS.pop(context.value, None)
    _LEASES.pop(context.value, None)
    return bool(lease and _lease_kernel().release(lease))


def _page_for(ctx: Any, args: dict | None = None):
    context = _context_key(ctx, args)
    session = _SESSIONS.get(context.value)
    return session["page"] if session else None


async def _page_text(page, limit: int = 8000) -> str:
    try:
        txt = await page.inner_text("body")
    except Exception:
        txt = await page.content()
    return (txt or "").strip()[:limit]


def _safe_ws_path(p: str) -> str | None:
    """把用户给的路径限制在工作区内,防越权读本机任意文件上传。"""
    full, error = resolve_path(p, require_exists=True)
    return full if not error else None


def _current_egress(page, *, method: str, data_classification: str) -> tuple[bool, str]:
    if page is None or not str(page.url).startswith(("http://", "https://")):
        return False, "browser has no approved http destination"
    from governance.egress import check_egress
    ok, why = check_egress(page.url, method=method, data_classification=data_classification, destination="browser")
    if not ok:
        return ok, why
    return _site_policies().allows(page.url, "write", data_classification)


def _append_trace(context: BrowserContextKey, operation_id: str, action: str, target: str,
                  *, url: str = "", result: str = "", error: str = "") -> None:
    try:
        from browser_runtime.kernel import BrowserTrace
        _lease_kernel().append_trace(BrowserTrace(
            trace_id=__import__("uuid").uuid4().hex, context_key=context.value,
            operation_id=operation_id, action=action, target=target, url=url,
            result=result, error=error,
        ))
    except Exception:
        pass


async def _accessibility_snapshot(page) -> dict[str, Any]:
    raw = await page.locator("body").evaluate("""(body) => {
      const nodes = [...body.querySelectorAll('a,button,input,textarea,select,[role],[contenteditable="true"]')];
      const tagRole = {A:'link', BUTTON:'button', INPUT:'textbox', TEXTAREA:'textbox', SELECT:'combobox'};
      return nodes.map((node, index) => {
        const ref = 'e' + index;
        node.setAttribute('data-captain-ref', ref);
        const labelNode = node.id ? body.querySelector(`label[for="${CSS.escape(node.id)}"]`) : null;
        const name = node.getAttribute('aria-label') || (labelNode && labelNode.innerText) ||
          node.innerText || node.value || node.getAttribute('title') || '';
        return {ref, role: node.getAttribute('role') || tagRole[node.tagName] || 'generic',
          name: String(name).trim().slice(0, 300), label: labelNode ? labelNode.innerText.trim() : '',
          value: node.type === 'password' ? '[REDACTED]' : String(node.value || '').slice(0, 300),
          disabled: !!node.disabled || node.getAttribute('aria-disabled') === 'true',
          checked: typeof node.checked === 'boolean' ? node.checked : null,
          expanded: node.getAttribute('aria-expanded') === null ? null : node.getAttribute('aria-expanded') === 'true'};
      });
    }""")
    return {"url": page.url, "title": await page.title(),
            "viewport": await page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio})"),
            "nodes": [node.__dict__ for node in normalize_nodes(raw or [])]}


async def _semantic_target(page, args: dict):
    selector = str(args.get("selector", "")).strip()
    ref = str(args.get("ref", "")).strip()
    role = str(args.get("role", "")).strip()
    name = str(args.get("name", "")).strip()
    label = str(args.get("label", "")).strip()
    text = str(args.get("text", "")).strip()
    if ref:
        locator = page.locator(f'[data-captain-ref="{ref}"]')
    elif label:
        locator = page.get_by_label(label, exact=True)
    elif role:
        locator = page.get_by_role(role, name=name or None, exact=True)
    elif text:
        locator = page.get_by_text(text, exact=True)
    elif selector:
        locator = page.locator(selector)
    else:
        raise ValueError("provide an accessibility ref, role/name, label, text, or CSS selector")
    count = await locator.count()
    if count != 1:
        raise ValueError(f"browser target must resolve to exactly one element; got {count}")
    if await locator.is_disabled():
        raise ValueError("browser target is disabled")
    return locator


async def _verify_page_state(page, args: dict) -> tuple[bool, str]:
    expected_url = str(args.get("expected_url", "")).strip()
    required = args.get("expected_text", ())
    forbidden = args.get("forbidden_text", ())
    if isinstance(required, str):
        required = (required,) if required else ()
    if isinstance(forbidden, str):
        forbidden = (forbidden,) if forbidden else ()
    if not expected_url and not required and not forbidden:
        return True, "remote state verification not requested"
    return RemoteStateAssertion("browser action", expected_url=expected_url,
                                required_text=tuple(required), forbidden_text=tuple(forbidden)).verify(
                                    url=page.url, text=await _page_text(page))


class BrowserPreview:
    name = "browser.preview"
    risk = Risk.READ
    description = "Render the exact target, account, fields, files, and irreversible consequence before a browser write."
    schema = {"type": "object", "properties": {
        "action": {"type": "string"}, "target": {"type": "string"},
        "account_id": {"type": "string"}, "fields": {"type": "object"},
        "files": {"type": "array", "items": {"type": "string"}},
        "consequence": {"type": "string"}, "irreversible": {"type": "boolean"},
    }, "required": ["action", "target"]}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        import json
        preview = BrowserActionPreview(
            action=str(args.get("action", "")), target=str(args.get("target", "")),
            account_id=str(args.get("account_id", "") or getattr(getattr(ctx, "identity", None), "subject_id", "")),
            fields=dict(args.get("fields") or {}), files=tuple(str(x) for x in (args.get("files") or [])),
            consequence=str(args.get("consequence", "")), irreversible=bool(args.get("irreversible", False)),
        )
        if not preview.action or not preview.target:
            return CapabilityResult(ok=False, error="preview requires action and target")
        return CapabilityResult(ok=True, output=json.dumps(preview.render(), ensure_ascii=False))


class BrowserTakeover:
    name = "browser.takeover"
    risk = Risk.WRITE
    description = "Pause a browser task for owner takeover during CAPTCHA, MFA, payment, or ambiguous interaction, then resume it."
    schema = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["request", "resume"]},
        "reason": {"type": "string"}, "owner_id": {"type": "string"},
        "account_id": {"type": "string"}, "project_id": {"type": "string"}, "task_id": {"type": "string"},
    }, "required": ["action"]}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        import json
        context = _context_key(ctx, args)
        try:
            state = _lease_kernel().takeover(context, str(args.get("reason", "owner takeover")),
                                             resume=str(args.get("action")) == "resume")
            return CapabilityResult(ok=True, output=json.dumps(state, ensure_ascii=False))
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))


class BrowserAccessibility:
    name = "browser.accessibility"
    risk = Risk.READ
    description = "Return accessible roles, names, labels, states, masked values, URL, title, and viewport for the current page."
    schema = {"type": "object", "properties": {
        "owner_id": {"type": "string"}, "account_id": {"type": "string"},
        "project_id": {"type": "string"}, "task_id": {"type": "string"},
    }}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        try:
            import json
            return CapabilityResult(ok=True, output=json.dumps(await _accessibility_snapshot(page), ensure_ascii=False))
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))


class BrowserOpen:
    name = "browser.open"
    risk = Risk.READ
    description = "用真实浏览器打开/跳转一个 URL(会执行 JS,适合客户端渲染的网站),返回渲染后的正文。"
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要打开的网址"},
            "wait_selector": {"type": "string", "description": "可选:等待此 CSS 选择器出现再取文本"},
            "owner_id": {"type": "string", "description": "Browser context owner identifier"},
            "account_id": {"type": "string", "description": "Browser account identifier"},
            "project_id": {"type": "string", "description": "Browser project identifier"},
            "task_id": {"type": "string", "description": "Browser task identifier"},
        },
        "required": ["url"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        url = str(args.get("url", "")).strip()
        if not url:
            return CapabilityResult(ok=False, error="缺少 url")
        if url.startswith("http://") or url.startswith("https://"):
            from governance.egress import check_egress
            ok_e, why = check_egress(url)
            if not ok_e:
                return CapabilityResult(ok=False, error=why)
        try:
            context = _context_key(ctx, args)
            page = await _ensure_page(context)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            sel = str(args.get("wait_selector", "")).strip()
            if sel:
                try:
                    await page.wait_for_selector(sel, timeout=8000)
                except Exception:
                    pass
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            await _save_state(context)
            text = await _page_text(page)
            _append_trace(context, context.value, "open", url, url=url, result="ok")
            return CapabilityResult(ok=True, output=f"[{await page.title()}] {url}\n{text}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserText:
    name = "browser.text"
    risk = Risk.READ
    description = "读取当前浏览器页面渲染后的正文(配合 browser.open/click/fill 串联使用)。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        return CapabilityResult(ok=True, output=await _page_text(page))


class BrowserWait:
    name = "browser.wait"
    risk = Risk.READ
    description = "等待某 CSS 选择器出现,或等待固定毫秒;应对慢加载/异步渲染的 SPA。"
    schema = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "要等待出现的 CSS 选择器(可选)"},
            "ms": {"type": "integer", "description": "固定等待毫秒(可选,默认 1000)"},
            "timeout": {"type": "integer", "description": "等选择器的超时毫秒,默认 15000"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        try:
            if sel:
                await page.wait_for_selector(sel, timeout=int(args.get("timeout", 15000)))
                return CapabilityResult(ok=True, output=f"元素已出现:{sel}")
            await page.wait_for_timeout(int(args.get("ms", 1000)))
            return CapabilityResult(ok=True, output="等待完成")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserScreenshot:
    name = "browser.screenshot"
    risk = Risk.READ
    description = "截图当前浏览器页面,存到工作区 产物/ 目录,返回文件路径(可再用 vision.see 看内容)。"
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "文件名(可选,默认 screenshot.png)"},
            "full_page": {"type": "boolean", "description": "是否整页截图,默认 true"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        name = str(args.get("name", "")).strip() or "screenshot.png"
        if not name.lower().endswith((".png", ".jpg", ".jpeg")):
            name += ".png"
        path = os.path.join(_artifacts_dir(), name)
        try:
            await page.screenshot(path=path, full_page=bool(args.get("full_page", True)))
            meta = await _accessibility_snapshot(page)
            return CapabilityResult(ok=True, output=f"已截图:{path} | url={meta['url']} | viewport={meta['viewport']}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserClick:
    name = "browser.click"
    risk = Risk.WRITE
    description = "点击当前页面上匹配 CSS 选择器的元素(可能触发提交/跳转)。"
    schema = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector fallback"},
            "ref": {"type": "string", "description": "Reference from browser.accessibility"},
            "role": {"type": "string", "description": "Accessible role"},
            "name": {"type": "string", "description": "Accessible name"},
            "text": {"type": "string", "description": "Exact visible text"},
            "expected_url": {"type": "string", "description": "Expected URL after the action"},
            "expected_text": {"type": "string", "description": "Text required after the action"},
            "forbidden_text": {"type": "string", "description": "Text that must not appear after the action"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        sel = str(args.get("selector", "")).strip()
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        if not any(str(args.get(key, "")).strip() for key in ("selector", "ref", "role", "name", "text")):
            return CapabilityResult(ok=False, error="missing browser target")
        ok_e, why = _current_egress(page, method="POST", data_classification="private")
        if not ok_e:
            return CapabilityResult(ok=False, error=why)
        try:
            target = await _semantic_target(page, args)
            await target.click(timeout=8000)
            await page.wait_for_timeout(500)
            await _save_state(_context_key(ctx, args))
            verified, reason = await _verify_page_state(page, args)
            if not verified:
                _append_trace(_context_key(ctx, args), _context_key(ctx, args).value, "click", "browser target", url=page.url, error=reason)
                return CapabilityResult(ok=False, error=reason)
            _append_trace(_context_key(ctx, args), _context_key(ctx, args).value, "click", "browser target", url=page.url, result="ok")
            return CapabilityResult(ok=True, output=f"已点击目标。当前页:{await page.title()}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserFill:
    name = "browser.fill"
    risk = Risk.WRITE
    description = (
        "往当前页面的输入框(CSS 选择器)填入文本。"
        "填密码时把 text 设为 secret:<凭据名>(如 secret:gmail),"
        "会从加密保险库内部解引用并填入,明文不经过你、不外露。"
    )
    schema = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector fallback"},
            "ref": {"type": "string", "description": "Reference from browser.accessibility"},
            "role": {"type": "string", "description": "Accessible role"},
            "name": {"type": "string", "description": "Accessible name"},
            "label": {"type": "string", "description": "Associated form label"},
            "expected_url": {"type": "string", "description": "Expected URL after the action"},
            "expected_text": {"type": "string", "description": "Text required after the action"},
            "forbidden_text": {"type": "string", "description": "Text that must not appear after the action"},
            "text": {"type": "string",
                     "description": "要填的内容;填密码用 secret:<凭据名> 引用保险库,绝不要写明文密码"},
        },
        "required": ["text"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        sel = str(args.get("selector", "")).strip()
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        if not any(str(args.get(key, "")).strip() for key in ("selector", "ref", "role", "name", "label")):
            return CapabilityResult(ok=False, error="missing browser target")
        raw = str(args.get("text", ""))
        masked = False
        if raw.startswith("secret:"):
            name = raw[len("secret:"):].strip()
            broker = getattr(ctx, "secret_broker", None)
            vault = getattr(ctx, "vault", None)
            if vault is None:
                return CapabilityResult(ok=False, error="未配置凭据保险库,无法解引用 secret:")
            pw = broker.resolve_named(name) if broker else vault.get(name)
            if pw is None:
                return CapabilityResult(ok=False, error=f"保险库里没有「{name}」的密码,请先用 secret.save 保存")
            raw, masked = pw, True
        ok_e, why = _current_egress(page, method="POST", data_classification="secret" if masked else "private")
        if not ok_e:
            return CapabilityResult(ok=False, error=why)
        try:
            target = await _semantic_target(page, args)
            await target.fill(raw, timeout=8000)
            await _save_state(_context_key(ctx, args))
            verified, reason = await _verify_page_state(page, args)
            if not verified:
                _append_trace(_context_key(ctx, args), _context_key(ctx, args).value, "fill", "browser target", url=page.url, error=reason)
                return CapabilityResult(ok=False, error=reason)
            _append_trace(_context_key(ctx, args), _context_key(ctx, args).value, "fill", "browser target", url=page.url, result="ok")
            if masked:
                return CapabilityResult(ok=True, output=f"已往 {sel} 填入凭据密码(已隐藏,未显示明文)。")
            return CapabilityResult(ok=True, output=f"已往 {sel} 填入内容。")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserUpload:
    name = "browser.upload"
    risk = Risk.WRITE
    description = "给页面上的文件输入框(<input type=file>)设置要上传的文件(限工作区内的文件)。"
    schema = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "文件输入框 CSS 选择器"},
            "path": {"type": "string", "description": "要上传的文件路径(工作区内的相对/绝对路径)"},
        },
        "required": ["selector", "path"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        full = _safe_ws_path(str(args.get("path", "")).strip())
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        if not full or not os.path.isfile(full):
            return CapabilityResult(ok=False, error="文件不存在或越出工作区范围")
        try:
            await page.set_input_files(sel, full, timeout=8000)
            return CapabilityResult(ok=True, output=f"已为 {sel} 选择上传文件:{os.path.basename(full)}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserDownload:
    name = "browser.download"
    risk = Risk.WRITE
    description = "点击会触发下载的元素,把下载的文件存到工作区 产物/ 目录,返回文件路径。"
    schema = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "点击后触发下载的元素 CSS 选择器"},
            "name": {"type": "string", "description": "另存文件名(可选,默认用网站建议名)"},
            "expected_sha256": {"type": "string", "description": "Expected SHA-256 of the downloaded artifact"},
        },
        "required": ["selector"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        page = _page_for(ctx, args)
        if page is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        try:
            async with page.expect_download(timeout=30000) as dl_info:
                await page.click(sel, timeout=8000)
            download = await dl_info.value
            fname = str(args.get("name", "")).strip() or download.suggested_filename or "download.bin"
            safe_name = os.path.basename(fname)
            path, error = resolve_path(os.path.join("产物", safe_name))
            if error:
                return CapabilityResult(ok=False, error=error)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            await download.save_as(path)
            expected = str(args.get("expected_sha256", "")).strip()
            if expected:
                import hashlib
                digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
                if digest != expected:
                    return CapabilityResult(ok=False, error="downloaded file hash does not match expected remote state")
            return CapabilityResult(ok=True, output=f"已下载到:{path}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserClose:
    name = "browser.close"
    risk = Risk.WRITE
    description = "Close the current isolated browser context and release its cross-process lease."
    schema = {
        "type": "object",
        "properties": {
            "owner_id": {"type": "string", "description": "Browser context owner identifier"},
            "account_id": {"type": "string", "description": "Browser account identifier"},
            "project_id": {"type": "string", "description": "Browser project identifier"},
            "task_id": {"type": "string", "description": "Browser task identifier"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        context = _context_key(ctx, args)
        try:
            released = await _close_context(context)
            return CapabilityResult(ok=True, output=(
                f"Browser context closed and lease released: {context.value[:12]}"
                if released else "Browser context was already closed"))
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))


class BrowserLoginAssist:
    name = "browser.login_assist"
    risk = Risk.WRITE
    description = (
        "人机协同登录:打开一个**可见的浏览器窗口**到登录页,由主人亲手完成"
        "(输验证码/滑块/扫码/二次验证),登录成功后自动保存会话——之后再访问该站点免登录。"
        "用于知乎/微博等带验证码或扫码的网站:验证码这一步必须由主人做,你不要硬猜或反复试。")
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "登录页 URL"},
            "success_contains": {"type": "string",
                                 "description": "可选:登录成功后 URL 里**不再**包含的片段(默认 signin/login/passport),用于判断登录完成"},
            "wait_sec": {"type": "integer", "description": "等待主人完成登录的秒数,默认 180"},
        },
        "required": ["url"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        url = str(args.get("url", "")).strip()
        if not url:
            return CapabilityResult(ok=False, error="缺少 url")
        if url.startswith("http"):
            from governance.egress import check_egress
            ok_e, why = check_egress(url)
            if not ok_e:
                return CapabilityResult(ok=False, error=why)
        try:
            wait_sec = int(args.get("wait_sec", 180) or 180)
        except (TypeError, ValueError):
            wait_sec = 180
        login_markers = ["signin", "login", "passport", "/account/", "sso"]
        hint = str(args.get("success_contains", "")).strip()
        try:
            context = _context_key(ctx, args)
            page = await _ensure_page(context, headless=False)   # visible window for human takeover
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"打开登录页失败:{e}")

        import asyncio as _a
        waited = 0
        interval = 2
        start_url = page.url
        while waited < wait_sec:
            await _a.sleep(interval)
            waited += interval
            try:
                cur = page.url
            except Exception:
                cur = start_url
            low = cur.lower()
            if hint:
                done = hint not in cur
            else:
                done = not any(m in low for m in login_markers)
            # 离开了登录页(被重定向到已登录页)→ 视为成功
            if done and cur != start_url:
                await _save_state(context)
                return CapabilityResult(
                    ok=True,
                    output=f"检测到登录完成(当前页 {cur}),会话已保存,之后访问该站免登录。")
        # 超时:无论是否检测到,都把当前 cookie 存下(主人可能已登录但页面未跳转)
        await _save_state(context)
        return CapabilityResult(
            ok=False,
            output="",
            error=(f"等待 {wait_sec}s 内未检测到登录完成。若你其实已登录,我已保存当前会话,可直接继续;"
                   "否则请在浏览器窗口完成登录后,让我重试或继续。"))
