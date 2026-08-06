---

description: "Task list for 007-cross-campaign-search"
---

# Tasks: Cross-Campaign Provenance-Aware Search Seam

**Input**: Design documents from `/specs/007-cross-campaign-search/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Included, and not optional here.** The spec's Success Criteria SC-001–SC-010 are
mechanical assertions, `plan.md`'s source layout names 14 test files, and the constitution
requires static guards (`test_layering.py`, `test_retrieve_render_isolation.py`) plus this
feature's own read-only and no-LLM guards. Tests are part of the deliverable, not an add-on.

**Organization**: Grouped by user story so each ships and demos independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: `[US1]`–`[US5]`, mapping to spec.md's user stories
- Every task names an exact file path

## Path Conventions

Two roots, and the distinction matters:

- **Code** → this repo, `/home/kostadis/src/CampaignGenerator/`
- **Authored data** → the campaign workspace, `~/src/campaigns/` (a *separate* git repo).
  Per `~/src/campaigns/CLAUDE.md`: **one campaign per commit, never bundled.**

## ⚠️ Two standing rules for whoever executes this list

1. **FR-029: the manifest and corrections records MUST be hand-authored — nothing may be
   populated by inference.** Tasks T023–T030 produce **drafts** transcribed from the
   *verified* directory survey in `research.md` D2/D10/D12 and the worked example in
   `contracts/manifest.md`. **T031 is a blocking GM review gate.** No task in Phase 3 or
   later may begin until the GM has ratified that data. This is Constitution II applied to
   this feature's own construction.
2. **FR-031/FR-032: never write to campaign content or identity stores.** No task below
   edits anything under a campaign except the *new* `docs/corrections.yaml` files. Making
   the D11 alias fixtures resolve is a GM action, recorded as T098–T099 and deliberately
   left undone.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton, packaging, and the guards that must be green from the first commit

- [X] T001 Create the package skeleton `provenance/__init__.py` with a module docstring naming this as the read-only, LLM-free provenance seam (Constitution V) and listing the module map from plan.md
- [X] T002 Add to `pyproject.toml`: `pydantic` in `[project.dependencies]` (research D7 — today it arrives only transitively via `fastapi`), the console scripts `provenance = "provenance.cli:main"` and `provenance_mcp = "provenance.provenance_mcp:main"`, and `"provenance"` in `[tool.hatch.build.targets.wheel] packages`
- [X] T003 [P] Add `CAMPAIGNS_ROOT` to `campaignlib/constants.py` with resolution order `$CAMPAIGNS_ROOT` → `~/src/campaigns`, documented in the module docstring style already used for `CONFIG_DIR_NAME` (research D5)
- [X] T004 [P] Refactor `pipelines/workspace/configure_mcp.py` to import `CAMPAIGNS_ROOT` from `campaignlib.constants`, deleting the bare literal at line 44 so there is one answer rather than two that drift (research D5)
- [X] T005 [P] Add `"provenance"` to `ENGINE_PACKAGES` in `tests/test_layering.py` so the new package can never import `server/`
- [X] T006 [P] Write `tests/test_provenance_no_llm.py` — AST guard failing on any import of `anthropic` or `campaignlib.api`, or any reference to `make_client`/`stream_api`/`call_api`/`run_batch` anywhere under `provenance/` (FR-033, research D16)
- [X] T007 [P] Build the pinned fixture workspace under `tests/fixtures/provenance/` — two synthetic campaigns covering all four tiers, an unclassified file, a tier-glob overlap, a generated-and-hand-edited file, a `.gitignore` that would hide a working-reference file, and one non-UTF-8 file (research D11, D12, D17, D18)
- [X] T008 Run `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` and verify `which provenance provenance_mcp` both resolve — required after any `[project.scripts]` change per repo `CLAUDE.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two hand-authored documents, their strict models, tier classification, and `provenance check`. This is plan.md's Phase 0.

**⚠️ CRITICAL**: No search can run without a ratified manifest — FR-009 refuses any campaign lacking a manifest entry rather than defaulting a tier. Every user story is blocked on this phase.

### Document models

- [X] T009 Implement `ProvenanceManifest`, `Campaign`, `TierGlobs`, `GeneratedDecl`, `Horizon`, `IdentityDecl` and `ProvenanceRange` in `provenance/manifest.py` — pydantic v2, `ConfigDict(extra="forbid")` on every model, per `contracts/manifest.md` and data-model.md §1–§4, §7, §9 (FR-027). **`Horizon` is chapter-only**: fields `latest: int` and `path_pattern: str`, with **no `kind` discriminator and no date branch** — all six campaigns are chapter-based and a declared-but-unimplemented branch is a promise the schema cannot keep (data-model.md §7)
- [X] T010 Implement manifest validation in `provenance/manifest.py`: `version == 1`; unique campaign keys; `root` rejects `..` escapes (error, never clamped); all four tier keys present; `horizon.path_pattern` compiles with exactly one capture group; `provenance_ranges` non-overlapping; **all-or-nothing loading** — one bad campaign block fails the whole load (FR-030)
- [X] T011 [P] Implement `CorrectionRecord` and `Correction` in `provenance/corrections.py` — strict pydantic per `contracts/corrections.md` (FR-028), with the four-state `corrections_status` enum (`consulted`/`no-record`/`not-consulted`) from data-model.md §5 (FR-005), plus the `verified: bool = True` and `note: str | None` fields an unreproducible correction needs (data-model.md §5)
- [X] T012 [P] Implement correction matching in `provenance/corrections.py`: attach on `applies_to.paths` glob match **and** (`subjects` empty **or** a subject appears case-insensitively in the query or excerpt). **`stale_claim` is display-only and MUST NOT be used for matching** — research D12 is the rationale and a comment must cite it, because incident 1's stale text has already been regenerated away
- [X] T013 Implement workspace-root resolution in `provenance/manifest.py`: `--campaigns-root` → `$CAMPAIGNS_ROOT` → `campaignlib.constants.CAMPAIGNS_ROOT`, returning both the resolved path **and which rule produced it** for later reporting (Principle VIII, research D5)

