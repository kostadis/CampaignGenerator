---
description: "Task list for 032 — Summary-Native NPC Dossiers"
---

# Tasks: Summary-Native NPC Dossiers

**Input**: Design documents from `specs/032-npc-dossiers-from-summaries/`: plan.md, spec.md, research.md (R1–R16), data-model.md, contracts/cli.md, contracts/http.md, contracts/files.md, quickstart.md (S1–S8).

**Tests**: Included. The plan names each test file, and the repo enforces its rules with guard tests (no-LLM AST walks, router default-literal guards, migrator tests). Write each story's tests before its implementation and confirm they fail first.

**Organization**: One phase per user story, in priority order. The layout migration (FR-022a–d) has no story of its own. It gets its own phase before US6, because publishing writes into the migrated layout.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6 from spec.md
- Paths are repo-relative. Read `contracts/*.md` and `data-model.md` for exact shapes before implementing a task that cites them.

## Conventions every task must follow

- **Model calls:** only through `campaignlib` (`client_from_args`, `stream_api`). Never import `anthropic`.
- **Atomic writes:** every write goes through `campaignlib.util.atomic_write_text`.
- **Determinism:** deterministic artifacts use sorted keys and sorted file order, with no timestamps or absolute paths (same rules as 031 `corpus.py`).
- **Defaults:** declared once, in `pipelines/summary_native/schema.py` (Principle XII).
- **Exit codes:** 0 ok, 1 blocking validation, 2 refusal, 3 incomplete, 4 model failure, 5 verification failed (`npc-verify` only).
- **Worktree caveat:** in a worktree, `import campaignlib` may resolve to the main checkout through the editable install. Run tests with `PYTHONPATH=$PWD python -m pytest …`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Constants, data files and fixtures every story uses.

- [X] T001 Add the 032 constants to `pipelines/summary_native/schema.py`:
  - `DEFAULT_NPC_ROOT = "docs/npcs/summary_native"`, `NPCS_DIR = "docs/npcs"`, `AUTHORED_DIR = "docs/npcs/authored"`, `DISTILLED_DIR = "docs/npcs/distilled"`;
  - link finding codes `ambiguous-form`, `generic-form`, `stale-link-ruling`, `link-ruling-unneeded`, `mention-without-heading` (all non-blocking);
  - `CITATION_RE` and `MANUAL_CITATION_RE` per the grammar in `contracts/files.md`;
  - `NPC_OUTLINE = "npc_dossier"`, `EXIT_VERIFY_FAILED = 5`, and `PUBLISH_HEADER_PREFIX`. Declare that one in `campaignlib/npc.py` as `PUBLISH_HEADER_PREFIX = "<!-- published by summary_native npc-publish"` and re-export it from `schema.py`: `campaignlib` must not import from `pipelines/`, and the T033 guard needs it (one spelling, Principle XII).
- [X] T002 [P] Vendor the SCOWL size-35 American English word list, lowercase entries only, sorted and deduplicated, at `pipelines/summary_native/data/english_words.txt`. Add the SCOWL licence text at `pipelines/summary_native/data/LICENSE.scowl`. Add `pipelines/summary_native/data/*` to package data in `pyproject.toml`, so the editable and installed console script both find it (research R4).
- [X] T003 [P] Create the prompt files:
  - `pipelines/summary_native/prompts/npc_dossier.outline.yaml`, with the seven headings in order: Identity, Personality and Motivations, History with the Party, Last Observed State, Relationships, Notable Quotes, Arc-Score Candidates.
  - `pipelines/summary_native/prompts/npc_dossier.system.md`, carrying every rule in research R9:
    - mention ≠ presence;
    - no status inferred from silence;
    - `UNSUPPORTED:` labels;
    - quotes verbatim from the evidence (any item; superseded wording, see T061);
    - arc candidates as quoted triggers only;
    - a manual edit beats conflicting evidence, and the contradicted claim is not repeated as fact;
    - cite `[manual N]` for each claim from an edit, and use every edit at least once;
    - citation grammar;
    - do not write a header;
    - no secrets section.
- [X] T004 [P] Create the fixture corpus `tests/fixtures/summary_native_npc/`, with a `README.md` that lists each seeded case. It holds `docs/summaries/` (4–5 chapter files in the 031 format), `docs/entity_registry.yaml` and `config/config.yaml`, and seeds these cases:
  - an NPC with entries and scene mentions;
  - a chapter where an NPC is only mentioned in a scene, with no `## NPCs` entry;
  - a moment outside any scene;
  - a first name shared by two registry NPCs (ambiguous);
  - an NPC named `Spider` (generic);
  - a registry NPC with `scope: chapter-3` (local);
  - a creature filed under `## NPCs` with no registry entry;
  - a name inside a longer word, and a lowercase occurrence (neither may link);
  - a registry `location` alias equal to an NPC heading (cross-type ambiguity).
- [X] T005 [P] Create `tests/conftest_npc.py` (imported by the 032 tests) with these helpers:
  - `npc_campaign(tmp_path)`: copies the fixture, runs `summary_native build --since 2 --until 6` through `cli.main`, and returns the campaign root;
  - `run_cli(args)`: returns `(exit_code, stdout, stderr)`;
  - `sha_tree(dir)`: for byte-identity checks.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helpers that two or more stories depend on.

**⚠️ CRITICAL**: No user story can start until this phase is complete.

