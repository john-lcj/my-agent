"""CLI 终端样式 — Hermes：黄框 Agent、状态栏、Markdown 表格列对齐。"""
from __future__ import annotations
import os, re, shutil, sys, time, unicodedata
from core.status_bar import progress_bar

PROMPT, _Y, _D, _R = "❯ ", "\033[33m", "\033[2m", "\033[0m"
_W = lambda ch: 0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "FW" else 1

def _cols() -> int:
    try: return shutil.get_terminal_size((80, 24)).columns
    except OSError: return 80

def agent_color_enabled() -> bool:
    e = os.environ
    return not (e.get("AGENT_CLI_PLAIN", "").lower() in ("1", "true", "yes") or e.get("NO_COLOR")) and sys.stdout.isatty() and (e.get("TERM") or "").lower() not in ("dumb", "unknown")

prompt_prefix = lambda: PROMPT
_dim = lambda s: f"{_D}{s}{_R}" if agent_color_enabled() else s
_term_cols = _cols

def format_cli_status(payload: dict, *, plain: bool = False) -> str:
    m = str(payload.get("model") or "—"); m = m[:25] + "…" if len(m) > 26 else m
    tok, pct = payload.get("tokens_label") or "—", int(round(float(payload.get("pct") or 0)))
    bar, dur = payload.get("bar") or progress_bar(float(payload.get("pct") or 0)), payload.get("session_label") or "0s"
    c = _cols()
    line = f" ⚕ {m} │ {tok} │ {bar} {pct}% │ {dur}" if c >= 76 else f" ⚕ {m} │ {tok} │ {pct}% │ {dur}" if c >= 52 else f" ⚕ {m} │ {dur}"
    return line if plain or not agent_color_enabled() else _dim(line)

def format_live_status(payload: dict | None, session_started_at: float | None) -> str:
    if not payload: return ""
    live = dict(payload)
    if session_started_at is not None:
        from core.status_bar import format_duration
        live["session_label"] = format_duration(time.time() - session_started_at)
    return format_cli_status(live, plain=True)

def status_separator() -> str:
    sep = "─" * min(_cols(), 72)
    return _dim(sep) if agent_color_enabled() else sep

def _dw(s: str) -> int: return sum(_W(ch) for ch in s)

def _pad(s: str, w: int, align: str = "left") -> str:
    s, g = s.strip(), w - _dw(s.strip())
    return s if g <= 0 else (" " * g + s if align == "right" else " " * (g // 2) + s + " " * (g - g // 2) if align == "center" else s + " " * g)

def _wrap(s: str, w: int) -> list[str]:
    if not s: return []
    lines, cur, cw = [], [], 0
    for ch in s:
        cww = _W(ch)
        if cw + cww > w: lines.append("".join(cur)); cur, cw = [ch], cww
        else: cur.append(ch); cw += cww
    if cur: lines.append("".join(cur))
    return lines or [""]

def format_cli_text(text: str) -> str:
    if not text: return ""
    out, md = [], (r"^#{1,6}\s+", r"^[-*+]\s+", r"\*\*(.+?)\*\*", r"__(.+?)__", r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"(?<!_)_([^_\n]+)_(?!_)", r"`([^`\n]+)`")
    for raw in text.splitlines():
        s = raw.strip()
        if not s: out.append(""); continue
        if s.startswith("|"): out.append(s); continue
        s = re.sub(md[0], "", s)
        s = ("• " + re.sub(md[1], "", s)) if re.match(md[1], s) else s
        for pat in md[2:]: s = re.sub(pat, r"\1", s)
        out.append(s)
    lines, tbl, i = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).splitlines(), [], 0
    while i < len(lines):
        if not lines[i].strip().startswith("|"): tbl.append(lines[i].rstrip()); i += 1; continue
        block = [[x.strip() for x in lines[i].strip().strip("|").split("|")]]; i += 1
        while i < len(lines) and lines[i].strip().startswith("|"):
            row = [x.strip() for x in lines[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in row if c): block.append(row)
            i += 1
        if len(block) < 2: tbl.append("| " + " | ".join(block[0]) + " |"); continue
        n = max(len(r) for r in block)
        widths = [max(_dw((r[j] if j < len(r) else "").strip()) for r in block) for j in range(n)]
        def al(j):
            ss = [(r[j] if j < len(r) else "").strip() for r in block[1:] if j < len(r) and r[j].strip()]
            return "right" if ss and all(re.fullmatch(r"[\d,.]+", s) for s in ss) else "right" if ss and all(re.search(r"\d", s) and re.search(r"万|w|W|k|K|%", s) for s in ss) else "center" if ss and all(re.fullmatch(r"\d+", s) for s in ss) else "left"
        rend = lambda cs, j=0: "  ".join(_pad(cs[k].strip() if k < len(cs) else "", widths[k], al(k)) for k in range(n))
        if tbl and tbl[-1].strip(): tbl.append("")
        tbl += [rend(block[0]), "  ".join("─" * w for w in widths)] + [rend(r) for r in block[1:]]
        if i < len(lines) and lines[i].strip(): tbl.append("")
    return "\n".join(tbl).strip()

sanitize_stream_token = lambda t: (t or "").replace("**", "").replace("__", "")

def _box() -> tuple[int, int, int]:
    try: ind = int(os.environ.get("AGENT_CLI_BOX_INDENT", "4"))
    except ValueError: ind = 4
    ind = min(12, max(2, ind))
    w = max(52, min(_cols() - ind - 2, 90))
    return ind, w, w - 4

def write_agent_body(body: str, prefix: str, inner: int) -> None:
    if agent_color_enabled(): sys.stdout.write(_Y)
    for para in body.split("\n"):
        if not para.strip(): continue
        tbl = "  " in para and len(para.split("  ", 1)[0].strip()) < 40
        for chunk in ([para] if tbl else _wrap(para, inner)):
            s = chunk
            if _dw(s) > inner:
                o, ww = [], 0
                for ch in s:
                    cw = _W(ch)
                    if ww + cw > inner - 1: s = "".join(o) + "…"; break
                    o.append(ch); ww += cw
            sys.stdout.write(f"{prefix}│ {_pad(s, inner)} │\n")
    if agent_color_enabled(): sys.stdout.write(_R); sys.stdout.flush()

def agent_frame(prefix: str, w: int, label: str, close: bool = False) -> str:
    if close: return f"{prefix}╰{'─' * (w - 2)}╯\n"
    title = f" {(label or 'Captain').strip()} "
    return f"\n{prefix}╭─{title}{'─' * max(0, w - 3 - len(title))}╮\n"

def print_agent_block(text: str, source: str = "Captain") -> None:
    body = format_cli_text(text)
    if not body: return
    ind, w, inner = _box(); prefix = " " * ind
    sys.stdout.write(agent_frame(prefix, w, source)); write_agent_body(body, prefix, inner)
    sys.stdout.write(agent_frame(prefix, w, source, True)); sys.stdout.flush()

def print_system(text: str) -> None:
    for line in (text or "").strip().splitlines(): print(_dim(f"  · {line}") if agent_color_enabled() else f"  · {line}")
def print_ok(text: str) -> None: print(f"  ✓ {text}")
def print_err(text: str) -> None: print(f"  ✗ {text}")
