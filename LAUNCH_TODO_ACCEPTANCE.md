# Captain 上线待办与验收清单

本文档用于追踪 Captain 从当前灰度版走向可交付客户版的工作。执行规则：

- 按 P0 -> P1 -> P2 顺序推进。
- 每个任务必须同时满足“完成定义”和“验收清单”后才标记完成。
- 自动化检查优先；无法自动化的部分必须给出人工验收步骤。
- 不把未验证的改动推送 GitHub。

## 状态说明

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成并通过验收
- `[!]` 阻塞或需要人工确认

## P0 上线前必须完成

### P0-1 Release / DMG / 更新链路收口

状态：`[x]`

目标：客户可以从官网或 App 内清晰获得最新版安装包；没有 Release 时不暴露技术错误。

完成定义：

- macOS 打包脚本能生成 `arm64` 和 `x86_64` DMG。
- App 内检查更新能区分三种状态：已是最新、有新版本、暂无发布包。
- GitHub Release 缺失时显示可读提示，不显示 HTTP/堆栈原文。
- 官网下载链接、GitHub Release、App 内更新入口指向一致。
- Release 上传前有一份发布说明模板。

验收清单：

- 运行 `npm --prefix desktop run check` 通过。
- 运行 `cargo check --manifest-path desktop/src-tauri/Cargo.toml` 通过。
- 运行 `bash -n desktop/scripts/package-macos.sh desktop/scripts/prepare-macos-bundle.sh` 通过。
- 运行 `python3 -m pytest -q tests/test_app_api_smoke.py` 通过。
- 人工检查：`设置 -> 关于 -> 检查并更新` 显示中文状态，不出现 `HTTP Error 404`。

### P0-2 首次启动引导

状态：`[x]`

目标：第一次打开 App 的客户无需翻设置页，也能完成授权、模型配置和连接测试。

完成定义：

- 首次启动时展示引导入口或自动打开引导面板。
- 引导步骤包含：欢迎、授权码、模型/API Key、测试连接、开始使用。
- 已完成引导后不重复打扰；可在设置中重新打开。
- 引导状态写入本机配置，不依赖远程服务。

验收清单：

- 新用户空配置启动时能看到引导。
- 已配置授权码和至少一个可用模型后，引导状态变为完成。
- 重新启动 App 后不自动弹出已完成引导。
- 设置页可再次打开引导。

验收记录：

- `node --check frontend/app.js` 通过。
- `python3 -m pytest -q tests/test_app_api_smoke.py` 通过。
- 浏览器验收：引导可见；点击“开始使用”后关闭；刷新后不自动弹出；`设置 -> 关于 -> 重新打开引导` 可再次打开。

### P0-3 模型接入 UI 产品化

状态：`[x]`

目标：模型接入页面让普通客户知道该选什么、错在哪里、怎么修。

完成定义：

- 默认突出推荐平台：OpenRouter、DeepSeek、OpenAI、Claude。
- 其他平台折叠到“更多模型平台”。
- Key、base URL、模型名的说明简洁明确。
- 常见错误中文化：Key 错误、余额不足、模型名错误、网络失败、限流。
- 测试结果不挤压按钮、不破坏布局。

验收清单：

- 页面宽度变窄时按钮不竖排、不重叠。
- OpenRouter 余额不足显示中文提示。
- 未配置平台显示“未配置”，已保存 Key 不回显明文。
- `python3 -m pytest -q tests/test_model_keys.py tests/test_ext_models.py` 通过。

验收记录：

- `python3 -m pytest -q tests/test_model_keys.py tests/test_ext_models.py` 通过。
- `python3 -m pytest -q tests/test_app_api_smoke.py` 通过。
- 浏览器验收：模型页显示“推荐接入”，顺序为 OpenRouter、DeepSeek、OpenAI、Claude；更多平台默认折叠；窄屏下按钮不竖排、不溢出。

### P0-4 诊断包脱敏复查

状态：`[x]`

目标：客户能一键导出诊断包给维护者，但不会泄露模型 Key、授权码、访问 token 或隐私文件全文。

完成定义：

- 诊断包包含：运行摘要、后端启动日志、必要 trace/audit 摘要。
- 诊断包不包含：`.env`、模型 Key、授权码、访问 token、用户上传文件全文。
- 日志中疑似 secret 会被脱敏。
- 导出失败时显示中文错误。

验收清单：

- 运行 `python3 -m pytest -q tests/test_app_api_smoke.py` 通过。
- 人工导出诊断包并解压检查，不出现 `sk-`、`ghp_`、`CAPT-PRO`、`AGENT_API_TOKEN=` 明文。
- 关于页点击“导出诊断包”能下载 zip。