- [X] T006 Move `_check_fresh` out of `pipelines/summary_native/synth.py` into a new `pipelines/summary_native/freshness.py` as `check_fresh(report, range_dir, root, manifest, registry_path) -> str | None`. Update `synth.py` to import it. `tests/test_summary_native_synth.py` must stay green, with behaviour unchanged.
- [X] T007 [P] Create `pipelines/summary_native/npc_slug.py` (research R6):
  - `slug_for(canonical) -> str`: lowercase, every run of non-alphanumerics becomes `-`, then strip leading and trailing `-`.
  - `stem_for(category, canonical)`: reuse `corpus.dossier_filenames` semantics.
  - `slug_collisions(canonicals) -> dict[str, list[str]]`.
  - Test it in `tests/test_summary_native_npc_slug.py`. Cover `Ilvara Mizzrym` → `ilvara-mizzrym` and a collision pair.
- [X] T008 [P] Extend `pipelines/summary_native/duplicates.py` `load_rulings` so it accepts `link_rulings: [{form, ruling: safe|never}]` alongside `not_duplicates` (research R5). It refuses duplicate forms, other keys and other ruling values, and exposes `Rulings.link_rulings: dict[str, str]`. Update `RULINGS_MESSAGE` to name both record types. Add cases to `tests/test_summary_native_duplicates.py`: valid rulings, a bad ruling value, a duplicate form, and an existing `not_duplicates`-only file that still loads.
- [X] T009 [P] Create `pipelines/summary_native/npc_authored.py`. It is the only module that opens `docs/npcs/authored/` files. It provides:
  - `load_manual(path, subject) -> list[str]`, which never returns or logs `secrets`;
  - `load_secrets(path, subject) -> str`;
  - `read_handbuilt(path) -> str`;
  - `init_authored(path, subject)`, which creates the file and refuses if it exists.
  - Validation is strict (contracts/files.md): `subject` must match, `manual` must be a list of non-empty strings, and unknown keys are refused.
  - Test it in `tests/test_summary_native_npc_authored.py`.
- [X] T010 Extend `tests/test_summary_native_no_llm.py`: add `npc_forms`, `npc_link`, `npc_verify`, `npc_compose`, `npc_publish`, `npc_slug`, `npc_authored` and `freshness` to `GUARDED`. Assert in `test_guard_covers_the_modules_that_exist` that each of them, once it exists, is checked. `npc_draft` is deliberately not guarded, because it is the model step.

**Checkpoint**: Foundation ready.

---

## Phase 3: User Story 1 - See every scene and moment an NPC appears in (Priority: P1) 🎯 MVP

**Goal**: `summary_native npc-link` writes a deterministic linked evidence dossier for every NPC corpus dossier. Each one holds the NPC's entries plus every whole scene and moment that names it, under a computed header. Ambiguous and generic forms are withheld, warned about, and listed in the link report.

**Independent Test**: quickstart S1. On the fixture, run `npc-link` twice and compare byte-for-byte. Check that every seeded case appears where expected.

### Tests for User Story 1

- [X] T011 [P] [US1] Write `tests/test_summary_native_npc_forms.py`:
  - **Forms:** headings plus exact registry name/aliases of type `npc` only; inferred first-token aliases are never used.
  - **Ambiguity** across types: the shared first name, and the location alias.
  - **Generic:** single-token forms found in the word list.
  - **Rulings:** `link_rulings safe` makes a generic form linkable; `never` keeps it withheld.
  - **Refusals and reports:** a ruling on an ambiguous form raises a refusal naming the collisions; `stale-link-ruling` and `link-ruling-unneeded` findings are reported.
  - **Precedence:** ambiguous wins over generic.
- [X] T012 [P] [US1] Write `tests/test_summary_native_npc_link.py`:
  - whole-scene attachment, with `mention_lines` listed and the text verbatim;
  - a moment-block boundary (blockquote, attribution and context kept together);
  - a moment with `scene: none`;
  - ordering: entry, then scenes by id, then moments;
  - case-sensitive, word-boundary matching (`Jimjar's` links; `Jimjarr` and `jimjar` do not);
  - a mention-only chapter included in `chapters` and `last_seen`;
  - no dossier for a heading-less name (it is reported instead);
  - linking applies to every NPC dossier, global or not (FR-012a);
  - the `global`/`exclusion` frontmatter (R1, including `registry scope chapter-3: local`);
  - the run-end warning text on stderr;
  - `link_manifest.json` digests;
  - byte-identical output across two runs;
  - refusals: missing corpus, stale corpus, ambiguous-form ruling, existing output without `--force`;
  - the 031 corpus under `docs/summary_native/` is unchanged.

### Implementation for User Story 1

- [X] T013 [US1] Implement `pipelines/summary_native/npc_forms.py` (research R2, R4, R5; data-model `NameForm`). It provides:
  - `build_form_index(registry, corpus_dossiers, wordlist, rulings) -> FormIndex`, which builds the cross-type ambiguity index without `explicit_aliases_by_type`;
  - `FormIndex.forms_for(stem)`;
  - `FormIndex.withheld()`;
  - `FormIndex.ruling_findings(occurring_forms)`;
  - one combined regex per run, alternation sorted longest-first, case-sensitive with `(?<!\w)`/`(?!\w)` boundaries;
  - `load_wordlist()`, which reads the packaged list and returns `(set, sha256)`.
- [X] T014 [US1] Implement scene and moment item extraction in `pipelines/summary_native/npc_link.py` (research R3):
  - `iter_items(parsed_file) -> list[LinkedItemCandidate]`, using 031 `parse.ParsedFile.scenes` and the `## Memorable Moments` section;
  - a moment starts at a paragraph opening with `>`, `**` or `- `; any other paragraph attaches to the moment before it (research R3, GM ruling 2026-10-06);
  - text is copied verbatim, keeping 1-based file lines.
- [X] T015 [US1] Implement the linker in `pipelines/summary_native/npc_link.py`:
  - `link(files, corpus_range_dir, form_index) -> list[EvidenceDossier]`, which matches forms per item and records `mention_lines` and `forms_matched`;
  - `ComputedHeader` per data-model;
  - R1 `global`/`exclusion`: registry `npc` + `persistent` and not a `players.yaml` `plays` character, otherwise `not in registry`, `registry scope <v>: local` or `player character (players.yaml)` (GM ruling 2026-10-06);
  - `mention-without-heading` findings for forms of registry NPCs that have no corpus dossier.
