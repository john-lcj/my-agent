# 连接器(Connectors)

把一个外部服务的接口用一份 JSON 描述清楚,Captain 启动时会自动把每个 action
注册成能力(名形如 `github.list_repos`),调用时从**加密保险库**按 `secret_ref`
取 token 组装鉴权头再发请求。新增一个连接器只需:

1. 在本目录放一份 `<name>.json`(见下方结构);
2. 在保险库存对应凭据:`secret.save name=<secret_ref> secret=<token>`
   (或在「自定义 · 连接器」面板里填),token 加密落盘、绝不明文外露;
3. 重启服务即可。`github.json` 是可参考的完整范例。

## JSON 结构

```json
{
  "name": "github",                       // 能力名前缀
  "label": "GitHub",                      // 展示名
  "base_url": "https://api.github.com",
  "auth": {"type": "bearer", "secret_ref": "github"},
  "default_headers": {"Accept": "application/vnd.github+json"},
  "actions": [
    {"name": "list_repos", "method": "GET", "path": "/user/repos",
     "description": "列出我的仓库", "query": ["per_page"]},
    {"name": "create_issue", "method": "POST", "path": "/repos/{owner}/{repo}/issues",
     "description": "新建 issue", "body": ["title", "body"]}
  ]
}
```

- 路径里的 `{占位符}` 会成为**必填**参数;`query` / `body` 字段为选填。
- 鉴权 `type`:`bearer`(Authorization: Bearer <token>)、`header`(自定义头名 `header`,
  可用 `template` 如 `"token {token}"`)、`basic`(用户名取保险库 username + 密码)、`none`。
- `GET/HEAD` 为只读(自动放行);其它写方法在 Chat 需确认、Cowork 自动放行。