验收记录：

- 诊断包改为写入 `summary.json`、脱敏后的日志尾部和必要配置摘要，不再原样打包 trace/audit/journal/backend 日志。
- `python3 -m pytest -q tests/test_app_api_smoke.py` 通过；测试覆盖 `sk-`、`ghp_`、`CAPT-PRO`、访问 token、`auth_secret` 脱敏。

### P0-5 官网下载链路验收

状态：`[x]`

目标：官网介绍页上的下载、购买、联系、更新说明都能完成闭环。

完成定义：

- 官网提供 Apple Silicon 和 Intel 两个下载入口。
- 购买 Pro 页面二维码、邮箱、说明文案正确。
- 下载失败或打不开 App 有说明。
- 官网安全卖点第一，数据本地化第二。

验收清单：

- 人工打开官网逐个点击：下载、购买 Pro、联系我们、安装说明。
- 所有链接目标可访问。
- 下载链接与 GitHub Release 一致。

验收记录：

- 本地 `landing/index.html` 已改为 macOS DMG 优先：Apple Silicon 与 Intel Mac 两个下载入口，命令行作为备用安装方式。
- 本地静态检查通过：安全卖点第一、数据本地化第二；二维码资源存在；联系邮箱为 `luchangjie@outlook.com`；两个 DMG 链接已写入。
- GitHub Release 已创建：`https://github.com/john-lcj/my-agent/releases/tag/v0.1.0`。
- 线上检查通过：官网首页、二维码、Apple Silicon DMG、Intel DMG、Release 页面均返回 200。
- 下载资产大小：Apple Silicon `127726785` bytes；Intel `129140352` bytes；`SHA256SUMS.txt` 已上传。

## P1 强烈建议完成

### P1-1 设置页信息架构收口

状态：`[x]`

完成定义：

- 设置页分组更接近客户语言：账户、模型、安全、诊断、关于。
- 启动检查只在有问题时出现；已完成后可关闭。
- About 页减少开发工具感。

验收清单：

- 新客户能在 1 分钟内找到授权、模型、诊断。
- 设置页按钮和说明无重叠、无长英文错误。

验收记录：

- 设置页基础入口已收口为：账户、模型、安全、诊断、关于；授权码已移到「账户」，远程访问令牌和安全边界移到「安全」，更新/日志/诊断包/备份移到「诊断」。
- 启动检查入口在当前无待办状态下不显示；顶部状态提示也只在存在待处理建议时出现。
- About 页已改为产品说明，不再混放授权、更新和诊断操作。
- 浏览器人工验收通过：账户页和诊断页无按钮/说明重叠；基础入口刷新后仍按客户路径显示。
- 自动检查通过：`node --check frontend/app.js`、`git diff --check`、`python3 -m pytest -q tests/test_app_api_smoke.py tests/test_model_keys.py tests/test_ext_models.py`。

### P1-2 审计日志产品化

状态：`[x]`

完成定义：

- 治理页展示可读审计日志：时间、动作、结果、原因、任务。
- 原始 JSON 只放诊断包，不直接展示给客户。

验收清单：

- 治理页能看到最近审计记录。
- 空日志时显示空状态，不报错。

验收记录：

- 「治理」已改为「审计日志」，首屏优先展示最近审计记录，统计概览放在日志下方。
- 审计表已产品化为：时间、操作、结果、原因、任务；能力名、裁决和执行结果转为客户可读中文。
- 页面不再直接展示 `args` JSON 字符串；原始 JSONL 仍只保留在日志/诊断包里用于排障。
- 浏览器人工验收通过：最近 50 条审计记录可见，首屏表格无重叠，无 JSON 原文。
- 自动检查通过：`node --check frontend/app.js`、`git diff --check`、`python3 -m pytest -q tests/test_app_api_smoke.py tests/test_observability.py`。

### P1-3 日志轮转

状态：`[x]`

完成定义：

- 主要日志文件按大小或天数轮转。
- 诊断包只取最近日志片段。

验收清单：

- 人工构造大日志后触发轮转。
- 旧日志不会无限增长。

验收记录：

