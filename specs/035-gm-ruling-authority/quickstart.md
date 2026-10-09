# Quickstart Validation: GM Rulings and Authority Tiers

This guide is the post-implementation acceptance contract; it does not claim a live smoke run before implementation. Set `CAMPAIGN_DIR` to an absolute disposable fixture containing summaries, `config/planning.yaml`, identity registries, and the four Summary Native projections.

## 1. Initialize and validate

```bash
summary_native authority init --campaign-dir "$CAMPAIGN_DIR"
summary_native authority validate --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority status --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Expect a strict empty `docs/authority.yaml`, a revision/digest, no pending transaction, and refusal from a second `init` without overwrite.

## 2. Stage notes and preview selection

Create strict record files covering `CANON`, `TABLE`, `PREP`, `OVERLAY`, and `OPEN`, with distinct GM/player/character grants. Stage/apply them through [the CLI contract](contracts/cli.md), then configure exact paths/globs.

```bash
summary_native authority record stage /tmp/note-record.yaml --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority record apply "$STAGE_ID" --stage-sha256 "$STAGE_SHA" --expected-ledger-sha256 "$LEDGER_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority notes preview --audience gm --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Expect concrete sorted members, reasons, digests, and external flags. Missing/unreadable/zero-match selectors and empty configured `notes` refuse. Changed glob membership invalidates the preview digest.

## 3. Apply the Earthstone correction

Stage a `RULED` record with exact summary path/anchor, rejected claim, replacement, source digest, audience, interval, and projections.

```bash
summary_native authority propose earthstone-responsible-actor --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority apply earthstone-responsible-actor --proposal-sha256 "$PROPOSAL_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Inspect immutable before/after artifacts before apply. Expect the maintained summary replacement, preserved original bytes, approval/ledger events, journal, receipt, stale prior outputs, and no generated Markdown patch. Modify the summary between propose/apply; expect exit 3 `AUTH_STALE_PROPOSAL` and no write.

## 4. Rebuild affected projections

```bash
summary_native synth planning --since 2 --until 57 --authority-selection "$SELECTION_SHA" --audience gm --force --config "$CAMPAIGN_DIR/config/config.yaml"
```

Run the existing build/extract and all four synth projections. Expect corrected source truth across affected views; a complete authority input manifest; and `PREP`, `OVERLAY`, and `OPEN` still future/planning/unresolved.

## 5. Prove audience and cache isolation

Preview/run for `gm`, then for a named character excluded from a sentinel secret.

```bash
summary_native authority notes preview --audience character:CHARACTER_ID --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth planning --since 2 --until 57 --authority-selection "$CHAR_SELECTION_SHA" --audience character:CHARACTER_ID --force --config "$CAMPAIGN_DIR/config/config.yaml"
```

Expect the sentinel absent from filtered extraction payload, audience-visible prompt/output, references, fallbacks, diagnostics, and errors. No GM cache entry is reused. Player grants do not grant the character. Required unclassified/partially classified source refuses.

## 6. Prove conflict semantics

Stage same-subject/key overlapping incompatible values: expect exit 5 with both records/scopes and no recency winner. Make intervals disjoint: expect valid evolution. `OVERLAY` directs ahead of conflicting `PREP`; two incompatible equal-scope overlays block. Prose-only candidates receive no automatic verdict.

## 7. Prove crash recovery

Inject failure after every transaction write, then run:

```bash
summary_native authority recover "$TRANSACTION_ID" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Expect idempotent all-before/all-after/mixed recovery; unexpected bytes exit 4 without overwrite; partial workspaces are unreadable; a manifest change during a model call leaves its result incomplete/stale.

## 8. Prove safe withdrawal

```bash
summary_native authority withdraw earthstone-responsible-actor --reason "Later ruling" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Expect a reversal proposal with no immediate source write. Unrelated edits remain. A changed corrected passage requires authored replacement. Applying reversal retains history and stales affected drafts.

## 9. Prove UI parity

Build the frontend and run the Summary Native E2E spec. Verify init, record stage/apply/retire, note preview, source diff/apply, withdrawal, conflict resolution, history, stale status, and recovery invoke matching CLI behavior and show identical digests/IDs.

## 10. Suggested checks

```bash
python -m pytest -q tests/test_summary_native_authority*.py tests/test_summary_native_planning.py tests/test_summary_native_routes.py tests/test_planning_config_service.py
python -m pytest -q tests/test_summary_native*.py tests/test_state_docs*.py
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- summary-native-state.spec.ts
```

Use fake model clients to inspect complete payloads; policy, transactions, caching, routes, and UI tests need no live credentials. When validating an uninstalled worktree, set `PYTHONPATH` to its absolute root so subprocess tests use the same code as pytest; an editable installation pointing at another checkout otherwise invokes that checkout’s CLI.
