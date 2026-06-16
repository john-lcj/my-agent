---
name: http_request
description: 发起HTTP请求,支持GET与POST并解析JSON返回
trigger: api 接口 http 请求 调用 webhook 查询
risk: WRITE
---

# http_request

调用任意 HTTP API(REST/Webhook 等),让 agent 能"接资源"——查第三方接口、调企业数据库 API、触发 Webhook。
默认带 SSRF 防护(拒绝内网/本地地址)。

输入参数:
- `url`(string,必填):请求地址(http/https)。
- `method`(string,可选):GET/POST/PUT/DELETE,默认 GET。
- `headers`(object,可选):请求头(如鉴权 Authorization)。
- `params`(object,可选):URL 查询参数。
- `json`(object,可选):POST/PUT 的 JSON body。
- `timeout`(number,可选):超时秒数,默认 20。

输出:状态码 + 响应(JSON 自动解析,否则截断文本)。风险 WRITE:可能写远端/外发,默认需确认。