### Tier classification

- [X] T014 Implement glob→tier classification in `provenance/tiers.py`: fixed precedence `authoritative`→`search_accelerator`→`working_reference`→`staging`, first match wins, **every additional match recorded in `tier_ambiguous`**, no match ⇒ `unclassified` and still returned (FR-013, research D8, data-model.md §3)
- [X] T015 [P] Add the `TrustTier` enum with its ranking ordinals (authoritative 0 … unclassified 4) to `provenance/tiers.py` — the tiebreak FR-010 requires

### CLI skeleton and refusals

- [X] T016 Implement the `provenance` argparse skeleton in `provenance/cli.py` with subcommands `search`/`resolve`/`capabilities`/`check`, the exit-code contract (`0` ok, `1` refusal, `2` usage, `3` load error) and `--campaigns-root`, per `contracts/cli.md`
- [X] T017 Implement the refusal messages in `provenance/cli.py`: missing scope, unknown campaign, missing manifest entry, missing campaign root, horizon-without-marker — **each enumerating the known campaigns**, each exiting `1` so a scriptable caller can distinguish "refused" from "found nothing" (FR-006, FR-009, FR-025, SC-003)
- [X] T018 Implement `provenance check` in `provenance/cli.py`, reporting `tier-ambiguous`, `stale-correction-entry`, `unverified-correction` (every `verified: false` entry), `unclassified-heavy`, `horizon-unattributable`, `campaign-root-missing` and `no-identity-store` as **GM-review findings** — never editing, never auto-resolving an ambiguity (mirrors `registry check`)

### Tests for Foundational

- [X] T019 [P] Write `tests/test_provenance_manifest.py` — schema acceptance, every validation rule from T010, and the loud-failure assertion that an unrecognised key raises rather than being ignored (FR-030)
- [X] T020 [P] Write `tests/test_provenance_corrections.py` — schema, the **four** distinguishable consultation states, and an explicit assertion that a correction still attaches when `stale_claim` no longer appears in the file (research D12)
- [X] T021 [P] Write `tests/test_provenance_tiers.py` — precedence order, `tier_ambiguous` population on overlapping globs, `unclassified` returned rather than dropped
- [X] T022 [P] Write `tests/test_provenance_scope.py` — SC-003: no input searches everything. Assert `--campaign` has **no default at any layer** (argparse, model, MCP signature) and that `all`, `*` and `""` are refused as unknown campaign names

### Authored data — DRAFTS for GM review (FR-029)

> These transcribe the **verified** survey in research.md D2/D10/D12 and the worked example
> in `contracts/manifest.md`. They are drafts. T031 is the gate.

- [X] T023 Draft `~/src/campaigns/provenance.yaml` for all six campaigns from `contracts/manifest.md`'s worked example (FR-027) — preserving the three per-campaign deviations a shared template would have broken: stormgiants'/toee's root-level `*_extractions/`, obelisk's `session_(\d+)_` chapter pattern, and out-of-the-abyss's two provenance ranges (research D2, D14). Include the `docs/*.yaml` / `docs/*.json` working-reference globs, and `config/*.yaml` **only** for the three campaigns that have a `config/` directory
- [X] T024 [P] Draft `~/src/campaigns/Phandalin/docs/corrections.yaml` seeded with the `woodland-manse-empty` entry, including the author's note that the stale sentence was regenerated away on 2026-08-05 (incident 1)
- [X] T025 [P] Draft `~/src/campaigns/toee/docs/corrections.yaml` (FR-028) seeded with `calmer-alive-undercover` (incident 2, verified on disk) and `sequioa-zephyr-species-swap` (incident 3) — the latter **must ship `verified: false`** with the evidence note from `contracts/corrections.md`: the swap is not reproducible in `toee/docs/party.md` as of 2026-08-05, and toee has no `characters/` directory to check against
- [X] T026 [P] Draft `~/src/campaigns/obelisk/docs/corrections.yaml` (FR-028) seeded with `naming-authority-is-the-glossary` (incident 4)
- [X] T027 [P] Draft `~/src/campaigns/out-of-the-abyss/docs/corrections.yaml` as `corrections: []` — present-but-empty, so it answers `consulted` rather than `no-record`
- [X] T028 [P] Draft `~/src/campaigns/stormgiants/docs/corrections.yaml` as `corrections: []`
- [X] T029 [P] Draft `~/src/campaigns/Hillsfar/docs/corrections.yaml` as `corrections: []`
- [X] T030 Run `provenance check --campaigns-root ~/src/campaigns` against the drafted `~/src/campaigns/provenance.yaml` and the six `~/src/campaigns/*/docs/corrections.yaml`, and resolve every error-level finding — expect informational `no-identity-store` for stormgiants and Hillsfar (research D10)