- [X] T016 [US1] Implement the evidence writers in `pipelines/summary_native/npc_link.py`, following the `contracts/files.md` evidence format:
  - `render_evidence(dossier) -> str`;
  - `write_link_outputs(npc_range_dir, dossiers, findings, digests)`, which writes `evidence/<stem>.md`, `link_report.md`, `link_report.json` and `link_manifest.json` (`kind: npc_link`, corpus manifest, registry, canon and word-list sha256, plus per-evidence sha256).
  - Use the deterministic serialisation rules.
- [X] T017 [US1] Add the `npc-link` subcommand to `pipelines/summary_native/cli.py` (contracts/cli.md):
  - shared flags plus `--npc-root` (precedence: flag > `npc_dossiers.yaml npc_root` > `schema.DEFAULT_NPC_ROOT`) and `--force`;
  - run 031 `scan` first; refuse on blocking problems (exit 1);
  - `corpus.load_manifest`, `freshness.check_fresh`, then link and write;
  - print the summary to stdout and the withheld-forms warning to stderr.
- [X] T018 [US1] Run quickstart S1 against the fixture and record the actual counts in `tests/fixtures/summary_native_npc/README.md`. Note: the OOTA counts in SC-001 come from a scratch script. Re-derive them with this linker on `~/out-of-the-abyss/out-of-the-abyss` and write them into the `## Validation` section of `quickstart.md` before treating them as goldens.

**Checkpoint**: `npc-link` is usable on its own, and the GM can read evidence dossiers.

---

## Phase 4: User Story 2 - Draft a readable dossier per selected NPC (Priority: P1)

**Goal**: `summary_native npc-draft` makes one model call per selected global NPC, over the evidence plus the numbered Manual edits (never Secrets). It writes the fixed-outline draft dossier with the computed header inserted, then composes the GM dossier (draft plus Secrets). `npc-compose` re-composes, and `--init` scaffolds authored files.

**Independent Test**: quickstart S2 and S5 with `--dump-only`, then with a stub client. Check selection and exclusions, the header, the outline, that no secret reaches a prompt, and that the GM dossier holds the Secrets byte-for-byte.

### Tests for User Story 2

- [X] T019 [P] [US2] Write `tests/test_summary_native_npc_draft.py`. Stub the model by monkeypatching `npc_draft.client_from_args` to return a fake client whose output is a canned body.
  - **Selection** (default all; `--all`; `--name`; `--recent-chapters`; `--recurring-min`), with exclusions recorded with reasons: `not in registry`, `registry scope chapter-3: local`, `no evidence in range`, `narrowed out`.
  - **Refusals:** a `--name` that is not global; an empty selection; a missing registry (the message names `registry init` / `registry import-inventory`); stale link output; changed summaries.
  - **Prompts:** the user prompt contains the evidence and the `[manual N]` list.
  - **Header and outline:** the computed header is inserted, and a model-written header is stripped and reported. A missing section writes `.incomplete.md` and exits 3, and the index is not updated.
  - **Records:** the `--dump-only` record and prompts.
  - **Composition:** the GM dossier is composed for drafted and skipped NPCs.
  - **Authored lookup:** each evidence `<stem>` resolves to `docs/npcs/authored/<slug>.authored.yaml` through `npc_slug`. Two selected NPCs that share a slug refuse drafting for both, naming them.
- [X] T020 [P] [US2] Write `tests/test_npc_draft_no_secrets.py`:
  - **AST guard:** `npc_draft.py` never opens `.authored.yaml` itself and reads authored data only through `npc_authored.load_manual`.
  - **Canary test:** a unique `SECRET-CANARY` string in `secrets` appears in no `runs/*/*.system.md`, `*.user.md` or `*.out.md`, and in no `draft/*.md`, but does appear in `gm/<stem>.md` (FR-018a).
- [X] T021 [P] [US2] Write `tests/test_summary_native_npc_compose.py`:
  - the GM dossier is the draft body plus `## Secrets`, with the Secrets byte-for-byte;
  - absent parts render as `_(not yet drafted)_` / `_(none authored)_`;
  - a `subject` mismatch is refused;
  - `--init` creates a file and refuses when one exists;
  - a hand-edit to `gm/<stem>.md` triggers the "unrecorded hand-edit" warning on recompose;
  - sources are never modified.

### Implementation for User Story 2

- [X] T022 [US2] Implement selection in `pipelines/summary_native/npc_draft.py`:
  - `select_global(evidence_dossiers, named, recent_chapters, recurring_min, all_flag) -> DraftSelection` (data-model);
  - reuse 031 `select.select_dossiers` for the recent and recurring reasons, applied only to global NPCs;
  - record every exclusion with its reason;
  - refuse an empty selection and an ineligible `--name`.
- [X] T023 [US2] Implement prompt building in `pipelines/summary_native/npc_draft.py`:
  - `build_prompt(evidence_md, header, manual: list[str]) -> (system, user)`;
  - the system prompt comes from `prompts/npc_dossier.system.md`;
  - the user prompt is the read-only header + the evidence verbatim + a `GM MANUAL EDITS` block (`[manual N] text`, or `(none)`) + the outline instruction;
  - the draft key is `sha256(json.dumps({system_sha, user_sha, backend, model, max_tokens}, sort_keys=True))` (research R8).
