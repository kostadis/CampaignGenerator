# Configuration architecture

How CampaignGenerator's configuration is stored, loaded, and saved. Read this when you need to
answer "where does the value of X come from?" or "what file should I edit to change Y?"

**This is the orientation page. The authoritative, code-verified maps live in
[`docs/config/`](../config/README.md)** — one document per question, kept current alongside the
code that owns each config surface. This page deliberately does *not* restate their tables: an
earlier cut of it did, and drifted a full five refactors out of date (it described
`CampaignConfigService`, `ui_state.yaml` v2, a flat-key legacy overlay and an in-progress frontend
sweep, none of which had existed for months). A second copy of a map is a second authority, which
is the exact anti-pattern the config work below spent five efforts removing.

| Question | Go to |
|---|---|
| What files exist, what shape is each, what's strict? | [`docs/config/schema.md`](../config/schema.md) |
| Who creates / reads / updates each one? | [`docs/config/crud.md`](../config/crud.md) |
| Which code reads this specific key? | [`docs/config/values.md`](../config/values.md) |
| How do the layers stack, from mneme wiring down to grounding docs? | [`docs/config/master.md`](../config/master.md) |
| Why is it shaped this way, and what's still open? | [`docs/config/service-cut.md`](../config/service-cut.md) |
| The ensemble + grounding subsystems specifically | [`docs/config/subsystems.md`](../config/subsystems.md) |

## The shape, in one page

Two tiers. **Platform** is global to the campaign; **service** config belongs to exactly one
workflow.

| Tier | File | Owner |
|---|---|---|
| Platform | `config.yaml` (tracked, **human-only** — no writer exists) | read-only via `PlatformConfigService` |
| Platform | `platform.yaml` — `runtime.default_model`, `runtime.session_dir` | `PlatformConfigService` |
| Platform | `.campaigngenerator.local.yaml` — host/port, nav (gitignored) | `PlatformConfigService` |
| Platform | `config/wiring.yaml` — external endpoints + data roots | mneme (rendered; do not edit) |
| Service | `session_doc.yaml` | `SessionEditorConfigService` |
| Service | `ensemble.yaml` | `EnsembleConfigService` |
| Service | `grounding.yaml` | `GroundingConfigService` |
| Service | `party.yaml` | `PartyConfigService` |
| Service | `planning.yaml` | `PlanningConfigService` |

Everything lives in `<campaign>/config/`. One location, no probes — a config file found anywhere
else is a migration input, not a supported alternative
([grounding-isolation.md](../config/grounding-isolation.md) Track 0, guarded by
`tests/test_config_location.py`).

Each service document is **strict** (`extra="forbid"`), lazily created, atomically written, and
reachable through exactly one typed route. There is no shared UI-state document and no generic
`PUT /section/{name}`: those were retired once the last six `ui.<section>` blobs turned out to be
empty and unwritten ([ui-state-retirement.md](../config/ui-state-retirement.md)).

## Hard rules (enforced in code or tests)

1. **`config.yaml` is never machine-written.** Hand-edit it freely; comments and ordering survive
   because no writer exists.
2. **One authority per value.** If you find yourself adding a second place to set something, that
   is the bug — see `service-cut.md` for the five efforts that removed the last ones.
3. **Boot CLI flags never persist.** They flow through `PlatformConfigService(boot_overrides=…)`
   and overlay the resolved view for the process only. An override naming a section with no
   consumer is a **`ConfigError` at boot**, not a silent no-op — twelve dead flags once survived
   for months behind exactly that silence.
4. **CLI subprocesses get plain command-line flags.** The server builds an argv and shells out;
   CLI scripts read their own `config.yaml` for `documents:`/prompts and nothing else from the web
   layer. Per [CLAUDE.md](../../CLAUDE.md): "the subprocess should look the same as if a human had
   typed it."
5. **Atomic writes.** Every persisting write is temp-file + `os.replace`. A crash mid-write leaves
   the existing file untouched.
6. **A service write cannot touch a sibling's document.** Separate files, separate locks —
   regression-tested per service (`test_another_services_write_cannot_touch_platform_yaml`,
   `test_ensemble_write_cannot_touch_sibling_documents`).
7. **No secrets in config.** API keys come from the environment; `claude-code` bills the local
   `claude` CLI instead. `codex-cli` uses Codex's saved ChatGPT login and strips
   `OPENAI_API_KEY` and `CODEX_API_KEY` from the child process.