### 🚦 Human checkpoint

- [X] T031 **GM REVIEW GATE — BLOCKING.** Present `~/src/campaigns/provenance.yaml` and all six `~/src/campaigns/*/docs/corrections.yaml` files to the GM for ratification. FR-029 requires this data be hand-authored; a drafted transcription is not ratified data until the GM has read it. **No Phase 3+ task may start until this is signed off.** Record the ratification in the commit message.
- [X] T032 Commit the authored data to `~/src/campaigns` as **seven separate commits** — one per campaign for the six `docs/corrections.yaml` files, plus one for root-level `provenance.yaml` — per that workspace's hard no-bundling rule

**Checkpoint**: Manifest ratified and loadable; `provenance check` clean; user stories can begin.

---

## Phase 3: User Story 1 — Where does this fact actually come from? (Priority: P1) 🎯 MVP

**Goal**: Every search hit comes back wrapped in a complete provenance envelope — campaign, path, tier, generated-by stage, chapter, and any recorded correction attached inline — ranked with trust tier as the tiebreak.

**Independent Test**: Search Phandalin for "Woodland Manse". The `docs/world_state.md` hit returns tagged `working-reference` / `generated-by: distill` / `known-stale` with the correction inline, and the authoritative chapter-43 material ranks above it at equal relevance.

### Tests for User Story 1

> Write these first; they must fail before implementation.

- [X] T033 [P] [US1] Write `tests/test_provenance_search.py` — the SC-001 structural assertion that **every hit's key set equals the required set exactly** (data-model.md §6), plus ranking order and the suppression counters
- [X] T034 [P] [US1] Write `tests/test_provenance_scan.py` — excerpt fidelity (verbatim, Constitution IV), `excerpt_encoding: "undecodable"` on the non-UTF-8 fixture, and that `elapsed_ms` + active scanner are reported
- [X] T035 [P] [US1] Write `tests/test_provenance_scanner_parity.py` — `rg` and the Python fallback return an **identical** `(path, line, excerpt)` set **and an identical `suppressed_by_exclude` count** over the fixture workspace and one live campaign (research D1). Must fail without the total-order sort tail
- [X] T036 [P] [US1] Write `tests/test_provenance_rg_flags.py` — assert the pinned flag set, and specifically that a fixture file hidden by `.gitignore` **is still returned**; `.gitignore` must never scope the search (research D17)
- [X] T037 [P] [US1] Write `tests/test_provenance_incidents.py` — SC-002 for **incidents 1–4** (the corrections-backed ones). Assert **labeling**, not stale-string presence (research D12). Incident 1 asserts against a pinned fixture for the mechanism plus the live corpus for the envelope; incident 3 asserts it surfaces as `verified: false` rather than as settled fact. **Incident 5 is not a correction** — it is identity, and its SC-002 coverage lives in T051/T052 (`contracts/corrections.md`, "Incident 5")
- [X] T038 [P] [US1] Write `tests/test_provenance_readonly.py` — the AST write-sentinel guard, the subprocess allow-list (only `rg`, only pinned flags), and the SC-010 before/after sha256 sweep over the fixture workspace (research D16)

### Implementation for User Story 1

- [X] T039 [US1] Define the scanner interface and implementation selection in `provenance/scan.py`: `--scanner` → `rg` if `shutil.which("rg")` resolves → `python`; forcing an unavailable scanner is a **refusal, not a silent fallback**; returns the active impl + version for reporting (research D1)
- [X] T040 [P] [US1] Implement the `rg` scanner in `provenance/scan.py` with the pinned flag set — `--no-config --no-ignore --hidden --json`, `-g '!.git/**'`, one `-g` per `search_extensions`, manifest `exclude` globs as `-g '!…'`, `-F` unless `regex`, `-e` for the pattern, explicit `-i`/`-s` and **never `--smart-case`** (research D17). Must **count** files removed by `exclude` rather than merely skipping them, so T047's `suppressed_by_exclude` has a value (needs a second `rg --files` pass or an equivalent enumeration)
- [X] T041 [P] [US1] Implement `--json` parsing in `provenance/scan.py`: JSON Lines, `match` events, `line_number`, `submatches` offsets, and the `{"bytes": base64}` non-UTF-8 branch mapping to `excerpt_encoding: "undecodable"` rather than `errors="replace"` (research D18, Constitution IV)
- [X] T042 [P] [US1] Implement the stdlib Python fallback scanner in `provenance/scan.py` — `os.walk` + `read_bytes()` + compiled `bytes` regex whole-file fast reject, decoding only surviving lines, honouring the same manifest `exclude` globs so both scanners share one scope declaration, and returning the **same `suppressed_by_exclude` count** as the rg path (covered by the T035 parity test)
- [X] T043 [US1] Implement `ProvenanceEnvelope` in `provenance/envelope.py` with **every field always present** — `null` plus a status field rather than an omitted key (FR-001, data-model.md §6, SC-001). There is **no `date` field**: horizon is chapter-only (data-model.md §7)
- [X] T044 [US1] Implement envelope assembly in `provenance/envelope.py`: tier + `tier_ambiguous` from `tiers.py`, `generated_by` from the manifest's `GeneratedDecl`, `generated_but_hand_edited` when a correction exists for a generated path, `chapter` from the manifest filename pattern only (FR-002, FR-003, research D14)
- [X] T045 [US1] Implement deterministic ranking in `provenance/envelope.py` — `(-relevance, tier_ordinal, campaign, path, line)`, with a comment stating the tail is load-bearing because rg is multithreaded and its file order is unstable (FR-010, research D9, D18)
- [X] T046 [US1] Implement search orchestration in `provenance/search.py`: scope validation → scan → classify → annotate corrections → rank → truncate, emitting `SearchRequest`/`SearchResponse` per data-model.md §12. Populate `backends_consulted` with the `literal` entry (name, status, `impl`, `impl_version`) in this phase — T075 adds the `semantic` entry in US3, so the field ships populated rather than empty
- [X] T047 [US1] Implement the suppression counters in `provenance/search.py` — `suppressed_by_tier` (per tier), `suppressed_by_horizon`, **`suppressed_by_exclude`**, `truncated_by_limit`; a filter that excludes everything returns `hits: []` **with** the counts, never a bare empty list (FR-011, FR-012, SC-005). `suppressed_by_exclude` closes the last silent narrowing: D17 made the manifest's `exclude` globs the single scope authority, so one glob added by a GM must not shrink every future search invisibly (data-model.md §12)
- [X] T048 [US1] Implement `provenance search` text rendering in `provenance/cli.py` — the boxed per-hit layout from `contracts/cli.md` with tier, generated-by and the **correction inside the hit's frame** (FR-004, SC-008), plus the header line carrying counts, `elapsed_ms` and the active scanner
- [X] T049 [US1] Implement `--json` output in `provenance/cli.py` emitting `SearchResponse` verbatim, identical data to the text form

