---
name: notify_dispatch
description: 统一推送至 email/wechat/qq；未配置凭证时返回可手动发送的文稿。
trigger: 推送 发送 通知 邮件 企微
risk: WRITE
---

# notify_dispatch

运营推送专用。封装 notify.email / notify.wechat / notify.qq。

输入参数:
- `channel`(string, 必填): `email` | `wechat` | `qq`
- `to`(string, 必填): 收件人/企微 UserId/QQ channel_id 或 group_openid
- `body`(string, 必填): 正文
- `subject`(string, 可选): 邮件主题(email 时建议填写)
- `group_openid`(string, 可选): QQ 群 openid(qq 渠道)
