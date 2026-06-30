# 部署到一台新电脑(开机自启 · 后台常驻)

目标:把项目拷到任意一台电脑,跑一条命令,就完成「装环境 + 装依赖 + 开机自启 + 后台运行」。
之后手机经 Tailscale 随时连(见 `CONNECT_PHONE.md`)。

> 前置:装好 **Python 3.10+**;手机远程用的话装好 **Tailscale**(两端同账号)。

## macOS

```bash
curl -fsSL https://irestart-your-life.club/install.sh | bash
```

做了:建 `.venv` → 装依赖 → 装 LaunchAgent(登录自启 + 崩溃自动拉起)→ 启动。
本地源码目录内也可运行项目根目录的 `install.sh`。

## Windows

在项目目录的 PowerShell 里:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$u = "https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1"; $p = Join-Path $env:TEMP "captain-install.ps1"; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile($u, $p); powershell -NoProfile -ExecutionPolicy Bypass -File $p'
```

做了:安装 Portable Python + Portable Git → 拉取代码 → 装依赖 → 生成 `captain.bat`/桌面快捷方式 → 启动。
已安装后的备用更新命令:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$u = "https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1"; $p = Join-Path $env:TEMP "captain-install.ps1"; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile($u, $p); powershell -NoProfile -ExecutionPolicy Bypass -File $p -UpdateOnly'
```

## 装完必配(两个平台一样)

编辑项目根的 `.env`:

```
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=...              # 你的模型 key
AGENT_WORKSPACE_ROOT=<本机项目绝对路径>   # 安全:把读写锁在工作区内
AGENT_WEB_HOST=0.0.0.0            # 手机经 Tailscale 连必需
AGENT_API_TOKEN=<随机串>          # 远程访问密码,手机上输一次
```

改完 `.env` 后重启服务:macOS 重新运行启动命令;Windows 双击桌面 Captain 或运行 `captain.bat`。

## 说明
- **后台常驻**:服务随登录启动、崩溃自动重启;机器需开机并登录到桌面(agent 在本机干活,电脑得醒着)。
- **不弹窗**:Windows 用 `pythonw` 静默运行;若仍偶发控制台窗口,可在「任务计划程序」把该任务改为「不管用户是否登录都运行」。
- **健康检查**:浏览器开 `http://localhost:8000/healthz` 看是否 `ok`。
