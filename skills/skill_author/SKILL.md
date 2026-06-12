---
name: skill_author
description: 新建技能的规范:放置目录、命名、格式、风险治理与去重原则
trigger: 写skill 创建技能 新建skill 做个skill 生成技能 skill怎么写
risk: READ
---

# skill_author —— 给本平台新建 skill 的规范(动手前必读)

当主人要你"写一个 skill / 创建一个技能"时,先读本规范再动手。目标:新 skill 风格统一、
走治理、不与现有能力重复、不破坏既有约定。

## 1. 放在哪

- **内置(优先)**:`<项目>/skills/<name>/` —— 随项目走、进版本库、被 CI 覆盖。
- **个人/临时**:`~/.agents/skills/<name>/` —— 只在本机生效,不进项目。
- 同名时内置优先(先发现先生效)。**别在用户目录放和内置同名/同功能的**,否则 UI 里会出现
  "一式两份"。

## 2. 命名

- 目录名 = `name` 字段,**全小写 + 下划线**(如 `csv_stats`、`file_edit`)。
- 不要用连字符(`my-skill`)——与现有约定不一致。

## 3. 目录结构与 SKILL.md

每个 skill 是一个目录,必含 `SKILL.md`(frontmatter + 正文):

```
---
name: <与目录同名,小写下划线>
description: <中文,正好 28 个字符>   # ★本项目硬约定:所有描述等长 28 字
trigger: <空格分隔的触发词,中英混写均可>
risk: READ | WRITE | DESTRUCTIVE | FORBIDDEN
---

# <name>
正文:给模型/人看的用法说明或工作流。
```

- `description` **必须是中文、且正好 28 字**(用脚本数,别凭感觉)。
- `risk` 如实标:只读=READ;改/写文件=WRITE;删除/危险命令/花钱/控屏=DESTRUCTIVE。

## 4. 两种类型

- **确定性工具型**:额外放 `impl.py`,定义
  `async def run(args: dict, ctx) -> CapabilityResult` 与 `SCHEMA`(参数 JSON Schema)。
  纯函数、确定性;异常要捕获并返回 `CapabilityResult(ok=False, error=...)`。
  扫描目录类要排除 `.venv/.git/__pycache__/logs` 并设结果上限。
- **指南型**:只放 `SKILL.md`(无 `impl.py`),正文就是 agent 要遵循的工作流/规范。

## 5. 风险与治理(关键,别漏)

- 带 `path` 参数的 skill 会**自动**受敏感路径硬边界保护(读写 `.env`/密钥会被拦)。
- **写文件/有副作用的 WRITE 类 skill**:除了标 `risk: WRITE`,还必须在
  `governance/policy.yaml` 的 `confirm.capabilities` 里加上 `skill.<name>`,否则会被自动放行
  (参考 `skill.file_edit`/`skill.file_append`)。
- DESTRUCTIVE 类默认就会要求确认,无需额外配置。

## 6. 先查重,不重复造

- 新建前先看现有能力(`/skills` 列表或 registry):**功能已有的别重做**。
- 能用现有工具组合完成的,优先组合,不新增 skill。
- 记忆相关**一律复用原生** `memory.remember` / `memory.recall`,**严禁**另造一套本地记忆
  store 或记忆 CLI(会与原生记忆冲突)。

## 7. 完成后自检

- [ ] 目录名、`name` 一致且小写下划线?
- [ ] `description` 是中文且正好 28 字?
- [ ] `risk` 标对?WRITE 写文件类是否已加入 `confirm.capabilities`?
- [ ] 与现有 skill/工具无重复?
- [ ] impl 异常已捕获、扫描类已排除噪声目录并设上限?
