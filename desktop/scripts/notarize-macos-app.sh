#!/usr/bin/env bash
# Notarize and staple Captain.app + DMG when Apple credentials are available.
set -euo pipefail

APP_PATH="${1:-}"
DMG_PATH="${2:-}"

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "用法: notarize-macos-app.sh /path/to/Captain.app [path/to/Captain.dmg]" >&2
  exit 1
fi

APPLE_ID="${NOTARY_APPLE_ID:-}"
TEAM_ID="${NOTARY_TEAM_ID:-${APPLE_TEAM_ID:-}}"
KEYCHAIN_PROFILE="${NOTARY_KEYCHAIN_PROFILE:-Captain-notary}"

if [[ -z "$APPLE_ID" || -z "$TEAM_ID" ]]; then
  printf '\033[33mWARN\033[0m 未设置 NOTARY_APPLE_ID / NOTARY_TEAM_ID，跳过公证\n'
  exit 0
fi

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }

SUBMIT_PATH="$APP_PATH"
if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
  SUBMIT_PATH="$DMG_PATH"
fi

info "提交公证: $SUBMIT_PATH"
if [[ -n "${NOTARY_PASSWORD:-}" ]]; then
  xcrun notarytool submit "$SUBMIT_PATH" \
    --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$NOTARY_PASSWORD" \
    --wait
else
  xcrun notarytool submit "$SUBMIT_PATH" \
    --keychain-profile "$KEYCHAIN_PROFILE" \
    --wait
fi

info "staple App"
xcrun stapler staple "$APP_PATH"
if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
  info "staple DMG"
  xcrun stapler staple "$DMG_PATH"
fi
ok "公证完成"
