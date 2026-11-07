# Research: Incremental Campaign Grounding and NPC Updates (039)

Each decision resolves a technical question the plan leaves open. Code references are to the baseline `887a5c1`.

## R1. Selected-source ingestion (G2, FR-004, SC-001)

- **Finding**: `validate.scan` parses every `*.md` in the summaries directory before the chapter range is applied (`pipelines/summary_native/validate.py:352-380`). `_check_input_dir` also lists all files. The range is a post-parse filter, so a range flag cannot bound reads.
- **Decision**: Add a `sources` argument (an explicit list of paths) to `scan` and `build_corpus`. When it is given, only those paths are parsed. When it is absent, the existing behavior is unchanged. An empty list is a refusal, not "all" (Principle X). Counters for parsed files, historical versus new, are returned in the report.
- **Rejected**: Pre-filtering by filename. Filenames can disagree with content (the spec's chapter-suffix edge cases), and the spec asks for an explicit set, not a guess.

## R2. Full versus sparse evidence (N2, FR-005)

- **Finding**: `CorpusIndex.targets` returns `(chapter, "entry")` and `(chapter, "moment")` for every in-range chapter (`npc_verify.py:103-111`). The citation check accepts a target if it is in that set (`npc_verify.py:273-276`). Under a sparse run this lets a `[ch 075 / entry]` citation pass even when no entry span was supplied.
- **Decision**: Introduce `SparseEvidence` in `delta/evidence.py`, built from an explicit list of bound spans. Its `targets` are exactly those spans, plus scene IDs with real bound support. The verifier takes an evidence-index argument and is given `CorpusIndex` in full mode and `SparseEvidence` in delta mode. Full-mode output is unchanged, and this is locked by golden tests before the change.
- **Rejected**: Changing `CorpusIndex` in place. That alters full-mode verifier output, and the goldens would break for no reason.

## R3. Where a model is allowed to decide (Principle II)

Each model call in the delta, with its checkpoint:

| Call | Input | Decision the model makes | Who checks before it feeds the next step |
|---|---|---|---|
| NPC draft (existing `npc_draft`) | Selected new evidence + reused historical blocks + manual (no Secrets) | Prose for new events and current status | Native verifier, then exact-draft GM sign-off |
| Contextual association proposal | Selected source span + entity list | Proposes a scoped association | GM approves, rejects, or Discuss each one. Rejected and Discuss never enter drafting evidence. |
| Census triage hint | Selected new sources + registry | Proposes a disposition for an unmatched name | GM rules; the model cannot assign a disposition on its own |
| Grounding edit proposal | Numbered baseline lines + selected source | Replacement text, category, rationale | Host validates before-text and targets; GM reviews each candidate |
| Grounding consistency pass | Candidate documents + selected source | Flags conflicts | Bounded findings; GM resolves; a model verdict never approves |

Safe calls (no precision decision reaches a human-skipped path): the NPC draft, because every output needs the sign-off gate. Every other call is listed above.

## R4. Baseline binding (FR-002, FR-003, G4)

- **Decision**: A grounding baseline is bound by the active generation's identity and manifest digest, plus the sha256 of each of the four documents' origin and live bytes. An NPC baseline is bound by its entry in `publish_log.json` (`npc_publish.py:164-190`), checked against the published file's header digest (`published_body_sha`, `npc_publish.py:151`). Newest directory is never used.
- **Adoption** is an explicit `delta baseline adopt` operation. It writes a new record and does not rewrite earlier generations. Live differences from the immutable generation are listed, and the operator must resolve each unreviewed one before the baseline is usable.
- **Rejected**: Inferring the baseline from the newest summary range directory. The spec's Chapter 73/74 evidence shows the nominal range is wrong.

## R5. Per-item freshness (N3, FR-014, SC-005)

- **Finding**: `_current_draft_signoff` (`npc_publish.py:220`) checks authority for the draft digest. Shared review custody can stale unrelated members.
- **Decision**: Extend `freshness.py` with a dependency graph per item: draft, evidence, composition, shared sources, identity rulings, rules, associations. A change to a node invalidates only items that list it. Shared nodes list every consumer. Test with the B/A case in SC-005.

## R6. Delta lineage through the claims and promotion gates (G3, FR-016, SC-009)

- **Finding**: `synth_record_complete` requires a `synth` step (`promotion/gates.py:23-35`). `_discovered_rows` and `mandatory_source_closure` resolve citations against the selected range's manifest (`claims/selection.py:61-73`, `:220`). A Chapter 75-only corpus cannot satisfy inherited Chapters 2–74 citations.
- **Decision**: A new record kind `delta` with its own completeness rule: complete means every required member is either (a) inherited by digest from the baseline, with its custody recorded, or (b) produced by this run with a passing check. `synth_record_complete` is unchanged. `claims/selection.py` resolves an inherited citation through baseline custody. Span and mapping checks carry over only where all their dependencies still hash equal.
- **Rejected**: Writing a synthetic full-range synth record. FR-021 forbids it, and it fabricates coverage.

## R7. Durable run state and resume (C1, FR-018, SC-006)

- **Finding**: `pipelines/summary_native/scheduler.py` already provides `Scheduler`, `WorkItem`, `atomic_write_record`, `select_resume` and `reconcile_items` (lines 22–354). `npc_draft` resume is already built on them.
- **Decision**: `delta/run.py` writes one versioned run file per run, with stages, artifacts, their digests and per-member outcomes. Work batches are materialized from the plan before dispatch. Resume reuses `Scheduler` and `reconcile_items`, not a new engine. Batch size is not an input to selection.
- **Failure-injection points** (SC-006): after evidence write, after model output, after verify, after review creation, after sign-off, after target write but before publish log, after publish log but before run receipt.

## R8. Strict models and XIII (resolved, per the plan's Constitution Check)

- **Finding**: `StrictPromotionModel` (`promotion/models.py:50`) and `_GateModel` (`gates.py:222`) use `extra="forbid"`. Adding a field to a subclass breaks readers of existing records.
- **Decision**: No new field on any strict model. Delta lineage is a new record and a new model, referenced from the run. If implementation proves that an existing strict record must gain a field, XIII applies: stop, write `migration.md`, add a one-shot migration CLI, and re-run the gate.

## R9. Option vocabulary across the family (XII)

- **Decision**: One spelling for each concept across `validate`, `build_corpus`, `npc-*`, and the new `delta` family:
  - `--campaign-dir`, `--config`, `--json`, `--force`, `--backend`, `--model` mean what they already mean.
  - Explicit file selection: `--source PATH`, repeatable, no default. Used everywhere a file set is accepted. It replaces nothing that exists.
  - Chapter-range flags `--since` and `--until` keep their current meaning. Delta mode does not use them to select sources.
  - Effort: `--effort` is introduced only if the existing backends accept it. Otherwise the existing model settings are reused. (To verify against the backend options before Phase A.)
- **Rule**: a new option is added to every sibling in the same change.

## R10. Test fixtures (open item 1 in plan.md)

- **Decision**: Tests use a synthetic campaign under `tests/fixtures/delta/` (two to three chapters, one forge-restart fact, one faction offer, one passing mention, one new NPC). The real Chapter 75 replay is a manual acceptance run (quickstart step 9), not a CI test, because it depends on private campaign data.

## R11. Frontend and CLI parity (XI, FR-022)

- **Decision**: Every subcommand in `contracts/cli.md` has one route in `contracts/http.md`, and each route only builds argv and streams the CLI's output over SSE (`server/subprocess_runner.py`). `test_delta_parity.py` asserts that a route's argv equals the CLI invocation and that both produce the same receipt.
