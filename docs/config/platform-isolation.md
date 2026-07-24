# Platform (Global) Configuration Isolation Design

> **Status: 📝 Proposed — nothing implemented. O1–O4 decided 2026-07-24.**
> Third in the series after [planning-isolation.md](./planning-isolation.md)
> (✅ 2026-07-23) and [session-editor-isolation.md](./session-editor-isolation.md)
> (✅ 2026-07-24). Those two carved *services* out of the shared config; this
> one addresses what they left behind — the **platform tier** itself. The four
> open questions are resolved under [Design decisions
> (O1–O4)](#design-decisions-o1o4); **O3 landed larger than this doc's first
> draft assumed** and turned a zero-migration plan into a Phase-5-shaped one.
> All "current state" claims are code-verified against source at `1caa583`.

## Overview

[service-cut.md](./service-cut.md) names a **PLATFORM** tier — mneme wiring,
repo prompts/agents/documents, runtime model + session, server binding,
campaign root — and calls the global-vs-service-local split "a convention, with
no enforced hierarchy or management layer."

Reading the source, the platform tier's problem is *not* the one the previous
two isolations solved. Planning and the Session Doc Editor were **owned by the
wrong service**. The platform tier is owned by the right service — it just
isn't a platform service. `CampaignConfigService` plays two roles at once:

1. **The platform** — path resolution, `runtime.{default_model, session_dir}`,
   `campaign_dir`/`config_dir`, boot overrides, the read-only `config.yaml`
   view. Every other service composes it for exactly this.
2. **The residual landlord** — sole owner of the ten un-isolated
   `ui.<section>` blobs, their generic `PUT /section/{name}` route, their
   `_PATH_FIELDS` entries, and their flat-key legacy projection.

Role 2 is what the remaining seven services will each eventually take back
(deferred). Role 1 is permanent. **They are fused in one 610-line class, and
there is a second, undeclared copy of role 1 sitting next to it in
`server/config.py`.**

This document splits the two roles, collapses the duplicate, and gives the
platform's own state the same file-level isolation planning and the editor got.

## Current state (verified)

### The second platform config: `server/config.py`

158 lines, imported by exactly two modules, holding platform-global values that
nothing reconciles with `CampaignConfigService`:

| Symbol | What it is | Conflicts with |
|---|---|---|
| `MODELS` (list of 5) | the registry served by `GET /api/config/models` | nothing — it is the *only* registry, and it is **stale**: no Opus 5 / Sonnet 5 / Fable 5 |
| `DEFAULT_MODEL` | `CAMPAIGN_MODEL` env or `claude-sonnet-4-6` | `config_models.RuntimeSection.default_model` and `campaignlib.constants.DEFAULT_MODEL` — three independent copies of one expression |
| `derive_campaign_paths()` | 100 lines of independent path derivation | `_PATH_FIELDS` / `resolve_path` — see below |
| `api_key_present`, `path_exists` | env + fs probes | — |
| `get_campaign_dir_from_request` | reaches into `app.state.config_service` | `config_routes._require_service` (its own docstring says so) |

`derive_campaign_paths` mixes two different jobs. **Derivation** duplicates the
service (`output_dir = session_dir`, `DERIVED_SUBDIRS`, hardcoded `docs/` /
`voice/` / `examples/` layout) — and has already drifted, emitting
`roleplay_extract_dir` / `summary_extract_dir`, the pre-Phase-5 names the
editor renamed to `*_extractions_dir`. **Discovery** does something the service
genuinely cannot: globbing `*.vtt`, sniffing `gm-assist.md` vs `gm_assist.md`
vs `recap.md`, finding `summaries.md` vs `all_summaries.md`, exist-checking
each `docs/*.md`. Single consumer: `GET /api/config/campaign-paths` ←
`SessionConfig.vue:123`.

### Twelve dead CLI flags

`main._boot_overrides_from_args` maps 12 flags to dotted `session_doc.*` keys:

```
--session --extract-dir --roleplay-extract-dir --output-dir --summary-extract-dir
--session-summary --party --voice-dir --examples --characters --narrate-tokens --context
```

`session_doc` left `UISection` in Phase 5. `resolved()` now routes those
overrides into `ui_raw.setdefault("session_doc", {})` — a phantom key.
`SessionEditorConfigService` reads only `platform_resolved["runtime"]
["session_dir"]` and `["default_model"]`; it never consults `boot_overrides`.
**All twelve flags silently do nothing.** Only `--campaign-dir`,
`--session-dir`, `--config-dir`, `--host`, `--port` still function.

`tests/test_main_boot_overrides.py` passes — it asserts the *mapping*, which is
still faithfully produced. Nothing asserts that anything reads it.

### One default model, fifteen literals

`"claude-sonnet-4-6"` is independently hardcoded in:

| Site | Count |
|---|---|
| `campaignlib/constants.py::DEFAULT_MODEL` | 1 |
| `server/config.py` (`MODELS[0]` + `DEFAULT_MODEL`) | 2 |
| `server/config_models.py::RuntimeSection.default_model` | 1 |
| `frontend/src/stores/config.ts:31` | 1 |
| router request-body defaults — `grounding.py` ×5, `prep.py` ×3, `experimental.py` ×2, `session_workflow.py`, `connections.py` | 12 |
| `ensemble.py::SYNTHESIS_CAPABLE` | separate list, also stale |

The routers' defaults are the dangerous ones: a request that omits `model` gets
the literal, **not** `runtime.default_model` — so the sidebar picker is
silently bypassed on those paths.

### `wiring.yaml` does not exist here

`config/wiring.yaml` is **gitignored and absent** on this machine;
`MNEME_WIRING` is unset. `campaignlib.wiring.load_wiring()` returns `{}`, so
every wiring read currently takes its fallback. The mneme template
(`hypostasis/templates/campaigngenerator.wiring.yaml.j2`) renders 8 keys, all
flat scalars. This constrains O4's sequencing — see
[Risks](#risks).

### The flat-key overlay is ~95% dead

`flatten_resolved_to_legacy` projects 10 section prefixes plus 4 experimental
sub-prefixes. Remaining genuine frontend **reads**: `values.session_dir`
(`utils/paths.ts:16`) and `global_model` (`stores/config.ts:52`).
`values.campaign_dir` comes from `new_shape`, not the overlay. The four
`values.party_*` / `values.plan_*` sites are **writes** — an optimistic
client-side mirror beside the real `updateSection` call. No prefixed key is
read anywhere.

## Problems

1. **Split-brain, again.** `server/config.py` is a second live copy of platform
   config with its own model default and path derivation, reconciled by
   nothing and already drifted. Same shape as `scene_editor.CONFIG` — a module
   of free functions that *looks* like a utility and *behaves* like an
   authority.
2. **Fused roles, unbounded blast radius.** A write to any of ten loose UI
   sections re-serializes the same `ui_state.yaml` that holds `runtime` — so a
   `ui.distill` save can corrupt `default_model` and `session_dir`, the values
   every service composes. Planning and the editor bought isolation *from* this
   file; the platform's own state never got it.
3. **Silent no-ops.** Twelve CLI flags accepted and ignored, with no error and
   no warning.
4. **No single default.** Fifteen literals mean the sidebar picker is
   authoritative only where it happens to be forwarded.
5. **Stale registry.** `GET /api/config/models` is the platform's answer to
   "what can I run?" and has not tracked the current model family.

## Why this is not planning, and not the session editor

| Dimension | Planning | Session editor | **Platform** |
|---|---|---|---|
| Core problem | wrong owner | split-brain + process-global | **fused roles + a shadow copy** |
| Fix direction | extract a service | delete a global, move a file | **split one class in two; delete a module; move a file** |
| Data lift | none | `ui_state.yaml` → `session_doc.yaml` | **`ui_state.yaml` → `platform.yaml`** (per O3) |
| Consumers to unwind | tests only | ~20 helpers | 2 modules, ~15 model literals, 2 frontend reads, **24 service refs + 11 test files** |
| Wire surface | net-new REST | nearly unchanged | nearly unchanged |

The distinguishing risk is that the platform's data lift moves
**`runtime.session_dir` — the base every session-scoped path resolves
against**. The editor's Phase 5 moved *leaf* config; this moves the *anchor*.
See [Risks](#risks).

## The ownership boundary

**Owned by `PlatformConfigService` (writable):**
- `runtime.default_model`, `runtime.session_dir` — relocating to
  `<config>/platform.yaml` (O3)
- `local.server.{host,port}`, `local.nav.last_page`

**Provided read-only (it is the accessor, not the owner):**
- `tracked` — `config.yaml` (human-owned; no writer exists, none is added)
- `wiring` — `config/wiring.yaml` via `campaignlib.wiring` (mneme-owned),
  **now including the model registry** (O4)
- `campaign_dir`, `config_dir`, `boot_overrides` — process context

**Provided as mechanism (unchanged, still the single implementation):**
- `resolve_path` / `relativize_path` and the session-vs-campaign base rule

**NOT owned — stays with the residual `UIStateService`:**
- the ten `ui.<section>` blobs, `PUT /section/{name}`, `_PATH_FIELDS`, the
  sibling-session rebase, `flatten_resolved_to_legacy`

**NOT in scope:** *backend selection.* Unifying the four backend selectors is
service-cut gap #3, **explicitly deferred by the maintainer**. The line: the
**model registry and the default model value are platform config**; **which
backend a service runs against, and that backend's remembered model, are the
service's** and stay put.

## Design decisions (O1–O4)

Decided 2026-07-24 by the maintainer. O3 is the consequential one — it enlarged
the plan.

- **O1 — The 12 dead boot flags → delete.** Removed from argparse and from
  `_boot_overrides_from_args`. The boot surface becomes the five flags that
  work. `test_main_boot_overrides.py` is rewritten to assert a flag **reaches a
  consumer**, not merely that a mapping dict is produced — the assertion gap
  that let all twelve die unnoticed.
- **O2 — `derive_campaign_paths` → narrow to discovery-only.** Moves onto the
  platform service; everything duplicating `resolve_path`/`_PATH_FIELDS` is
  stripped (`output_dir`, `DERIVED_SUBDIRS`, layout constants). What survives
  is only filesystem probing: VTT glob, gm-assist/recap sniff, summaries sniff,
  `docs/*.md` exist-checks. **This kills the drift class permanently** — a
  function that emits no path fields cannot go stale when a path field is
  renamed.
- **O3 — Extract, rename, *and* relocate.** `PlatformConfigService` is
  extracted; the remainder is renamed `UIStateService`; and
  `runtime.{default_model, session_dir}` moves out of `ui_state.yaml` into a
  dedicated `<config>/platform.yaml` the platform service owns exclusively.
  This is the option that actually fixes problem #2 — the first draft of this
  doc named that problem and then left it unfixed, since it proposed no new
  file. Costs a data lift + migration CLI, mirroring Phase 5.
- **O4 — Model registry → `wiring.yaml`.** The selectable-model list becomes
  mneme-rendered per-install config alongside `dgx_endpoint`/`dgx_model`, so
  adding a model needs no CampaignGenerator release. Consistent with the
  existing external/internal split (`dgx_model` already sets that precedent).
  **Carries a cross-repo prerequisite** — see [Risks](#risks).

## Data model

### `<config>/platform.yaml` (new, per O3)

Strict (`extra="forbid"`), matching `SessionEditorConfig` and `PlanningConfig`:

```yaml
runtime:
  default_model:            # sidebar picker; unset → env CAMPAIGN_MODEL → wiring default
  session_dir:              # campaign-based path — the session-resolution anchor
```

`.campaigngenerator.local.yaml` keeps its shape (`server`, `nav`) and becomes
strictly typed under the same service.

`UIState` is `extra="allow"`, so a pre-migration `ui_state.yaml` with a
leftover `runtime:` block loads without error and is simply ignored — the exact
precedent Phase 5 set for `session_doc`/`profiles`. `SCHEMA_VERSION` should
bump to 3: Phase 5 left it at 2 while removing two sections, which is why the
field currently carries no information. A second structural removal is the
moment to make it mean something again.

**Migration:** `python -m server.migrate_platform_config --campaign-dir DIR`,
modelled directly on `migrate_session_doc.py` — raw `yaml.safe_load` (so it can
rescue a field the live schema no longer declares), `--config-dir`, `--force`,
`nothing to migrate` + exit 0 when clean, and path values copied as-is without
re-resolution.

### Model resolution precedence (O4)

Stated explicitly because it is now six levels deep and each was added
separately:

| # | Source | Owner |
|---|---|---|
| 1 | explicit `--model` / request `model` field | caller |
| 2 | active backend's remembered model (`session_doc.yaml` `backends.<active>.model`) | Session Doc Editor (gap #3 — untouched) |
| 3 | `runtime.default_model` (`platform.yaml`, sidebar picker) | platform |
| 4 | `CAMPAIGN_MODEL` env | operator |
| 5 | `wiring.yaml` model registry default | mneme |
| 6 | literal fallback in `campaignlib.constants` | code |

Levels 5–6 are new; 1–4 exist today. Level 6 cannot be removed while
`wiring.yaml` is optional.

## API surface

| Method | Path | Change |
|---|---|---|
| `GET` | `/api/config/` | shape unchanged; legacy overlay drops out |
| `PUT` | `/api/config/runtime` | unchanged wire shape; writes `platform.yaml` |
| `PUT` | `/api/config/local` | unchanged; writes through the platform service |
| `GET` | `/api/config/models` | **content changes** — wiring-sourced, with fallback |
| `GET` | `/api/config/campaign-paths` | **narrowed** to discovery fields (O2) |
| `GET` | `/api/config/session-paths` | deleted — one-line wrapper, no caller |
| `PUT` | `/api/config/section/{name}` | unchanged, moves to `UIStateService` |

## Phases

| # | Work | Risk | Blocked by |
|---|---|---|---|
| 0 | **Delete the 12 dead flags** (O1); rewrite `test_main_boot_overrides.py` to assert a flag reaches a consumer | low | — |
| 1 | **Retire `flatten_resolved_to_legacy`**: migrate `paths.ts` (`session_dir`) and `stores/config.ts` (`global_model`) to `resolved.runtime.*`; drop the two optimistic-mirror writes; delete the projection + both prefix tables | low | — |
| 2 | `PlatformConfigService` + strict `PlatformConfig`; rename the remainder `UIStateService`; 24 service refs + 11 test files follow. **No file move yet** | medium (wide, mechanical) | — |
| 3 | **Relocate `runtime` → `<config>/platform.yaml`** (O3) + `migrate_platform_config.py`; bump `SCHEMA_VERSION` to 3; carry write-time relativization and load-time normalize for `session_dir` | **high** — moves the session-resolution anchor | 2 |
| 4 | Fold `server/config.py` in: `get_campaign_dir_from_request` → platform accessor; `derive_campaign_paths` → discovery-only helper (O2); delete `derive_session_paths`; migrate `SessionConfig.vue` | medium (frontend) | 2 |
| 5 | **Model registry → wiring** (O4): `models:` key + fallback chain; the 12 router defaults become `None`, handlers fall back to the platform | medium; **behavior change** | mneme render |
| 6 | Docs: `schema.md`, `values.md`, `crud.md`, `master.md`, `service-cut.md`; "as shipped" here | low | all |

Phases 0 and 1 are self-contained cleanup and can land immediately. Phase 5 is
gated on a change in another repo and should not block 0–4.

## Risks

- **Phase 3 moves the anchor, not a leaf.** `runtime.session_dir` is the base
  for *every* session-scoped path resolution:
  `CampaignConfigService.resolve_path`/`relativize_path` fall back to it,
  `_normalize_stored_paths` keys off the persisted value, the sibling-session
  rebase in `resolved()` reads it, and `SessionEditorConfigService` reads it
  both for `_relativized_paths` (persisted) and `resolved_editor_config`
  (boot-overridden). Once it lives in a different file, **load order becomes
  load-bearing**: `platform.yaml` must be read before any path resolution,
  including `ui_state.yaml`'s own `vtt_summary` session fields — which will now
  resolve against a base held in another document. The editor's Phase 5 had no
  equivalent hazard.
- **Phase 5 depends on another repo.** `config/wiring.yaml` does not exist on
  this machine and is gitignored; the mneme template renders 8 flat scalars.
  A model registry needs a `models:` source in `hypostasis.yaml`, a template
  change (the first list-valued key), and a re-render. **Until then the
  fallback is the only live path**, so build and test the fallback first and
  treat wiring as the override, not the base case.
- **Phase 5 changes behavior.** Call paths that omit `model` and silently take
  the literal will start taking `runtime.default_model` — the intended fix, but
  a live change on 12 routes. Land it apart from Phases 2–4 so a regression is
  attributable.
- **Strict `runtime`.** `RuntimeSection`/`LocalConfig`/`ServerSection`/
  `NavSection` are all `extra="allow"` today, so a typo persists silently.
  Tightening risks rejecting an in-the-wild key — warn-and-drop at load, not a
  fatal `ConfigError`. The local file already uses warn-and-ignore for exactly
  this reason.
- **Phase 2 is wide but shallow.** 24 references and 11 test files, plus the
  `app.state.config_service` attribute name. Keep logic identical; change only
  which object holds it.

## Out of scope (named, deferred)

- **Central backend/model provider** (gap #3) — deferred by the maintainer.
  The four backend selectors stay four. This plan unifies the *registry* and
  the *default value*, not *selection*.
- **`ensemble.py::SYNTHESIS_CAPABLE`** — also stale, but it encodes a
  *capability judgment* ("good enough to synthesize"), not a registry. It
  should consume the registry once one exists; deciding which models are
  synthesis-capable is a separate call.
- **Isolating the remaining ~7 services** out of `ui_state.yaml`.
  `UIStateService` exists to make that debt countable, not to discharge it.
- **Splitting `config.yaml`** (mixes platform keys with `mempalace.*`) — human-
  owned, no writer, and a split costs a migration for every campaign.
- **Grounding-doc producer/consumer contracts** (gap #4) and the service
  registry (gap #6).

## Contrast with the prior two isolations

| | Planning | Session editor | Platform |
|---|---|---|---|
| New service LoC | 137 | 303 + 212 | ~150 (mostly moved) |
| Net code change | additive | −1 global, −1 rename table | **net deletion** (`server/config.py`, the overlay, 12 flags) |
| Migration | none | one-shot CLI | **one-shot CLI** (O3) |
| Cross-repo dependency | none | none | **yes** (mneme render, Phase 5) |
| Bugs surfaced during design | 2 (while finishing) | 3 (while implementing) | **4, while planning** — dead flags, drifted derivation names, stale registry, 12 literal model defaults |
