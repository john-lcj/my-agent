#!/usr/bin/env bash
# 开发目录 → 各运行端同步(App Support 运行时 + 桌面 bundle 资源)
# 用法: bash scripts/sync-all.sh [--restart]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUPPORT_APP="${CAPTAIN_MACOS_SUPPORT_DIR:-$HOME/Library/Application Support/Captain}/app"
BUNDLE_APP="$REPO_ROOT/desktop/src-tauri/resources/app"
DO_RESTART=0

for arg in "$@"; do
  case "$arg" in
    --restart) DO_RESTART=1 ;;
    -h|--help)
      echo "用法: bash scripts/sync-all.sh [--restart]"
      echo "  同步项目到 App Support 与 desktop bundle,不覆盖 .env/logs/.venv"
      echo "  --restart  若 8000 由 App Support 后端占用,同步后重启"
      exit 0
      ;;
  esac
done

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }

sync_tree() {
  local dest="$1"
  local label="$2"
  mkdir -p "$dest"
  info "同步 → $label"
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/stage_runtime.py" \
    --source "$REPO_ROOT" --destination "$dest" --preserve-state
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/build_bundle_stamp.py" \
    --root "$REPO_ROOT" --output "$dest/.captain_bundle_stamp" \
    --platform "macos-development" --trust "development"
  ok "$label"
}

sync_tree "$SUPPORT_APP" "App Support ($SUPPORT_APP)"
if [[ -x "$SUPPORT_APP/.venv/bin/python" ]]; then
  info "校验 App Support 运行依赖"
  "$SUPPORT_APP/.venv/bin/python" -m pip install -q -e "$SUPPORT_APP[all]"
  "$SUPPORT_APP/.venv/bin/python" -c "import fastapi, uvicorn, websockets; print('App Support runtime imports OK')"
fi

if [[ -d "$REPO_ROOT/desktop/src-tauri" ]]; then
  sync_tree "$BUNDLE_APP" "桌面 bundle ($BUNDLE_APP)"
fi

if [[ "$DO_RESTART" -eq 1 ]]; then
  LEGACY_PLIST="$HOME/Library/LaunchAgents/com.captain.backend.plist"
  if [[ -f "$LEGACY_PLIST" ]]; then
    info "移除旧的独立后端 LaunchAgent…"
    launchctl bootout "gui/$(id -u)/com.captain.backend" >/dev/null 2>&1 || true
    rm -f "$LEGACY_PLIST"
  fi
  # 先退出 Captain,避免与手动 nohup 叠两个后端(8000/8001 分裂)
  if pgrep -x Captain >/dev/null 2>&1; then
    info "退出 Captain.app…"
    osascript -e 'tell application "Captain" to quit' >/dev/null 2>&1 || true
    sleep 2
  fi
  for port in $(seq 8000 8099); do
    PID="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "$PID" ]] && continue
    CWD="$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    if [[ "$CWD" == *"Captain/app"* ]] || [[ "$CMD" == *"Captain/app"* ]] || [[ "$CMD" == *"server.app"* && "$CWD" == *"Captain"* ]]; then
      info "停止旧后端 pid $PID (port $port)"
      kill "$PID" 2>/dev/null || true
    fi
  done
  sleep 2
  CAPTAIN_APP=""
  if [[ -d "/Applications/Captain.app" ]]; then
    CAPTAIN_APP="/Applications/Captain.app"
  elif [[ -d "$HOME/Applications/Captain.app" ]]; then
    CAPTAIN_APP="$HOME/Applications/Captain.app"
  fi
  if [[ -n "$CAPTAIN_APP" ]]; then
    info "启动 Captain.app（桌面进程统一托管后端）"
    open "$CAPTAIN_APP"
    sleep 3
    if curl -sf http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
      ok "Captain 后端已重启 (8000)"
    else
      info "Captain 已启动，后端仍在初始化"
    fi
  elif [[ -x "$SUPPORT_APP/.venv/bin/python" ]]; then
    info "未安装 Captain.app，回退为单个 App Support 后端"
    (cd "$SUPPORT_APP" && nohup .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 >> logs/web-autostart.log 2>> logs/web-autostart.err.log &)
  else
    info "未找到 Captain.app 或 $SUPPORT_APP/.venv"
  fi
fi

ok "全端同步完成 (源: $REPO_ROOT)"
