#!/usr/bin/env bash
# Sign a built Captain.app (Developer ID + embedded Python dylibs).
# Skips gracefully when APPLE_SIGNING_IDENTITY is unset.
set -euo pipefail

APP_PATH="${1:-}"
ENTITLEMENTS="${2:-}"

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "用法: sign-macos-app.sh /path/to/Captain.app [entitlements.plist]" >&2
  exit 1
fi

IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [[ -z "$IDENTITY" ]]; then
  printf '\033[33mWARN\033[0m 未设置 APPLE_SIGNING_IDENTITY，跳过代码签名\n'
  exit 0
fi

ENT="${ENTITLEMENTS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/entitlements/Captain.entitlements}"
SIGN_OPTS=(--force --options runtime --timestamp --entitlements "$ENT" --sign "$IDENTITY")

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }

info "签名内嵌 Python / dylib / so ($APP_PATH)"
while IFS= read -r -d '' bin; do
  codesign "${SIGN_OPTS[@]}" "$bin" 2>/dev/null || true
done < <(find "$APP_PATH" \( -name '*.dylib' -o -name '*.so' -o -name 'python*' \) -type f -print0)

info "签名 Captain.app"
codesign --deep --strict "${SIGN_OPTS[@]}" "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
printf '\033[32mOK\033[0m 签名完成: %s\n' "$APP_PATH"
