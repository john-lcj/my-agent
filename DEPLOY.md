# 部署到一台新电脑(开机自启 · 后台常驻)

目标:把项目拷到任意一台电脑,跑一条命令,就完成「装环境 + 装依赖 + 开机自启 + 后台运行」。
之后手机经 Tailscale 随时连(见 `CONNECT_PHONE.md`)。

> 前置:装好 **Python 3.10+**;手机远程用的话装好 **Tailscale**(两端同账号)。

## macOS

```bash
cd "<项目目录>"
bash scripts/install.sh
```

做了:建 `.venv` → 装依赖 → 装 LaunchAgent(登录自启 + 崩溃自动拉起)→ 启动。
卸载自启:`bash scripts/uninstall-autostart.sh`。

## Windows

在项目目录的 PowerShell 里:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

做了:建 `.venv` → 装依赖 → 注册计划任务 `MyAgentWeb`(登录自启,用 `pythonw` 后台静默运行)→ 立即启动。
卸载自启:`powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1`。

## 装完必配(两个平台一样)

编辑项目根的 `.env`:

```
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=...              # 你的模型 key
AGENT_WORKSPACE_ROOT=<本机项目绝对路径>   # 安全:把读写锁在工作区内
AGENT_WEB_HOST=0.0.0.0            # 手机经 Tailscale 连必需
AGENT_API_TOKEN=<随机串>          # 远程访问密码,手机上输一次
```

改完 `.env` 后让自启重新加载:macOS 重跑 `bash scripts/install-autostart.sh`;Windows 重跑 `install.ps1`(或在「任务计划程序」里重启 MyAgentWeb)。

## 说明
- **后台常驻**:服务随登录启动、崩溃自动重启;机器需开机并登录到桌面(agent 在本机干活,电脑得醒着)。
- **不弹窗**:Windows 用 `pythonw` 静默运行;若仍偶发控制台窗口,可在「任务计划程序」把该任务改为「不管用户是否登录都运行」。
- **健康检查**:浏览器开 `http://localhost:8000/healthz` 看是否 `ok`。
