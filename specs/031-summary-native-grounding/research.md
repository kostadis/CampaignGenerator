# Research: Summary-Native Grounding Docs

All decisions below come from walking the existing code with codebase-memory-mcp
(`pipelines/ensemble/synthesise_world_state.py`, `campaignlib/registry.py`,
`campaignlib/api/client.py`, `server/routers/grounding.py`,
`server/grounding_config_shared.py`, `frontend/src/components/layout/AppSidebar.vue`),
plus the issue #499 prototype (`/tmp/campaigngenerator-direct-summary-prototype/pipelines/ensemble/summary_native.py`,
uncommitted, 322 lines) and its retained outputs in
`experiments/20261004-oota-ensemble-summary-prototype/`.

No `NEEDS CLARIFICATION` remained after the spec sessions. The user has already
ruled on three points, and they are recorded as fixed inputs:

- Chapter identity disagreement is a hard failure. There is no override (spec FR-002).
- Validation scans the whole directory and reports everything in one pass (FR-005a).
- The GM can restrict a run to an inclusive chapter range (FR-005c–f).

---

## R1. Where the code lives

**Decision**: a new package `pipelines/summary_native/` exposed through one console
script, `summary_native`, with subcommands: `validate`, `build`, `synth`,
`compare`.

**Rationale**:
- This is a distinct rendering path, so it must not sit inside `pipelines/ensemble/`.
  Putting it there would invite reuse of ensemble outputs, which FR-011 forbids.
- Subcommands follow the existing pattern of `registry` and `thread_registry`: one
  noun with several verbs, and one `[project.scripts]` entry for the server's
  `console_script()` to resolve.
- Splitting deterministic modules from rendering modules lets an AST test prove that
  no deterministic module calls a model. This mirrors `tests/test_block_model_no_llm.py`.

**Alternatives considered**:
- Promote the prototype `pipelines/ensemble/summary_native.py` as-is. Rejected: it
  raises on the first malformed file (FR-005a), lets the filename win over the title
  (FR-002), has no range, uses a positional scene index instead of the declared scene
  id (FR-009), and applies the registry's first-token inference without regard to
  category (FR-013).
- Four separate console scripts, one per stage. Rejected: four `[project.scripts]`
  entries and four sets of shared flags (`--summaries-dir`, `--out-dir`, `--since`, `--until`)
  is a dialect-drift risk under Principle XII.

## R2. Validation is a collector, not a raiser

**Decision**: `validate.scan(paths) -> ValidationReport`. It never raises on content
problems. Each check appends a `Finding(file, line, code, message, expected, found,
blocking)`. Only I/O failures that prevent reading the directory raise.

`build` and `synth` call the same `scan()` first and refuse when
`report.blocking_count > 0`. They print the same report the standalone `validate`
command prints.

Problem codes (stable strings, so tests and the UI can key on them):

| Code | Blocking | Meaning |
|---|---|---|
| `no-numeric-prefix` | yes | filename lacks a leading `\d+` followed by `-`, `_` or `.` |
| `duplicate-chapter` | yes (whole directory) | two files share a prefix number |
| `missing-title` | yes | no `# Chapter N` line |
| `title-chapter-mismatch` | yes | title N ≠ filename prefix |
| `missing-scenes` | yes | no `## Scenes` H2 |
| `empty-scenes` | yes | `## Scenes` has no `###` entries |
| `bad-scene-id` | yes | a `###` under Scenes does not start with `NNN.SS` |
| `scene-chapter-mismatch` | yes | scene id's chapter part ≠ filename prefix |
| `duplicate-scene-id` | yes | the same scene id appears twice in one file |
| `unreadable-file` | yes | the file cannot be read or decoded (OSError / UnicodeDecodeError text in the message); the scan continues with the other files |
| `unknown-section` | no | an H2 not in the recognised set (it is preserved) |
| `possible-duplicate` | no | two same-category headings at or above `dup_threshold`, or equal after a qualifier strip; lists every `file:line` (R7) |
| `stale-ruling` | no | a `canon.yaml` `not_duplicates` pair whose headings occur in no readable summary in the directory (`canon.yaml` is shared across ranges, so the range does not matter) (R7) |
| `range-gap` | no (informational) | a chapter number inside the range has no file |

Out-of-range files are scanned with the same checks. Their findings carry
`in_range=false` and are never blocking, except `duplicate-chapter`, which always
blocks (spec edge case).

**Rationale**: the user asked to fix every problem in one pass. A collector that
compares expected values against found values gives each finding enough detail to
fix it without re-running.

**Alternatives considered**: reusing the prototype's `ValueError` raises with
try/except at file level. Rejected: one problem per file still hides a second problem
in the same file.

## R3. Scene identity

