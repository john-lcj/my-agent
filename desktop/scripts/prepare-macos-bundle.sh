#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RESOURCE_APP="$DESKTOP_ROOT/src-tauri/resources/app"
CACHE_ROOT="${CAPTAIN_MACOS_CACHE_DIR:-$HOME/Library/Caches/Captain}"
PY_RUNTIME="$RESOURCE_APP/runtime/python"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }
fail() { printf '\033[31mERROR\033[0m %s\n' "$1" >&2; exit 1; }

arch_name() {
  local raw="${CAPTAIN_MACOS_ARCH:-$(uname -m)}"
  case "$raw" in
    arm64|aarch64) printf '%s\n' "aarch64" ;;
    x86_64|amd64) printf '%s\n' "x86_64" ;;
    *) fail "不支持的 macOS 架构: $raw" ;;
  esac
}

download_python_runtime() {
  local arch
  local meta
  local asset
  local url
  local tarball
  arch="$(arch_name)"
  mkdir -p "$CACHE_ROOT/python"
  meta="$CACHE_ROOT/python/python-build-standalone-latest.json"

  info "解析 Python standalone runtime ($arch)"
  python3 - "$meta" "$arch" "$CACHE_ROOT/python" <<'PY'
import json
import os
import re
import sys
import urllib.request

meta_path, arch, cache_dir = sys.argv[1], sys.argv[2], sys.argv[3]
pattern = re.compile(
    rf"^cpython-3\.12\.\d+\+\d+-{re.escape(arch)}-apple-darwin-install_only\.tar\.gz$"
)

matches = []
try:
    url = "https://api.github.com/repos/indygreg/python-build-standalone/releases/latest"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    matches = [
        {"name": asset["name"], "url": asset["browser_download_url"]}
        for asset in data.get("assets", [])
        if pattern.match(asset.get("name", ""))
    ]
except Exception as exc:
    print(f"[prepare-macos-bundle] GitHub latest lookup failed, trying local cache: {exc}", file=sys.stderr)
    cached = sorted(name for name in os.listdir(cache_dir) if pattern.match(name))
    if cached:
        matches = [{"name": cached[-1], "url": ""}]

if not matches:
    raise SystemExit(f"No matching python-build-standalone asset for {arch}")

with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(matches[0], f)
PY

  asset="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$meta")"
  url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$meta")"
  tarball="$CACHE_ROOT/python/$asset"

  if [[ ! -f "$tarball" ]]; then
    [[ -n "$url" ]] || fail "缺少 Python runtime 缓存且无法联网解析下载地址: $asset"
    info "下载 Python runtime: $asset"
    curl -L --fail --retry 3 -o "$tarball" "$url"
  else
    ok "Python runtime 缓存已存在"
  fi

  rm -rf "$PY_RUNTIME"
  mkdir -p "$RESOURCE_APP/runtime"
  info "解压 Python runtime"
  tar -xzf "$tarball" -C "$RESOURCE_APP/runtime"
  if [[ ! -x "$PY_RUNTIME/bin/python3" ]]; then
    fail "Python runtime 解压失败: $PY_RUNTIME/bin/python3 不存在"
  fi
}

sync_backend_source() {
  info "准备 App 内置后端资源"
  python3 "$REPO_ROOT/scripts/stage_runtime.py" \
    --source "$REPO_ROOT" \
    --destination "$RESOURCE_APP"
}

write_bundle_stamp() {
  python3 "$REPO_ROOT/scripts/build_bundle_stamp.py" \
    --root "$REPO_ROOT" \
    --output "$RESOURCE_APP/.captain_bundle_stamp" \
    --platform "macos-$(arch_name)" \
    --trust "${CAPTAIN_BUNDLE_TRUST:-development}"
}

install_python_dependencies() {
  info "安装 Python 依赖到内置 runtime"
  "$PY_RUNTIME/bin/python3" -m ensurepip --upgrade
  "$PY_RUNTIME/bin/python3" -m pip install -U pip
  "$PY_RUNTIME/bin/python3" -m pip install --no-warn-script-location "$RESOURCE_APP[all]"
  "$PY_RUNTIME/bin/python3" -c "import fastapi, uvicorn, server.app; print('embedded backend import ok')"
  find "$PY_RUNTIME/lib/python3.12/site-packages" \
    \( -type d -name tests -o -type d -name test -o -type d -name __pycache__ \) \
    -prune -exec rm -rf {} +
  find "$RESOURCE_APP" -type d -name __pycache__ -prune -exec rm -rf {} +
  rm -rf "$RESOURCE_APP/build" "$RESOURCE_APP"/*.egg-info
  ok "内置 Python runtime 已就绪"
}

sync_backend_source
if [[ "${CAPTAIN_SKIP_RUNTIME:-0}" != "1" ]]; then
  download_python_runtime
  install_python_dependencies
fi
write_bundle_stamp

ok "App 内置资源已准备好: $RESOURCE_APP"
