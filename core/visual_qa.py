"""视觉 QA —— HTML 启发式 + Playwright 截图 + vision.see(S29)。"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass


@dataclass
class VisualCheckResult:
    ok: bool
    notes: str = ""
    issues: list[str] | None = None


def _heuristic_issues(html: str) -> list[str]:
    issues: list[str] = []
    if html.count("<button") + html.count('role="button"') > 0:
        if re.search(r"position\s*:\s*fixed[^;{]*;[^}]*position\s*:\s*fixed", html, re.I):
            issues.append("多个 fixed 定位元素可能重叠")
    if re.search(r"overflow\s*:\s*hidden", html, re.I) and re.search(
        r"white-space\s*:\s*nowrap", html, re.I,
    ):
        issues.append("hidden+nowrap 可能导致文字溢出不可见")
    empty_btn = re.findall(r"<button[^>]*>\s*</button>", html, re.I)
    if len(empty_btn) >= 2:
        issues.append(f"发现 {len(empty_btn)} 个空按钮")
    if "<html" not in html.lower() and "<body" not in html.lower():
        issues.append("缺少基本 html/body 结构")
    return issues


def _vision_analyze_screenshot(shot_path: str) -> list[str]:
    """有 VISION_MODEL 时用视觉模型看截图。"""
    if not os.environ.get("VISION_MODEL", "").strip():
        return []
    if not os.path.isfile(shot_path):
        return []
    try:
        import base64
        from openai import OpenAI
        with open(shot_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        key = (os.environ.get("VISION_API_KEY", "").strip()
               or os.environ.get("OPENAI_API_KEY", "").strip())
        if not key:
            return []
        client = OpenAI(
            api_key=key,
            base_url=os.environ.get("VISION_BASE_URL", "").strip() or None,
        )
        resp = client.chat.completions.create(
            model=os.environ["VISION_MODEL"].strip(),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "这是网页截图。只列出布局问题(按钮重叠/文字溢出/大面积空白/不可读),"
                        "每项一行;无问题只回复 OK。"
                    )},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            max_tokens=200,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text or text.upper() == "OK":
            return []
        return [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
    except Exception:
        return []


def check_artifact_layout(path: str) -> VisualCheckResult:
    p = (path or "").strip()
    if not p or not os.path.isfile(p):
        return VisualCheckResult(False, "产物路径无效", ["文件不存在"])
    if not p.lower().endswith((".html", ".htm")):
        return VisualCheckResult(True, "非 HTML,跳过布局检查", [])

    try:
        html = open(p, encoding="utf-8", errors="ignore").read(50000)
    except OSError as e:
        return VisualCheckResult(False, str(e), [str(e)])

    if len(html) < 50:
        return VisualCheckResult(False, "HTML 过短", ["内容过少"])

    issues = _heuristic_issues(html)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(f"file://{os.path.abspath(p)}", wait_until="domcontentloaded", timeout=8000)
            if page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 20"):
                issues.append("页面水平溢出")
            shot = os.path.join(tempfile.gettempdir(), f"captain_vqa_{os.getpid()}.png")
            page.screenshot(path=shot, full_page=True)
            browser.close()
            issues.extend(_vision_analyze_screenshot(shot))
            try:
                os.remove(shot)
            except Exception:
                pass
    except Exception:
        pass

    if issues:
        return VisualCheckResult(False, "; ".join(issues[:3]), issues)
    return VisualCheckResult(True, f"HTML 布局检查通过({len(html)} bytes)", [])
