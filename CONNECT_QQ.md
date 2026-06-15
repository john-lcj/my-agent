# 把 QQ 接到 Captain(个人号 · 扫码即连)

目标:你的 QQ 个人号扫个码,就能在 QQ 里直接和 Captain 对话。中间所有脏活由脚本和 agent 干,你只动两下手。

> 走的是 **OneBot v11 + NapCat** 这条业界通用路子(LangBot / AstrBot 同款)。
> NapCat 是非官方实现(基于新版 QQ 内核),**有封号风险,建议先拿小号试**。

## 三步走

**第 1 步:起 NapCat(它负责扫码登录 + 暴露接口)**

```bash
bash scripts/napcat-up.sh
```

需要本机装了 Docker。脚本会起好容器,并把接口开在 `ws://127.0.0.1:3001`。

**第 2 步:扫码登录 QQ**

打开 http://localhost:6099 ,用**手机 QQ** 扫码登录。登录态会缓存,以后免扫。
（首次进管理页要的 token 在日志里:`docker logs napcat-myagent | grep -i token`)

进去后确认"网络配置"里有一条 **正向 WebSocket** 开在 `3001`,记下它的 access token。

**第 3 步:让 Captain 连上**

在项目根 `.env` 里加这几行(token 跟第 2 步一致),再启动 `myagent-web`:

```
ONEBOT_ENABLE=1
ONEBOT_WS_URL=ws://127.0.0.1:3001
ONEBOT_ACCESS_TOKEN=<第2步那个token>
QQ_MASTER_UIN=<你自己的QQ号>
```

启动后,用**另一个 QQ**(或让朋友)给你这个登录的号发消息,Captain 就会回复。
群里则需要 **@这个机器人** 才会应答(防刷屏)。

## 说明

- `QQ_MASTER_UIN` 很重要:设了之后**只听你这个号的指令**,别人发消息不会驱使你的 agent。强烈建议设。
- 高危/花钱类操作,Captain 会在 QQ 里发"需要确认",你回 `y 确认码` 放行、`n 确认码` 拒绝。
- 断线会自动重连;NapCat 容器 `--restart unless-stopped`,开机自启。
- 卸载:`docker rm -f napcat-myagent`。
