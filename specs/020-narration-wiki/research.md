# Research: Persistent Narration Wiki

All technical unknowns from the plan are resolved below. Each decision is constrained by the clarified specification and CampaignGenerator constitution.

## R1. Engine boundary and package shape

**Decision**: Implement a `session_doc.narration_wiki` package with separate modules for models, path policy, collection, measurement, indexes/conflicts, proposals, persistence, and CLI dispatch. Add one console script named `narration_wiki`.

**Rationale**: Scope containment, exact-byte mutation, and deterministic serialization are security and audit boundaries. Separate modules keep each boundary testable while preserving one public engine.

**Alternatives considered**:

- One large script: rejected because path security, parsing, and mutation logic would be difficult to audit independently.
- Domain logic in FastAPI: rejected by the CLI-engine and split-brain principles.

## R2. Authoritative guidance resolution

**Decision**: Add one read-only resolver in `campaignlib/narration_context.py`. It resolves the configured campaign rulebook, voice files, example files, and checker source without creating directories, probing legacy locations, or borrowing another campaign's rules.

**Rationale**: Measurement, proposal authorization, CLI, and UI must agree on one campaign-specific source of guidance. A single resolver prevents copied target lists and cross-campaign leakage.

**Alternatives considered**:

- Resolve paths independently in each command: rejected as configuration drift.
- Fall back to another campaign's rulebook: rejected as a canon and safety violation.

## R3. Explicit scope and safe collection

**Decision**: Require explicit campaign and session directories on every command. Discover only fixed-depth allowlisted layouts, strictly resolve every candidate, refuse any path or followed link outside the selected session or campaign, hash exact bytes, and serialize session-relative POSIX paths.

**Rationale**: The feature must never interpret an empty selection as all sessions or let a symlink expand the collection boundary. Fixed-depth discovery is deterministic and bounded.

**Alternatives considered**:

- Recursive globbing: rejected because unknown layouts could expand scope silently.
- Trust lexical path prefixes: rejected because symlinks and `..` can escape them.

## R4. Deterministic manifest identity

**Decision**: Define `corpus_id` as SHA-256 over canonical sorted tuples of measurement path, content digest, and narrator identity. Record present artifacts and expected-but-missing roles separately. Exclude mtimes, absolute paths, random values, and read-time timestamps.

**Rationale**: The same selected inputs must produce byte-identical manifests and measurements across CLI and UI runs.

**Alternatives considered**:

- Hash only filenames: rejected because content changes would not invalidate the corpus.
- Include mtimes: rejected because metadata changes are not evidence changes and break reproducibility.

## R5. Structured measurement and legacy compatibility

**Decision**: Refactor `session_doc.voice_lint` to expose a structured analysis API and named budget profiles. Preserve the current `lint()` return shape, CLI text, ordering, and exit behavior as a characterized legacy projection. Narration-wiki uses a named D4 profile with taxonomy budget zero and em-dash budget two.

**Rationale**: The wiki needs observed value, budget, verdict, and occurrences without copying regexes or silently changing existing callers.

**Alternatives considered**:

- Parse current lint messages: rejected as fragile and lossy.
- Copy checker rules into narration-wiki: rejected because it creates a second rule source.

## R6. Eligible prose and cross-narrator convergence

**Decision**: Reuse established document readers and exclude frontmatter, headings, fenced code, metadata tables, audit spans, and direct-dialogue-only blocks. Normalize visible prose with Unicode normalization and case folding. Emit only maximal sequences of three or more consecutive words found in at least two distinct narrators, sorted deterministically.

**Rationale**: Narrator identity, not occurrence count, is the requirement. Maximal matches avoid flooding evidence with every overlapping sub-gram.

**Alternatives considered**:

- Emit every matching n-gram: rejected as unusably repetitive.
- Add stopword filtering or configurable thresholds now: rejected because the specification fixes the initial threshold.

