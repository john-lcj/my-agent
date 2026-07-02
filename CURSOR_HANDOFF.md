# Cursor Handoff - Captain

Date: 2026-07-02

## Current State

Captain is being prepared as a customer-facing macOS-first desktop AI Agent app. P0 and P1 launch-hardening work is complete in this branch.

GitHub remote:

- `origin`: `https://github.com/john-lcj/my-agent.git`
- branch: `main`

Live marketing site:

- `https://irestart-your-life.club/`

Release already created:

- `https://github.com/john-lcj/my-agent/releases/tag/v0.1.0`
- Assets include Apple Silicon and Intel DMGs plus `SHA256SUMS.txt`.

## Completed In This Handoff

### P1-1 Settings Information Architecture

- Settings nav now uses customer-facing groups and entries:
  - Account
  - Models
  - Security
  - Diagnostics
  - About
- License activation moved to Account.
- Remote access token and safety boundary settings moved to Security.
- Update, logs, diagnostics export, and backup moved to Diagnostics.
- About page now reads as product information instead of a developer toolbox.
- Startup check is hidden when there are no pending warnings.

Key files:

- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`

### P1-2 Audit Log Productization

- Governance page is now customer-facing Audit Log.
- Recent audit records are shown first, before stats.
- Table columns are:
  - time
  - action
  - result
  - reason
  - task
- Raw `args` JSON is no longer displayed on the customer page.
- Raw JSONL remains in logs/diagnostic package for support use.

Key files:

- `frontend/app.js`
- `frontend/index.html`
- `frontend/styles.css`

### P1-3 Log Rotation

- Added `observability/log_rotation.py`.
- Size-based rotation defaults:
  - `AGENT_LOG_MAX_BYTES`: defaults to 20 MB
  - `AGENT_LOG_BACKUPS`: defaults to 3
- Integrated rotation into:
  - `trace.jsonl`
  - `audit.log`
  - `journal.md`
- Diagnostics package still exports only recent tail snippets.

Key files:

- `observability/log_rotation.py`
- `observability/trace.py`
- `observability/audit.py`
- `memory/journal.py`
- `tests/test_observability.py`

### P1-4 License UX

- Account page now has a license status card:
  - plan
  - days left
  - expiry date
  - machine id short
  - local storage mode
  - recheck button
- `/api/license/status` now returns:
  - `expires_at`
  - `machine_id`
  - `machine_id_short`
  - `keychain`
  - `error`
- `/api/license/status?refresh=1` forces recheck.
- Common license errors are translated into customer-facing Chinese text.
- License client now supports `check_license(force=True)`.
- Keychain write path remains in `license_client/client.py` via `CAPTAIN_LICENSE_KEY` when macOS App/Keychain path is active.

Key files:

- `server/routers/license.py`
- `license_client/client.py`
- `frontend/app.js`
- `frontend/index.html`
- `frontend/styles.css`

### P1-5 Website Install And Troubleshooting

- Landing page now includes:
  - macOS DMG install instructions
  - Gatekeeper warning instructions for unsigned test build
  - update/reinstall guidance
  - diagnostics package support instructions
  - support email: `luchangjie@outlook.com`
- Windows wording was softened: macOS App is current priority; Windows desktop is later.

Key file:

- `landing/index.html`

## Verification Already Run

Latest full P1 verification:

```bash
node --check frontend/app.js
git diff --check
python3 -m pytest -q tests/test_app_api_smoke.py tests/test_model_keys.py tests/test_ext_models.py tests/test_observability.py tests/test_journal.py tests/test_license.py
npm --prefix desktop run check
```

Results:

- Python tests: `51 passed, 1 warning`
- Desktop prereq check: OK for project root, Node, npm, Python 3.12, Rust, Cargo
- Frontend JS syntax: OK
- Diff whitespace check: OK

Manual/browser checks done during implementation:

- Account page visually showed license panel without overlap.
- Diagnostics page grouped update/logs/diagnostics/backup.
- Audit log page showed readable rows and no raw JSON.
- Landing page static checks confirmed Gatekeeper, diagnostics, email, Apple Silicon DMG and Intel DMG links.

## Important Notes

- Current product direction is macOS-first. Windows compatibility exists in older scripts but should not be treated as ready customer desktop support.
- macOS DMGs are currently unsigned/unnotarized unless signing/notarization is added later. The website now explains the Gatekeeper workaround.
- License status may show `keychain=false` in a local development repo. In packaged macOS App data path or with `CAPTAIN_USE_KEYCHAIN=1`, Keychain logic should be active.
- Do not commit generated release assets or local app data. `release-assets/` is ignored.
- The `.env` and any model keys must not be committed.

## Recommended Next Work

### P2-1 Real Tauri Auto Update

Current update flow opens release/download manually. Mature version should use Tauri updater or an equivalent signed manifest.

Suggested acceptance:

- Version manifest with signature/checksum.
- App can detect a newer version.
- App can download/install or guide user reliably.
- Failure path has clear fallback.

### P2-2 Tray And Background Resident Mode

Add macOS menu bar/tray behavior:

- keep backend running in background
- quick open app/logs/diagnostics
- quit/restart service

### P2-3 Crash And Diagnostics Polish

Diagnostics exists, but customer-grade polish should include:

- clear backend startup failure reason
- one-click copy support summary
- visible current log path
- port conflict messaging and auto-recovery

### P2-4 Packaging Maturity

Before broad customer delivery:

- code signing decision
- notarization decision
- universal DMG or clearer separate architecture download UX
- installer/uninstaller story

### P2-5 UI Polish

Suggested areas:

- Settings footer currently always shows Refresh/Save even on read-only pages.
- Account license card can show current email/customer id if license server provides it later.
- Audit log can add filters: failed only, blocked only, tool/action.
- Model provider cards can be made more compact for smaller screens.

## Useful Commands

Run app backend:

```bash
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Run main tests:

```bash
python3 -m pytest -q tests/test_app_api_smoke.py tests/test_model_keys.py tests/test_ext_models.py tests/test_observability.py tests/test_journal.py tests/test_license.py
```

Desktop prereq check:

```bash
npm --prefix desktop run check
```

Package macOS bundle scripts are under:

```bash
desktop/scripts/
```

## Files Changed In P1

- `LAUNCH_TODO_ACCEPTANCE.md`
- `frontend/app.js`
- `frontend/index.html`
- `frontend/styles.css`
- `landing/index.html`
- `license_client/client.py`
- `memory/journal.py`
- `observability/audit.py`
- `observability/log_rotation.py`
- `observability/trace.py`
- `server/routers/license.py`
- `tests/test_observability.py`
