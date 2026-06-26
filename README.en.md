# my-agent · Captain

[中文](README.md) · **English**

A **personal AI agent platform** built with a sense of restraint — local-first, self-hosted, model-agnostic (DeepSeek / Zhipu / OpenAI / Claude / Ollama).

Design philosophy in one line: **a focused loop, strict governance, full observability, safe autonomy.**
Aggressive about process (reads / thinks / tries on its own), conservative about decisions (only comes back to ask before delete / overwrite / spend / anything irreversible).

> ⚠️ **Scope**: built for **personal / trusted-network use**, bound to `127.0.0.1` by default. It runs
> shell commands and reads/writes files on your machine — the governance layer enforces restraint, but it
> is **not a sandbox**. Don't expose it to the public internet or run it as a multi-user service without
> extra hardening (shell sandboxing, multi-tenant isolation). When exposing it (`AGENT_WEB_HOST=0.0.0.0`),
> always set `AGENT_API_TOKEN`. See [SECURITY.md](SECURITY.md).

---

## Quick start (60 seconds)

```bash
make setup     # create .venv and install deps (first time)
make config    # setup wizard: model key / image gen / token (skippable)
make web       # launch web UI → http://127.0.0.1:8000
make cli       # or: terminal chat (runs zero-config with MockLLM)
```

**Docker (no local env needed):**

```bash
echo "AGENT_API_TOKEN=$(openssl rand -hex 16)" >> .env
make docker-up        # = docker compose up -d --build
# open http://127.0.0.1:8000 → Settings → "Access Token" → paste the token above
```

> No `make`? All commands live in the `Makefile`. The base runs with MockLLM and zero deps;
> for real models run `make config` or set `DEEPSEEK_API_KEY` in `.env`.

---

## Architecture: single-agent loop

One Captain, executing sequentially — it never delegates to other agents. Perceive → plan → govern → act → observe, looping until done or until it determines it can't.

```
channels/       external interfaces (cli / web / email)
core/loop.py    main loop (the agent's heart): perceive→plan→govern→act→reflect + todo list
core/bootstrap.py   assembly; core/bus.py event bus
core/presets.py     persona presets (office / coder / general)
governance/     ★ governance layer: declarative policy + risk tiers + budget + egress review + resource locks
capabilities/   unified capability layer: 40+ tools (fs/shell/web/browser/git/calendar/image/plan/schedule…) + GUI + MCP + skills
memory/         hybrid long-term memory (SQLite keyword + vector) + experience/preference/goals/checkpoints/templates/calendar/encrypted vault
observability/  trace + rollback + audit + transcript
server/         FastAPI + WebSocket streaming + routers/ grouped routes + governance/usage stats
llm/            DeepSeek / Zhipu / OpenAI / Claude / Ollama + Router + Fallback
scheduler/      scheduled tasks (briefing / indexing / cleanup)
skills/         30 built-in skills (docx/pptx/xlsx/pdf/meeting-notes/weekly-report/email/search/writing…)
evals/          40 real-task evals + LLM judge + stability detection
```

---

## Capabilities

- **Files / commands**: `fs.read/write/list/search`, `shell.run` (governed; dangerous commands hard-blocked).
- **Web**: `web.search` + `web.fetch` (free DuckDuckGo by default; optional Exa / Tavily / Brave / Serper), `http.request` (authenticated calls to internal APIs).
- **Browser** (optional Playwright): open / click / fill / screenshot / upload-download / persistent login.
- **Git** (for programmers, governed): `git.read` (status/diff/log, read-only, never prompts) + `git.commit` (stage + commit, **blocks .env and other secrets, never pushes**).
- **Local calendar**: `calendar.add/list/remove`, writes a local `.ics` subscribable from Apple / Google / Outlook.
- **Office docs**: `docx_writer` / `pptx_writer` / `xlsx_writer` / `pdf_extract` (install the `[office]` extra).
- **Multimodal**: `image.generate` (Zhipu CogView free / Runware / OpenAI-compatible), `image.ocr` / `vision.see`.
- **Memory / self-improvement**: `memory.remember/recall`, automatic experience capture, preference mining, crystallizing frequent tasks into skills (`skill.scaffold`).
- **Proactive / monitoring**: `monitor.*` (trigger on change), `goal.*`, `schedule.*`, daily briefing.
- **WeChat formatting**: `wechat.format` produces paste-ready inline-styled HTML.
- **Encrypted vault**: `secret.save/list`; passwords are Fernet-encrypted at rest, never sent in plaintext to the model / logs / git.
- **MCP connectors**: external MCP server tools (filesystem / Git / databases / Notion…), governed exactly like built-in tools.

