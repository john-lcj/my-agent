"""Agent 规格说明 —— 把"一个 agent 是什么"从代码里分离出来。

两种定义方式:
  YAML 文件  (agents/roster/*.yaml)  —— 简单 agent,配置即可
  Python 文件(agents/roster/*.py)   —— 进阶 agent,继承 WorkerAgent 添加自定义逻辑

YAML 格式示例:
  name: code_analyst
  role: 代码分析专家
  description: 擅长阅读代码结构、发现潜在问题
  capabilities:          # 能力白名单(fsread/fs.list 等前缀)
    - fs.read
    - fs.list
  llm: deepseek          # 可选,覆盖全局 provider
  auto_confirm: true     # 经 Dispatcher 分配的任务自动放行写操作
  system_prompt: |
    你是资深代码审查专家...
  trigger_keywords:      # 关键词兜底路由(LLM 失效时使用)
    - 分析代码
    - 代码审查

Python 格式:在文件顶部写 SPEC 字典(与 YAML 字段相同),并可定义
WorkerAgent 子类来覆盖任何行为。
"""
from __future__ import annotations

import os
import importlib.util
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentSpec:
    name: str
    role: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)   # 能力白名单前缀
    llm: str = ""                                            # 覆盖全局 provider
    auto_confirm: bool = True                                # 经 Dispatcher 分配的任务自动放行
    max_steps: int = 12                                      # 执行型 worker 默认步数上限
    system_prompt: str = ""
    trigger_keywords: list[str] = field(default_factory=list)
    source_file: str = ""                                    # 来源文件路径(调试用)
    python_class: Optional[type] = None                     # Python 扩展类(可选)


def load_specs_from_roster(roster_dir: str = "agents/roster") -> list[AgentSpec]:
    """扫描 roster 目录,加载所有 YAML / Python 格式的 agent 规格。"""
    if not os.path.isdir(roster_dir):
        return []
    specs: list[AgentSpec] = []
    for fname in sorted(os.listdir(roster_dir)):
        fpath = os.path.join(roster_dir, fname)
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            spec = _load_yaml_spec(fpath)
        elif fname.endswith(".py") and not fname.startswith("_"):
            spec = _load_python_spec(fpath)
        else:
            continue
        if spec is not None:
            specs.append(spec)
    return specs


def _expand_worker_prompt(text: str) -> str:
    from agents.worker_prompts import EXECUTION_WORKER_RULES
    return (text or "").replace("{{EXECUTION_RULES}}", EXECUTION_WORKER_RULES)


def _load_yaml_spec(path: str) -> Optional[AgentSpec]:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not data.get("name"):
            return None
        return AgentSpec(
            name=data["name"],
            role=data.get("role", data["name"]),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            llm=data.get("llm", ""),
            auto_confirm=data.get("auto_confirm", True),
            max_steps=int(data.get("max_steps", 12)),
            system_prompt=_expand_worker_prompt(data.get("system_prompt", "")),
            trigger_keywords=data.get("trigger_keywords", []),
            source_file=path,
        )
    except Exception as e:
        print(f"[spec] 加载 {path} 失败: {e}")
        return None


def _load_python_spec(path: str) -> Optional[AgentSpec]:
    """从 Python 文件加载:文件顶部必须有 SPEC 字典,可选定义 AgentClass。"""
    try:
        mod_name = f"_roster_{os.path.basename(path)[:-3]}"
        spec_obj = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(mod)
        data: dict = getattr(mod, "SPEC", {})
        if not data.get("name"):
            return None
        python_class = getattr(mod, "AgentClass", None)
        return AgentSpec(
            name=data["name"],
            role=data.get("role", data["name"]),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            llm=data.get("llm", ""),
            auto_confirm=data.get("auto_confirm", True),
            max_steps=int(data.get("max_steps", 12)),
            system_prompt=_expand_worker_prompt(data.get("system_prompt", "")),
            trigger_keywords=data.get("trigger_keywords", []),
            source_file=path,
            python_class=python_class,
        )
    except Exception as e:
        print(f"[spec] 加载 {path} 失败: {e}")
        return None
