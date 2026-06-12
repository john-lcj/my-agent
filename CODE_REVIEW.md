# 代码审查报告 —— my agent 平台

审查日期:2026-06-12
审查范围:核心循环、治理、能力层、LLM 层、多 agent 编排、记忆、channels/server、测试。
方法:逐文件通读关键路径 + 运行回归测试(`tests/test_regression.py`)。

> 说明:本报告基于真实代码。channels/ 与 server/ 为快速扫描(非逐行),相关条目已标注"待核实"。

---

## 总体评价

架构成熟、分层干净,几个关键设计决策都做对了:

- **治理是循环里的硬关卡,不是 prompt 请求**(`core/loop.py` 中模型每次出招都必须先过 `policy.review_detailed`)。这是"分寸感"的正确物理位置。
- **统一能力收口**(`capabilities/base.py`):工具/skill/GUI/委托都收敛成一个 `Capability`,治理只有一个面要审。
- **机制与策略分离**(`governance/engine.py` + `policy.yaml`):改规则只动 YAML。
- **工具调用与结果严格配对**(每个 tool_call 无论放行/拒绝都补一条 tool 结果),避免 provider 400。
- **并行写资源锁 + 写前快照**,以及**按角色的能力白名单**,为多 agent 安全打了底。
- **确定性 MockLLM + 一套回归用例**(治理、鉴权、记忆、协调器都有覆盖)。

回归测试结果:**48/49 通过**。唯一失败是 GUI 截图用例,因为 `screencapture` 是 macOS 专有命令、在 Linux 环境跑不了——这是环境问题,不是代码缺陷(详见 P2-④)。

下面按严重度排序,**安全 > 正确性 > 设计/工程**。每条给出位置、问题、建议。

---

## P0 · 安全(优先处理)

### ① shell.run 可绕过机密文件保护
**位置**:`governance/engine.py` `review_detailed` 的 `forbidden_paths` 检查。
**问题**:敏感路径(`.env`/`id_rsa`/`credentials`/`.ssh/`)只对 `call.args["path"]` 匹配,而 `shell.run` 把命令放在 `args["command"]`。于是:

```
shell.run  "cat .env"            → 不命中 forbidden_path,也不命中任何 confirm 模式 → 直接 ALLOW 自动执行
shell.run  "cat ~/.ssh/id_rsa"   → 同上,自动读出私钥
```

机密保护对 shell 形同虚设,而 shell 恰恰是最容易读到任何文件的能力。
**建议**:把 `forbidden_paths` 也对 shell 命令文本(以及所有 args 值组成的 blob)做匹配;命令里出现 `.env`/`id_rsa`/`credentials` 即 BLOCK(或至少 ASK)。

### ② 硬边界 forbidden_patterns 是"会漏的黑名单"
**位置**:`governance/engine.py` / `policy.yaml` 的 `forbidden_patterns`。
**问题**:
- `rm\s+-rf` **不**匹配 `rm -fr`、`rm -r -f`、`rm --recursive --force`。这些只会落到 confirm 段的 `\brm\b`(ASK),对 `auto_confirm` 专家=自动放行=可删(见 ③)。
- 命令字符串可被轻易混淆绕过:`r''m -rf`、`$(echo rm) -rf`、`bash -c '...'`、base64 解码后执行等。
- 漏掉一些危险项:`> /dev/sda`(只挡了 `dd`/`mkfs`)、`shred`、`find . -delete`、`chmod -R 777 /`、`curl ... | sh`。
**定位要诚实**:对命令字符串做正则黑名单,是"防呆背书",**不是真正的沙箱**。真正的安全应来自:(a) 在受限环境/容器里跑 shell;(b) 最小权限白名单。
**建议**:补齐明显遗漏的模式;同时在文档/注释里讲清这层只是 backstop,主要安全依赖白名单 + 运行环境隔离。

### ③ auto_confirm 专家把人移出回路
**位置**:`agents/worker.py` `_make_confirm` → `auto_yes` 恒返回 True。
**问题**:被 Captain 升级/派发的专家若 `spec.auto_confirm=True`,其确认回调对**所有 ASK 一律放行**。硬边界 BLOCK 仍然生效,但凡是"仅需确认"的动作(`fs.write`、`shell.run` 的 mv/cp/sed/git/install……)都会**无人确认地执行**。`code_agent`、`data_analyst_agent` 的白名单含 `shell.run`+`fs.write`,意味着一个自治专家可以无人值守地跑 shell、写文件。此时仅剩两道防线:角色白名单 + ②里那张会漏的正则。这是无人值守自治里**风险最高的面**。
**建议**:即便 auto_confirm,也对"高危子集"(删除、网络安装、写系统路径、`>` 重定向)保留人工确认或更严的 deny;或把 `shell.run` 移出默认自治专家白名单,改用结构化工具暴露受控操作。
**好的一面**:`payment.` 未出现在任何角色白名单里,因此付费类对带角色的专家会被 BLOCK——这点是对的。

