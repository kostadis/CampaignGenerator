# Research: installable package

Issue [#494](https://github.com/kostadis/CampaignGenerator/issues/494) reproduces a clean non-editable installation whose import fails before any console command can start. The source audit and [Python resource documentation](https://docs.python.org/3/library/importlib.resources.html) resolve the design questions below. All choices are for implementation planning; no runtime code changes are made here.

## D1 — Package read-only defaults inside an importable package

**Decision**: Move the shipped prompt tree and needed default text into `campaignlib/resources/`, retain the `config/agents/...` logical names in existing campaign configs, and make the wheel include those bytes. Use `importlib.resources.files(...)` to read text rather than deriving the checkout from `__file__`. Include `session_doc/review/reviewer.html` as package data and read it through the same resource model.

**Rationale**: Hatchling currently packages seven Python trees but omits root `config/`, so import-time prompt loading fails. [Python's resource API](https://docs.python.org/3/library/importlib.resources.html) supports package data independent of physical checkout paths. [Hatch's wheel builder](https://hatch.pypa.io/latest/plugins/builder/wheel/) documents explicit file selection and inclusion. Wheel content must be inspected because presence in the checkout does not prove inclusion in the installed artifact.

**Alternatives considered**: Install root `config/` beside `site-packages` and retain parent traversal (fragile, ambiguous ownership); copy defaults into each campaign (duplicates and diverges); add a repo-path environment variable (keeps checkout dependency).

## D2 — Preserve override precedence without an accidental fallback

**Decision**: `load_agent_prompt(name, base_dir)` resolves the campaign `config/agents/<name>.md` first, then the packaged default. `load_repo_file(path, base_dir)` accepts existing logical `config/...` names and checks the campaign location before packaged defaults: when `base_dir` is the campaign's `config/` directory, its parent anchors the logical path. An explicitly selected missing absolute file reports the missing path; it does not recover by basename from an unrelated packaged file. Missing named prompts report both override and shipped logical names. Keep strict placeholder substitution and prompt caching, with cache identity distinguishing local and shipped resources.

**Rationale**: Issue #494 requires campaign overrides to keep winning. Current `load_repo_file`'s final basename fallback can silently substitute a different file for a stale absolute path, contrary to spec FR-006; tests and guidance must make that behavior change visible. Existing `new_workspace` configs write logical `config/system_prompt.md` and `config/agents/*.md` names, so those must continue to map to shipped defaults if there is no local override.

**Alternatives considered**: Search CWD and checkout in an expanded fallback chain (violates explicitness and remains checkout-dependent); require rewriting every campaign config (unnecessary state migration).

## D3 — Keep campaign config and writable state outside the distribution

**Decision**: `config/config.yaml` remains campaign-owned at `<campaign>/config/config.yaml` and is not an application default to auto-load. The workspace creator may embed its existing template string but must print installed console commands, not commands pointing to root `.py` files. Any runtime write identified in the 17-site audit resolves from a selected workspace or documented user-data location.

**Rationale**: `campaignlib/config.py:find_default_config` deliberately removed a checkout fallback so running from the wrong directory cannot silently use the toolkit's own config. That decision remains valid for installed mode. Packaged defaults are read-only prompts and assets, not a hidden campaign.

**Alternatives considered**: Bundle and auto-load `config/config.yaml` (reintroduces the earlier wrong-campaign failure); write beside packaged defaults (fails read-only installations).

## D4 — Remove source-path command dispatch

**Decision**: Replace root/sibling `.py` subprocess targets with `python -m <module>` or the current interpreter's console-script entry point. Remove unnecessary `sys.path` root insertions. Replace `new_workspace`'s root-relative next-step examples with `campaign_state`/`prep` commands and checkout-only `./start` guidance. Keep web asset lookup in `server/main.py` scoped to the checkout UI; the installed package is CLI-only.

**Rationale**: A wheel may include sibling Python files, but running them by filesystem path assumes a physical tree and invites import-context failures. Module execution preserves package imports and uses the already-selected Python environment. Existing `server/subprocess_runner.py` has a current-interpreter console-script helper. The user explicitly chose CLI-only installed mode.

**Alternatives considered**: Rely on `.py` paths inside `site-packages` (works only while wheel layout happens to match checkout); include frontend build output in the wheel (outside the chosen scope).

## D5 — One external wiring path and one accessor

**Decision**: `campaignlib/wiring.py` remains the sole accessor. Resolution is explicit `load_wiring(path)` → `MNEME_WIRING` → `~/.config/campaigngenerator/wiring.yaml`; no CWD or checkout fallback. If an explicit path or env path is supplied but missing/malformed, report that error instead of searching another location. With no configured wiring and no default file, retain `{}`. Update mneme's `components.CampaignGenerator.config_target` and related guidance to the same user-config path. Test in fresh processes because some consumers capture wiring at import and `load_wiring` caches it.

**Rationale**: The user selected a user-config default and explicit-path override. Mneme's current example renders into `~/src/CampaignGenerator/config/wiring.yaml`; installed code cannot own that path. Mneme `apply` creates parent directories and renders a source-stamped file, while `status` checks that target. The two programs must agree on the destination.

**Alternatives considered**: Continue source/CWD fallback (split state); campaign-local wiring (duplicates host configuration); environment-only location (requires setup on every invocation).

## D6 — Move old rendered wiring deliberately

**Decision**: Add an installed `migrate_wiring` one-shot CLI accepting an explicit `--source-checkout`, optional `--target` for shared-user deployments, and `--force` only for a deliberate overwrite. It reads the old file raw, validates mapping shape, preserves unrecognised keys, refuses an existing target by default, reports destination and any unknown keys, and removes the old file only after the target is safely written. Normal startup never migrates and never uses a retired checkout path as a fallback. When the source checkout is known and old wiring is present, report the migration command; an installed command run with no source path cannot discover arbitrary historical checkouts, so absent default wiring retains the optional `{}` behavior. Ship `specs/030-installable-package/migration.md` and an operator guide in `docs/` during implementation.

**Rationale**: Constitution XIII requires a separate migration and documentation for state-location changes. Mneme `apply` does not delete the old target. The new render stamp may change even if wiring values do not, so verification should compare settings, not final file bytes.

**Alternatives considered**: Automatic move on first read (forbidden lazy migration); old/new dual probe (forbidden split state); just re-render and leave old file (stale state remains and source checkout may keep using it).

## D7 — Respect CLI/UI parity without shipping a web build

**Decision**: The migration engine is the CLI. The checkout Settings page gains a small invocation surface that selects the old checkout, shows destination and refusal/result, and calls a thin server route that executes the CLI. It does not implement migration logic. No UI assets are placed in the installed distribution.

**Rationale**: Constitution XI requires a UI face for a new CLI capability unless the human explicitly exempts it. The user's CLI-only ruling applies to installed mode; the existing checkout UI remains available. Constitution VI keeps migration logic in one engine.

**Alternatives considered**: A CLI-only migrator with no checkout UI (would need a separate explicit parity exemption); a second migration implementation in the route (split behavior).

## D8 — Verify the artifact, not merely the source tree

**Decision**: The release gate builds a wheel, inspects its required resource names, installs that wheel non-editably into a temporary fresh environment, changes to an unrelated working directory, imports the five named package areas, exercises three representative `--help` commands, checks prompt override/default precedence, and checks wiring/migration behavior. Run a separate `./start` checkout smoke. Keep `requirements.txt` from becoming a second unbounded dependency declaration by removing it or making the documented install use the project's declared dependencies.

**Rationale**: The reported failure passes dependency compatibility checks and appears only after installation. The [Python packaging guide](https://packaging.python.org/en/latest/flow/) describes wheels as the built distribution installed into user environments. Source-tree tests alone cannot detect missing wheel data or path assumptions.

**Alternatives considered**: Editable install smoke (source tree masks missing package data); import from repo root (same masking); only a static wheel listing (does not prove entry points work).

## Lookup inventory for implementation

| Class | Sites from #494 | Planned outcome |
|---|---|---|
| Shipped prompts/default text | `campaignlib/config.py:139`, `:199`; `session_doc/narrate.py:88` | Package data and truthful override/default diagnostics |
| Host wiring | `campaignlib/wiring.py:28` | Chosen external default, explicit precedence, migration |
| Source-root shims and subprocess paths | `pipelines/workspace/new_workspace.py:39`; `pipelines/rlm/mcp_server.py:37`; `pipelines/grounding/{grounding_sections:54,event_spine:36,thread_registry:72,build_recent_events:22}.py`; `server/routers/{connections:17,scene_editor:80}.py` | Remove root insertion; dispatch via module/entry point; portable instructions |
| Package-local files and scripts | `session_doc/review/serve.py:40`; `pipelines/ensemble/{ensemble_extract:74,ensemble:38,ensemble_batch:25}.py` | Include `reviewer.html`; invoke Python modules instead of paths |
| Checkout web artifact | `server/main.py:62` | Keep `frontend/dist` for `./start`; no installed UI promise |

The issue counts these as 17 lookup sites across 16 modules. The implementation audit must test every row, including package-local cases that currently appear to work from a wheel.
