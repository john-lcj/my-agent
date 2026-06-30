"""Captain .env 配置向导。

保持零第三方依赖，供 `make config` 与安装后手动配置使用。
"""
from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path


ENV_FILE = Path(os.environ.get("AGENT_ENV_FILE", ".env"))


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _parse_kv(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _set_value(lines: list[str], key: str, value: str) -> list[str]:
    prefix = key + "="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        k, _ = line.split("=", 1)
        if k.strip() == key:
            out.append(prefix + value)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(prefix + value)
    return out


def _write_env(path: Path, lines: list[str]) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ask(prompt: str, default: str = "") -> str:
    v = input(prompt).strip()
    return v if v else default


def main() -> int:
    lines = _read_lines(ENV_FILE)
    if not lines:
        lines = [
            "# Captain 配置文件",
            "AGENT_WEB_PORT=8000",
            "AGENT_WEB_HOST=127.0.0.1",
        ]
    current = _parse_kv(lines)

    print("Captain 配置向导")
    print("1) DeepSeek  2) OpenAI  3) Claude  4) 跳过")
    model_choice = _ask("主模型选择 [1]: ", "1")
    if model_choice == "1":
        key = _ask("DeepSeek API Key: ", current.get("DEEPSEEK_API_KEY", ""))
        model = _ask("模型 ID [deepseek-v4-flash]: ", "deepseek-v4-flash")
        lines = _set_value(lines, "AGENT_PROVIDER", "deepseek")
        lines = _set_value(lines, "AGENT_MODEL", model)
        if key:
            lines = _set_value(lines, "DEEPSEEK_API_KEY", key)
    elif model_choice == "2":
        key = _ask("OpenAI API Key: ", current.get("OPENAI_API_KEY", ""))
        model = _ask("模型 ID [gpt-4o-mini]: ", "gpt-4o-mini")
        lines = _set_value(lines, "AGENT_PROVIDER", "openai")
        lines = _set_value(lines, "AGENT_MODEL", model)
        if key:
            lines = _set_value(lines, "OPENAI_API_KEY", key)
    elif model_choice == "3":
        key = _ask("Anthropic API Key: ", current.get("ANTHROPIC_API_KEY", ""))
        model = _ask("模型 ID [claude-sonnet-4-20250514]: ", "claude-sonnet-4-20250514")
        lines = _set_value(lines, "AGENT_PROVIDER", "claude")
        lines = _set_value(lines, "AGENT_MODEL", model)
        if key:
            lines = _set_value(lines, "ANTHROPIC_API_KEY", key)

    print("1) 智谱 CogView  2) OpenAI  3) 跳过")
    image_choice = _ask("文生图选择 [3]: ", "3")
    if image_choice == "1":
        image_key = _ask("智谱 IMAGE_API_KEY: ", current.get("IMAGE_API_KEY", ""))
        lines = _set_value(lines, "IMAGE_PROVIDER", "zhipu")
        lines = _set_value(lines, "IMAGE_MODEL", "cogview-3-flash")
        if image_key:
            lines = _set_value(lines, "IMAGE_API_KEY", image_key)
    elif image_choice == "2":
        image_key = _ask("OpenAI IMAGE_API_KEY: ", current.get("IMAGE_API_KEY", ""))
        lines = _set_value(lines, "IMAGE_PROVIDER", "openai")
        if image_key:
            lines = _set_value(lines, "IMAGE_API_KEY", image_key)

    _ask("搜索配置：1) 跳过 [1]: ", "1")

    preset_choice = _ask("使用者画像：1) 通用  2) 职场办公  3) 写代码 [1]: ", "1")
    preset = {"1": "general", "2": "office", "3": "coder"}.get(preset_choice, "general")
    lines = _set_value(lines, "AGENT_PERSONA_PRESET", preset)

    token_choice = _ask("访问令牌：1) 保持当前  2) 生成新的 [1]: ", "1")
    host_choice = _ask("绑定地址：1) 本机  2) 所有网卡 [1]: ", "1")
    if token_choice == "2" or not current.get("AGENT_API_TOKEN"):
        lines = _set_value(lines, "AGENT_API_TOKEN", secrets.token_urlsafe(24))
    if not current.get("AUTH_SECRET"):
        lines = _set_value(lines, "AUTH_SECRET", secrets.token_urlsafe(32))
    lines = _set_value(lines, "AGENT_WEB_HOST", "0.0.0.0" if host_choice == "2" else "127.0.0.1")
    if not _parse_kv(lines).get("AGENT_WEB_PORT"):
        lines = _set_value(lines, "AGENT_WEB_PORT", "8000")

    confirm = _ask(f"写入 {ENV_FILE}? [y/N]: ", "n").lower()
    if confirm not in {"y", "yes"}:
        print("已取消。")
        return 1
    _write_env(ENV_FILE, lines)
    print(f"已写入 {ENV_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
