"""CLI 启动画面 —— Hermes 风格极简横幅 + 可选完整版(AGENT_BANNER=full)。"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable

# ── 调色板(Hermes 式中性 + 单一强调色)────────────────────────────────
_MUTED = (120, 120, 120)
_DIM = (90, 90, 90)
_TEXT = (220, 220, 220)
_ACCENT = (180, 140, 100)
_LINE = (60, 60, 60)
_OK = (120, 180, 140)


def _fg(rgb: tuple[int, int, int], bold: bool = False) -> str:
    r, g, b = rgb
    return f"\033[{1 if bold else 0};38;2;{r};{g};{b}m"


def _reset() -> str:
    return "\033[0m"


def _term_cols() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except OSError:
        return 80


def _clear_screen() -> None:
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _clip(s: str, width: int) -> str:
    if width <= 0:
        return ""
    return s if len(s) <= width else s[: max(0, width - 1)] + "…"


def _banner_mode() -> str:
    return (os.environ.get("AGENT_BANNER", "minimal") or "minimal").strip().lower()


def _print_minimal_banner(
    *,
    model_id: str,
    tagline: str,
    project_root: str,
    experts: Iterable[tuple[str, str]],
    skills: Iterable[tuple[str, str]],
    cols: int,
) -> None:
    """Hermes 风格:紧凑顶栏 + 可折叠信息行,无大块 ASCII 艺术。"""
    from llm.model_registry import get_model

    w = max(40, min(cols - 2, 78))
    inner = w - 2
    spec = get_model(model_id)
    ctx = spec.context
    if ctx >= 1_000_000:
        ctx_label = f"{ctx // 1_000_000}M"
    elif ctx >= 1000:
        ctx_label = f"{ctx // 1000}K"
    else:
        ctx_label = str(ctx)

    expert_list = list(experts)
    skill_list = list(skills)
    expert_names = ", ".join(n for n, _ in expert_list[:5])
    if len(expert_list) > 5:
        expert_names += f" +{len(expert_list) - 5}"
    skill_names = ", ".join(n for n, _ in skill_list[:6]) or "—"

    lines = [
        f"Captain · {tagline}",
        f"model {model_id} · {ctx_label} ctx · {_clip(project_root, inner - 24)}",
        f"{len(expert_list)} experts · {len(skill_list)} skills · / 斜杠命令 · exit 退出",
    ]
    if _banner_mode() in ("verbose", "full", "expanded"):
        lines.append(f"experts: {_clip(expert_names, inner - 10)}")
        lines.append(f"skills:  {_clip(skill_names, inner - 10)}")

    import textwrap
    from channels.cli_style import _cols, _pad

    w, inner = min(max(48, _cols() - 4), 72), min(max(48, _cols() - 4), 72) - 4
    sys.stdout.write(f"\n╭{'─' * (w - 2)}╮\n")
    for line in lines:
        if line.strip():
            for chunk in textwrap.wrap(line, width=inner, break_long_words=True) or [""]:
                sys.stdout.write(f"│ {_pad(chunk, inner)} │\n")
    sys.stdout.write(f"╰{'─' * (w - 2)}╯\n")
    sys.stdout.write("❯ 直接说任务 · /skills 命令 · /model 换模型 · exit 退出\n\n")


# ── 完整版(原章鱼哥 + Logo,AGENT_BANNER=full)──────────────────────────
_GOLD = (255, 215, 0)
_ACCENT_FULL = (255, 191, 0)
_BRONZE = (205, 127, 50)
_DIM_FULL = (184, 134, 11)
_TEXT_FULL = (255, 248, 220)
_SKIN = (136, 198, 190)
_SKIN_HI = (162, 218, 210)
_SKIN_LO = (94, 156, 148)
_SKIN_SPOT = (56, 92, 78)
_WRINKLE = (84, 138, 132)
_EYE = (250, 244, 218)
_PUPIL = (132, 44, 56)
_LID = (98, 164, 156)
_NOSE = (122, 186, 178)
_NOSE_SH = (92, 148, 142)
_MOUTH = (56, 66, 76)
_HAT = (246, 246, 246)
_HAT_BRIM = (26, 26, 30)
_HAT_ANCHOR = (46, 86, 156)
_HAT_TRIM = (186, 50, 46)
_SHIRT = (214, 170, 74)
_SHIRT_COLLAR = (188, 146, 56)
_MAG = (234, 198, 58)
_MAG_TITLE = (92, 58, 138)
_PALETTE = (_GOLD, _ACCENT_FULL, _BRONZE, _DIM_FULL)
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_TAGLINE = "章鱼哥值班 · 分寸感总指挥 · Captain"

CAPTAIN_LOGO: tuple[tuple[int, str], ...] = (
    (0, " ██████╗ █████╗ ██████╗ ████████╗ █████╗ ██╗███╗   ██╗"),
    (0, "██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██║████╗  ██║"),
    (1, "██║     ███████║██████╔╝   ██║   ███████║██║██╔██╗ ██║"),
    (1, "██║     ██╔══██║██╔═══╝    ██║   ██╔══██║██║██║╚██╗██║"),
    (2, "╚██████╗██║  ██║██║        ██║   ██║  ██║██║██║ ╚████║"),
    (2, " ╚═════╝╚═╝  ╚═╝╚═╝        ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"),
)


def _c(rgb: tuple[int, int, int], text: str) -> str:
    return f"{_fg(rgb)}{text}{_reset()}"


def _build_squidward_art() -> list[str]:
    s, sh, sl, sp, wr = _SKIN, _SKIN_HI, _SKIN_LO, _SKIN_SPOT, _WRINKLE
    e, p, lid = _EYE, _PUPIL, _LID
    n, ns, m = _NOSE, _NOSE_SH, _MOUTH
    hw, hb, ha, ht = _HAT, _HAT_BRIM, _HAT_ANCHOR, _HAT_TRIM
    t, tc = _SHIRT, _SHIRT_COLLAR
    mg, mt = _MAG, _MAG_TITLE

    def eye_pair(left: str, right: str) -> str:
        return (
            f"{_c(s, left)}"
            f"{_c(e, '▓')}{_c(p, '┃')}{_c(e, '▓')}"
            f"{_c(s, '    ')}"
            f"{_c(e, '▓')}{_c(p, '┃')}{_c(e, '▓')}"
            f"{_c(s, right)}"
        )

    return [
        "",
        _c(hw, "            ┌─────────────┐"),
        _c(hw, "            │             │"),
        _c(hw, "            │") + _c(ha, "      ⚓      ") + _c(hw, "│"),
        _c(ht, "            ├─────────────┤"),
        _c(hb, "            └─────────────┘"),
        _c(sl, "          ▄██") + _c(s, "·") + _c(sp, "°·°") + _c(s, "██") + _c(sp, "°·") + _c(s, "·") + _c(sl, "██▄"),
        _c(sl, "         ██") + _c(sh, "░░░░░░░░░░░░░░░░") + _c(sl, "██"),
        _c(s, "        ██") + _c(wr, "════════════════") + _c(s, "██"),
        _c(s, "        ██") + _c(wr, "════════════════") + _c(s, "██"),
        _c(s, "        ██") + _c(wr, "════════════════") + _c(s, "██"),
        _c(s, "       ██  ") + _c(lid, "▀████▀") + _c(s, "  ") + _c(lid, "▀████▀") + _c(s, "  ██"),
        eye_pair("      ██  ", "  ██"),
        _c(s, "      ██           ") + _c(n, "▄████▄") + _c(s, "           ██"),
        _c(s, "      ██          ") + _c(ns, "████████") + _c(s, "          ██"),
        _c(s, "      ██           ") + _c(n, "████████") + _c(s, "           ██"),
        _c(s, "       ██           ") + _c(n, "██████") + _c(s, "           ██"),
        _c(s, "        ██           ") + _c(n, "████") + _c(s, "           ██"),
        _c(s, "         ██            ") + _c(m, "╰──╯") + _c(s, "            ██"),
        _c(s, "          ██▄                      ▄██"),
        _c(tc, "           ▄████████████████████▄"),
        _c(t, "          ████████████████████████"),
        _c(t, "          ████████████████████████"),
        _c(s, "           ██") + _c(mg, "┌──────────────┐") + _c(s, "██"),
        _c(s, "           ██") + _c(mg, "│") + _c(mt, "FANCY LIVING") + _c(mg, "│") + _c(s, "██"),
        _c(s, "           ██") + _c(mg, "│") + _c(mt, "   DIGEST   ") + _c(mg, "│") + _c(s, "██"),
        _c(s, "           ██") + _c(mg, "└──────────────┘") + _c(s, "██"),
    ]


def _play_hero_entrance(cols: int) -> None:
    if not sys.stdout.isatty() or cols < 70:
        return
    painted = _build_squidward_art()
    delay = float(os.environ.get("AGENT_BANNER_DELAY", "0.045"))
    for end in range(1, len(painted) + 1):
        sys.stdout.write("\033[H")
        for line in painted[:end]:
            sys.stdout.write(line + "\n")
        frame = _SPINNER[(end - 1) % len(_SPINNER)]
        sys.stdout.write(f"{_fg(_DIM_FULL)}{frame} 上线中…{_reset()}\n")
        sys.stdout.flush()
        import time
        time.sleep(delay)
    sys.stdout.write("\033[1A\033[2K")
    sys.stdout.flush()


def _print_full_banner(
    *,
    model_id: str,
    tagline: str,
    project_root: str,
    experts: Iterable[tuple[str, str]],
    skills: Iterable[tuple[str, str]],
    cols: int,
) -> None:
    """原完整启动画(章鱼哥 + 分栏面板)。"""
    if cols >= 88:
        for idx, text in CAPTAIN_LOGO:
            color = _PALETTE[idx % len(_PALETTE)]
            sys.stdout.write(f"{_fg(color, bold=True)}{text}{_reset()}\n")
        sys.stdout.write(f"{_fg(_DIM_FULL)}🐙 {_TAGLINE}{_reset()}\n\n")

    hero_lines = _build_squidward_art()
    hero_w = 42
    left_w = min(hero_w + 2, max(24, cols // 3))
    right_w = max(20, cols - left_w - 7)
    inner = left_w + right_w + 3
    top = f"╭{'─' * (inner - 2)}╮"

    from llm.model_registry import get_model
    spec = get_model(model_id)
    ctx = spec.context
    ctx_label = f"{ctx // 1_000_000}M" if ctx >= 1_000_000 else (f"{ctx // 1000}K" if ctx >= 1000 else str(ctx))

    left_meta = ["", *hero_lines, "",
                 f"{_fg(_ACCENT_FULL)}{model_id}{_reset()}{_fg(_DIM_FULL)} · {ctx_label}{_reset()}",
                 f"{_fg(_DIM_FULL)}{_clip(project_root, left_w)}{_reset()}"]
    right_meta = [f"{_fg(_ACCENT_FULL, bold=True)}执行专家{_reset()}"]
    expert_list = list(experts)
    for name, role in expert_list[:6]:
        right_meta.append(f"{_fg(_DIM_FULL)}{name}:{_reset()} {_fg(_TEXT_FULL)}{_clip(role, right_w - len(name) - 2)}{_reset()}")
    right_meta.extend(["", f"{_fg(_ACCENT_FULL, bold=True)}Skill{_reset()}"])
    skill_list = list(skills)
    if skill_list:
        names = ", ".join(s[0] for s in skill_list[:8])
        right_meta.append(f"{_fg(_TEXT_FULL)}{_clip(names, right_w)}{_reset()}")
    rows = max(len(left_meta), len(right_meta))
    sys.stdout.write(f"\n{_fg(_BRONZE)}{top}{_reset()}\n")
    for i in range(rows):
        left_raw = left_meta[i] if i < len(left_meta) else ""
        right_raw = right_meta[i] if i < len(right_meta) else ""
        pad_l = max(0, left_w - len(_strip_ansi(left_raw)))
        pad_r = max(0, right_w - len(_strip_ansi(right_raw)))
        sys.stdout.write(
            f"{_fg(_BRONZE)}│{_reset()} {left_raw}{' ' * pad_l} {_fg(_BRONZE)}│{_reset()} "
            f"{right_raw}{' ' * pad_r} {_fg(_BRONZE)}│{_reset()}\n"
        )
    sys.stdout.write(f"{_fg(_BRONZE)}{'╰' + '─' * (left_w + 2) + '┴' + '─' * (right_w + 2) + '╯'}{_reset()}\n\n")


def prelude_entrance() -> bool:
    if os.environ.get("AGENT_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return False
    if _banner_mode() not in ("full", "hero"):
        return False
    if not sys.stdout.isatty():
        return False
    cols = _term_cols()
    _clear_screen()
    if cols >= 70:
        _play_hero_entrance(cols)
    return True


def show_captain_banner(
    *,
    model_id: str,
    tagline: str = "有分寸感的总指挥助理",
    project_root: str,
    experts: Iterable[tuple[str, str]] = (),
    skills: Iterable[tuple[str, str]] = (),
    animate: bool = True,
    clear: bool = True,
) -> None:
    if os.environ.get("AGENT_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return
    if not sys.stdout.isatty():
        print(f"Captain · model={model_id}")
        return

    cols = _term_cols()
    if clear and _banner_mode() in ("full", "hero"):
        _clear_screen()
    if animate and _banner_mode() in ("full", "hero") and cols >= 70:
        _play_hero_entrance(cols)

    if _banner_mode() in ("full", "hero"):
        _print_full_banner(
            model_id=model_id, tagline=tagline, project_root=project_root,
            experts=experts, skills=skills, cols=cols,
        )
    else:
        _print_minimal_banner(
            model_id=model_id, tagline=tagline, project_root=project_root,
            experts=experts, skills=skills, cols=cols,
        )
