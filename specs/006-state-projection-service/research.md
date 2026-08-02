# Research: State-Projection Rendering as its own service

**Feature**: (pending `/speckit-specify`) | **Date**: 2026-08-01

> **Destination.** This file is the pre-seeded research payload for the spec-kit run described in
> `StateProjectionService_seed.md`. After `/speckit-specify` creates the feature directory (read the
> real path from `.specify/feature.json`), copy this file in as `research.md` and let
> `/speckit-plan` **extend** it rather than regenerate it. It is kept outside `specs/` until then
> because `create-new-feature.sh` bumps to the next free number when a requested directory already
> exists, which would orphan a pre-created one.

Codebase facts below come from a direct survey at `71ae176` (branch `feat/213-phase1-source-lineage`):
the three #213 modules, `pipelines/ensemble/`, `server/routers/{grounding,ensemble}.py`, the config
series under `docs/config/`, and the flow docs under `docs/system/`. Every file:line was read, not
inferred. Doctrine citations are quoted from the config series.

## The four services (GM rulings, 2026-08-01)

- **R1** — `ensemble_batch` + `facts_to_state` are their own service, not part of path 2. The shared
  substrate is corpus **and** dossiers: both are aggregations of facts, neither renders prose.
- **R2** — paths 2 and 3 both depend on that shared service, and not on each other.
- **R3** — each path produces its own documents in its own directory, without errors or collisions.
- **R4** — path 3 gets its own configuration.
- **R5** — path 3 gets its own UI layer.

| Service | Scripts | Produces | Config today |
|---|---|---|---|
| **Extraction & State** *(shared)* | `ensemble_batch` → `ensemble` → `ensemble_extract` / `ensemble_merge`; then `facts_to_state`; GM skills `/ensemble-alias-review`, `/ensemble-type-merge` | `docs/ensemble/per_chapter/*/merged.json`, `state_dossiers/`, `merged_dossiers/` | `ensemble.yaml` |
| **Path 1 — per-tool rendering** | `distill`, `campaign_state`, `party`, `planning` | the four docs (own extraction; no shared-service dependency) | `grounding.yaml` |
| **Path 2 — dossier synthesis** | `synthesise_world_state`, `synthesise_facts`, `synthesise_polish`, `--synthesize-only` staging on `campaign_state`/`party`/`planning` | `docs/*_draft.md` | `ensemble.yaml` *(shared with extraction — Q1)* |
| **Path 3 — state projection** | `event_spine`, `thread_registry`, `grounding_sections` | per-section files → assembled draft | **none — Python literals** |

Path 3 also owns two stores of its own: `docs/ensemble/events.jsonl` and `docs/thread_registry.yaml`
(+ `docs/ensemble/thread_proposals.yaml`).

## Execution order (verified against the flow docs and the call sites)

```
0  one-off:  new_workspace · configure_mcp · dnd_sheet · make_tracking
             /module-inventory → registry import-inventory → registry check
             convert_book → fivetools_ingest · resolve_refs → launch_5etools_mcp

A  post-session:  enhance_summary ◀GM  scene_extract ◀GM  sd_consistency ◀GM
                  sd_plan ◀GM  sd_narrate ◀GM  (voice_lint · check_consistency · /scrub)
                  assemble --chapter N   ← mints chapter/session frontmatter (#213 Phase 0)
                  polish (optional)

B  identity:  normalize_bible_headings → split_chapters → renumber_chapters
              summary_map ◀GM sets approved: true per row

C  SHARED SERVICE:  ensemble_batch [--source auto]  → per_chapter/*/merged.json
                      └ spawns ensemble.py per chapter (sys.executable — ensemble_batch.py:39,149)
                        → ensemble_extract (5 lenses) → ensemble_merge (+ stamp_lineage)
                    facts_to_state --list ◀GM scope  →  --known-only → state_dossiers/
                    /ensemble-alias-review → /ensemble-type-merge ◀GM → merged_dossiers/

   PATH 2:  synthesise_world_state · campaign_state|party --synthesize-only · planning --npc
            build_recent_events (zero-token side track)              → drafts ◀GM promote

   PATH 3:  event_spine update --corpus …                            → events.jsonl
            thread_registry propose --corpus … ◀GM triage            → thread_proposals.yaml
              verbs: add · log · set-status · alias (each save runs check); speculate → notes/
            grounding_sections list --doc D                          (staleness)
            grounding_sections build --doc D [--backend …]           → drafts ◀GM promote

D  prep:  rpg_retriever|query → dossier_proposer ◀GM approves → prep --mode single|pipeline
```