**Checkpoint**: US1 is independently demoable. Run quickstart Scenarios 1, 2, 3, 4, 6, 7, 7b, 8.

---

## Phase 4: User Story 2 — Which name is this, really? (Priority: P2)

**Goal**: Resolve a surface form within a campaign to its canonical entity, aliases and recorded known confusions — and expand a search across aliases — without ever treating name similarity as evidence of identity.

**Independent Test**: `resolve Ilvara --campaign out-of-the-abyss` → `Ilvara Mizzrym`. `resolve Topsy --campaign out-of-the-abyss` → resolved **with an explicit non-identity note for Turvy**. `resolve Vera --campaign obelisk` → `not-found`. `resolve` anything in stormgiants → `no-store`.

### Tests for User Story 2

- [X] T050 [P] [US2] Write `tests/test_provenance_identity.py` covering the three distinguishable states (`resolved` / `not-found` / `no-store`) and asserting `not-found` and `no-store` are never collapsed (FR-017, FR-018, SC-006)
- [X] T051 [P] [US2] Add contract tests over **pinned synthetic registries** in `tests/fixtures/provenance/` for spec Story 2 AS-1 (Vera→Veyra) and AS-2 (KP + the Kostadinious non-identity note) — these Givens are **false on the live corpus** and the fixtures prove the mechanism independent of corpus drift (research D11)
- [X] T052 [P] [US2] Add live-corpus tests to `tests/test_provenance_identity.py` using the confusions that **do** exist — `[Topsy, Turvy]`, `[Barkinar, Deggum]`, `[Meril's Staff, Staff of Birdcalls]`, and rejected pairs `[Corbin, Corwin]`, `[Shoor Vandree, Stool]` — and assert `resolve("Vera", "obelisk")` returns the honest `not-found` (research D10, D11)
- [X] T053 [P] [US2] Add an assertion to `tests/test_provenance_identity.py` that **no string-distance function is used to assert identity** anywhere in `provenance/identity.py` (FR-016)

### Implementation for User Story 2

- [X] T054 [US2] Implement `provenance/identity.py` as a **read-only adapter over the existing `campaignlib.registry` loader** — `load_registry`, `alias_to_canonical()`, `known_names()` (FR-014, FR-032). Do **not** write a second registry parser; a second parser would be a Split-Brain on identity (research D10)
- [X] T055 [US2] Implement `IdentityResolution` in `provenance/identity.py` with the three-state `status` field, per data-model.md §8
- [X] T056 [US2] Map `KnownConfusion` in `provenance/identity.py` onto the two real registry fields, kept distinct: `distinct:` → kind `distinct`, `rejected_aliases:` → kind `rejected-alias` (FR-015)
- [X] T057 [US2] Implement `known_wrong_variants` in `provenance/identity.py` returning `{status: "not-recorded-by-schema"}` — the registry has no such field and wrong variants are stored as ordinary aliases; classifying them by inspection would be the name-similarity reasoning FR-016 forbids (research D10)
- [X] T058 [US2] Implement `provenance resolve` output in `provenance/cli.py` per `contracts/cli.md` — all three states rendered distinguishably, confusions printed as explicit non-identity assertions
- [X] T059 [US2] Implement `--expand-aliases` in `provenance/search.py`: search once per `{canonical} ∪ {aliases}`, set `matched_surface_form` per hit, dedupe on `(campaign, path, line)` keeping the **longest** matched form (FR-019, data-model.md §8)

**Checkpoint**: US1 and US2 both work independently. Run quickstart Scenario 5.

---

## Phase 5: The MCP Seam (delivers US1 + US2 outward — increment 1 completion)

