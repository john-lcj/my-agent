#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(node -e "console.log(require('$DESKTOP_ROOT/package.json').version)")"
TAG="${CAPTAIN_RELEASE_TAG:-v$VERSION}"
DMG_DIR="${CAPTAIN_DMG_DIR:-$DESKTOP_ROOT/src-tauri/target/release/bundle/dmg}"
OUT_DIR="${CAPTAIN_RELEASE_OUT_DIR:-$REPO_ROOT/release-assets/$TAG}"
NOTES_TEMPLATE="$REPO_ROOT/docs/RELEASE_NOTES_TEMPLATE.md"
NOTES_OUT="$OUT_DIR/RELEASE_NOTES.md"

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

info "生成发布说明草稿"
if [[ -f "$NOTES_TEMPLATE" ]]; then
  sed "s/{{VERSION}}/$VERSION/g; s/{{TAG}}/$TAG/g" "$NOTES_TEMPLATE" > "$NOTES_OUT"
else
  cat > "$NOTES_OUT" <<EOF
# Captain $VERSION

## 下载

- Apple Silicon: Captain_${VERSION}_arm64.dmg
- Intel Mac: Captain_${VERSION}_x86_64.dmg

## 校验

见 SHA256SUMS.txt
EOF
fi

ok "Release 资料已准备好: $OUT_DIR"
printf '\n下一步人工上传 GitHub Release:\n'
printf '  gh release create "%s" "%s/Captain_%s_arm64.dmg" "%s/Captain_%s_x86_64.dmg" "%s/SHA256SUMS.txt" --title "Captain %s" --notes-file "%s"\n' \
  "$TAG" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$VERSION" "$OUT_DIR" "$VERSION" "$NOTES_OUT"
