# 前端契约(Cursor 改前端前必读)

> 目的:界面/排版/交互**随便重写**,但**这些"接线点"不能动**,否则后端功能会断。
> 改完后由 Claude 跑回归 + 逐条核对本表。只要本表全绿,就算改成功。

---

## 1. WebSocket `/ws`

- 连接地址带 token:`/ws?token=<AGENT_API_TOKEN>`(本机可空)。**保留 `getAccessToken()` 取 token 的逻辑**(localStorage key = `agentApiToken`)。
- **前端发出**(`ws.send(JSON.stringify({...}))`)的 `type` 必须保持以下字段名不变:

| type | 必带字段 | 说明 |
|---|---|---|
| `init` | `session_id`, `model`, `mode` | 连上后第一条;`mode` ∈ `chat`/`code`/`coworker`,后端据此设 `ctx.coworker` |
| `user` | `text` | 普通消息 |
| `approval` | `approved`(bool), 关联 id | 确认弹窗的回应 |
| `rollback` | — | 回滚上一轮 |
| `task_stop` | — | 停止当前任务 |
| `roundtable_start` / `roundtable_user_speak` / `roundtable_stop` | 见原实现 | 圆桌/辩论模式 |

- **前端接收**:按 `data.type`(代码里叫 `etype`)分发。以下事件**必须继续被处理**(可改样式,不能丢):
  `assistant_token`(流式增量,要逐字追加)、`assistant_message`、`user_message`、`history`、`plan_update`(喂给 `wb-progress` 清单)、`status_bar`、`error`、`approval_request`、`capability_call`、`capability_result`、`governance_decision`、`task_done`、`rollback_result`,以及圆桌系列 `rt_*` / `debate_*`。

## 2. REST API(路径/方法不能改)

所有 `/api/*` 请求经过统一 fetch 包装,自动加 `X-Agent-Token` 头——**保留这个 fetch 包装**(index.html ~1169 行)。

- `GET/POST/PATCH/DELETE /api/projects`(`/api/projects/{id}`)— 项目增删改查
- `GET /api/sessions`、`GET /api/sessions/search?q=`、会话改名/设项目走 `/api/sessions/...`
- `POST /api/artifact` — 产物预览(`openArtifact` 用)
- `GET /api/files?dir=<相对路径>` — 工作区文件树(右侧"项目文件",`loadFiles` 用;后端有越界拦截,前端只传相对路径)
- `POST /api/upload` — **JSON + base64**,不是 multipart。字段:文件名 + base64 内容
- `GET /api/config`、`/api/models`(在 config 内)、`/api/keys`、`/api/channels`、`/api/channels/email/test`、`/api/tasks`、`/api/agents/roster`、`/api/commands`、`/api/skills`、`/api/usage`、`/api/governance/stats`、`/api/roundtable/presets`
- `GET /healthz`、`/manifest.json`

## 3. 必须保留的 DOM id(JS 按 id 取元素)

容器可换标签/样式/位置,但 **id 名不变**:

- 聊天区:`chat-messages`、`chat-inp`、`chat-empty`
- 工作台:`workbench`、`wb-plan`、`wb-progress`、`wb-files`、`wb-artifacts`
- 侧栏:`sb-backdrop`(移动端遮罩)

## 4. 必须保留的函数名(或保留等价调用关系)

`connectWS`、`sendMessage`、`openArtifact`、`loadFiles`、`wbHandlePlan`、`onProjectChange`、`createProjectPrompt`、`getAccessToken`。
> 可以重构内部实现,但**事件→函数**的触发链要在,且 `plan_update` 事件最终要落到 `wb-progress` 的勾选清单(✔/◔/○/✘)。

## 5. 红线

- 不要把 token 逻辑去掉(否则远程/手机访问全挂)。
- 不要把 `/api/upload` 改回 multipart(后端没装 python-multipart)。
- 不要在 URL query 里塞用户数据(token 走 ws 是既定例外)。
- 不引外部 JS/CSS CDN(离线也要能用),除非先跟我确认。

---

改完把 diff 给我,我跑 `python -m pytest`(当前 83 passed/1 skipped,必须仍绿)+ `node --check` JS 语法 + 照上表核对接线。