- [X] T024 [US2] Implement the draft loop in `pipelines/summary_native/npc_draft.py`, mirroring 031 `synth.run_synth`'s run directory, record and failure handling:
  - before any model call, map each selected `<stem>` to its `<slug>` with `npc_slug.slug_for(canonical)`, refuse on `slug_collisions` (exit 2, both names), and load Manual edits through `npc_authored.load_manual(AUTHORED_DIR/<slug>.authored.yaml, subject)`; a missing file means no edits;
  - one `render_part` per NPC;
  - `synth.check_outline` against `npc_dossier.outline.yaml`;
  - strip a model-written header;
  - write `draft/<stem>.md` (provenance comment + computed header + body) or `draft/<stem>.incomplete.md`;
  - `runs/<stamp>/` holds `selection.json`, `record.json` (`DraftRecord`), and per NPC `<stem>.system.md`, `.user.md` and `.out.md`;
  - `--dump-only` makes no client call;
  - a model failure exits 4 and records where it stopped.
- [X] T025 [US2] Implement `pipelines/summary_native/npc_compose.py`:
  - `compose_gm(draft_path, authored_path, out_path)` follows `contracts/files.md` "GM dossier", with header shas, and uses `npc_authored.load_secrets`;
  - hand-edit detection compares the existing file's body against its recorded `composed sha256`;
  - `compose_many(...)` takes a names list or all;
  - `init(names)` delegates to `npc_authored.init_authored`.
- [X] T026 [US2] Add the `npc-draft` and `npc-compose` subcommands to `pipelines/summary_native/cli.py` (contracts/cli.md):
  - `npc-draft` takes the selection flags (`--name`, `--all`, `--recent-chapters`, `--recurring-min`, with `--all` mutually exclusive with narrowing), `--model`, `--max-tokens`, `add_backend_args`, `--dump-only` and `--force`;
  - resolve the model with `resolve_cli_model` as `_synth` does;
  - `npc-draft` calls `compose_gm` for every selected NPC after drafting or skipping;
  - `npc-compose` takes `--name` and `--init`.

**Checkpoint**: US1 + US2 make the MVP. The GM can draft, read and hand-review NPC dossiers.

---

## Phase 4b: Chunked drafting and the Spark default (FR-013, research R17; GM rulings 2026-10-06)

**Goal**: `npc-draft` drafts in chunked mode by default on the local Spark model, with one-shot kept as `--mode one-shot`. Code checks every map output before anything reaches the reduce call.

**Independent Test**: on the fixture with a stub client, chunked mode makes N map calls plus 1 reduce call, drops a seeded bad citation and a seeded scene-dialogue quote with logged reasons, and assembles a dossier that passes the outline check. On `oota-copy`, `--dump-only` writes the map prompts for Jimjar with the expected chunk ranges.

- [X] T059 [US2] Add the drafting defaults to `pipelines/summary_native/schema.py`, declared once: `DEFAULT_DRAFT_BACKEND = "dgx"`, `DEFAULT_DRAFT_MODEL = "qwen3.8-flash-next"`, `DEFAULT_DRAFT_MODE = "chunked"`, `DRAFT_MODES = ("chunked", "one-shot")`, `DEFAULT_CHUNK_CHARS = 60000`. No endpoint constant: the dgx endpoint resolves through campaignlib's existing chain. Extend the interim `npc_dossiers.yaml` reader in `cli.py` to read a `draft:` block (`backend`, `model`, `mode`, `chunk_chars`); precedence flag > `npc_dossiers.yaml` > schema. Unknown keys under `draft:` refuse.
- [X] T060 [P] [US2] Write `tests/test_summary_native_npc_chunked.py` (stub client; tests first):
  - chunking: whole chapters only, in order, packed to the limit; an oversize chapter is its own chunk; deterministic;
  - map check: drops a History bullet with no citation, one citing a target outside its chunk, a quote not in the chunk's evidence (a quote from a scene body is KEPT: GM ruling, quotes may come from any evidence item), and an arc candidate with a bad citation; keeps a quote that differs only in curly/straight marks and records it as `typography-normalised`; every drop is in `<stem>.drops.md` with its text and reason;
  - attribution parsing: inside the blockquote, on the next line, on the same line, and two pairs on one line (use the four real lines from the prototype: the in-blockquote Jorlan attribution, the plain-line Jimjar attribution, the same-line Buppido excerpt and the same-line "I don’t hear…" pair);
  - stitch keeps chapter order and removes exact duplicates only;
  - the reduce prompt carries the stitched notes plus only the last chunk's evidence, and the manual edits; the map prompts carry the manual edits; no Secrets anywhere (extend the T020 canary to map and reduce files);
  - assembly is in outline order and passes `check_outline`; a missing reduce section gives `.incomplete.md` and exit 3;
  - `--mode one-shot` behaves exactly as before (existing US2 tests stay green);
  - the draft key changes with `mode`, `chunk_chars` or any prompt;
  - `--dump-only` in chunked mode writes the map prompts and makes no call;
  - defaults: with no flags and no config, the record says backend `dgx`, model `qwen3.8-flash-next`, mode `chunked`.
- [X] T061 [US2] Create `prompts/npc_dossier.map.system.md` and `prompts/npc_dossier.reduce.system.md`. Both carry the R9 rules. Add to all three system prompts (one-shot, map, reduce): quotes are copied verbatim from anywhere in the evidence (entry, scene or moment) and cite the item they come from; they are **about** the NPC and may be spoken by anyone; each names its speaker exactly as the evidence gives it, never a placeholder such as `Speaker`. Remove "from moments only" / "never quote a scene body" from the existing one-shot prompt.
- [X] T062 [US2] Implement chunked mode in `pipelines/summary_native/npc_draft.py` (or a new `npc_chunked.py` for the deterministic parts: chunking, map check, stitch, assembly — guarded no-LLM, added to `GUARDED`): research R17 exactly. The map check reuses the US3 quote and citation primitives once they exist; until then put them in the guarded module and have `npc_verify` import them (one implementation). Run files per data-model. A model failure on any map or reduce call exits 4 and records where it stopped.
- [X] T063 [US2] Re-run on `oota-copy` with the default flags (Spark, chunked) for Jimjar, Ilvara Mizzrym and Eldeth Feldrun. Record citations, quotes kept/dropped by reason, and wall-clock in `quickstart.md ## Validation`, and compare with the prototype's numbers (253 / 100 / 121 citations; 34 / 8 / 3 quotes, which were filtered to moments only, so report quotes by source item). Copy the drafts to `My Drive/NPC Dossier Drafts (spec 032)/<name> - Spark chunked (pipeline).md`.

