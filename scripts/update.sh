#!/usr/bin/env bash
# Safe development-checkout updater. Packaged apps update through Tauri.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

fail() { printf 'ERROR %s\n' "$1" >&2; exit 1; }
ok() { printf 'OK %s\n' "$1"; }

[[ -d "$ROOT/.git" ]] || fail "This is not a development checkout; use the signed desktop updater."
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || fail "The checkout has local changes; commit or stash them before updating."

git -C "$ROOT" fetch --depth=1 origin main
LOCAL="$(git -C "$ROOT" rev-parse HEAD)"
REMOTE="$(git -C "$ROOT" rev-parse FETCH_HEAD)"
if [[ "$LOCAL" == "$REMOTE" ]]; then
  ok "Already current at ${LOCAL:0:12}"
  exit 0
fi
git -C "$ROOT" merge-base --is-ancestor "$LOCAL" "$REMOTE" \
  || fail "The remote branch is not a fast-forward update."
git -C "$ROOT" merge --ff-only "$REMOTE"

[[ -x "$PY" ]] || fail "Missing $PY"
"$PY" -m pip install -q -e "$ROOT[all]"
"$PY" "$ROOT/scripts/check_version_contract.py" --root "$ROOT"
TEST_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/captain-update-tests.XXXXXX")"
trap 'rm -rf "$TEST_LOG_DIR"' EXIT
AGENT_LOG_DIR="$TEST_LOG_DIR" "$PY" -m pytest -q "$ROOT/tests"
ok "Updated to ${REMOTE:0:12}; restart the development server to activate it."
