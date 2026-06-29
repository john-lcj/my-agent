#!/usr/bin/env bash
# ============================================================
#  Captain — 一键安装脚本
#  用法:
#    curl -fsSL https://raw.githubusercontent.com/john-lcj/my-agent/main/install.sh | bash
#  或者 clone 后本地执行:
#    bash install.sh
# ============================================================
set -euo pipefail

REPO_URL="https://github.com/john-lcj/my-agent.git"
INSTALL_DIR="$HOME/captain"
VENV_DIR="$INSTALL_DIR/.venv"
ENV_FILE="$INSTALL_DIR/.env"
MIN_PYTHON="3.10"

# ── 颜色 ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▶${RESET}  $*"; }
success() { echo -e "${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()     { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }

# ── 检测操作系统 ──────────────────────────────────────────────
detect_os() {
    case "$(uname -s)" in
        Darwin)  OS="macos" ;;
        Linux)   OS="linux" ;;
        *)       die "暂不支持 $(uname -s)，请在 macOS 或 Linux 上运行" ;;
    esac
}

# ── 确保 Homebrew 存在（macOS）───────────────────────────────
ensure_brew() {
    if ! command -v brew &>/dev/null; then
        info "未检测到 Homebrew，正在安装（需要输入密码）..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Apple Silicon 路径
        [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
        # Intel 路径
        [[ -f /usr/local/bin/brew ]] && eval "$(/usr/local/bin/brew shellenv)"
        success "Homebrew 安装完成"
    fi
}

# ── 检测 / 自动安装 Python ────────────────────────────────────
detect_python() {
    for cmd in python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" &>/dev/null; then
            VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            MAJ="${VER%%.*}"; MIN="${VER#*.}"
            if [[ "$MAJ" -ge 3 && "$MIN" -ge 10 ]]; then
                PYTHON_CMD="$cmd"
                info "检测到 Python $VER ($cmd)"
                return 0
            fi
        fi
    done

    warn "未找到 Python 3.10+，尝试自动安装..."
    if [[ "$OS" == "macos" ]]; then
        ensure_brew
        brew install python@3.11
        PYTHON_CMD="$(brew --prefix)/bin/python3.11"
        [[ -x "$PYTHON_CMD" ]] || PYTHON_CMD="python3.11"
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y python3.11 python3.11-venv python3-pip
        PYTHON_CMD="python3.11"
    elif command -v yum &>/dev/null; then
        sudo yum install -y python311 python311-pip
        PYTHON_CMD="python3.11"
    else
        die "无法自动安装 Python，请手动安装 Python 3.10+：https://www.python.org/downloads/"
    fi

    if ! command -v "$PYTHON_CMD" &>/dev/null; then
        die "Python 安装失败，请手动安装：https://www.python.org/downloads/"
    fi
    success "Python 已安装：$($PYTHON_CMD --version)"
}

# ── 检测 / 自动安装 git ───────────────────────────────────────
detect_git() {
    if command -v git &>/dev/null; then
        return 0
    fi
    warn "未找到 git，尝试自动安装..."
    if [[ "$OS" == "macos" ]]; then
        # macOS: xcode-select --install 会弹窗，优先用 brew
        ensure_brew
        brew install git
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y git
    elif command -v yum &>/dev/null; then
        sudo yum install -y git
    else
        die "无法自动安装 git，请手动安装后重试"
    fi
    command -v git &>/dev/null || die "git 安装失败，请手动安装后重试"
    success "git 已安装：$(git --version)"
}

# ── 下载或更新代码 ────────────────────────────────────────────
clone_or_update() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        warn "检测到已有安装目录，执行 git pull 更新..."
        cd "$INSTALL_DIR"
        git pull --ff-only || warn "更新失败，继续使用当前版本"
    else
        info "正在下载 Captain..."
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
        success "代码已下载到 $INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
}

# ── 创建虚拟环境 & 安装依赖 ───────────────────────────────────
setup_venv() {
    info "创建 Python 虚拟环境..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    info "安装依赖（首次可能需要 1-2 分钟）..."
    pip install --quiet --upgrade pip
    if [[ -f "requirements.txt" ]]; then
        pip install --quiet -r requirements.txt
    fi
    success "依赖安装完成"
}