**Purpose**: Expose the two shipped stories through the single outward seam (Constitution V). No new retrieval behaviour — this phase adds a face over the CLI engine (Constitution VI).

- [X] T060 Implement `provenance/provenance_mcp.py` as a thin in-process wrapper calling `provenance.cli.main(argv)` under `redirect_stdout`/`redirect_stderr`, catching `SystemExit`, returning captured output as `str` — the exact pattern of `entity_registry/registry_mcp.py`
- [X] T061 Guard the FastMCP import lazily inside `build_server()` in `provenance/provenance_mcp.py` so the core functions unit-test without the `mcp` package installed
- [X] T062 [P] Implement the `provenance_search` tool in `provenance/provenance_mcp.py` with `campaigns: list[str]` as a **required parameter carrying no default** — the signature must offer no way to express "everything" (FR-006, Constitution X)
- [X] T063 [P] Implement `provenance_resolve` and `provenance_check` tools in `provenance/provenance_mcp.py` per `contracts/mcp.md`
- [X] T064 Write the server `instructions` string in `provenance/provenance_mcp.py` from `contracts/mcp.md` — stating that scope is required, that a `generated_by` hit will be clobbered and may be stale, and that this server never writes
- [X] T065 [P] Write `tests/test_provenance_mcp.py` — every MCP tool has an exactly equivalent CLI invocation (Constitution VI), no tool writes, and an empty `campaigns` list is refused
- [X] T066 Add a `provenance` block to `pipelines/workspace/configure_mcp.py`'s `build_server_block`, gated on the workspace manifest existing and emitted **once per repo root** rather than once per campaign, carrying **no campaign argument** (research D4)
- [X] T067 [P] Add coverage to `tests/test_configure_mcp.py` asserting the `provenance` block is gated on the manifest and contains no `--campaign-dir` or `CAMPAIGN_DIR`
- [X] T068 Register `provenance` in `~/src/campaigns/.mcp.json` alongside the three existing pinned servers, with `"args": []` and no campaign binding

**Checkpoint**: Increment 1 complete. Run quickstart Scenario 10 and verify an unpinned cross-campaign search works without editing `.mcp.json`.

---

## Phase 6: User Story 3 — Can I trust this empty result? (Priority: P3)

**Goal**: Report which campaigns exist and which retrieval backends are live **on the current machine**, so an empty result is never ambiguous.

**Independent Test**: `provenance capabilities` enumerates all six campaigns with manifest / identity-store / corrections status and reports the semantic backend as **unavailable — not installed on this machine**, distinct from "available, returned nothing."

### Tests for User Story 3

- [X] T069 [P] [US3] Write `tests/test_provenance_capabilities.py` — SC-004: an unavailable backend is reported as unavailable with a reason and **never** as zero hits; all six campaigns enumerated with their three status flags (FR-021, FR-023)
- [X] T070 [P] [US3] Add a test to `tests/test_provenance_capabilities.py` asserting every `SearchResponse` carries `backends_consulted`, so a result set is never implied complete (FR-022)

### Implementation for User Story 3

- [X] T071 [P] [US3] Implement the backend roster in `provenance/backends.py` — `{name, status, reason, contributed, impl, impl_version}` with `status ∈ {available, unavailable, not-wired}` (FR-020, data-model.md §11)
- [X] T072 [P] [US3] Implement the per-machine MemPalace probe in `provenance/backends.py` reusing the guarded-import pattern at `pipelines/rlm/mcp_server.py:22-26` plus a palace-directory check — it must report `available` on a host that has it and `unavailable` here (research D15)
- [X] T073 [US3] Implement the `literal` backend entry in `provenance/backends.py` reporting `impl` (`rg`/`python`) and `impl_version`, so the ~60× latency difference is observable rather than tribal (research D1, Principle VIII)
- [X] T074 [US3] Implement `provenance capabilities` in `provenance/cli.py` per `contracts/cli.md` — the resolved workspace root **and which rule resolved it**, the six-campaign table, the backend roster, and the `--no-ignore` note explaining that `.gitignore` does not scope search
- [X] T075 [US3] Wire `backends_consulted` into every `SearchResponse` in `provenance/search.py`, with `contributed: "not-consulted (semantic backend not wired in increment 1)"` for the semantic entry (FR-022)

**Checkpoint**: Run quickstart Scenario 9.

---

## Phase 7: User Story 4 — What did the world look like at chapter N? (Priority: P4)

**Goal**: Filter results to what was true as of chapter N, and label each hit's within-campaign provenance range.

**Independent Test**: Search out-of-the-abyss with a horizon of chapter 15 and confirm no chapter-16+ material returns; run it without a horizon and confirm the later material appears tagged as the AI-assisted range.

### Tests for User Story 4

- [X] T076 [P] [US4] Write `tests/test_provenance_horizon.py` — chapter attribution from the manifest `path_pattern` only, the excluded-hit count (FR-012), and `horizon_disposition: unattributable` surfacing rather than silently dropping a file
- [X] T077 [P] [US4] Add a test to `tests/test_provenance_horizon.py` asserting a horizon request against a campaign with **no** marker is refused, not served unfiltered (FR-025)
- [X] T078 [P] [US4] Add a test to `tests/test_provenance_horizon.py` asserting obelisk's `session_(\d+)_` pattern attributes correctly — the case a shared chapter pattern would silently fail (research D2)