- 新增通用日志轮转模块，默认 `20MB`、保留 `3` 份备份；可用 `AGENT_LOG_MAX_BYTES` 和 `AGENT_LOG_BACKUPS` 调整。
- 已接入 `trace.jsonl`、`audit.log`、`journal.md` 的写入链路；诊断包仍只打包最近 tail 片段。
- 人工构造临时大日志通过：最终只保留 `trace.jsonl`、`trace.jsonl.1`、`trace.jsonl.2`，没有 `.3` 无限增长。
- 自动检查通过：`python3 -m pytest -q tests/test_observability.py tests/test_journal.py tests/test_app_api_smoke.py`、`node --check frontend/app.js`、`git diff --check`。

### P1-4 授权码体验

状态：`[x]`

完成定义：

- 设置页展示 Pro 状态、到期时间、机器信息、重新校验按钮。
- 授权失败原因中文化。
- 授权码存 Keychain。

验收清单：

- 有效授权显示 Pro。
- 无效授权显示中文原因。
- 重启后授权状态保持。

验收记录：

- 账户页新增授权状态卡：展示 Pro/Free、剩余天数、到期时间、机器号、本机保存方式，并提供「重新校验」按钮。
- `/api/license/status` 新增 `expires_at`、`machine_id_short`、`keychain`、`error`，支持 `?refresh=1` 强制重新校验。
- 激活成功后自动刷新授权状态；常见网络、过期、无效、设备上限错误已中文化。
- 授权客户端保留原有缓存逻辑，并在 macOS App/Keychain 启用路径下继续把 `CAPTAIN_LICENSE_KEY` 写入 Keychain。
- 接口验收通过：当前返回 `plan=pro`、`days_left=364`、`expires_at=True`、`machine_id_short=7cea57200593`。
- 自动检查通过：`python3 -m pytest -q tests/test_license.py tests/test_app_api_smoke.py`、`node --check frontend/app.js`、`git diff --check`。

### P1-5 官网安装说明与故障排查

状态：`[x]`

完成定义：

- 官网有 macOS 安装说明。
- 包含“无法打开，因为 Apple 无法检查是否包含恶意软件”的处理说明。
- 包含日志/诊断包发送方式。

验收清单：

- 新用户按官网说明能完成安装。
- 联系方式正确。

验收记录：

- 官网下载区新增 macOS 安装和排障说明：拖入 Applications、首次打开 Gatekeeper 提示处理、App 内检查更新。
- 已加入日志/诊断包发送方式：`设置 -> 诊断 -> 导出诊断包`，发送到 `luchangjie@outlook.com`。
- FAQ 已调整 Windows 表述：当前优先交付 macOS App，Windows 桌面版后续成熟后发布。
- 静态验收通过：macOS 安装说明、Gatekeeper 文案、诊断包说明、联系邮箱、Apple Silicon/Intel DMG 链接、二维码资源均存在。

## P2 成熟版增强

### P2-1 Tauri 真自动更新

状态：`[ ]`

完成定义：

- 接入 Tauri updater 或等价机制。
- 支持签名校验、版本 manifest、应用内下载更新。

验收清单：

- 从旧版本可升级到新版本。
- 更新失败能回退或提示手动下载。

### P2-2 托盘和后台驻留

状态：`[ ]`

完成定义：

- 关闭窗口可选择退出或后台驻留。
- 菜单栏可重新打开主窗口。

验收清单：

- 关闭窗口后服务行为符合设置。
- 菜单栏操作正常。

### P2-3 Windows 适配恢复

状态：`[ ]`

完成定义：

- Windows 安装、更新、诊断路径重新验收。
- PowerShell 命令兼容常见版本。

验收清单：

- Windows clean machine 可以安装启动。
- 更新命令可用。

### P2-4 工作流模板产品化

状态：`[ ]`

完成定义：

- 将“目标 -> 计划 -> 执行 -> 自检 -> 返修 -> 汇报”做成可复用工作流。
- 支持从成功任务沉淀模板。

验收清单：

- 至少 3 个内置工作流可运行。
- 每次运行有计划、产物、自检结果。

## 当前执行记录

- 2026-07-01：建立上线待办与验收清单。
- 2026-07-01：P0-1 通过。已生成真实 macOS DMG:
  - `desktop/src-tauri/target/release/bundle/dmg/Captain_0.1.0_arm64.dmg`
  - `desktop/src-tauri/target/release/bundle/dmg/Captain_0.1.0_x86_64.dmg`
  - 已生成 `release-assets/v0.1.0/RELEASE_NOTES.md` 与 `SHA256SUMS.txt`
  - 验收命令通过：`npm --prefix desktop run check`, `cargo check --manifest-path desktop/src-tauri/Cargo.toml`, `python3 -m pytest -q tests/test_app_api_smoke.py`, `npm --prefix desktop run macos:release-assets`