**Checkpoint**: chunked Spark is the default and matches the prototype.

---

## Phase 5: User Story 3 - Trust a draft: citations, quotes and manual edits checked mechanically (Priority: P2)

**Goal**: `summary_native npc-verify`, and the verification step at the end of `npc-draft`, report invalid and outside-evidence citations, non-verbatim quotes, uncited history bullets, dropped manual edits and invalid `[manual N]` citations. Deterministic, never edits a draft.

**Independent Test**: quickstart S3 and the dropped-edit bullet of S5. Seed each defect into a draft and expect exit 5 with each defect listed. A clean draft gives exit 0.

### Tests for User Story 3

- [X] T027 [P] [US3] Write `tests/test_summary_native_npc_verify.py`. One test per status:
  - `invalid` (scene id absent from the corpus);
  - `outside-evidence` (real scene, not in this NPC's pack);
  - `not-found` quote (one changed character other than a quote mark or apostrophe);
  - `typography-normalised` advisory (differs only in curly/straight marks; verdict stays pass);
  - a Notable Quote taken from a scene body passes (quotes may come from any evidence item);
  - `uncited` history bullet;
  - a label bullet with every nested bullet cited passes; a label with one uncited nested bullet reports that nested bullet;
  - manual `dropped` (an edit with no `[manual N]`) and manual `invalid` (`[manual 4]` with only 3 edits);
  - a clean draft passes with totals;
  - the report carries the fixed "used, not meaning" note and pairs each edit with its cited passages;
  - an advisory `status-claim-unsupported` ("killed" in Last Observed State, absent from the evidence) is reported but leaves the verdict at pass;
  - the draft file is unchanged;
  - `npc-verify` exits 5 on failure and 2 when there are no drafts;
  - the verdict appears in `record.json` after `npc-draft`.

### Implementation for User Story 3

- [X] T028 [US3] Implement `pipelines/summary_native/npc_verify.py` (research R10; data-model `VerificationResult`):
  - `verify(draft_text, evidence_dossier, corpus_index, summaries_text, manual) -> VerificationResult`;
  - citation parsing with `schema.CITATION_RE` and `MANUAL_CITATION_RE`;
  - quote extraction (blockquote lines under Notable Quotes, plus `"…"`/`“…”` spans) checked with `campaignlib.textproc.locate_quote`, with curly/straight quote marks and apostrophes compared as equal and reported as `typography-normalised`; attribution lines are split off in all three placements (shared with T062's map check, one implementation);
  - nested History bullets: a parent with nested bullets is a label and needs no citation when all its nested bullets are cited;
  - the advisory status-word check from research R10, reported under `advisories`, never in the verdict;
  - `render_verify_md(result)`, which writes `draft/<stem>.verify.md`.
- [X] T029 [US3] Wire verification into `npc_draft.py`: after each NPC, write `<stem>.verify.md`, put the verdict into `record.json`, and print the per-NPC warning for dropped edits. Also add the `npc-verify` subcommand (`--name`; exit 5 on any fail) to `pipelines/summary_native/cli.py`.

**Checkpoint**: Every draft carries a mechanical trust report. Spark and Claude drafts become comparable (quickstart S3, Spark A/B).

---

## Phase 6: Layout migration — `docs/npcs/{authored,distilled,summary_native}` (FR-022a–d, Constitution XIII)

**Purpose**: Move existing `docs/npcs/` contents under GM control, and repoint every distilled-dossier reader. This blocks US6, because publishing writes into the migrated layout. It is independent of US1–US3.

### Tests for the migration

- [X] T030 [P] Write `tests/test_migrate_npc_dossiers.py`, modelled on `tests/test_migrate_wiring.py`.
  - **`--propose`**, on a temporary git repo built in the test:
    - a marked file is `distilled`;
    - sidecars and state files are `distilled`;
    - an unmarked file is `unknown`;
    - commit wording never sets a disposition (a commit titled "Eelrich Vane NPC" still yields `unknown`);
    - a file changed since it was added is flagged `hand-edited`;
    - outside git, the evidence is `unavailable`;
    - output is deterministic;
    - `nothing to classify` on a migrated campaign.
  - **`--apply`:**
    - it refuses while any entry is `unknown`;
    - it refuses on sha drift after propose;
    - it refuses an existing target without `--force`;
    - it moves `distilled` and `authored` entries byte-identical;
    - the `grounding.yaml` `planning.dossiers.dossier_dir` rewrite and the `planning.yaml` `npcs[].dossier` rewrites preserve comments;
    - out-of-tree values are reported, not changed;
    - the closing message mentions `npc-publish --authored-all`;
    - `--help` runs as a module.
- [X] T031 [P] Write `tests/test_no_loose_dossier_reads.py`.
  - Every reader in the R12 table goes through `campaignlib.npc.refuse_unmigrated_dossier_dir`, and no in-repo dossier reader uses `rglob` on a `docs/npcs` path.
  - The guard refuses: a loose `.md` without the publish header (unmigrated); and `docs/npcs` itself as the configured directory. Each refusal names the migration command.
  - The guard does **not** refuse: a campaign whose `docs/npcs/` holds only published files and has no `distilled/` (the OOTA case); or a campaign with no `docs/npcs/` at all. Both read as "no distilled dossiers".
- [X] T032 [P] Write `tests/test_no_writes_to_authored.py`, an AST and behaviour guard. No module in `pipelines/summary_native/` writes, renames or deletes under `docs/npcs/authored/` except `npc_authored.init_authored`. Running link, draft, compose, verify and publish over a fixture seeded with `docs/npcs/authored/` and `docs/npcs/distilled/` files leaves both byte-identical (SC-005, FR-022).

### Implementation for the migration

- [X] T033 Add `refuse_unmigrated_dossier_dir(path)` to `campaignlib/npc.py` (research R12 guard). "Unmigrated" means a loose `docs/npcs/*.md` whose first line does not start with `schema.PUBLISH_HEADER_PREFIX`, and the guard also refuses `docs/npcs` itself as the target. A missing `distilled/` with nothing unmigrated is not an error. Use `campaignlib.npc.PUBLISH_HEADER_PREFIX` (declared in T001). Call the guard at the top of `load_alias_map` when `dossier_dir` is given.
- [X] T034 [P] Repoint `server/grounding_config_shared.py` so that `DossierBuild.dossier_dir` defaults to `"docs/npcs/distilled/"`. Update `tests/test_grounding_config_service.py` and `tests/test_grounding_routes_config.py` to match.
- [X] T035 [P] Repoint `pipelines/grounding/planning.py`:
  - the default `--dossier-dir` comes from `DossierBuild.dossier_dir`, replacing the `cwd/npcs` fallback at `planning.py:912`;
  - call `refuse_unmigrated_dossier_dir`;
  - make the flat glob at `:385` skip `.new_notes.` files, as `load_alias_map` does.
  - Update `tests/test_planning.py` and `tests/test_planning_routes.py`.
- [X] T036 [P] Repoint `entity_registry/resolve.py` (`DOSSIER_REL` becomes `docs/npcs/distilled`, plus the guard) and `entity_registry/registry.py` `check` (`docs/npcs/distilled/.dedup_state.json` and the dossier dir at `:1004` and `:1071`, plus the guard). Update `tests/test_resolve_name.py`, `tests/test_registry.py` and `tests/test_registry_import.py`.
- [X] T037 [P] Repoint `server/platform_config_service.py` `discover_campaign_paths` (`:1148`) to `docs/npcs/distilled`, with the guard. Update `tests/test_platform_config_service.py`.
- [X] T038 [P] Update the frontend fallbacks from `'docs/npcs/'` to `'docs/npcs/distilled/'` in `frontend/src/views/grounding/PlanningDocument.vue` (`:57`, `:64`) and `frontend/src/views/prep/ConnectionGraph.vue` (`:341`).
- [X] T039 Implement `server/migrate_npc_dossiers.py` (contracts/cli.md "Migration", contracts/files.md "Migration classification", research R12):
  - **`--propose`**: git evidence via read-only `git log --follow` / `git diff --quiet` with `subprocess.run`, and the proposal rules;
  - **`--apply`**: re-hash every entry; refuse on `unknown`, drift or target conflicts; move with `os.replace`; make line-level, comment-preserving config rewrites;
  - report the external references (`~/src/campaigns/provenance.yaml`, gm-npc-build per kostadis/campaigns#370, `/dossier-merge`, `vtt-spell-pass`, `consistency-check`);
  - print the closing `--authored-all` notice.
- [X] T040 Write `specs/032-npc-dossiers-from-summaries/migration.md` and `docs/cli/npc_dossiers_migration.md`, following Constitution XIII's required contents: what changed shape; affected workspaces (toee, stormgiants with files; Phandalin, out-of-the-abyss, obelisk config-only); the exact commands; what happens to a workspace that never migrates (readers refuse with the command); and how to verify (quickstart S6). Also cover the classification workflow, the post-apply `npc-publish --authored-all` step, the recursive search tools that will see Secrets, and the external follow-ups (#370, provenance.yaml globs).

**Checkpoint**: Run quickstart S6 on worktree copies of toee and stormgiants. The full test suite passes with the repointed readers.

---

## Phase 7: User Story 6 - Publish reviewed dossiers where the GM's skills read them (Priority: P2)

**Goal**: `summary_native npc-publish` is an explicit, deterministic GM act and the only writer of `docs/npcs/<slug>.md`. It publishes a GM dossier (`[manual N]` becomes `[GM]`, chapter citations kept, Secrets included) or a hand-built `authored/<slug>.md` verbatim, under a provenance header, with refusals.

**Independent Test**: quickstart S8. Publish Jimjar and check the header, that no `[manual N]` remains, and that the Secrets are present. Then check each refusal path and `--authored-all`.

### Tests for User Story 6

- [X] T041 [P] [US6] Write `tests/test_summary_native_npc_publish.py`:
  - **Selection:** no selection refuses; `--name`, `--all` and `--authored-all` each work.
  - **Summary-native source:** header fields per contracts/files.md; `[manual N]`→`[GM]` everywhere; chapter citations unchanged; Secrets present.
  - **Hand-built source:** copied verbatim, with a `source: hand-built` header.
  - **Refusals:** both sources without `--source`; failed verification (`--force` publishes with `verify: fail(forced)`); a foreign target with no header; a hand-edited target whose sha differs from `publish_log.json`; a slug collision.
  - **Log and side effects:** `publish_log.json` contents; publishing never deletes; nothing outside `docs/npcs/<slug>.md` and `publish_log.json` changes; exit 2 with the passing NPCs still published.

### Implementation for User Story 6

- [X] T042 [US6] Implement `pipelines/summary_native/npc_publish.py` (research R16; data-model `PublishedDossier`). It provides `plan_publish(...)` (resolve sources and refusals), `rewrite_manual_citations(text)`, `render_published(source, body, facts) -> str`, `read_publish_log` / `write_publish_log` (`docs/npcs/summary_native/publish_log.json`) and `publish(...)`. It uses `npc_slug` for slugs and collisions, and `npc_authored.read_handbuilt` for hand-built sources.
- [X] T043 [US6] Add the `npc-publish` subcommand to `pipelines/summary_native/cli.py`: `--name`, `--all`, `--authored-all`, `--source summary_native|hand-built` and `--force`. Per-NPC stdout as in contracts/cli.md; exit 0 or 2.

**Checkpoint**: Published dossiers appear in `docs/npcs/` and the gm-assistant skills read them unchanged.

---

## Phase 8: User Story 4 - Re-draft only what changed (Priority: P3)

**Goal**: Re-runs skip NPCs whose draft key is unchanged. Secrets-only edits re-compose without a model call. `--force` re-drafts everything.

**Independent Test**: quickstart S4 and the Secrets-only bullet of S5.

- [X] T044 [P] [US4] Add incremental tests to `tests/test_summary_native_npc_draft.py`:
  - a second run skips everything as `unchanged`;
  - editing one summary that mentions one NPC (then rebuild and re-link) re-drafts only that NPC;
  - a change to the template, backend, model or `max_tokens` re-drafts;
  - a Manual edit change re-drafts, while a Secrets-only change skips but updates `gm/<stem>.md`;
  - `--force` re-drafts all;
  - an incomplete output never updates `draft/index.json`.
- [X] T045 [US4] Implement `draft/index.json` read and write, plus the skip logic, in `pipelines/summary_native/npc_draft.py` (research R8). Print a per-NPC `drafted | skipped (unchanged)` reason.

**Checkpoint**: Large selections are cheap to re-run.

---

## Phase 9: User Story 5 - Run the stages from a dedicated NPC dossiers page (Priority: P3)

**Goal**: A new NPC dossiers page and router, separate from Grounding, that runs link, draft, verify, compose and publish through the CLI with explicit arguments. Config lives in `<config>/npc_dossiers.yaml`.

**Independent Test**: quickstart S7. Files match the CLI runs. Draft and publish refuse without an explicit selection, and Grounding → Summary-native shows no NPC stages.

### Tests for User Story 5

- [X] T046 [P] [US5] Write `tests/test_npc_dossiers_config_defaults.py`: there are no default literals in `server/routers/npc_dossiers.py` (same pattern as `tests/test_summary_native_config_defaults.py`). `npc_dossiers.yaml` is strict, so an unknown key returns 422. `summaries_dir`, `registry` and `canon_file` are not declared in the new model (Principle XII).
- [X] T047 [P] [US5] Write `tests/test_npc_dossiers_routes.py`, modelled on `tests/test_summary_native_routes.py`:
  - each `_build_*_cmd` produces the exact argv in contracts/http.md, including the backend/model flags from `selection_cli_args`;
  - 400 responses with no spawn for a missing range, a missing draft `select` and a missing publish `select`;
  - the `/state` shape, read from disk only;
  - `/file` is read-only;
  - no route writes `authored/`.

### Implementation for User Story 5

- [X] T048 [P] [US5] Create `server/npc_dossiers_config.py`:
  - a strict Pydantic model (`npc_root`, `recent_chapters`, `recurring_min`, `max_tokens`, `selection`, and a strict `draft` block: `backend`, `model`, `mode`, `chunk_chars`), with defaults imported from `schema.py`; supersede T059's interim reader;
  - `NpcDossiersConfigService`, mirroring `server/party_config_service.py`, including `get_selection()`, so `_selection_for`-style backend/model overrides work;
  - make `cli.py` read `npc_root` from `npc_dossiers.yaml`.
- [X] T049 [US5] Create `server/routers/npc_dossiers.py` at `/api/npc-dossiers` (contracts/http.md):
  - `GET`/`PUT /config`, `/chapters` (shared helper with summary_native), `/state`, `/report/link`, `/report/verify/{stem}` and `/file`;
  - SSE `/run/link`, `/run/draft`, `/run/verify`, `/run/compose` and `/run/publish`, using `stream_subprocess(console_script("summary_native"), …)`;
  - defaults resolved at the route edge from `NpcDossiersConfigService` and `GroundingConfigService.resolved().summary_native`.
  - Include the router in `server/main.py`.
- [X] T050 [P] [US5] Add the frontend route and sidebar entry:
  - in `frontend/src/router.ts`, `/npcs/dossiers` maps to `views/npcs/NpcDossiers.vue`;
  - in `frontend/src/components/layout/AppSidebar.vue`, add a new top-level "NPCs" path (`id: 'npcs'`, `matchPrefixes: ['/npcs']`), separate from Grounding, and add it to the id union at `:172`;
  - widen the `doc` union in `frontend/src/composables/useGroundingRun.ts`, or add a sibling `useNpcDossierRun.ts`.
- [X] T051 [US5] Create `frontend/src/views/npcs/NpcDossiers.vue` with seven sections:
  1. range picker;
  2. Link (warning badge and link-report table);
  3. Draft (explicit selection mode required, backend/model, dump-only, force);
  4. per-NPC state table from `/state` (draft status, verify verdict, dropped manual edits, authored present);
  5. Verify;
  6. Compose (`--init` for chosen NPCs);
  7. Publish (named, all or all hand-built, plus `--source` and `--force`, showing each refusal).
  - Use `RunPanel` and `PathField`. All file views are read-only.
- [X] T052 [US5] Extend `frontend/e2e/sidebar-navigation.spec.ts` with the new NPCs path, and assert that the Grounding → Summary-native page has no NPC stages.

**Checkpoint**: Every CLI capability of this feature has a face (Constitution XI), including the Publish button (GM ruling: publish exists in both places), except the migration, which follows the out-of-band precedent. Config-only paths are reachable through `PUT /config`, and a config-management page is tracked in #502.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T053 [P] Write `docs/cli/npc_dossiers_howto.md`, task-oriented, in the style of `docs/cli/summary_native_howto.md`:
  - link → draft → verify → compose → publish;
  - writing authored files;
  - ruling on generic forms;
  - reading a verify report, including the "used, not meaning" caveat;
  - Spark A/B;
  - every refusal and exit code decoded.
- [X] T054 [P] Update the `CLAUDE.md` doc table and `docs/README.md`. Add rows for `npc_dossiers_howto.md` and `npc_dossiers_migration.md`, and add a critical-rules note that `docs/npcs/` holds only published dossiers, `authored/` is never written by a tool, and only `npc-publish` writes `docs/npcs/<slug>.md`.
- [X] T055 [P] Update `docs/core/architecture.md` with the NPC dossier pipeline (link → draft → verify → compose → publish) and the `docs/npcs/` layout.
- [X] T056 Run the full suite: `PYTHONPATH=$PWD python -m pytest tests/`. Then run `cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts`. Fix any regressions in the repointed readers.
- [X] T057 Run quickstart S1–S8 end to end against a worktree copy of the OOTA workspace and of toee. For SC-005a, on worktree copies of toee and stormgiants, capture three deterministic, model-free outputs **before** the migration: `registry check`; `load_alias_map(<dossier dir>)` serialised with sorted keys; and the prompt written by `planning --dump-input /tmp/plan.md --dump-only`. Do not use `--build-dossiers`, which calls a model. Capture them then again after `--propose`/`--apply` with the readers repointed. Diff them and record the result. Any difference is a finding for the GM, not something to adjust silently. Record the actual numbers (SC-001 counts, link time, verify results) in `quickstart.md` under `## Validation`. Note any spec deviation for the GM; do not silently adjust.
- [ ] T058 Reinstall the console script into the server venv (`uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`), so the UI can spawn the new subcommands and the packaged word list resolves (CLAUDE.md "editable-installed" rule).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)** → **Foundational (Phase 2)** → everything else.
- **US1 (Phase 3)**: needs Phase 2. This is the MVP base.
- **US2 (Phase 4)**: needs US1, because drafting reads evidence dossiers.
- **Phase 4b (chunked drafting)**: needs US2. Its map check shares quote/citation primitives with US3 (one implementation).
- **US3 (Phase 5)**: needs US2's draft outputs; its tests can be written alongside US2 and Phase 4b.
- **Migration (Phase 6)**: needs only Phase 2 (`npc_slug`, `npc_authored`). It can run in parallel with US1–US3.
- **US6 (Phase 7)**: needs US2 (GM dossiers), US3 (verify verdict, used in refusals) and the migration (layout).
- **US4 (Phase 8)**: needs US2.
- **US5 (Phase 9)**: needs every CLI stage (US1, US2, US3, US6, US4).
- **Polish (Phase 10)**: last.

### Within each story

Tests first, written to fail. Then: modules, then CLI wiring, then the checkpoint run.

### Parallel opportunities

- **Phase 1:** T002, T003, T004 and T005 together.
- **Phase 2:** T007, T008 and T009 together, after T006.
- **US1:** T011 and T012 together, before T013–T017.
- **US2:** T019, T020 and T021 together.
- **Migration:** T030, T031 and T032 together; then the repointing tasks T034–T038 together (different files), after T033.
- **Cross-phase:** the whole migration phase can be handed to a second implementer while US1–US3 proceed.
- **US5:** T046, T047, T048 and T050 together.

## Parallel Example: Migration phase alongside US1

```text
Implementer A (US1):        T011, T012 → T013 → T014 → T015 → T016 → T017 → T018
Implementer B (migration):  T030, T031, T032 → T033 → [T034, T035, T036, T037, T038] → T039 → T040
```

## Implementation Strategy

### MVP first (US1 + US2)

1. Phases 1–2.
2. US1: `npc-link`. Validate S1 and re-derive the SC-001 counts on OOTA.
3. US2: `npc-draft` + `npc-compose`. Validate S2 and S5 with `--dump-only`, then with a real backend on two or three NPCs.
4. **Stop and review with the GM:** read the drafts before building trust tooling on top.

### Incremental delivery

5. US3, verification (makes the Spark-versus-Claude comparison meaningful).
6. Migration, run per campaign by the GM (`--propose`, review, then `--apply`).
7. US6, publishing. After the migration, run `npc-publish --authored-all`, then publish the reviewed summary-native NPCs.
8. US4, incremental re-drafting.
9. US5, the UI page.
10. Polish.

### Orchestration (GM instruction: Sonnet implements, Opus orchestrates)

- **Opus**, in the main session, does no implementation itself. It orchestrates and reviews.
- **Sonnet implements.** Each phase, or each parallel group within a phase, goes to an `Agent` subagent launched with `model: "sonnet"`. Hand it this file, the phase's task IDs, and the exact contract and research sections the tasks cite. Independent groups (for example, the migration phase alongside US1) run as concurrent subagents.
- **Opus reviews each checkpoint** before the next phase starts:
  - read the diff;
  - run that phase's tests with `PYTHONPATH=$PWD python -m pytest …`;
  - check the constitution guards: no-LLM AST, no default literals, no writes to `authored/`, secrets canary;
  - send fixes back to the same subagent with `SendMessage`, rather than patching in the main thread.
- **Precision decisions** that surface during implementation (identity, scope, ordering, an unexpected count) are escalated to the GM, never decided by a subagent.