**Decision**: the declared `### NNN.SS Title` id is the `source_scene_id`, stored
verbatim (e.g. `070.03`). The chronology keys on it. Nothing in this pipeline chunks
scenes, so no derived index exists. If a later consumer subdivides scenes, it carries
`source_scene_id` through unchanged (FR-009).

**Rationale**: the prototype minted `summary-native:070:scene:003` from position, and
the DGX prototype's `scene_index` drifted from the H3 when it split long scenes. The
issue names both as defects.

## R4. Where entity observations attach to scenes

**Finding**: in the reference corpus, entity sections (`## NPCs`, …) are appendices
after `## Scenes` and carry no scene reference. So `source_scene_id` is `null` for
every appendix observation, with an explicit `"scene": null` written in the dossier.
That is the spec's "no scene" marker.

**Decision**: the parser records `source_scene_id` only when an entity H3 sits
*inside* a scene body. The current format never does that, but the field and its
test exist so a future format change does not silently drop it. No scene is ever
inferred, for example from a name appearing in scene text (spec edge case).

## R5. Byte-stable output

**Decision**:
- Sort files by chapter number, scenes by declared order within a file, and dossiers
  by `(category, casefold(subject))`.
- Write YAML with `sort_keys=False` from ordered dicts, and JSON with `indent=2` and
  `sort_keys=True`.
- Use `campaignlib.util.atomic_write_text` for every write.
- Put no timestamps in deterministic artifacts. The run time goes only in synthesis
  records, which are not deterministic artifacts.
- Make path fields in artifacts relative to the campaign root, never absolute. The
  prototype wrote `summary.path.resolve()`, which would break byte-equality between
  checkouts.

**Test**: build twice into two temp dirs and compare every file byte-for-byte (SC-002).

## R6. Corpus separation (FR-011)

**Decision**: every output directory is stamped with `manifest.json`, which records
`"kind": "summary_native"` and `"schema": 1`. `build` refuses to write into a
directory that:
- contains a `manifest.json` with a different `kind`; or
- contains any ensemble marker (`merged.json`, `state_dossiers/`,
  `merged_dossiers/`, `facts_*.json`, `extract_*.md`); or
- is non-empty and has no summary-native manifest.

`synth` refuses a `--corpus` directory without the summary-native manifest.

The default output root is `docs/summary_native/`, a sibling of `docs/ensemble/` and
never nested in it. Input files are refused if they live under an ensemble directory.

## R7. Grouping and duplicate detection (FR-013–016)

**GM rulings (2026-10-05):**
- Duplicates are fixed in the raw summary files, never mapped as aliases.
- `canon.yaml` stays separate from the registry. It follows the same model as the
  spell pass's side files: hand-authored and read-only to the tool.
- The registry does not carry spells.

**Category map** (H2 heading → category key → registry type that may supply aliases):

| H2 | category | registry type |
|---|---|---|
| NPCs | npc | npc |
| Locations | location | location |
| Items | item | item |
| Spells | spell | *(none; identical heading only)* |
| Abilities | ability | *(none; identical heading only)* |

**Decision**:
1. **Grouping.** Headings are grouped only by identical text (exact match after
   whitespace trim) within a category. They are also grouped by an explicit registry
   `name`/`aliases` entry whose entity `type` equals the category's registry type.
   The registry's first-token inference (`Registry.alias_to_canonical` turning
   "Kazryn" into "Kazryn Nyantani") is **excluded**. A new helper,
   `Registry.explicit_aliases_by_type()` in `campaignlib/registry.py`, returns
   `{type: {casefold(alias): canonical}}` from existing data. Registry aliases are
   approved alternate names, never misspellings (the `registry-cleanup` rule), so
   using them does not paper over errors.
2. **Detection.** Within each category, the remaining distinct headings are compared
   deterministically: the `difflib.SequenceMatcher` ratio, at or above
   `dup_threshold` (default **0.88**, declared once in `schema.py` and imported by `SummaryNativeRun`, CLI
   `--dup-threshold`, a page control, and recorded in the report header). This is
   the approach already used in `synthesise_facts.detect_clusters`, plus a parenthetical-qualifier strip
   (`"Manshoon (Simulacrum)"` vs `"Manshoon"`). Each hit is a non-blocking
   `possible-duplicate` finding in the validation report. It lists every file and
   line for both spellings, so the GM can fix the summaries in the same pass as
   every other problem.
3. **Rulings.** `canon.yaml` has a single key, `not_duplicates`. Pairs listed there,
   or in the registry's `distinct`/`rejected_aliases`, are not flagged. The file
   cannot express a merge, and the tool never writes it.
4. **Never** merge across categories, and never merge by score.

**Rationale**: a misspelled heading is an error in the source. Mapping it hides the
error and leaves every other consumer of the summaries reading the misspelling.
Fixing the summary corrects it once, for everyone. That is the same reasoning as
`transcript_corrections.yaml` and `/chapter-enhance`'s fix-at-source queue.
Because detection is non-blocking, false positives cost a one-line ruling rather
than a failed run.