## Model resolution

Which model a run uses, in precedence order:

1. An explicit `--model` / request `model` field.
2. The active backend's remembered model (`session_doc.yaml`'s `backends.<active>.model`, or
   `ensemble.yaml`'s per-stage model).
3. `platform.yaml`'s `runtime.default_model` — the sidebar picker.
4. `campaignlib.constants.DEFAULT_MODEL` (env `CAMPAIGN_MODEL`, else the literal).

The consistency auditor has one deliberate subscription exception: with
`--backend codex-cli`, an omitted `--model` does not inherit the Claude default.
It resolves explicit `--model`, then `CG_CODEX_MODEL`, then lets Codex use its
subscription default. `CG_CODEX_TIMEOUT` sets the positive finite child-process
deadline in seconds and defaults to `600`; neither setting is persisted in a
campaign config file.

This omission rule applies to the complete 30-command backend family, not just
the consistency auditor. An explicitly supplied compatible Codex model is
forwarded unchanged; an explicit `claude-*` model is refused rather than
silently replaced. Every Codex request requires a locally installed Codex CLI
and a completed `codex login`; the saved ChatGPT subscription login is used by
the isolated child, while `OPENAI_API_KEY` and `CODEX_API_KEY` are removed from
its environment.

## Codex reasoning effort

All 30 Codex-capable commands accept `--codex-reasoning-effort` with exactly
`minimal`, `low`, `medium`, `high`, `xhigh`, or `max`. Resolution is explicit
CLI/UI value, then `CG_CODEX_REASONING_EFFORT`, then omission. Omission sends no
`model_reasoning_effort` override and is displayed as “Codex default.” Model
support varies (`gpt-5.6-sol` supports `max`); incompatibility is reported with
the selected model and effort and never triggers fallback.

The global value is `platform.yaml`'s
`runtime.default_codex_reasoning_effort`. Service/profile values live beside
their existing Codex model under the owning service document, including the
Session Doc Editor backend profile and each ensemble stage. Values remain
dormant when another backend is active. The sidebar, service override panel,
Session Doc Editor drawer, and ensemble setup all use the server-published
vocabulary and serialize “Codex default” as null/omitted.

## Claude Code effort

All 30 `claude-code`-capable commands accept `--claude-code-effort` with exactly
`low`, `medium`, `high`, `xhigh`, or `max` — five values, not the Codex six:
`claude --effort` has no `minimal`. Resolution is explicit CLI/UI value, then
`CG_CLAUDE_CODE_EFFORT`, then omission.

Omission preserves the pre-021 behaviour exactly and means one of two things,
which are now reported separately: the engine's **compatibility clamp**
(`--effort high` when thinking is suppressed on a model whose thinking can be
disabled — the API refuses `xhigh`/`max` without thinking), or **inherited**,
where nothing is sent and `claude -p` resolves `effortLevel` from the operator's
own `~/.claude/settings.json`. An inherited run never claims a level, because
this process does not read that file.

An explicit `xhigh`/`max` on a run whose thinking is suppressed is **refused
before any child process starts**, naming both remedies (lower the effort, or
`CG_CLAUDE_CODE_THINKING=1`). No fallback, no silent repair, and the thinking
setting is never changed on the operator's behalf. The refusal does not fire on
always-thinking model families.

The global value is `platform.yaml`'s `runtime.default_claude_code_effort`.
Service/profile values live beside their existing model under the owning
service document, including the Session Doc Editor's `claude-code` backend
profile and each ensemble stage. A stored Claude Code effort and a stored Codex
reasoning effort coexist independently; each lies dormant while the other
backend is active, and setting one never reads, writes, or clears the other.
The sidebar, service override panel, Session Doc Editor drawer, and ensemble
setup all use the server-published vocabulary and serialize “Claude Code
default” as null/omitted.