---

## Persona presets

`AGENT_PERSONA_PRESET` (or pick in `make config`) switches emphasis by who's using it — flavor only, never touching the safety rules:

- **office**: documents / email / meetings / weekly reports first, leans on templates and docx/pptx/xlsx;
- **coder**: check `git` before changing, run tests after, commit carefully, never push on its own;
- **general** (default).

Ships with **8 office templates** (weekly report→Word, meeting notes→Word+todos, report→PPT, business email, monthly summary, data→Excel, notice, leave request) — one sentence, finished file.

---

## Governance (security enforced by code, not prompts)

- **Declarative policy** `governance/policy.yaml`: capabilities whitelisted per role; the model can't bypass it.
- **Risk tiers**: READ (never prompts) / WRITE (asks by default) / DESTRUCTIVE (always asks) / FORBIDDEN (rejected in code — e.g. writing `.env`, `rm -rf`, force push).
- **Three modes**: `AGENT_GOVERNANCE_MODE` = conservative / balanced / aggressive.
- **Rollback**: auto-snapshot before write/delete; CLI `/rollback` + web rollback.
- **Egress review**: outbound-domain allowlist + audit; **injection-proof**: never acts on "send the data somewhere" instructions found in web pages / emails / files.
- **Remote auth**: bound to `127.0.0.1` (no password locally); once exposed or reached via a reverse proxy (Cloudflare Tunnel), the `/api/*` control plane requires `AGENT_API_TOKEN`.

---

## Quality

```bash
make test          # regression tests (MockLLM, deterministic, no key needed)
make cov           # full suite + coverage report (needs .[dev])
make eval          # 40-case real-model eval (needs DEEPSEEK_API_KEY)
make compare       # multi-model comparison (flash vs pro, quality × latency)
```

- **220+ tests** across governance / memory / capabilities / API; `scripts/run_evals.py` runs 40 real tasks with deterministic checks + LLM judge + baseline comparison.
- `--repeat N` flakiness detection (quantifies occasional regressions); anti-thrash (stops when one capability keeps failing), anti-sycophancy (mechanism-level reminder under agreement pressure).

---

## Install & share

```bash
# editable install (recommended for development)
git clone https://github.com/john-lcj/my-agent && cd my-agent
pip install -e ".[all]"
myagent          # terminal chat (runs zero-dep with MockLLM)
myagent-web      # launch web → http://127.0.0.1:8000
```

Dependencies are opt-in: base is zero-dep (MockLLM); `[llm]` real models, `[web]` web service, `[memory]` vector memory,
`[channels]` external channels, `[cli]` slash completion, `[mcp]` MCP connectors, `[office]` office docs, `[dev]` tests+coverage, `[all]` everything.

---

## Common environment variables

| Variable | Description |
|------|------|
| `AGENT_MODEL` | primary model id (e.g. `deepseek-v4-flash`) |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | model keys |
| `AGENT_PERSONA_PRESET` | office / coder / general |
| `IMAGE_PROVIDER` / `IMAGE_MODEL` / `IMAGE_API_KEY` | image gen (zhipu / runware / openai) |
| `AGENT_GOVERNANCE_MODE` | conservative / balanced / aggressive |
| `AGENT_WEB_HOST` / `AGENT_API_TOKEN` | bind address / remote access token |
| `AGENT_WORKSPACE_ROOT` | workspace root (scope for produced files) |
| `EXA_API_KEY` / `TAVILY_API_KEY` | optional, better search quality |
| `AGENT_FALLBACK_MODELS` | fallback model chain |

Full list in `.env.example` (or run `make config`).

---

## Roadmap

- Calendar CalDAV cloud sync (currently local `.ics`)
- Frontend single-file modularization (like app.py — add tests first, then split)
- More built-in connectors; keep raising test coverage
- Deeper programmer "code mode" (run-tests / code-review loop)

---

License: [LICENSE](LICENSE). Security: [SECURITY.md](SECURITY.md). Deployment: [DEPLOY.md](DEPLOY.md).
