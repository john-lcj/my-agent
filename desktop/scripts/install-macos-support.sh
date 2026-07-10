#!/usr/bin/env bash
set -euo pipefail

SUPPORT_ROOT="${CAPTAIN_MACOS_SUPPORT_DIR:-$HOME/Library/Application Support/Captain}"
APP_ROOT="$SUPPORT_ROOT/app"
REPO_URL="${CAPTAIN_REPO_URL:-https://github.com/john-lcj/my-agent.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }
warn() { printf '\033[33mWARN\033[0m %s\n' "$1"; }
fail() { printf '\033[31mERROR\033[0m %s\n' "$1" >&2; exit 1; }

keychain_get() {
  security find-generic-password -s club.irestart.captain -a "$1" -w 2>/dev/null || true
}

keychain_set() {
  security add-generic-password -U -s club.irestart.captain -a "$1" -w "$2" >/dev/null 2>&1
}

ensure_keychain_secret() {
  local account="$1"
  local value
  value="$(keychain_get "$account")"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi
  value="$("$APP_ROOT/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  if keychain_set "$account" "$value"; then
    printf '%s\n' "$value"
    return 0
  fi
  return 1
}

python_cmd() {
  if command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' "python3.12"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    if python3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 10) and sys.version_info[:2] <= (3, 12) else 1)
PY
    then
      printf '%s\n' "python3"
      return
    fi
  fi
  fail "需要 Python 3.10-3.12。建议运行: brew install python@3.12"
}

copy_from_repo() {
  local src="$1"
  info "同步后端到 $APP_ROOT"
  python3 "$src/scripts/stage_runtime.py" \
    --source "$src" --destination "$APP_ROOT" --preserve-state
  python3 "$src/scripts/build_bundle_stamp.py" \
    --root "$src" --output "$APP_ROOT/.captain_bundle_stamp" \
    --platform "macos-development" --trust "development"
}

clone_or_update() {
  info "从 GitHub 准备后端源码"
  if [[ -d "$APP_ROOT/.git" ]]; then
    git -C "$APP_ROOT" fetch --depth=1 origin main
    git -C "$APP_ROOT" reset --hard FETCH_HEAD
  else
    rm -rf "$APP_ROOT"
    git clone --depth=1 "$REPO_URL" "$APP_ROOT"
  fi
}

ensure_env() {
  local env_file="$APP_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    ensure_keychain_secret "env:AUTH_SECRET" >/dev/null 2>&1 || true
    ensure_keychain_secret "env:AGENT_API_TOKEN" >/dev/null 2>&1 || true
    ok ".env 已存在"
    return
  fi
  info "生成 macOS 本机 .env"
  local auth_secret
  local api_token
  if auth_secret="$(ensure_keychain_secret "env:AUTH_SECRET")" \
     && api_token="$(ensure_keychain_secret "env:AGENT_API_TOKEN")"; then
    cat > "$env_file" <<EOF
# Captain macOS local config
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek-v4-flash
AGENT_WEB_PORT=8000
AGENT_WORKSPACE_ROOT=$HOME
CAPTAIN_USE_KEYCHAIN=1
CAPTAIN_LICENSE_KEY=
# AUTH_SECRET and AGENT_API_TOKEN are stored in macOS Keychain.

# Fill your model key before using real models.
DEEPSEEK_API_KEY=
EOF
  else
    warn "Keychain 写入失败,回退到 .env 保存本机 secret"
    auth_secret="$("$APP_ROOT/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
    api_token="$("$APP_ROOT/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
    cat > "$env_file" <<EOF
# Captain macOS local config
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek-v4-flash
AGENT_WEB_PORT=8000
AGENT_WORKSPACE_ROOT=$HOME
AUTH_SECRET=$auth_secret
AGENT_API_TOKEN=$api_token
CAPTAIN_LICENSE_KEY=

# Fill your model key before using real models.
DEEPSEEK_API_KEY=
EOF
  fi
  chmod 600 "$env_file"
  ok ".env 已生成: $env_file"
}

install_python_env() {
  local py
  py="$(python_cmd)"
  info "创建/更新 Python 环境 ($py)"
  "$py" -m venv "$APP_ROOT/.venv"
  "$APP_ROOT/.venv/bin/python" -m pip install -U pip
  "$APP_ROOT/.venv/bin/python" -m pip install -e "$APP_ROOT[all]"
  ok "Python 环境已就绪"
}

if [[ -f "$REPO_ROOT/server/app.py" ]]; then
  copy_from_repo "$REPO_ROOT"
else
  clone_or_update
fi

install_python_env
ensure_env

LEGACY_PLIST="$HOME/Library/LaunchAgents/com.captain.backend.plist"
if [[ -f "$LEGACY_PLIST" ]]; then
  warn "移除旧的独立后端 LaunchAgent，由 Captain.app 统一托管后端"
  launchctl bootout "gui/$(id -u)/com.captain.backend" >/dev/null 2>&1 || true
  rm -f "$LEGACY_PLIST"
fi

ok "macOS 支持目录已准备好: $APP_ROOT"
printf '\n下一步可运行:\n'
printf '  cd "%s/desktop" && npm run build\n' "$APP_ROOT"
printf '或在开发仓库运行:\n'
printf '  cd "%s/desktop" && npm run macos:package\n' "$REPO_ROOT"