# ── 生成 .env 模板 ────────────────────────────────────────────
setup_env() {
    if [[ -f "$ENV_FILE" ]]; then
        warn ".env 已存在，跳过（如需重置请手动删除 $ENV_FILE）"
        return
    fi
    info "生成 .env 配置模板..."
    cat > "$ENV_FILE" << 'EOF'
# ============================================================
#  Captain 配置文件  —  请填写以下内容后保存
#  文件路径：~/captain/.env
# ============================================================

# ── LLM API Key（至少填一个）──────────────────────────────────
# DeepSeek（推荐，性价比最高）
DEEPSEEK_API_KEY=sk-xxx

# OpenAI（可选）
# OPENAI_API_KEY=sk-xxx

# Anthropic Claude（可选）
# ANTHROPIC_API_KEY=sk-ant-xxx

# ── 默认使用的模型 ────────────────────────────────────────────
# 选项: deepseek/deepseek-chat | openai/gpt-4o | anthropic/claude-3-5-sonnet
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek/deepseek-chat

# ── Pro 授权码（留空则以 Free 版运行）────────────────────────
CAPTAIN_LICENSE_KEY=

# ── 服务端口（默认 8765）──────────────────────────────────────
AGENT_PORT=8765

# ── WebSocket 接入令牌（可自定义，保持随机即可）──────────────
AGENT_API_TOKEN=change-me-to-random-string

# ── 日志 & 数据目录（默认 ~/captain/logs）────────────────────
# LOG_DIR=~/captain/logs
EOF
    success ".env 模板已生成：$ENV_FILE"
}

# ── 创建启动脚本 ──────────────────────────────────────────────
create_launcher() {
    LAUNCHER="$INSTALL_DIR/captain.sh"
    cat > "$LAUNCHER" << SCRIPT
#!/usr/bin/env bash
# Captain 启动脚本
set -euo pipefail
cd "$INSTALL_DIR"
source "$VENV_DIR/bin/activate"
exec python server/app.py "\$@"
SCRIPT
    chmod +x "$LAUNCHER"

    # macOS: 也在 /usr/local/bin 放一个软链（需要权限时跳过）
    if [[ "$OS" == "macos" ]]; then
        if [[ -w "/usr/local/bin" ]] || sudo -n true 2>/dev/null; then
            sudo ln -sf "$LAUNCHER" /usr/local/bin/captain 2>/dev/null || true
            success "已创建命令 'captain'，可在任意目录运行"
        fi
    fi
}

# ── macOS: 创建 launchd plist（开机自启，可选）───────────────
create_macos_service() {
    PLIST_PATH="$HOME/Library/LaunchAgents/com.captain-ai.agent.plist"
    [[ -f "$PLIST_PATH" ]] && return   # 已存在则跳过
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>com.captain-ai.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>$INSTALL_DIR/server/app.py</string>
    </array>
    <key>WorkingDirectory</key>  <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:$VENV_DIR/bin</string>
    </dict>
    <key>RunAtLoad</key>         <false/>
    <key>KeepAlive</key>         <false/>
    <key>StandardOutPath</key>   <string>$INSTALL_DIR/logs/agent.log</string>
    <key>StandardErrorPath</key> <string>$INSTALL_DIR/logs/agent_err.log</string>
</dict>
</plist>
PLIST
    mkdir -p "$INSTALL_DIR/logs"
    info "已生成 macOS LaunchAgent（默认不自启，需要时运行）："
    info "  launchctl load $PLIST_PATH    # 启动"
    info "  launchctl unload $PLIST_PATH  # 停止"
}

# ── Linux: 生成 systemd user service ────────────────────────
create_linux_service() {
    SERVICE_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_DIR/captain.service" << SERVICE
[Unit]
Description=Captain AI Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/server/app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:$INSTALL_DIR/logs/agent.log
StandardError=append:$INSTALL_DIR/logs/agent_err.log

[Install]
WantedBy=default.target
SERVICE
    mkdir -p "$INSTALL_DIR/logs"
    info "已生成 systemd user service，开机自启命令："
    info "  systemctl --user enable captain && systemctl --user start captain"
}

# ── 打印完成信息 ──────────────────────────────────────────────
print_done() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}║        Captain 安装完成 🎉             ║${RESET}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "  ${BOLD}第 1 步：填写 API Key${RESET}"
    echo    "    编辑 $ENV_FILE"
    echo    "    填入 DEEPSEEK_API_KEY（或 OPENAI_API_KEY）"
    echo ""
    echo -e "  ${BOLD}第 2 步：启动 Captain${RESET}"
    echo    "    cd $INSTALL_DIR"
    echo    "    bash captain.sh"
    echo    "    浏览器打开 http://localhost:8765"
    echo ""
    echo -e "  ${BOLD}第 3 步（可选）：激活 Pro${RESET}"
    echo    "    python -m license_client.cli activate CAPT-PRO-XXXX-XXXX-XXXX"
    echo ""
    echo -e "  ${CYAN}购买 Pro：https://irestart-your-life.club/#pricing${RESET}"
    echo ""
}

# ── 主流程 ────────────────────────────────────────────────────
main() {
    header "⚡ Captain 安装程序"
    detect_os
    detect_git
    detect_python
    clone_or_update
    setup_venv
    setup_env
    create_launcher
    if [[ "$OS" == "macos" ]]; then
        create_macos_service
    else
        create_linux_service
    fi
    print_done
}

main "$@"
