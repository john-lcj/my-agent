#!/usr/bin/env bash
# Generate Tauri updater latest.json + signed .app.tar.gz bundles.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(node -e "console.log(require('$DESKTOP_ROOT/package.json').version)")"
TAG="${CAPTAIN_RELEASE_TAG:-v$VERSION}"
DMG_DIR="${CAPTAIN_DMG_DIR:-$DESKTOP_ROOT/src-tauri/target/release/bundle/dmg}"
OUT_DIR="${CAPTAIN_RELEASE_OUT_DIR:-$REPO_ROOT/release-assets/$TAG}"
NOTES_OUT="$OUT_DIR/RELEASE_NOTES.txt"
UPDATER_KEY="${TAURI_PRIVATE_KEY:-$HOME/.captain-updater.key}"
UPDATER_PASS="${TAURI_KEY_PASSWORD:-captain-updater-dev}"
GITHUB_REPO="${CAPTAIN_GITHUB_REPO:-john-lcj/my-agent}"
BASE_URL="https://github.com/${GITHUB_REPO}/releases/download/${TAG}"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }
fail() { printf '\033[31mERROR\033[0m %s\n' "$1" >&2; exit 1; }

mkdir -p "$OUT_DIR"

arm_dmg="$DMG_DIR/Captain_${VERSION}_arm64.dmg"
intel_dmg="$DMG_DIR/Captain_${VERSION}_x86_64.dmg"

[[ -f "$arm_dmg" ]] || fail "缺少 Apple Silicon DMG: $arm_dmg。请先运行 CAPTAIN_MACOS_TARGETS=\"arm64 x86_64\" npm run macos:package"
[[ -f "$intel_dmg" ]] || fail "缺少 Intel DMG: $intel_dmg。请先运行 CAPTAIN_MACOS_TARGETS=\"arm64 x86_64\" npm run macos:package"

info "复制 DMG 到 release-assets/$TAG"
cp -f "$arm_dmg" "$OUT_DIR/"
cp -f "$intel_dmg" "$OUT_DIR/"

info "生成 SHA256SUMS.txt"
(cd "$OUT_DIR" && shasum -a 256 "Captain_${VERSION}_arm64.dmg" "Captain_${VERSION}_x86_64.dmg" > SHA256SUMS.txt)

make_updater_bundle() {
  local arch="$1"
  local dmg="$2"
  local mount="$OUT_DIR/.mount_${arch}"
  local app="$mount/Captain.app"
  local tgz="$OUT_DIR/Captain_${VERSION}_${arch}.app.tar.gz"
  local sig_file="$OUT_DIR/Captain_${VERSION}_${arch}.app.tar.gz.sig"

  info "生成 updater .app.tar.gz (${arch})" >&2
  rm -rf "$mount"
  mkdir -p "$mount"
  hdiutil attach "$dmg" -mountpoint "$mount" -nobrowse -quiet
  codesign --verify --deep --strict "$app" \
    || fail "${arch} App code signature verification failed"
  stamp="$(find "$app/Contents/Resources" -name .captain_bundle_stamp -type f -print -quit)"
  [[ -n "$stamp" ]] || fail "${arch} App 缺少 .captain_bundle_stamp"
  python3 "$REPO_ROOT/scripts/check_bundle_stamp.py" "$stamp" \
    --version "$VERSION" --trust platform-signed \
    || fail "${arch} bundle identity verification failed"
  tar -czf "$tgz" -C "$app" .
  hdiutil detach "$mount" -quiet
  rm -rf "$mount"

  if [[ -f "$UPDATER_KEY" ]]; then
    (cd "$DESKTOP_ROOT" && npx tauri signer sign "$tgz" --private-key-path "$UPDATER_KEY" -p "$UPDATER_PASS")
  else
    fail "缺少 updater 私钥: $UPDATER_KEY"
  fi
}

make_updater_bundle arm64 "$arm_dmg"
arm_sig="$(cat "$OUT_DIR/Captain_${VERSION}_arm64.app.tar.gz.sig")"

make_updater_bundle x86_64 "$intel_dmg"
intel_sig="$(cat "$OUT_DIR/Captain_${VERSION}_x86_64.app.tar.gz.sig")"

PUB_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
NOTES="Captain ${VERSION} — macOS 桌面版更新。"

info "生成 latest.json"
node -e "
const fs = require('fs');
const out = process.argv[1];
const payload = {
  version: process.argv[2],
  contract_version: 1,
  bundle_schema: 1,
  commit: process.argv[8],
  notes: process.argv[3],
  pub_date: process.argv[4],
  platforms: {
    'darwin-aarch64': {
      signature: process.argv[5],
      url: process.argv[6] + '/Captain_' + process.argv[2] + '_arm64.app.tar.gz',
    },
    'darwin-x86_64': {
      signature: process.argv[7],
      url: process.argv[6] + '/Captain_' + process.argv[2] + '_x86_64.app.tar.gz',
    },
  },
};
fs.writeFileSync(out, JSON.stringify(payload, null, 2) + '\n');
" "$OUT_DIR/latest.json" "$VERSION" "$NOTES" "$PUB_DATE" "$arm_sig" "$BASE_URL" "$intel_sig" "$(git -C "$REPO_ROOT" rev-parse HEAD)"

info "生成发布说明草稿"
cat > "$NOTES_OUT" <<EOF
Captain $VERSION

Downloads

- Apple Silicon: Captain_${VERSION}_arm64.dmg
- Intel Mac: Captain_${VERSION}_x86_64.dmg

Checksums

See SHA256SUMS.txt.
EOF

ok "Release 资料已准备好: $OUT_DIR"
printf '\n下一步上传 GitHub Release:\n'
printf '  gh release create "%s" "%s/Captain_%s_arm64.dmg" "%s/Captain_%s_x86_64.dmg" "%s/Captain_%s_arm64.app.tar.gz" "%s/Captain_%s_x86_64.app.tar.gz" "%s/SHA256SUMS.txt" "%s/latest.json" --title "Captain %s" --notes-file "%s"\n' \
  "$TAG" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$OUT_DIR" "$VERSION" "$NOTES_OUT"
