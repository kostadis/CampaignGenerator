# Quickstart: Validating 039 (incremental grounding and NPC updates)

A run guide to prove the feature works end to end. It does not contain implementation code. Expected results are stated so a pass or fail is observable.

## Prerequisites

- The repo on branch `039-incremental-campaign-updates`, with the package editable-installed into the server's venv (see the project CLAUDE.md, "The package MUST be editable-installed"). Verify the console script resolves: `summary_native delta --help` must list the `delta` family.
- Tests: `python -m pytest tests/ -k delta` runs the delta suite. `cd frontend && npm test` runs the page tests.
- Synthetic fixture: `tests/fixtures/delta/` (two to three chapters, one forge restart, one faction offer, one passing mention, one new NPC). It contains no private campaign data.

## 1. Full suite stays green (regression first)

Run `python -m pytest tests/`. Expected: no change in failures from the 039 baseline. The full-mode verifier goldens must be byte-identical (research R2).

## 2. One new chapter is the only parsed input (SC-001)

On the fixture, with the baseline bound to chapters 1–2:

1. `summary_native delta plan --source fixtures/…/ch03.md --product grounding --stop prepare --json`
2. `summary_native delta sources --plan <id> --json`

Expected: `read_counts.parsed_new == 1`, `read_counts.parsed_historical == 0`, `call_counts.model == 0`. Integrity-only reads are reported separately and are non-zero only for pinned custody hashes.

## 3. Empty selection refuses (Principle X)

`summary_native delta plan --product grounding --json` with no `--source`. Expected: exit 2, message "no sources selected". No plan file is written.

## 4. Baseline binding and drift (FR-002, FR-003)

1. `summary_native delta baseline status --plan <id>`. Expected: every document bound to a generation and origin digest.
2. Edit one live document by hand, then re-run status. Expected: the drift is listed, and the baseline is `unadopted` until each hunk is resolved.
3. `summary_native delta baseline adopt --resolve <hunk>=accept`. Expected: a new adoption record. Earlier generation and receipt files are unchanged (verify by digest).

## 5. Grounding edit reconstruction (SC-002)

1. `delta grounding propose --plan <id> --backend <b> --model <m>`
2. Decide every proposal (`delta grounding decide … --decision approve`), then `delta grounding check`.

Expected: every untouched baseline line is byte-identical after reconstruction. A proposal whose `before_sha256` is stale is rejected. Duplicate `target_id` is rejected. Heading, table width and citation target checks pass.

## 6. NPC changed, new, mention and mixed-horizon (SC-004)

1. `delta census --plan <id>`. Expected: each fixture subject has exactly one disposition; the passing mention is `mentioned_unchanged`; the unknown name is `unresolved`, not absent.
2. `delta npc draft`, then `delta npc verify`. Expected: the changed NPC keeps its old history bytes; the new NPC has a bounded dossier; verification uses sparse targets only (no chapter-membership entries).
3. `delta npc attest <passing-mention> --reason "…" --publication <sha>`. Expected: the published dossier is byte-identical; the attestation is recorded.

## 7. Freshness scope (SC-005)

After sign-off, change only subject B's evidence and re-check. Expected: B is stale; A stays valid. Change the shared source. Expected: both A and B are stale. Change an unrelated dossier. Expected: no effect on A's approval.

## 8. Failure injection and resume (SC-006)

Interrupt the run at each boundary listed in research R7 (the fixture harness does this with injected failures). Then `delta run resume --plan <id>`. Expected: completed compatible stages reuse by digest with zero model calls; no duplicate approvals; a crash between target write and publish log is reconciled, not repeated; the run reports `partial` where members are held, never `complete`.

## 9. Real chapter replay (manual acceptance, SC-003)

Not a CI test. Run the same steps against the reference campaign's Chapter 75 inputs in a worktree. Expected: the accepted agreements and the completed forge restoration are present; exhausted dust is recorded; the missing-memory requester is unresolved; no deployment, attunement or Glabbagool reward is asserted.

## 10. Secrets canaries (SC-007)

Place canary strings in the Secrets section of an authored NPC file. Run draft and verify. Expected: canaries appear in no prompt log, intermediate artifact, or player-facing output. A player-audience request that touches GM evidence is refused before content is exposed.

## 11. Parity and restart (SC-008, FR-023)

1. Run `delta plan` through the CLI and `POST /plans` on the same inputs. Expected: identical plan records (after removing timestamps).
2. Stop the server, restart it, load `/grounding/delta`. Expected: saved decisions and the status banner match `delta run status`.

## 12. Inherited grounding delta (SC-009)

On the fixture, complete a grounding delta whose candidates cite chapter 1 material. Expected: the claims check resolves those citations through baseline custody; no synthetic full-corpus record is written; a deliberately removed inherited support blocks with a targeted repair message.

## Done when

Steps 1–8, 10, 11 and 12 pass on the fixture. Step 9 is run once by the operator before the PR is merged, and its result is recorded in the PR description.