## R7. Baseline lifecycle and Gate 1 binding

**Decision**: `measure --phase before` must succeed after collection and before any conflict or pattern ruling. Each Gate 1 record stores the baseline artifact hash, corpus digest, guidance digest, and measurement profile. A ruling rehashes the current corpus and guidance. Drift before any ruling permits deterministic remeasurement; drift after the first ruling requires a new iteration.

**Rationale**: Rewriting the baseline after a human has ruled would detach that decision from its reviewed evidence. Requiring a new iteration preserves audit history.

**Alternatives considered**:

- Allow Gate 1 without measurement: rejected because before/after evidence would have no trusted baseline.
- Replace a baseline after rulings: rejected because it silently changes the evidence behind existing decisions.

## R8. Pattern, index, and seed-conflict contracts

**Decision**: Use Markdown pattern pages with YAML frontmatter and literal `Problem`, `Root Cause`, `Corrective Strategy`, and `Evidence` sections. Normalize slugs and detect collisions across both visible tiers. Companion-produced conflict drafts contain a stable conflict ID, campaign scope, rule key, and sorted competing source references and digests. A separate `conflict-rule` command persists one GM resolution and rationale under `<campaign>/wiki/conflicts/`; an affected pattern cannot be accepted while a referenced conflict is unresolved.

**Rationale**: Structure is mechanically validatable, while semantic selection remains a human decision. A dedicated conflict artifact makes the Phandalin em-dash discrepancy testable and auditable.

**Alternatives considered**:

- Let the first seed source win: rejected because source ordering is not authority.
- Embed conflict prose only in a pattern page: rejected because the ruling needs stable identity and independent provenance.

## R9. Proposal safety and exact restoration

**Decision**: Stage exactly one configured target with `before.snapshot`, `after.snapshot`, target and snapshot hashes, an affected-rule key, confirmed source patterns, and a complete generated unified diff. Apply only when the current hash equals the before hash. Gate 2 accepts by retaining the after bytes or rejects by restoring the exact before bytes. The diff is display evidence and is never executed.

**Rationale**: Fuzzy patch tools and text round-tripping cannot guarantee exact restoration or target identity.

**Alternatives considered**:

- Execute `patch` or `git apply`: rejected because fuzz and path headers expand the mutation surface.
- Store only a reverse diff: rejected because it cannot prove exact original bytes.

## R10. Deterministic reconsideration of rejected proposals

**Decision**: Define a canonical evidence binding as source reference, source SHA-256, affected kind (`rule` or `measurement_category`), and affected key. `proposal-stage` validates that every digest exists in the current manifest, the affected key matches the proposal, and at least one digest is absent from the prior equivalent impact. A changed path or artifact ID with an already-recorded digest is not new evidence. Without a qualifying binding, staging requires a GM-supplied override rationale. Gate 2 only consumes the basis captured at staging.

**Rationale**: Checking at Gate 2 is too late: the rejected proposal has already recurred, been applied for comparison, and been measured. Digest identity makes novelty mechanical.

**Alternatives considered**:

- Compare artifact IDs: rejected because renames would masquerade as new evidence.
- Let the proposer declare its own override: rejected because an override is a human decision.

## R11. Atomicity, locking, and recovery

**Decision**: Add an exact-byte atomic writer beside existing utilities. Hold a Linux/WSL `fcntl.flock` across mutation read-check-write sequences. Persist an intent journal before each multi-file conflict, Gate 1, or Gate 2 transaction and advance hash-checked idempotent phases. Unknown external state becomes `needs_attention`; the engine never guesses.

**Rationale**: Atomic replacement protects one file but not compare-and-swap, concurrent ledger appends, or target-plus-ledger finalization.

**Alternatives considered**:

- Add a database transaction: rejected as unnecessary persistent infrastructure contrary to disk truth.
- Rely only on atomic replace: rejected because two processes can both pass a stale check.

## R12. Portable tier and companion capability contract