### Implementation for User Story 4

- [X] T079 [US4] Implement chapter attribution in `provenance/envelope.py` from the manifest's `horizon.path_pattern` applied to the **repo-relative path only** — never to file contents, which would be inference and violate FR-029 (research D14). Chapter-only: there is no date branch to dispatch on (data-model.md §7)
- [X] T080 [US4] Implement horizon filtering in `provenance/search.py` with the excluded count reported and unattributable files returned with an explicit disposition (FR-024, FR-012)
- [X] T081 [US4] Implement the horizon refusal path in `provenance/cli.py` for campaigns with no recorded marker (FR-025)
- [X] T082 [US4] Implement `provenance_range` labeling in `provenance/envelope.py` from the manifest's declared ranges; a chapter in no declared range gets `null`, never a guess (FR-026, data-model.md §9)

**Checkpoint**: out-of-the-abyss hits are labeled `gm-written` vs `ai-assisted`.

---

## Phase 8: User Story 5 — Deliberate cross-campaign search (Priority: P5)

**Goal**: Search across campaigns when — and only when — explicitly asked, with every hit labeled by its owning campaign and nothing merged across games.

**Independent Test**: A search naming two campaigns returns hits from each, labeled; the same search with no scope is refused rather than defaulting to all six.

### Tests for User Story 5

- [X] T083 [P] [US5] Write `tests/test_provenance_cross_campaign.py` — hits from each named campaign are returned and labeled, and are **never merged or de-duplicated across campaigns** (FR-008)
- [X] T084 [P] [US5] Add a test to `tests/test_provenance_cross_campaign.py` asserting that two campaigns containing an entity with the same name keep them separate and never assert they are the same entity (spec edge case)
- [X] T085 [P] [US5] Add a test to `tests/test_provenance_scope.py` re-asserting SC-003 at multi-campaign scope: omitting scope entirely is still refused, never materialized as "all"

### Implementation for User Story 5

- [X] T086 [US5] Extend `provenance/search.py` to iterate the explicitly named campaign list, keeping per-campaign result sets separate through ranking so `(campaign, path, line)` ordering holds across campaigns (FR-007 — cross-campaign is reached only by naming N≥2 campaigns, never by a default)
- [X] T087 [US5] Ensure `campaigns_searched` echoes the resolved scope in every `SearchResponse` so the caller sees what actually ran (data-model.md §12)
- [X] T088 [US5] Grep `provenance/cli.py`, `provenance/search.py` and `provenance/provenance_mcp.py` to verify no `all`/`*` scope token was introduced during Phases 3–8; the deliberate cross-campaign act remains naming N≥2 campaigns by hand (Constitution X)

**Checkpoint**: All five user stories independently functional.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T089 [P] Write the operator guide — what the seam is, the trust tiers, how to author the manifest and a corrections record, and the `.gitignore`-is-not-scope rule. **Landed at `docs/cli/provenance_search.md`, not `docs/provenance/provenance_search.md`.** That file already existed (written for the T031 review gate) and is already indexed in `docs/README.md` and `CLAUDE.md`; creating a second copy under a new directory would be a Split-Brain on documentation, and `docs/cli/` is where every other CLI's guide lives. Updated in place to cover the built surface instead.
- [X] T090 [P] Update `docs/mcp/mcp_servers.md` from four servers to five, adding a `provenance` section and noting it is the only **unpinned** one
- [X] T091 [P] Add the operator guide to the doc index in `docs/README.md` and to the detailed-docs table in `CLAUDE.md` — both already point at `docs/cli/provenance_search.md` (see T089)
- [X] T092 [P] Add a "Provenance search" row to the critical-rules section of `CLAUDE.md` stating that render pipelines and consistency checks must prefer authoritative-tier hits over generated ones
- [X] T093 Run the full `python -m pytest tests/ -q` suite and confirm `test_layering.py` and `test_retrieve_render_isolation.py` still pass with the new package present
- [X] T094 Execute every scenario in `specs/007-cross-campaign-search/quickstart.md` end-to-end against the live workspace at `~/src/campaigns` and record the measured p95 for SC-007. **Measured 2026-08-06, rg 15.1.0, 12 runs per cell.** Worst single-campaign p95 over realistic queries: **594 ms** (out-of-the-abyss / "Ilvara", 7,916 matches) against the 2,000 ms budget — **SC-007 PASS**. Every other cell is 13–117 ms. Broad single-term queries are outside the criterion and are recorded because they are large: all six campaigns / "the party" (67,303 matches) 2.3 s; out-of-the-abyss / "the" (232,495 matches) 4.2 s; all six / "the" (551,507 matches) 10.7 s. Cost is linear in *matched lines*, not corpus size — see the ranking note below.
- [X] T095 Verify SC-009 by asserting the feature produces **no** derived artifact — `git status` in `~/src/campaigns` is clean after a full exercise, and the only files the feature added are the hand-authored inputs
- [X] T096 [P] Confirm live-corpus tests skip cleanly when `~/src/campaigns` is absent, so CI and fresh clones stay green
- [X] T097 Verify in any worktree that `python -c "import provenance; print(provenance.__file__)"` resolves to the branch checkout, not the main tree — the editable-install `.pth` shadowing hazard recorded for this repo. Verified: resolves to `/home/kostadis/src/CampaignGenerator/provenance/__init__.py`, which is this branch. **The hazard is unchanged for anyone who does use a worktree** — the `.pth` still hardcodes the main checkout, so a green worktree run is not proof the branch was tested.

