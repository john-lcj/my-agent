# Captain License Server — VPS 部署指南

## 前提条件

- 一台 Linux VPS（1 核 1G 内存已够用，腾讯云/阿里云最便宜规格即可）
- 安装 Docker + Docker Compose
- 可选：一个域名，用于 HTTPS（推荐，否则客户端走 HTTP）

---

## 1. 安装 Docker（Ubuntu/Debian）

```bash
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# 重新登录后生效
```

---

## 2. 上传并启动

```bash
# 把 license_server/ 目录 scp 到 VPS
scp -r license_server/ root@YOUR_VPS_IP:~/captain-license/

# SSH 进 VPS
ssh root@YOUR_VPS_IP
cd ~/captain-license/

# 设置管理员 token（替换为强随机字符串！）
export ADMIN_TOKEN="$(openssl rand -hex 32)"
echo "ADMIN_TOKEN=$ADMIN_TOKEN" > .env
echo "保存好这个 token：$ADMIN_TOKEN"

# 启动
docker compose up -d

# 查看日志
docker compose logs -f
```

访问 `http://YOUR_VPS_IP:8080/healthz` 应返回 `{"ok": true, ...}`

---

## 3. 配置 Nginx + HTTPS（推荐）

```nginx
# /etc/nginx/sites-available/captain-license
server {
    listen 80;
    server_name license.your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name license.your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/license.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/license.your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# 申请证书（certbot）
apt install certbot python3-certbot-nginx -y
certbot --nginx -d license.your-domain.com

# 启用配置
ln -s /etc/nginx/sites-available/captain-license /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

配好后，把 `license_client/client.py` 里的 `_DEFAULT_SERVER` 改为
`https://license.your-domain.com`

---

## 4. 日常运维命令

```bash
cd ~/captain-license/

# 查看状态
docker compose ps

# 重启
docker compose restart

# 更新镜像后重建
docker compose up -d --build

# 进入容器调试
docker compose exec license bash

# 备份数据库
docker compose exec license cat /data/license.db > backup_$(date +%F).db
```

---

## 5. 管理 API

所有管理接口需要请求头 `X-Admin-Token: YOUR_ADMIN_TOKEN`

### 生成授权码

```bash
# 生成 3 个年付 Pro key
curl -X POST http://localhost:8080/api/license/generate \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","months":12,"n":3,"note":"batch-2025-01"}'

# 返回示例：
# {"ok":true,"keys":["CAPT-PRO-A1B2-C3D4-E5F6",...],"expires_at":1767225600}
```

```bash
# 生成月付 key
curl -X POST http://localhost:8080/api/license/generate \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","months":1,"n":1,"note":"monthly"}'
```

### 查看所有 key

```bash
curl http://localhost:8080/api/license/list \
  -H "X-Admin-Token: $ADMIN_TOKEN" | python3 -m json.tool
```

---

## 6. 收款 → 发码自动化（初期半自动流程）

1. 买家扫码付款，备注邮箱
2. 微信/支付宝收到付款通知
3. 你运行以下命令生成 1 个 key 并发邮件：

```bash
# 生成单个 key
KEY=$(curl -s -X POST http://localhost:8080/api/license/generate \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","months":12,"n":1}' | python3 -c "import sys,json; print(json.load(sys.stdin)['keys'][0])")

echo "授权码: $KEY"

# 然后手动发邮件/微信给买家
```

> Day 5 会实现收款回调 + 自动发码。

---

## 7. 防火墙

仅开放必要端口：

```bash
ufw allow 22    # SSH
ufw allow 80    # HTTP（Nginx）
ufw allow 443   # HTTPS（Nginx）
# 不需要直接暴露 8080，Nginx 反代即可
ufw enable
```

---

## 故障排查

| 问题 | 检查 |
|------|------|
| 健康检查失败 | `docker compose logs license` 查看启动错误 |
| 激活返回 403 | 检查 ADMIN_TOKEN 是否设置正确 |
| 证书过期 | `certbot renew --dry-run` 测试，确认 cron 自动续期 |
| 数据库损坏 | 从备份恢复：`docker compose down && cp backup.db data/license.db && docker compose up -d` |