**Decision**: Store campaign knowledge at `<campaign>/wiki/` and read the portable deployment from `~/.claude/narration-wiki/`. Require companion-owned `capabilities.yaml` with source repository/revision, `narration_wiki_contract: 1`, `guidance_source: campaign-resolved`, and sorted `maintainer` and `proposer` capabilities. CampaignGenerator validates this file read-only. Portable Gate 1 acceptance creates a local handoff and remains `pending_portable_sync` until a compatible deployment contains the validated slug and ruling provenance.

**Rationale**: The manifest provides a locally inspectable contract without writing into or depending on network access to another repository.

**Alternatives considered**:

- Keep only generic source metadata: rejected because it does not prove campaign-resolved guidance or role support.
- Copy portable pages into each campaign: rejected because it recreates divergent rule forks.

## R13. CLI, HTTP, SSE, and UI parity

**Decision**: Public commands are `status`, `collect`, `measure`, `index-check`, `conflict-rule`, `pattern-rule`, `proposal-stage`, `proposal-apply`, and `proposal-rule`. Add a bounded read-only JSON subprocess helper to `server/subprocess_runner.py` for status only. Every other command uses `stream_subprocess(..., save_run_log=False)` and returns SSE. Add a backward-compatible logging flag that defaults to current behavior for existing routes. Use a fetch/ReadableStream SSE client with `AbortController` for POST bodies, and refresh status after every terminal or interrupted run.

**Rationale**: This preserves one process boundary, POST semantics for human rulings, cancellation-driven process-group cleanup, and CLI/UI persisted-artifact parity. The existing runner's timestamped logs must be disabled because the engine already owns canonical journals and CLI runs do not create those logs.

**Alternatives considered**:

- Router-local `subprocess.run` for workflow commands: rejected as a constitutional split seam.
- State-changing GET routes solely to use native `EventSource`: rejected because a small POST-SSE reader preserves HTTP semantics.
- Parse streamed JSON per chunk: rejected because subprocess chunks have arbitrary boundaries.

## R14. UI consistency, panel resizing, and verification

**Decision**: Add one `/workflow/wiki` page as session-workflow step 7 and sidebar item `③ Narration Wiki`. Reuse existing Catppuccin variables, button/status/focus conventions, typography, spacing, radii, and scrollbar skin. The page owns scrolling at 1280x720. Manifest/evidence, measurement, diff/prior-ruling, and history/output are explicitly resizable border-box panels with `min-width: 320px`, `min-height: 160px`, `resize: both`, `overflow: auto`, and stable gutters. Panel internals use intrinsic wrapping or container-sized layout.

**Rationale**: The application shell uses `overflow: hidden`, and viewport media queries cannot respond to an independently resized 320px panel. Automated browser checks are required to prove reachability.

**Alternatives considered**:

- Retain the broader legacy viewport matrix: rejected by the clarified support contract.
- Manual resize testing only: rejected because SC-014 requires complete reachability.

## R15. Persisted usability result and rollout

**Decision**: The post-implementation real-session exercise writes `specs/020-narration-wiki/validation/usability-result.json`. Timing begins when `/workflow/wiki` opens with an explicitly selected session and ends when the Gate 2 ruling is persisted. Record total elapsed seconds, excluded model-response seconds, derived active-operator seconds, Gate 1 and Gate 2 references, and ruling path. Passing requires active operator time below 900 seconds. Wiki state remains additive; do not migrate, dual-read, or backfill historical sessions.

**Rationale**: A measurable success criterion needs persisted evidence and exact boundaries. Keeping this as validation evidence avoids adding browser-owned runtime timing state or an orphan CLI capability.

**Alternatives considered**:

- Infer usability from automated test runtime: rejected because it does not measure operator work.
- Store timing only in browser state: rejected because it would not be durable or CLI-visible.
- Automatically import historical critiques: rejected by explicit scope and human-gate requirements.
