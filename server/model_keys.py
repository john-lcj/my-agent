"""模型 API key 的服务端持久化 —— 让"在网页里填的模型 key"真正生效。

与 channels/config_store.py 同思路:把 key 落到 logs/model_keys.json,并在加载/更新时
写进 os.environ。各 provider 的 LLM 实现本就从 env 读 key(如 DEEPSEEK_API_KEY),
因此无需改动它们,填完即可在 /api/models 里看到对应模型变为"已配置"。

安全:
- get_masked 永不回明文,只回 'configured' 标记。
- 空字符串或 '******' 视为"不改动",不会覆盖已存 key。
- ⚠ 本端点本身需要鉴权(见审查报告 P0-⑤):录入 key 的入口若随 server 对外暴露,
  等于把填 key 的能力开放给任何能访问该端口的人。务必仅绑 127.0.0.1 或加访问控制。
"""
from __future__ import annotations

import json
import os

# provider -> 环境变量名(各 LLM 实现读取的 key)
PROVIDER_KEY_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

_MASK = "******"


class ModelKeyStore:
    def __init__(self, path: str = "logs/model_keys.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict[str, str] = self._read()
        self.apply_to_env()

    def _read(self) -> dict[str, str]:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return {}
        # 只保留已知 provider 的字符串值
        return {p: str(v) for p, v in data.items()
                if p in PROVIDER_KEY_ENV and isinstance(v, (str, int))}

    def _write(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def apply_to_env(self) -> None:
        """把已存 key 写进环境变量(以网页配置为准,覆盖)。"""
        for provider, env_name in PROVIDER_KEY_ENV.items():
            val = self._data.get(provider)
            if val:
                os.environ[env_name] = str(val)

    def get_masked(self) -> dict:
        """对外返回每个 provider 是否已配置(不回明文)。

        configured 综合判断:既看本 store,也看 env(允许用户仍用 .env 提供 key)。
        """
        out: dict = {}
        for provider, env_name in PROVIDER_KEY_ENV.items():
            stored = bool(self._data.get(provider))
            from_env = bool(os.environ.get(env_name, "").strip())
            out[provider] = {
                "env": env_name,
                "configured": stored or from_env,
                "key": _MASK if stored else "",
            }
        return out

    def update(self, values: dict) -> None:
        """更新一个或多个 provider 的 key。

        values 形如 {"deepseek": "sk-...", "openai": ""}。
        空串或 '******' 表示"不改动"(保留原值);其余写入并落盘。
        """
        changed = False
        for provider, key in (values or {}).items():
            if provider not in PROVIDER_KEY_ENV:
                continue
            key = "" if key is None else str(key).strip()
            if key == "" or key == _MASK:
                continue  # 不覆盖已存 key
            self._data[provider] = key
            changed = True
        if changed:
            self._write()
            self.apply_to_env()

    def clear(self, provider: str) -> bool:
        """显式删除某 provider 的 key(网页上的"移除"按钮用)。"""
        if provider in self._data:
            del self._data[provider]
            self._write()
            env_name = PROVIDER_KEY_ENV.get(provider)
            if env_name and os.environ.get(env_name):
                # 仅清除由本 store 注入的值;若用户另在 .env 配过,这里不强删 env。
                pass
            return True
        return False

    def is_configured(self, provider: str) -> bool:
        env_name = PROVIDER_KEY_ENV.get(provider, "")
        return bool(self._data.get(provider) or os.environ.get(env_name, "").strip())