**Alternatives considered**:
- An `accepted:` merge mapping in `canon.yaml`, from the first design draft.
  Rejected by the GM: it maps misspellings instead of fixing them.
- Holding the rulings in `entity_registry.yaml`. Rejected by the GM: the registry
  must not carry spells.
- Making possible duplicates blocking. Rejected: similarity is noisy, so every false
  positive would stop a run until it was ruled on.

## R8. Selection (FR-017)

**Decision**: a new pure function `select_dossiers(dossiers, range_end,
recent_chapters, recurring_min) -> Selection`, in the same shape as
`synthesise_world_state.split_dossiers`:
- **recent**: every dossier with `last_chapter >= range_end - recent_chapters + 1`
  (counted from the end of the selected *range*, not from the newest file present).
- **recurring**: the rest with `n_observations >= recurring_min`.

Each selected dossier is recorded in `selection.json` with its reason (`recent` /
`recurring` / `named`), `last_chapter` and `n_observations`.

Defaults come from the prototype: `recent_chapters = 4` and `recurring_min = 10`.
They are declared once, in the config model (R11).

`split_dossiers` itself is not reused. It derives `latest` from the dossiers, which
breaks when a range ends at a chapter with no new entities. The helper is 20 lines,
and a cross-package import of an ensemble module would weaken FR-011's separation
for no gain.

## R9. Synthesis, the API seam, and staging long output (FR-018–023)

**Decision**:
- **One call path.** `make_client`/`client_from_args` → `stream_api`, with backend
  options added through `add_backend_args`. Flags are `--backend --endpoint --model
  --max-tokens`, the same vocabulary as `synthesise_world_state` (Principles V and XII).
- **Declared outline per document.** Each document has an outline shipped in
  `pipelines/summary_native/prompts/<doc>.outline.yaml`, an ordered list of required
  H2 headings.
- **Completeness check that works on every backend.** After each call, a deterministic
  check confirms every declared heading is present, in order, with a non-empty body.
  `stream_api`'s `stop_reason` warning is not enough on its own: non-Anthropic
  backends always report `end_turn` (`campaignlib/api/backends.py:68`,
  `codex_cli.py:171`), so truncation is invisible to them.
  - If the check passes, write `drafts/<doc>.draft.md`.
  - If it fails, write `drafts/<doc>.incomplete.md`, exit non-zero, and name the
    missing headings and the `--parts` remedy.
- **`--parts N|outline`** stages generation explicitly. Each part is one call that
  receives the same context, the outline, and the instruction to write only its
  assigned headings. Parts are joined deterministically. Each part's prompt and
  output are retained. On the Anthropic backend, the shared context is the cached
  system prefix, so repeating it is cheap.
- **Inputs to a draft.** Upstream drafts are passed only through explicit flags:
  `--world-state FILE` for campaign_state/party/planning, and `--campaign-state FILE`
  for party/planning. Nothing reads "the previous step's output" implicitly (FR-020).
- **Tracking files as audit questions.** These are `--audit FILE…` (campaign_state).
  They go in a separately fenced prompt block labelled as audit questions, not
  evidence. The system prompt requires an
  `## Audit: Tracking Claims` section where each claim is tagged
  `SUPPORTED (ch N, scene X)` or `NOT FOUND IN SUMMARIES`.
- **Planning arc scores.** Read from `config/planning.yaml` through the existing
  loader. When there are none, the prompt states "no arc scores configured — leave
  the Threat Tracker empty". A deterministic post-check fails the run if the Threat
  Tracker section contains a score line.
- **Party sources.** `config/party.yaml` + sheets/backstories, using the existing
  `players`/`party` loaders.

**Rationale**: the prototype's world-state call hit Claude Code's per-turn output
ceiling and silently auto-continued. The issue asks for explicit staging. An outline
check is the only completeness signal that every backend shares.

**Alternatives considered**:
- Always one call per section. Rejected as the default: it multiplies context tokens
  by the section count when one call usually fits (the prototype's longest draft was
  41 KB). It stays available through `--parts`.
- Relying on `stop_reason`. Rejected: not reported by most backends.

## R10. Retrieval/render isolation

**Decision**:
- **Deterministic modules call no model.** `validate`, `parse`, `corpus`, `canon`,
  `select`, `compare` and `context` import nothing from `campaignlib.api` and never
  call `stream_api`/`call_api`. An AST test enforces this.
- **Rendering stays separate from context assembly.** `synth.render_part()` calls
  `stream_api`. `context.build_context()` assembles strings and makes no model call.
  The existing `tests/test_retrieve_render_isolation.py` covers the package
  automatically. There is no retrieval call here: the corpus is the human-reviewed
  summaries, read from disk.