### Findings surfaced by the build, for the GM — not fixed here

> Both are the system working: it found problems in hand-authored data and in a
> specified formula. Neither is this feature's to decide (FR-029, FR-031).

- [ ] **F1 — toee's `docs/npcs/` is undeclared.** 104 NPC dossiers written by `planning --build-dossiers` are neither tiered nor declared generated in `~/src/campaigns/provenance.yaml`. Phandalin and stormgiants both declare `docs/npcs/*.md` generated by `planning`; toee does not. So `toee/docs/npcs/calmer.md` — the corpus's live example of "generated AND hand-edited afterward", and the reason incident 2 exists — comes back `tier: unclassified`, `generated_by: null`. Its correction still attaches (path match), so a reader is warned it is stale; what is missing is the warning that the next pipeline run destroys the hand-written banner. `provenance check --campaign toee` already reports it as `unclassified-heavy: docs/npcs/ — 104/104`. Fix is two globs, and it is a manifest edit — GM's call. Pinned by `test_provenance_incidents.py::test_incident_2_exposes_a_gap_in_toees_ratified_manifest`, which fails the day it is closed.
- [ ] **F2 — the relevance formula lets one big file own the whole page.** Research D9 fixes `relevance = matches-in-this-file + 2.0 whole-word + 1.5 heading + 1.0 basename`, and it is implemented exactly. The file term is unbounded while the bonuses are ≤ 4.5, so on this corpus a single large file swamps everything: `search Calmer --campaign toee` returns 200 hits, all from `docs/ensemble/merged.json` (~1,500 matching lines); `search "Woodland Manse" --campaign Phandalin` returns hits only from `docs/NeverwinterExpansionismandtheNorth.md` (~700). Nothing is lost — the header reports what was withheld — and `--tier`, a longer query, or an `exclude` glob all work around it today. A bounded file term (log-scaled, or capped) would restore the bonuses' intended weight, but changing a specified formula is a GM decision, not an implementation one.

### GM action items — outside this feature's write scope (FR-032)

> Deliberately **not** implementable by this task list. Recorded so the gap is visible
> rather than discovered at demo time (research D11). **Both run by the GM on
> 2026-08-06**, at their direction and with them electing the canonical form.

