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
from typing import Any

from core.types import CapabilityResult, Risk

_PW = None      # playwright 实例
_BROWSER = None
_CONTEXT = None
_PAGE = None
_HEADLESS_MODE = None   # 当前浏览器是无头还是有头(供登录助手切换可见窗口)


def _default_headless() -> bool:
    return os.environ.get("AGENT_BROWSER_HEADLESS", "1").strip() != "0"


def _state_file() -> str:
    base = (os.environ.get("AGENT_LOG_DIR", "").strip() or "logs")
    return os.path.join(base, "browser_state.json")


def _artifacts_dir() -> str:
    ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    d = os.path.join(ws, "产物")
    os.makedirs(d, exist_ok=True)
    return d


async def _ensure_page(headless: bool | None = None):
    """惰性启动 Chromium + 载入已保存登录态,返回持久 page。

    headless=None 用默认(env AGENT_BROWSER_HEADLESS,默认无头);
    显式传 True/False 时,若与当前模式不同则**重启浏览器**切换(供登录助手开可见窗口)。
    """
    global _PW, _BROWSER, _CONTEXT, _PAGE, _HEADLESS_MODE
    want = _default_headless() if headless is None else headless
    if _PAGE is not None and _HEADLESS_MODE == want:
        return _PAGE
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "未安装 Playwright。请先:pip install playwright && python -m playwright install chromium"
        ) from e
    # 模式切换:先关掉旧浏览器(登录态已落盘,不会丢)
    if _PAGE is not None and _HEADLESS_MODE != want:
        await _save_state()
        try:
            await _BROWSER.close()
        except Exception:
            pass
        _BROWSER = _CONTEXT = _PAGE = None
    if _PW is None:
        _PW = await async_playwright().start()
    _BROWSER = await _PW.chromium.launch(headless=want)
    state = _state_file()
    kwargs = {"accept_downloads": True}
    if os.path.isfile(state):
        kwargs["storage_state"] = state          # 复用上次登录态
    _CONTEXT = await _BROWSER.new_context(**kwargs)
    _PAGE = await _CONTEXT.new_page()
    _HEADLESS_MODE = want
    return _PAGE


async def _save_state() -> None:
    """把当前 context 的 cookie/localStorage 落盘,实现跨会话保持登录。"""
    if _CONTEXT is None:
        return
    try:
        path = _state_file()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        await _CONTEXT.storage_state(path=path)
    except Exception:
        pass


async def _page_text(page, limit: int = 8000) -> str:
    try:
        txt = await page.inner_text("body")
    except Exception:
        txt = await page.content()
    return (txt or "").strip()[:limit]


def _safe_ws_path(p: str) -> str | None:
    """把用户给的路径限制在工作区内,防越权读本机任意文件上传。"""
    ws = os.path.abspath(os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd())
    full = os.path.abspath(p if os.path.isabs(p) else os.path.join(ws, p))
    return full if (full == ws or full.startswith(ws + os.sep)) else None


class BrowserOpen:
    name = "browser.open"
    risk = Risk.READ
    description = "用真实浏览器打开/跳转一个 URL(会执行 JS,适合客户端渲染的网站),返回渲染后的正文。"
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要打开的网址"},
            "wait_selector": {"type": "string", "description": "可选:等待此 CSS 选择器出现再取文本"},
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
            page = await _ensure_page()
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
            await _save_state()
            text = await _page_text(page)
            return CapabilityResult(ok=True, output=f"[{await page.title()}] {url}\n{text}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserText:
    name = "browser.text"
    risk = Risk.READ
    description = "读取当前浏览器页面渲染后的正文(配合 browser.open/click/fill 串联使用)。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        return CapabilityResult(ok=True, output=await _page_text(_PAGE))


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
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        try:
            if sel:
                await _PAGE.wait_for_selector(sel, timeout=int(args.get("timeout", 15000)))
                return CapabilityResult(ok=True, output=f"元素已出现:{sel}")
            await _PAGE.wait_for_timeout(int(args.get("ms", 1000)))
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
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        name = str(args.get("name", "")).strip() or "screenshot.png"
        if not name.lower().endswith((".png", ".jpg", ".jpeg")):
            name += ".png"
        path = os.path.join(_artifacts_dir(), name)
        try:
            await _PAGE.screenshot(path=path, full_page=bool(args.get("full_page", True)))
            return CapabilityResult(ok=True, output=f"已截图:{path}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


class BrowserClick:
    name = "browser.click"
    risk = Risk.WRITE
    description = "点击当前页面上匹配 CSS 选择器的元素(可能触发提交/跳转)。"
    schema = {
        "type": "object",
        "properties": {"selector": {"type": "string", "description": "CSS 选择器"}},
        "required": ["selector"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        sel = str(args.get("selector", "")).strip()
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        try:
            await _PAGE.click(sel, timeout=8000)
            await _PAGE.wait_for_timeout(500)
            await _save_state()
            return CapabilityResult(ok=True, output=f"已点击 {sel}。当前页:{await _PAGE.title()}")
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
            "selector": {"type": "string", "description": "输入框 CSS 选择器"},
            "text": {"type": "string",
                     "description": "要填的内容;填密码用 secret:<凭据名> 引用保险库,绝不要写明文密码"},
        },
        "required": ["selector", "text"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        sel = str(args.get("selector", "")).strip()
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        raw = str(args.get("text", ""))
        masked = False
        if raw.startswith("secret:"):
            name = raw[len("secret:"):].strip()
            vault = getattr(ctx, "vault", None)
            if vault is None:
                return CapabilityResult(ok=False, error="未配置凭据保险库,无法解引用 secret:")
            pw = vault.get(name)
            if pw is None:
                return CapabilityResult(ok=False, error=f"保险库里没有「{name}」的密码,请先用 secret.save 保存")
            raw, masked = pw, True
        try:
            await _PAGE.fill(sel, raw, timeout=8000)
            await _save_state()
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
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        full = _safe_ws_path(str(args.get("path", "")).strip())
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        if not full or not os.path.isfile(full):
            return CapabilityResult(ok=False, error="文件不存在或越出工作区范围")
        try:
            await _PAGE.set_input_files(sel, full, timeout=8000)
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
        },
        "required": ["selector"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        if _PAGE is None:
            return CapabilityResult(ok=False, error="还没有打开页面,先用 browser.open")
        sel = str(args.get("selector", "")).strip()
        if not sel:
            return CapabilityResult(ok=False, error="缺少 selector")
        try:
            async with _PAGE.expect_download(timeout=30000) as dl_info:
                await _PAGE.click(sel, timeout=8000)
            download = await dl_info.value
            fname = str(args.get("name", "")).strip() or download.suggested_filename or "download.bin"
            path = os.path.join(_artifacts_dir(), fname)
            await download.save_as(path)
            return CapabilityResult(ok=True, output=f"已下载到:{path}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


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
            page = await _ensure_page(headless=False)   # 强制可见窗口,让主人能操作
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
                await _save_state()
                return CapabilityResult(
                    ok=True,
                    output=f"检测到登录完成(当前页 {cur}),会话已保存,之后访问该站免登录。")
        # 超时:无论是否检测到,都把当前 cookie 存下(主人可能已登录但页面未跳转)
        await _save_state()
        return CapabilityResult(
            ok=False,
            output="",
            error=(f"等待 {wait_sec}s 内未检测到登录完成。若你其实已登录,我已保存当前会话,可直接继续;"
                   "否则请在浏览器窗口完成登录后,让我重试或继续。"))