- **Constitution III's dossier-proposal gate.** The gate applies to render pipelines
  that consume raw `rpg_retriever` output. This pipeline consumes no retrieval output,
  so `require_approved_proposal` does not apply. That is recorded in the Constitution
  Check.

## R11. Configuration and UI (Principles VI, X, XI, XII)

**Decision**:
- **Config group.** Add a `summary_native: SummaryNativeRun` group to the existing
  strict `GroundingConfig` (`server/grounding_config_shared.py`). Its fields:
  `summaries_dir`, `out_root` (default `docs/summary_native`), `canon_file` and `registry` (`None` = derive: `<out_root>/canon.yaml` / auto-discover), `range_since`/`range_until` (`None` = unset),
  `recent_chapters` (4), `recurring_min` (10), `dup_threshold` (0.88), `parts` (0 = single call),
  and per-doc `output` overrides.
- **No migration needed.** The group is new and every field has a default, so an
  existing `grounding.yaml` still loads and needs no migration (Principle XIII does
  not trigger). This is confirmed by `load_grounding_config` returning defaults for
  absent keys.
- **Reuse existing groups.** Party characters/backstory and the planning config path
  come from the existing `party`/`planning` groups. The `--audit` default comes from the existing
  `campaign_state.track_files`. They are not duplicated
  (Principle XII).
- **Router.** New file `server/routers/summary_native.py`, mounted under
  `/api/grounding/summary-native`. Every run route builds argv through
  `console_script("summary_native")` and streams it with the existing
  `stream_subprocess` SSE helper. Routes take sentinels and resolve from the config
  service at the route edge, the same as `grounding.py`'s `_pick`. A
  `tests/test_summary_native_config_defaults.py` fails the build if a default literal
  appears in the router.
- **Read-only routes.** These serve the validation report JSON (including
  possible duplicates), the list of chapters present (for the range picker), and the list of
  drafts. They read files only.
- **Explicit range in the UI.** The run routes refuse when `since`/`until` are unset. The
  UI "All chapters" button writes the first and last chapters present as explicit
  values (Principle X). The CLI keeps "no range = whole named directory", because a
  typed `--summaries-dir DIR` is an explicit act.
- **Page and sidebar.** A Vue page at `frontend/src/views/grounding/SummaryNative.vue`
  on `/grounding/summary-native`. A fourth `RenderingPath` in `AppSidebar.vue`: id
  `summary-native`, label "Summary-native", description "Parses reviewed session
  summaries directly — no extraction pass.", `usesSharedExtraction: false`.
  Widen the `id` union type to match.
- **No promote button.** Promotion stays a human act at the CLI or in chat
  (Principle IX). The page shows the compare output and the draft path.

## R12. Comparison report (FR-026)

**Decision**: `summary_native compare --draft FILE --live FILE` prints bytes, lines,
the highest chapter mentioned (regex `ch(apter)?\s*\d+`, reported as a heuristic),
and a unified diff written to `drafts/<doc>.vs-live.diff`. It reads only and has no
model call.

## R13. Regression goldens (SC-008)

**Decision**: tests use small synthetic fixture corpora under
`tests/fixtures/summary_native/`. These cover a well-formed corpus, a multi-error
corpus seeded with every blocking code, out-of-range errors, a corpus with gaps, and
alias near-duplicates.

The Out of the Abyss prototype outputs are the qualitative golden. They are already
committed under `experiments/20261004-oota-ensemble-summary-prototype/` (on branch
`experiments/oota-ensemble-summary-prototype`) and in the campaign workspace.
Quickstart step Q7 is a manual GM comparison against them. Nothing compares model
prose automatically, because model output is not byte-stable.

Deterministic corpus counts on the real OOTA directory (67 files, 409 scenes, entity
observation counts) are checked by an opt-in test
(`CG_OOTA_SUMMARIES=/path pytest -m oota`), skipped when the variable is unset.

## R14. Delivery process (user directive)

Delivery follows the user's directive and their recorded preference: Opus
orchestrates, Sonnet codes.

- **Coding.** Implementation is done per phase by `Agent` subagents with
  `model: "sonnet"`, which is Sonnet 5.5 (`claude-sonnet-5-5`).
- **Orchestration.** This Opus 5.5 session writes each phase brief, reviews the diff,
  runs the tests, and commits.
- **Review after each commit.** After every commit, run `/code-review` on that commit
  and fix confirmed findings before the next phase starts.
- **Branch.** Work happens on a feature branch, never `main`. Merging waits for the
  user's go-ahead.
- **Docs.** `docs/cli/summary_native_howto.md` ships with the feature (user
  directive). It is linked from `docs/README.md` and from the "Detailed docs" table
  in `CLAUDE.md`.