Provider `--batch` is Anthropic Message Batches and is rejected before model or
child work for Codex. It is distinct from application controls such as
`--batch-scenes`, ensemble fan-out, resume, and review checkpoints. The
brokered ensemble `polish` loop keeps tool execution in the parent process and
uses an isolated Codex child only for structured turn responses. The seven
new UI invocation faces (consistency audit, transform, voice comparison,
Scabard sync, synthesis polish, chapter narration, and post-assemble polish)
reuse existing owning config boundaries; they do not add persisted stage
configuration. Scabard's access key is request-scoped and child-environment
only, never an argv or log value.
Every `/run/*` router resolves through
`server/platform_config_service.py::resolve_default_model` rather than hardcoding a default. Which
*backend* a service runs against is resolved by the same canonical request → service → platform
selection seam; command builders render only that resolved selection. A service-level Codex choice
therefore remains separate from inherited Claude model defaults and is not silently rewritten.

## Migrating a pre-isolation campaign

A campaign whose `config/` still has `ui_state.yaml` has undrained data. Run all four one-shot
CLIs, then delete the file:

```bash
python -m server.migrate_platform_config  --campaign-dir DIR   # runtime.* -> platform.yaml
python -m server.migrate_session_doc      --campaign-dir DIR   # ui.session_doc/profiles
python -m server.migrate_ensemble_config  --campaign-dir DIR   # ui.ensemble
python -m server.migrate_grounding_config --campaign-dir DIR   # the five grounding sections
```

The first is the one that usually matters: a missing `platform.yaml` loads as all-defaults, so an
unmigrated campaign silently boots on the literal default model with no session anchor. Each CLI
is idempotent, refuses to overwrite without `--force`, exits 0 with `nothing to migrate` when
clean, and reports unrecognised keys as skipped rather than dropping them.

## When you're touching this code

- **Adding a field to a service's config** — add it to that service's model in
  `server/<service>_config_shared.py`. The model is strict, so the write path validates it for
  free; add a default that matches whatever literal the route used before.
- **Adding a path field** — resolve it against the campaign root unless it is genuinely
  session-scoped, and let the owning service delegate to `PlatformConfigService.resolve_path` /
  `relativize_path` rather than re-implementing the base rule.
- **Reading config in a router handler** — take the owning service via `Depends`, or
  `require_platform(request)` for platform values. Never reach into another service's document.
- **Reading config in a CLI subprocess** — DON'T. Pass values as command-line flags.
- **Persisting a value from the frontend** — call that service's store method (`updateEditor`,
  `updateGrounding`, `updateRuntime`, `updateLocal`, or the party/planning/ensemble resource
  APIs). There is no generic section writer.
- **Adding a new config surface** — read `service-cut.md` first. The shipped pattern is: designed
  strict schema → an owning service → a dedicated file → one typed route → a migration CLI if
  there is existing data.

## Reference

| File | Role |
|---|---|
| [`server/platform_config_service.py`](../../server/platform_config_service.py) | `PlatformConfigService` — the platform tier; `resolved()`, `resolve_path`, `resolve_default_model`, `require_platform` |
| [`server/platform_config_shared.py`](../../server/platform_config_shared.py) | `PlatformDocument` / `PlatformLocalConfig`, the shared validators (`OptStr`/`OptBool`) and `ConfigError` |
| `server/{session_editor,ensemble,grounding,party,planning}_config_service.py` | One owning service per document |
| `server/{session_editor,ensemble,grounding}_config_shared.py` | Their strict pydantic schemas |
| [`server/routers/config_routes.py`](../../server/routers/config_routes.py) | `/api/config/*` — runtime, local, path discovery, model registry |
| [`server/main.py`](../../server/main.py) | Constructs the platform at boot; `_boot_overrides_from_args` builds the dotted-key map |
| [`server/migrate_common.py`](../../server/migrate_common.py) + `server/migrate_*.py` | The four one-shot drains; the only readers of `ui_state.yaml` |
| [`frontend/src/stores/config.ts`](../../frontend/src/stores/config.ts) | Pinia store — `resolved`, `editorConfig`, `groundingConfig` + the per-service write methods |
| [`tests/test_platform_config_service.py`](../../tests/test_platform_config_service.py) | Platform ownership, atomic writes, boot overrides, the isolation invariant |
| [`tests/test_config_location.py`](../../tests/test_config_location.py) | No source file probes a second location for a config document |
| [`tests/test_no_ui_state.py`](../../tests/test_no_ui_state.py) | The retired tier stays retired — and the migration CLIs keep working |
| [`tests/test_layering.py`](../../tests/test_layering.py) | Nothing under `pipelines/`, `session_doc/`, `campaignlib/` imports `server.*` |