- [X] T098 **WONTFIX — the task is superseded, and the ruling against it predates it.** *Asked for:* register Veyra with alias "Vera" in `~/src/campaigns/obelisk/docs/entity_registry.yaml`, so spec Story 2 AS-1 resolves on the live corpus. *Outcome:* run on 2026-08-06, then **reverted before shipping** (`campaigns` PR #133 carries the reasoning; the commit survives only on the unpushed local branch `kostadis/provenance-manifest`).
  **Why.** `campaigns@f091bf28` (2026-08-01, five days before the run) audited all 377 obelisk entities and set the rule the registry now follows: *"title and short-form variants are legitimate aliases ("Professor Orryn Voss"); **ASR mishearings are not** ("Oren Voss", "Dessa")."* The same commit removed `Dendar` from the Dendrar family's aliases on those grounds and moved `Sister Vera → Veyra` into `notes/vtt_transcription_corrections.md`. `Vera` is a garble — the commit message written for it said so — so registering it would put one back into a registry deliberately cleaned of them, and it is redundant besides: the glossary carries **four** rows for the variant (`Vera`, `Sister Vera`, `veera`, `Melavera`) against one alias.
  **The distinction worth keeping.** A *transcription* variant is repaired before text reaches a pipeline; an *identity* variant is a claim about who someone is. T098 conflated the two; T099 did not, which is why one shipped and the other did not.
  **So `resolve("Vera", "obelisk")` answering `not-found` is correct**, and spec Story 2 AS-1 is not achievable as written without breaking the workspace's own rule. `tests/test_provenance_identity.py::test_live_vera_is_honestly_not_found` asserts the miss and carries the reason, so nobody "fixes" it later.
  **Also invalidated:** the mechanical finding that T098's stated verb (`registry alias`) could not work, because obelisk had no `Veyra` entity. True, and now moot.
- [X] T099 **GM ONLY** — done 2026-08-06: register Kazneporium Ketternopappux and Kostadinious the Sage in `~/src/campaigns/Phandalin/docs/entity_registry.yaml` and mark them distinct, so spec Story 2 AS-2's known confusion resolves on the live corpus.
  **An entity named `KP` already existed** (type `deity`, with a note describing him as a gnome wizard / planar optimizer). The GM chose canonical = the full spelling, matching their own correction note's "the only canonical spelling is Kazneporium Ketternopappux", and elected to keep `type: deity` rather than change it in the same act. Ran: `registry add Phandalin --name "Kazneporium Ketternopappux" --type deity` → `registry merge Phandalin KP --into "Kazneporium Ketternopappux"` (folds `KP` in as an alias, note preserved verbatim) → `registry add Phandalin --name "Kostadinious the Sage" --type npc` → `registry mark-distinct`.
  Ground truth was already on disk: `Phandalin/notes/corrections/kp_identity_attribution.md`, filed 2026-04-20 at the DM's direction, states that KP = Kazneporium Ketternopappux and that Kostadinious the Sage is his **in-world biographer** — the confusion arising from a source file named `KP post Barovia - Kostadinious the Sage.md`, whose (subject–author) filename LLMs read as (alias–true name). Registering it turns a note the model had to re-read each session into a guard the registry enforces.
  Effect on drift: Phandalin's `missing-from-legacy` went 469→471 — the two new entities are not yet in the `aliases.json` projection. `registry project Phandalin` clears it; deliberately not run, since it rewrites a large tracked file.
  **Not done, left for the GM:** the same correction note names `Knazreponnium Ketternopappux` as a live misspelling in `docs/background/Withering Grove.md`. `registry alias Phandalin "Knazreponnium Ketternopappux" --to "Kazneporium Ketternopappux"` would make it resolve.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1. **BLOCKS every user story** — FR-009 refuses any campaign without a manifest entry, so there is no partial start
- **T031 (GM review gate)**: Blocks Phases 3–9 absolutely. FR-029 makes ratification a precondition, not a formality
- **Phase 3 (US1, P1)**: Depends on Phase 2 — the MVP
- **Phase 4 (US2, P2)**: Depends on Phase 2. Independent of US1 except `--expand-aliases` (T059), which needs T046
- **Phase 5 (MCP seam)**: Depends on Phases 3 and 4 — it exposes them. Completes increment 1
- **Phase 6 (US3, P3)**: Depends on Phase 2; T075 touches `search.py` so it wants Phase 3 done
- **Phase 7 (US4, P4)**: Depends on Phase 3 (extends `envelope.py` and `search.py`)
- **Phase 8 (US5, P5)**: Depends on Phase 3
- **Phase 9 (Polish)**: Depends on whichever stories shipped

### Within Each User Story

- Tests written first and failing before implementation
- Models → classification → scanners → envelope → orchestration → CLI rendering
- `provenance/scan.py` (T039–T042) before `provenance/envelope.py` (T043–T045) before `provenance/search.py` (T046–T047) before CLI output (T048–T049)

### Parallel Opportunities

- **Phase 1**: T003–T007 all parallel (distinct files)
- **Phase 2**: T019–T022 parallel (four test files); T024–T029 parallel (six corrections drafts in six campaigns — and they must be six separate commits anyway)
- **Phase 3**: T033–T038 parallel (six test files); then T040–T042 parallel (rg scanner, JSON parsing, Python fallback are separable once T039 defines the interface)
- **Phase 4**: T050–T053 parallel
- **Phase 5**: T062–T063 parallel; T065/T067 parallel
- **Phase 6**: T069–T072 parallel
- **Phases 3 and 4** can run concurrently after T032 if two people are available — US2 only touches `identity.py` until T059
- **Phase 9**: T089–T092 parallel (four doc files)

---

## Parallel Example: User Story 1

```bash
# All six US1 test files, written together before any implementation:
Task: "Write tests/test_provenance_search.py — SC-001 key-set assertion + ranking"
Task: "Write tests/test_provenance_scan.py — excerpt fidelity + encoding + reporting"
Task: "Write tests/test_provenance_scanner_parity.py — rg vs python identical hit sets"
Task: "Write tests/test_provenance_rg_flags.py — pinned flags; .gitignore never scopes"
Task: "Write tests/test_provenance_incidents.py — SC-002, incidents 1-4"
Task: "Write tests/test_provenance_readonly.py — AST guard + sha256 sweep"

# Then the three scanner implementations, once T039 fixes the interface:
Task: "Implement the rg scanner with the pinned flag set in provenance/scan.py"
Task: "Implement rg --json parsing incl. the non-UTF-8 branch in provenance/scan.py"
Task: "Implement the stdlib Python fallback scanner in provenance/scan.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup (T001–T008)
2. Phase 2 Foundational (T009–T032) — **including the T031 GM gate**
3. Phase 3 US1 (T033–T049)
4. **STOP AND VALIDATE**: quickstart Scenarios 1, 2, 3, 4, 6, 7, 7b, 8

US1 alone prevents the entire documented failure class — incidents 1, 2 and 4 all reduce to "a generated file was read as canon," and labeling every hit removes that possibility with nothing else built.

### Incremental Delivery

1. Setup + Foundational → manifest ratified, `check` clean
2. **+ US1** → provenance-labeled scoped search (MVP, demoable at the CLI)
3. **+ US2** → identity resolution and alias expansion
4. **+ MCP seam** → **increment 1 complete** per the GM's ruling; usable from any Claude session without editing `.mcp.json`
5. **+ US3** → trustworthy empty results
6. **+ US4** → chapter horizon and provenance ranges
7. **+ US5** → deliberate cross-campaign search

### Parallel Team Strategy

After T032, one developer takes US1 (Phase 3) and another takes US2 (Phase 4) — they share only `search.py` at T059. Both converge on Phase 5.

---

## Notes

- `[P]` = different files, no dependency on incomplete work
- **Two guards must stay green from T006 onward**: no LLM call anywhere in `provenance/` (FR-033) and no write of any kind (FR-031). If a task seems to require either, the structure is wrong — fix the structure, do not bypass the guard
- **T031 is not a formality.** FR-029 makes the manifest and corrections records hand-authored data; a drafted transcription is not ratified until the GM has read it
- Authored-data commits go to `~/src/campaigns`, one campaign per commit, never bundled
- Commit after each task or logical group; stop at any checkpoint to validate a story independently
