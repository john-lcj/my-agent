#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DEST="${CAPTAIN_MACOS_APP_DEST:-$HOME/Applications/Captain.app}"
DMG_STAGE="$DESKTOP_ROOT/src-tauri/target/release/bundle/dmg/stage"
TARGETS="${CAPTAIN_MACOS_TARGETS:-$(uname -m)}"
VERSION="$(node -e "console.log(require('$DESKTOP_ROOT/package.json').version)")"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }
fail() { printf '\033[31mERROR\033[0m %s\n' "$1" >&2; exit 1; }

info "安装桌面依赖"
npm --prefix "$DESKTOP_ROOT" install

for raw_arch in $TARGETS; do
  case "$raw_arch" in
    arm64|aarch64) export CAPTAIN_MACOS_ARCH="aarch64"; RUST_TARGET="aarch64-apple-darwin"; DMG_ARCH="arm64" ;;
    x86_64|amd64) export CAPTAIN_MACOS_ARCH="x86_64"; RUST_TARGET="x86_64-apple-darwin"; DMG_ARCH="x86_64" ;;
    *) fail "不支持的 macOS 架构: $raw_arch" ;;
  esac
  DMG_DEST="$DESKTOP_ROOT/src-tauri/target/release/bundle/dmg/Captain_${VERSION}_${DMG_ARCH}.dmg"

  if [[ "$(uname -m)" != "$raw_arch" && "$(uname -m)" != "$DMG_ARCH" ]]; then
    rustup target add "$RUST_TARGET" >/dev/null 2>&1 || true
  fi

  info "准备 App 内置后端与 Python runtime ($DMG_ARCH)"
  npm --prefix "$DESKTOP_ROOT" run macos:prepare-bundle

  info "构建 macOS App ($DMG_ARCH)"
  if [[ "$(uname -m)" == "$raw_arch" || "$(uname -m)" == "$DMG_ARCH" ]]; then
    (cd "$DESKTOP_ROOT" && npx tauri build --bundles app)
    SOURCE_APP="$DESKTOP_ROOT/src-tauri/target/release/bundle/macos/Captain.app"
  else
    (cd "$DESKTOP_ROOT" && npx tauri build --target "$RUST_TARGET" --bundles app)
    SOURCE_APP="$DESKTOP_ROOT/src-tauri/target/$RUST_TARGET/release/bundle/macos/Captain.app"
  fi

  if [[ -d "$SOURCE_APP" ]]; then
    bash "$SCRIPT_DIR/sign-macos-app.sh" "$SOURCE_APP"

    if [[ "$DMG_ARCH" == "$(uname -m)" || ("$DMG_ARCH" == "arm64" && "$(uname -m)" == "arm64") ]]; then
      mkdir -p "$(dirname "$APP_DEST")"
      rm -rf "$APP_DEST"
      ditto "$SOURCE_APP" "$APP_DEST"
      ok "Captain.app 已安装到 $APP_DEST"
    fi

    info "创建 macOS DMG ($DMG_ARCH)"
    rm -rf "$DMG_STAGE"
    mkdir -p "$DMG_STAGE" "$(dirname "$DMG_DEST")"
    ditto "$SOURCE_APP" "$DMG_STAGE/Captain.app"
    ln -s /Applications "$DMG_STAGE/Applications"
    hdiutil create -volname "Captain" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_DEST"
    rm -rf "$DMG_STAGE"
    bash "$SCRIPT_DIR/notarize-macos-app.sh" "$SOURCE_APP" "$DMG_DEST"
    ok "DMG 已生成: $DMG_DEST"
  fi
done

printf '\n可直接运行:\n'
printf '  open "%s"\n' "$APP_DEST"
printf '\n可分发安装包:\n'
find "$DESKTOP_ROOT/src-tauri/target/release/bundle/dmg" "$DESKTOP_ROOT/src-tauri/target" -name "Captain_${VERSION}_*.dmg" 2>/dev/null | sed 's/^/  /'
