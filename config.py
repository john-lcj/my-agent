"""全局配置 —— 密钥统一收口,只从环境变量/.env 读取,绝不硬编码。

提供一个零依赖的 .env 加载器(无需 python-dotenv 也能用)。
"""
from __future__ import annotations

import os

def _resolve_project_root() -> str:
    """项目根目录。优先 AGENT_PROJECT_ROOT(launch.sh 注入),否则为本文件所在目录。"""
    explicit = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if explicit:
        return os.path.abspath(explicit)
    return os.path.dirname(os.path.abspath(__file__))


_PROJECT_ROOT = _resolve_project_root()


def load_env(path: str | None = None) -> None:
    """极简 .env 加载:KEY=VALUE 逐行读入环境变量(不覆盖已存在的)。

    默认加载项目根下的 .env,与启动 uvicorn 时的工作目录无关。
    """
    if path is None:
        path = os.path.join(_PROJECT_ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# 在读取任何配置前先加载 .env,确保 Config 的类属性能拿到 .env 的值。
load_env()
# 兼容:若用户在 cwd 放了另一份 .env,也合并进来(不覆盖已有变量)。
load_env(os.path.join(os.getcwd(), ".env"))

try:
    from server.keychain_store import get_secret, secret_ref, should_use_for_path
    if should_use_for_path(_PROJECT_ROOT):
        for _env_key in ("AGENT_API_TOKEN", "AUTH_SECRET", "CAPTAIN_LICENSE_KEY"):
            _secret = get_secret(secret_ref("env", _env_key))
            if _secret:
                os.environ[_env_key] = _secret
except Exception:
    pass


class Config:
    # 选择模型 provider:mock / openai / claude / deepseek / router
    PROVIDER = os.environ.get("AGENT_PROVIDER", "mock")

    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
    OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "~anthropic/claude-sonnet-latest")
    OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # 会话首选模型 id(与 /model 一致;可被 runtime.json 覆盖)
    MODEL = os.environ.get("AGENT_MODEL", DEEPSEEK_MODEL)
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")

    POLICY_PATH = os.environ.get("AGENT_POLICY", "governance/policy.yaml")
    # 治理档位:conservative / balanced / aggressive(可被 runtime.json 覆盖)
    GOVERNANCE_MODE = os.environ.get("AGENT_GOVERNANCE_MODE", "balanced")
    _log_default = os.path.join(_PROJECT_ROOT, "logs")
    LOG_DIR = os.environ.get("AGENT_LOG_DIR", _log_default)
    if not os.path.isabs(LOG_DIR):
        LOG_DIR = os.path.join(_PROJECT_ROOT, LOG_DIR)
    MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "20"))
    # 已废弃:Captain 不再单独限步,由 triage 决定是否派子 agent;保留变量仅供旧文档兼容。
    CAPTAIN_MAX_STEPS = int(os.environ.get("AGENT_CAPTAIN_MAX_STEPS", "0") or "0")

    # 控制台是否回显 trace(开发期方便观察)
    TRACE_ECHO = os.environ.get("AGENT_TRACE_ECHO", "0") == "1"

    # Budget 上限(可选,不填则无金额限制)
    MAX_COST_USD = float(os.environ.get("AGENT_MAX_COST_USD", "0") or "0") or None

    # 长期记忆向量嵌入:mock(确定性回归) / openai(需 OPENAI_API_KEY)
    EMBED_PROVIDER = os.environ.get("AGENT_EMBED_PROVIDER", "openai")

    # 偏好自动沉淀:会话结束后抽取耐用偏好写入长期记忆(on/off;mock provider 下自动关)
    PREF_MINING = os.environ.get("AGENT_PREF_MINING", "on").lower() in ("on", "1", "true")

    # Skill 预加载:任务开始前自动调用轻量 READ skill(默认 on;大文档 skill 不预加载)
    SKILL_PREFETCH = os.environ.get("AGENT_SKILL_PREFETCH", "on").lower() in ("on", "1", "true")
    SKILL_PREFETCH_MAX_CHARS = int(os.environ.get("AGENT_SKILL_PREFETCH_MAX_CHARS", "2000"))

    # 个人数据目录(只读接入,路径分隔符分隔),如 ~/Documents/notes:~/Desktop/docs
    PERSONAL_DIRS = [
        os.path.expanduser(p.strip())
        for p in os.environ.get("AGENT_PERSONAL_DIRS", "").split(os.pathsep)
        if p.strip()
    ]

    # 每日简报:daily HH:MM 推送渠道(email/none)
    BRIEFING_AT = os.environ.get("AGENT_BRIEFING_AT", "08:00")
    BRIEFING_CHANNEL = os.environ.get("AGENT_BRIEFING_CHANNEL", "email")
    # 投递目标:邮件渠道留空则发给 EMAIL_USER 自己
    BRIEFING_TO = os.environ.get("AGENT_BRIEFING_TO", "")