## D1 — One declaration per path, in the owning service's document

**Decision**: every path below collapses to a single declaration owned by one service.

| Value | Declared at | Also at |
|---|---|---|
| `docs/ensemble/events.jsonl` | `event_spine.py:35` `DEFAULT_STORE` | `grounding_sections.py:116`, `:150`, `:355` |
| `docs/thread_registry.yaml` | `thread_registry.py:66` | `grounding_sections.py:118` |
| `docs/ensemble/thread_proposals.yaml` | `thread_registry.py:67` | `grounding_sections.py:98` (SPECS) |
| `docs/grounding_sections` | `grounding_sections.py:56` `SECTIONS_DIR` | — |
| `docs/{doc}_draft.md` | `grounding_sections.py:540` (inline) | `ensemble.py:66-69` (path 2's map) |
| `docs/tracking*.txt` | `grounding_sections.py:124` | — |
| `docs/ensemble/merged_dossiers` | `--dossiers-dir` default | `EnsemblePaths.dossiers_glob` |
| `docs/ensemble/narrative_importance.yaml` | `grounding_sections.py:254` | — |
| copy sources: `docs/party.md`, `docs/planning_notes.md`, `notes/thread_speculations.md` | `SPECS` `source=` — `:87`, `:101`, `:104` | — |
| `docs/ensemble/summary_map.yaml`, `summaries/` | `campaignlib/lineage.py:40,41` | `summary_map.py:462`, `ensemble_batch.py:84` |

**Rationale**: the same defect `ensemble-isolation.md` Phase 3 and `grounding-isolation.md` Phase 8
each fixed — *"`paths` and `tuning` were Python literals in route signatures — unreachable without
editing code"* — arriving a third time, in a subsystem written after both.

**Worth noting**: `events.jsonl` appears three times inside one file — `:116` is the freshness-hash
input, `:150` is the spine read, `:355` is the tracking read. The hash input and the read are
declared independently, so redirecting one stamps a section with `inputs-sha` over bytes it was not
rendered from. Whatever the design, those three must resolve from one value.

**Alternatives considered**: leaving the literals and documenting them — rejected; R4 requires
configuration, and the three-way `events.jsonl` split is a live correctness bug, not a style issue.

## D2 — The three paths collide on output today

**Decision**: R3 is not satisfiable by config alone; the output namespaces must move.

- `server/routers/ensemble.py:66-69` maps the four docs to `docs/<doc>_draft.md` (path 2).
- `grounding_sections.py:540` writes `docs/{doc}_draft.md` — the same four filenames (path 3).
- `campaign_state.py:130` auto-stages `docs/world_state_draft.md` as an extract input (path 1
  consuming path 2's output).

So path 3 silently overwrites path 2's drafts, and path 1 then reads whichever ran last.
`flow-state-projections.md` already lists half of this under "known seams" (*"do not run both"*).

**Consequence the spec must handle**: giving each path its own directory means path 1's auto-stage
must be re-pointed at path 2's new location or retired — otherwise it silently reads nothing. This
is the one place R3 forces a change to an existing path (Q3).

## D3 — The fact-record contract is undeclared and unasserted

**Decision**: with R1 making this an inter-service boundary, the corpus record is the shared
service's published output contract and needs a test.

| Consumer | Keys read off `merged.json` |
|---|---|
| `event_spine.rows_from_corpus` (`:69-86`) | `type=="event"`, `fact`, `scene_index`, `quote_offset`, `source_quote`, `quote_verified`, `source` |
| `thread_registry` propose (`:166-181`) | `type=="thread"`, `subject`, `fact`, `quote_verified`, `source_quote`, `source` |
| `facts_to_state` | groups by `(type, subject)` |

Producer is `ensemble_merge` (+ `stamp_lineage` for `source`, + #213 Phase 1.2's `entity`→`subject`
normalisation).

**Rationale**: no test asserts these agree. A rename upstream degrades every consumer *silently* — a
non-matching `type` is skipped, so the spine shrinks rather than failing, and the failure surfaces
later as a thin grounding doc nobody can explain.

## D4 — What "sibling" costs: the per-section dependency

| Sections | Mode | Needs `merged_dossiers/`? |
|---|---|---|
| `world_state`: npcs, factions, locations, world | synthesis | yes |
| `planning`: factions, npc_outlook | synthesis / npc_outlook | yes |
| `campaign_state`: recent_events; `planning`: threads, emerging | spine / threads | no — corpus or own stores |
| `campaign_state`: tracking | LLM over spine + `tracking*.txt` | no |
| copy: `party`, `speculations`, `notes` | copy | no (but `party` copies a promoted doc) |

Six of thirteen need dossiers. **Under R1 that is a dependency on the shared service**, satisfied by
running `facts_to_state` — not a dependency on path 2. One residue: `render_synthesis` (`:368`) execs
`pipelines/ensemble/synthesise_world_state.py`, which is path-2 code (Q2).

`outlook_inputs` (`:267`) falls back `merged_dossiers` → `state_dossiers` **in code**. Phandalin has
no `merged_dossiers/`, so one live campaign runs entirely on the fallback with nothing on disk
saying so — the fallback should become declared.

## D5 — Config doctrine the spec must obey

| Constraint | Source | Consequence |
|---|---|---|
| One config location, no probes | `grounding-isolation.md` Track 0 / D6; `campaignlib.constants.config_path`; `test_config_location.py` | Locate documents with `config_path()`; a candidate list fails the build |
| `config/` = how a pipeline runs; `docs/` = what it operates on | D7 | `events.jsonl` / `thread_registry.yaml` stay in `docs/`; only *pointers* are config |
| Engine may not import the server | `test_layering.py` | Shared models go in `campaignlib/`, as party/planning did (Phase 1) |
| Every service owns a strict `extra="forbid"` document | `service-cut.md`, `schema.md` | New service → new document; `_deep_merge` for partial writes |
| No cross-service config reads | feature 003 deleted `grounding.py:_backend_flags` for doing exactly this | A consumer declares its own input pointer — the root-`summaries` shape |
| Route-edge resolution; sentinels in signatures | `ensemble-isolation.md` Phase 3; `test_ensemble_config_defaults.py` | No default literals in routers; argparse defaults become `None` |
| Selection through one seam | feature 003; `test_selection_isolation.py` | Token-spending endpoints resolve via `resolve_selection`; the document carries `selection: ModelSelection` |
| No silent "all" | Constitution X; `test_ensemble_chapters.py` | See D6 |
| Paths relative to the campaign root | `grounding-isolation.md` Track A′ | CLIs run `cwd == campaign_dir`; no resolution layer needed |
| Each isolation ships `docs/config/<name>-isolation.md` **and** reconciles README/schema/crud/values/service-cut/master | the whole series | Doc work is part of the feature, not follow-up |

## D6 — The corpus glob must NOT become a config field

**Decision**: no `corpus` field in any new document; assert its absence in a test.

**Rationale**: `event_spine update --corpus` (`:179`) and `thread_registry propose --corpus` (`:392`)
are both `required=True, nargs="+"`. There is no default literal to remove, and adding one converts
an explicitly-required scope decision into an implicit "all chapters" — the Constitution X violation
`ensemble.yaml`'s `chapters_selected` exists to prevent. The UI (R5) must pass the chapter set
explicitly too.

**Alternatives considered**: a default glob "for convenience" — rejected; that is the implicit blast
radius Principle X names.

## D7 — `build_recent_events` straddles the boundary

It is a compatibility wrapper over the projection engine (`update()` + `render()` imported from
`event_spine`), but it is routed by Dossier Synthesis (`/api/ensemble/run/recent-events`) and
resolves `recent_events_out` / `recent_events_window` from `ensemble.yaml`, while its `--store`
default comes from `event_spine.DEFAULT_STORE`. It is the only piece of the projection engine wired
to a server route today. Moving the store's declaration must not orphan it.

**Superseded by D15** — the straddle is resolved rather than tolerated.

## D8 — Invocation conventions already in use

`ensemble_batch` spawns `ensemble.py` by repo-relative path via `sys.executable` (`:39`, `:149`), and
`grounding_sections.render_synthesis` does the same for `synthesise_world_state.py` (`:368`) — rather
than `console_script()`, which is what the server uses. Pre-existing convention in this subsystem,
not something #213 introduced. All three path-3 tools **are** registered console scripts in
`pyproject.toml`, so the R5 UI can spawn them the normal way via `server/subprocess_runner.py`.

## D9 — Enforcement tests that will gate this work

`test_config_location.py` (no probes; `CONFIG_FILENAMES` gains any new document) ·
`test_layering.py` (no `pipelines/` → `server.*`) · `test_ensemble_config_defaults.py` (no literals in
the ensemble router) · `test_selection_isolation.py` (exactly one `--model` emitter; every
token-spending endpoint through the seam) · `test_retrieve_render_isolation.py` ·
`test_no_ui_state.py` · `test_ensemble_chapters.py` (empty selection refuses).

## D10 — Invariants no design may break

Disk is truth · every precision decision keeps its GM checkpoint · verbatim quotes are never
paraphrased · `inputs-sha` stays content-derived, never mtime (#137) · a build without `--backend`
stays deterministic and spends nothing · the draft → diff → promote gate survives · `SPECS` (which
sections exist and which doc they belong to — the GM's granularity ruling on the #213 anchor) is
structure, not config.

---

# Appended by `/speckit-plan`, 2026-08-01

D1–D10 above are the pre-run survey and were **not** regenerated. D11–D14 settle what planning
actually had to decide; nothing above was re-derived.

## D11 — The shared service keeps `ensemble.yaml`; it is not split in this feature

**Decision**: `<config>/ensemble.yaml` remains the document for both the Extraction & State service
and the Dossier Synthesis service. This feature adds exactly one new document, for State Projection.

**Rationale**: The spec requires that State Projection own a document *nothing else can corrupt* —
satisfied by adding one, not by splitting another. Splitting `ensemble.yaml` would mean a new
migration CLI, changes to `EnsembleConfigService`, the ensemble router and the ensemble Vue pages, in
a service that is not this feature's subject and was isolated only recently. The constitution's tax
clause ("every new database, daemon, cache or LLM call is a recurring tax — justify it") cuts against
a second document with no consumer asking for one.

The precedent is also direct: `grounding-isolation.md` gave four pages one document because *"they
are not four services — they are one pipeline run four times."* Extraction → bundling → dossier
synthesis is one pipeline run end to end, with a single operator running the stages in sequence.

**What this leaves open, named rather than hidden**: the Extraction/Dossier-Synthesis boundary is
real in the service map but is **not** reflected in config ownership. The trigger for splitting is a
knob one service needs and the other must not see — for example a synthesis-only backend that must
not affect extraction fan-out. Until that exists, splitting buys a migration and no correctness.

**Alternatives considered**: a new `extraction.yaml` leaving `ensemble.yaml` to the renderer —
rejected as above, and it would rename the document every existing campaign, skill and doc refers to.
Renaming `ensemble.yaml` to `extraction.yaml` and giving the renderer the new file — rejected for the
same churn with the labels reversed.

## D12 — The synthesis engine stays with Dossier Synthesis; State Projection invokes it as a tool

**Decision**: `pipelines/ensemble/synthesise_world_state.py` remains Dossier Synthesis's engine.
State Projection's `render_synthesis` keeps invoking it as a subprocess. The dependency becomes
*declared* — recorded in `contracts/cli.md` and pinned by a test that fails if the flags State
Projection passes stop existing.

**Rationale**: It renders prose, so by R1's own definition it cannot belong to the Extraction & State
service, which aggregates facts and renders nothing. Duplicating it is the worst option — two copies
of a synthesis prompt is exactly the drift the constitution's one-seam principle exists to prevent.
That leaves "stays put, dependency declared", which is what the code already does; the gap was that
nothing recorded or tested it.

**Mechanism stays as-is**: invocation by `sys.executable` + repo-relative path (D8). It cannot become
`console_script()` — that helper lives in `server/subprocess_runner.py`, and `test_layering.py`
forbids the engine importing the server. Changing the mechanism would mean a new resolver in
`campaignlib` for one caller.

**Alternatives considered**: extract the synthesis primitive into `campaignlib` so both services call
it as a library — the right move if a third consumer appears, but out of proportion for two, and it
would pull prompt assembly into the engine layer. Move the script to a shared location — cosmetic;
the coupling is the flag surface, not the path.

## D13 — Output namespace and the legacy-draft gate

**Decision**: each rendering service writes drafts under its own subdirectory of `docs/`:

| Service | Draft location |
|---|---|
| Per-Tool Rendering | `docs/pertool/<doc>_draft.md` |
| Dossier Synthesis | `docs/ensemble/drafts/<doc>_draft.md` |
| State Projection | `docs/projections/<doc>_draft.md` |

The cross-service input (`campaign_state.py:130` auto-staging the world-state draft) is re-pointed at
Dossier Synthesis's new location, preserving today's behaviour (spec FR-007a).

The legacy gate (FR-007b): before writing `<doc>`, a rendering service checks for
`docs/<doc>_draft.md` — the pre-move shared path — and if present refuses, naming the file and
stating that moving or deleting it clears the gate. The system never moves or deletes it. Once gone,
the check costs one `stat` and never fires again.

**Rationale**: the old drafts cannot be attributed to a service, and they are the left-hand side of
the GM's diffs. Refusing is the only option that neither guesses nor destroys. It is also
self-clearing, so it does not become permanent machinery.

**Alternatives considered**: an attributing migration (rejected by the operator — it would guess);
deletion (destroys diff baselines); leaving them inert (silent orphaning, the failure mode
`grounding-isolation.md` accepted only because a `mv` fixed it, which does not apply to generated
output whose provenance is unknown).

## D14 — How the CLIs locate and resolve the document

**Decision**: `campaignlib.constants.config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME)`. A missing
or empty file loads as an all-defaults `ProjectionConfig`; malformed YAML raises. Argparse defaults
become `None` sentinels; the config is loaded once at the top of `main()` and an explicit flag still
wins. Paths are used exactly as stored — relative to the campaign root — with no resolution layer.

**Rationale**: `config_path()` is the declared-location helper and is already used CLI-side by
`resolve_refs.py:132`, `launch_5etools_mcp.py:442` and `campaignlib/party.py:54`. A candidate list
would fail `test_config_location.py`. `CAMPAIGN_CONFIG_DIR` already keeps a CLI consistent with a
server started under `--config-dir`. No resolution layer is needed because these CLIs run with
`cwd == campaign_dir`, the property `GroundingConfigService.get_config`'s docstring records for
`grounding.yaml`.

The sentinel-and-resolve shape is the router rule `test_ensemble_config_defaults.py` enforces next
door, applied one layer down: resolution happens before argv is consumed, so `--help` and the
copyable command stay explicit.

**Alternatives considered**: walking up from cwd for the config directory — a probe, forbidden.
Passing `--config` explicitly on every invocation — pushes the declared location back onto the
caller, which is what the helper exists to prevent.

## D15 — `build_recent_events` moves to State Projection (supersedes D7)

**Decision**: `recent_events_out` and `recent_events_window` move from `ensemble.yaml` into
`projections.yaml` as `output.recent_events` and `output.recent_events_window`; the route moves from
`/api/ensemble/run/recent-events` to `/api/projections/run/recent-events`; the button moves with it.

**Rationale**: D14 makes `event_spine`'s `--store` default resolve from `projections.yaml`. Because
`build_recent_events` wraps `event_spine`, leaving its route on the ensemble side would make a
Dossier Synthesis route read the State Projection service's config document — exactly what FR-003
forbids and what `grounding.py`'s `_backend_flags` was deleted for. The alternatives are worse: have
the ensemble route pass `--store` explicitly and the store path is declared in two documents (the
duplication this feature exists to remove), or document an exception and the rule has a hole in it.

D7 already identified this script as the one piece of the projection engine wired to a route, so
this finishes a boundary rather than widening scope. It is the second and last place where this
feature touches a file belonging to another service — the first being FR-007a's cross-service input.

**No compatibility shim; the two campaign files are hand-edited** (GM, 2026-08-01: *"I am okay with
campaigns breaking on a first load, I can fix the config files."*). Delete
`paths.recent_events_out` and `tuning.recent_events_window` from `EnsembleConfig` outright. Both
live campaigns' `config/ensemble.yaml` currently carry `recent_events_out`, so both will fail
validation until the key is removed by hand — that is the intended, visible outcome, and it matches
the standing single-user rule: migrate-and-delete, never a legacy shim.

Blast radius is bounded: `EnsembleConfigService.get_config` catches the `ValidationError` (a
`ValueError` subclass) and returns `400` naming the offending key, so the **ensemble page** errors
while the **server still boots** and every other service keeps working. The error must name the key
and say to delete it — a bare "invalid ensemble config" would send the GM hunting.

The rejected alternative was the retired-fields strip `session_doc.yaml` used for `narrate.batch` in
005-ui-batch-selection. It works, but it is a shim carried forever for two files one person can edit
in a minute, and it makes the retirement invisible in the document itself.

**Alternatives considered**: keep the route where it is and pass `--store` explicitly (duplicate
declaration); keep it and document the cross-service read as an accepted exception (a rule with a
quiet hole, and the next reader cannot tell it was deliberate); leave `build_recent_events` reading
`event_spine.DEFAULT_STORE` as a hardcoded constant while everything else moves to config
(reintroduces the single-declaration defect this feature closes).

## Environment notes for whoever implements this

- **Worktree import shadowing.** The editable-install `.pth` hardcodes
  `/home/kroussos/src/CampaignGenerator`, so inside this worktree `import campaignlib` can resolve to
  the *main* checkout. `grounding-isolation.md` hit this as a phantom failure that passed in
  isolation and failed in a suite run. Confirm
  `python -c "import campaignlib; print(campaignlib.__file__)"` before trusting a green run.
- **Console scripts.** After any `[project.scripts]` change,
  `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` into the venv the server runs under, or
  `/run/*` fails with "Stream error — check terminal".
- **Live campaigns for verification.** `~/out-of-the-abyss/out-of-the-abyss` (62 chapters, has
  `merged_dossiers/`) and `~/Phandalin/Phandalin` (**no** `merged_dossiers/` — exercises the D4
  fallback). Both have a materialised `paths:` block in `config/ensemble.yaml`.
