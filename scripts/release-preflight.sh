#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { printf '\033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }
ok() { printf '\033[32mOK\033[0m %s\n' "$1"; }

read_version() {
  local file="$1"
  local pattern="$2"
  grep -E "$pattern" "$file" | head -1 | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/' | sed -E 's/.*=\s*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/'
}

VERSION="$(tr -d '[:space:]' < VERSION)"
PYTHON="$(test -x .venv/bin/python && printf '%s' .venv/bin/python || command -v python3)"
"$PYTHON" scripts/check_version_contract.py --root "$ROOT" \
  || fail "版本契约校验失败"
PKG_VERSION="$(node -e "console.log(require('./desktop/package.json').version)")"
TAURI_VERSION="$(node -e "console.log(require('./desktop/src-tauri/tauri.conf.json').package.version)")"
CARGO_VERSION="$(grep '^version = ' desktop/src-tauri/Cargo.toml | head -1 | sed 's/version = "\(.*\)"/\1/')"
PY_VERSION="$(grep '^version = ' pyproject.toml | head -1 | sed 's/version = "\(.*\)"/\1/')"

[[ "$VERSION" == "$PKG_VERSION" ]] || fail "VERSION ($VERSION) != desktop/package.json ($PKG_VERSION)"
[[ "$VERSION" == "$TAURI_VERSION" ]] || fail "VERSION != tauri.conf.json ($TAURI_VERSION)"
[[ "$VERSION" == "$CARGO_VERSION" ]] || fail "VERSION != Cargo.toml ($CARGO_VERSION)"
[[ "$VERSION" == "$PY_VERSION" ]] || fail "VERSION != pyproject.toml ($PY_VERSION)"
ok "版本号一致: $VERSION"

if [[ -f CHANGELOG.md ]]; then
  grep -q "$VERSION" CHANGELOG.md || fail "CHANGELOG.md 缺少 $VERSION 条目"
  ok "CHANGELOG 含 $VERSION"
else
  printf '\033[33mWARN\033[0m 无 CHANGELOG.md，跳过条目检查\n'
fi

grep -q "Captain_${VERSION}_arm64.dmg" landing/index.html || fail "landing/index.html 未指向 Captain_${VERSION}_arm64.dmg"
grep -q "Captain_${VERSION}_x86_64.dmg" landing/index.html || fail "landing/index.html 未指向 Captain_${VERSION}_x86_64.dmg"
ok "landing 下载链接匹配 $VERSION"

if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -m pytest -q tests/ || fail "pytest 未通过"
  ok "pytest 全绿"
else
  python3 -m pytest -q tests/ || fail "pytest 未通过"
  ok "pytest 全绿"
fi

ok "release-preflight 全部通过，可以发版 $VERSION"