### ④ web.fetch 的 SSRF 防护可被绕过
**位置**:`capabilities/tools/web.py` `_url_allowed`。
**问题**:已有基础防护(挡 localhost / 内网网段),但:
- **不跟踪重定向**:一个公网 URL 通过 302 跳到 `http://169.254.169.254/`(云元数据)会被 urllib 自动跟随,而校验只发生在初始 URL。
- 只挡字面 IP/域名:解析到内网的**域名**、IPv6 `[::1]` / `[::ffff:127.0.0.1]`、十进制/十六进制 IP(`http://2130706433/` = 127.0.0.1)都能绕过。
**建议**:禁用自动重定向并对每一跳重新校验;先把主机解析成 IP 再判网段;覆盖 IPv6 与数字 IP 编码。

### ⑤ (待核实)server 的 /api/* 控制面与 webhook 鉴权
**位置**:`server/app.py`、`channels/*_channel.py`。
**问题**:
- `/api/config`(可写 channel 密钥)、`/api/tasks`、`/api/sessions`(可删)、`/api/rollback`、`/api/memory/preferences`(可删)等大量端点未见鉴权。若服务仅绑 `127.0.0.1` 风险有限;一旦对外暴露,即是无认证的完整控制面。
- Slack 渠道**有** HMAC 签名校验(很好),但 `if self.signing_secret and not verify(...)` ——**未配置 signing_secret 时校验被整段跳过**,等于接受任意未签名请求。telegram/qq/wechat 的 webhook 同样需核实。
**建议**:确认 bind host;非本机暴露时给 `/api/*` 加最简鉴权(本地 token);webhook 在缺密钥时应"拒绝"而非"跳过校验"。

---

## P1 · 正确性 / 可靠性

### ① Budget 只计 output,不计 input/prompt token —— 成本严重低估
**位置**:`core/loop.py`(只 `charge(text)` 和 `charge(intent)`)、`governance/budget.py`。
**问题**:agent 循环每轮把"全部历史 + 能力 specs"发给模型,**input 才是 token 大头**,却完全没计费。结果 token/金额统计严重偏低,`max_cost_usd` 刹车可被突破。
**建议**:`next_step` 前对 `ctx.llm_view()` + `registry.specs()` 估算 input token 并计费;更准的做法是用 provider 返回的 usage 字段。

### ② rollback 只覆盖 fs.write,shell 写不可回滚
**位置**:`core/loop.py`(仅对 `cap.risk>=WRITE` 且有 `path` 的调用快照)。
**问题**:`shell.run` 写文件(`echo > file`、`sed -i`、`mv`、`rm`)经确认后执行但**不快照**→ 不可回滚。"放手安全"的承诺窄于实现。
**建议**:至少在文档里说明回滚边界;或对高危 shell 做工作区级快照(成本高,可作为可选项)。

### ③ ResourceLock 字典无界增长
**位置**:`governance/resource_lock.py` `_get`。
**问题**:每个不同写路径建一把 `asyncio.Lock` 且**永不回收**,长跑会缓慢漏内存。`try_acquire` 里 `acquired` 变量取了没用。
**建议**:加 LRU/空闲清理;删掉无用变量。

---

## P2 · 设计 / 工程卫生

### ① EventBus 静默吞订阅者异常
**位置**:`core/bus.py` `publish` 的 `except Exception: pass`。订阅者(渲染/观测)出错被完全吞掉,开发期会让 bug 隐形。**建议**:至少把异常记到 tracer/stderr 一行。

### ② .env 还会从当前工作目录加载
**位置**:`config.py` 末尾 `load_env(os.getcwd()/.env)`。在他人目录下运行可能误读到非预期的 `.env`。低危,留意即可。

### ③ 仓库尚未提交,体积隐患
`git status` 显示所有文件均未跟踪(无 commit)。`.gitignore` 已存在但仓库还没初始化提交。**建议**:尽快 `git init` + 首次提交,并确认 `.gitignore` 忽略 `.venv/`(这是 Python 3.14 的虚拟环境,体积大,绝不该进库)、`logs/`、`.env`。

### ④ GUI 测试无平台守卫
**位置**:`tests/harness.py` 的 `_gui_screenshot_check`。依赖 macOS 专有 `screencapture`,在 Linux/CI 上必失败(本次 49→48 的唯一失败就是它)。**建议**:`@skipUnless(sys.platform=="darwin")` 或在 harness 探测后跳过,让 CI 干净。

---

## 建议的处理顺序

1. **P0-①(shell 读机密)** 与 **P0-③(auto_confirm 高危子集)**:改动小、收益最高,直接堵住最现实的越权路径。
2. **P0-②/④**:补齐黑名单与 SSRF;同时把"命令黑名单只是 backstop"写进文档,避免过度信任。
3. **P1-①(input 计费)**:接真实 provider 前必修,否则成本失控。
4. **P0-⑤**:核实 server bind host 与各 webhook 鉴权。
5. 其余 P1/P2 作为清理项分批做。

需要的话,我可以从 P0-① + P0-③ 开始,做成带测试的小补丁逐个交付。
