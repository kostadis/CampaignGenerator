# Quickstart: validate chunked grounding documents end to end

Validation runs on **a copy** of the Out of the Abyss campaign (`~/out-of-the-abyss/out-of-the-abyss`, which already holds a ch002-070 corpus and 24 published dossiers from the experiment). The live campaign is never written. The reference numbers come from the experiment (`experiments/20261007-chunked-state-docs/RESULTS.md`), and every scenario below names the result it should reproduce.

## Prerequisites

- The package is editable-installed into the venv the server uses (`uv pip install -e . --python ~/.venv/bin/python`).
- One or two Spark endpoints serving the extraction model. Check with `/spark-status`; the experiment's best was Qwen3-Next-80B, MTP-2, 8 sequences per box.
- **Reference hardware for SC-007's timings:** two NVIDIA DGX Spark (GB10, 128 GB unified memory) boxes, each running one vLLM endpoint; prose on the Claude subscription via `claude -p`. On other hardware, record the measured times rather than holding them to SC-007's numbers.
- The `claude` CLI is logged in for the `claude-code` prose backend.
- A built and fresh corpus: `summary_native build --since 2 --until 70` (add `--force` if the registry changed).

All commands below run from the campaign root.

## S1. Extract and check (User Story 1)

```bash
summary_native extract --since 2 --until 70 \
  --backend dgx --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 \
  --endpoints http://192.168.1.147:8001/v1 http://192.168.1.121:8001/v1 --parallel 8
```

Expect:
- 60 chunks, each served by one of the two endpoints, listed in `state/runs/<stamp>/record.json`;
- `state/notes/drops.md` with a reason on every drop;
- **no Audit section in any prompt** (`grep -L "AUDIT" state/notes/*.user.md` lists every prompt).

Wall time should be about 30 minutes or less on two boxes (experiment: 30.5 min, with the audit list still inside).

**Re-run with nothing changed:** every chunk is reported `cached`, and no model call is made.

## S2. Build both documents (User Stories 1, 2, 5)

```bash
summary_native synth campaign_state --since 2 --until 70 \
  --backend claude-code --model claude-sonnet-5-5 --claude-code-effort medium
summary_native synth world_state --since 2 --until 70 \
  --backend claude-code --model claude-sonnet-5-5 --claude-code-effort medium
```

Expect:
- The prose calls finish in under 10 minutes (experiment: 308 s of calls).
- **world_state:**
  - begins with the reading contract;
  - every prose section is within its budget (the report prints `words/budget`);
  - every section links its `reference/*.md`;
  - the Canon Events Timeline section points to `canon_events_timeline.md`.
- **Party level:** the documents report the party at level nine (ch 63).
- **NPC status table:** one row each for Ilvara Mizzrym (Dead) and Sarith Kzekarit (Dead); no row for Daz, Gyrgum, Thorin or Zalthir; Jimjar's row shows a later report.

Measure (the experiment's `check_doc.py` and `known_facts.py` reproduce these):
- scene coverage of the drafts plus the timeline ≥ 95% (SC-001);
- prose quotes ≥ 90% verbatim, and each of the rest carries `⚠ unverified:` (SC-003);
- world_state, excluding the timeline and reference files, no larger than the one-shot synth draft for the same range (23K characters; `experiments/20261007-chunked-state-docs/baseline_backup/drafts/world_state.draft.md`) (SC-004);
- at least 12 of the 16 hand-verified facts correct (SC-006).

## S3. Missing dossier: refuse, then fall back (User Story 3)

1. Unpublish one selected NPC on the copy: move `docs/npcs/kalan-strongbranch.md` aside.
2. Run `synth world_state --force`. **Expect exit 2**, naming `Kalan Strongbranch: drafted, not published` with the publish command and the `--fallback-npc-lines` alternative. No draft is written.
3. Re-run with `--fallback-npc-lines`. Expect Kalan's line to end `(no published dossier — from checked notes)`, with every citation from the checked notes, and the report listing the fallback.
4. Restore the file, rebuild, and confirm the line now ends `→ docs/npcs/kalan-strongbranch.md`.
5. **Secrets canary:** add a unique string to an authored file's `secrets`, re-compose and republish that dossier, rebuild, and confirm the string is in no draft and in no `state/runs/*/*.user.md`.

## S4. Annotations, not rewrites (User Story 4)

Confirm in `drafts/annotations.md` and the drafts:
- the line calling Jimjar a travelling companion (ch 26) has `⚠ later:` citing ch 48;
- the Avowed line saying Kalan fled (ch 65) has `ℹ since:` citing his ch 67 status;
- "Alaundo — Dead" with no earlier status row produces **no** annotation.

Run `summary_native annotate world_state --dry-run` and confirm it lists the same hits. Compare each annotated line's text with the prose call's raw output in `state/runs/`: the text is identical.

## S5. The audit as its own step (User Story 6)

```bash
summary_native audit --since 2 --until 70 --backend dgx --model … --endpoints …
```

Expect:
- every SUPPORTED verdict has a citation inside its item's candidate chapters and a verbatim span;
- Bloppblippodd's confrontation (008.01) and Alkrist's confession (ch 61) are SUPPORTED;
- Droki's capture and Kalan's presumed death are NOT FOUND.

Rebuild campaign_state and confirm its Audit section renders from `audit.json`.

## S6. UI parity (Principle XI)

On `/grounding/summary-native`:
- run Extract with two endpoints, Synth for both documents (the fallback checkbox is unchecked by default and resets on reload), Audit and Annotate;
- confirm each streams the same command the CLI runs;
- confirm the Missing-dossier refusal renders its NPC list.

## S7. Session prep under the contract (User Story 7)

Promote the drafts on the copy (copy the drafts, timeline and `reference/` into `docs/`). Then run the pointer variant of `gm-session-prep` with a beat that puts at least five generated-doc entities on stage. Expect:
- every verified entity tagged `[TABLE chNN NNN.SS]`;
- a "Doc errors found" section;
- no verified fact contradicting the latest summary (SC-009).

## Automated tests

`python -m pytest tests/test_summary_native_*.py`. That covers the new units below and the guard tests; see `plan.md` for the list. They run on `tests/fixtures/summary_native/` and use a fake client for the model steps.

## Validation

Run 2026-10-07/08 (T061) on a copy of `~/out-of-the-abyss/out-of-the-abyss` (`config/` + `docs/`, without `summaries/`, `ensemble*` and `distill`), with the branch's code via `PYTHONPATH`. Extraction and audit used `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` (MTP-2, `vllm-chat`) on both Sparks; prose used `claude-sonnet-5-5` at medium effort through `claude -p`.

| Scenario | Result |
|---|---|
| **S1 extract** | 60/60 chunks in **12.6 min** on two boxes (29 spark, 31 spark2), `--parallel 8`. Kept 4,110 notes, dropped 257, every drop with a reason (uncited 105, malformed-row 96, outside-chunk 22, quoted-span-not-found 21, missing-world-tag 10, invalid-citation 2, missing-thread-tag 1). **No Audit text in any of the 60 prompts.** The experiment's 30.5 min carried the in-map audit (42% of its output); this run's map output is 786K chars against the experiment's ~820K non-audit. SC-007 met. |
| **S2 campaign_state** | Exit 0. NPC table: Ilvara Mizzrym Dead (one row), Sarith Kzekarit Dead (one row), no rows for Daz/Gyrgum/Thorin/Zalthir, Jimjar Alive with `later, status not stated` (ch 48). Prose sections 24–41 s each. 34 quotations, **34 verbatim** in their cited chapter. |
| **S2 world_state** | Opens with the reading contract; party at **level 9**; 15 quotations, **15 verbatim** (SC-003 met; the experiment's Qwen reduce had 184/300). Budgets: Factions 493/450 and Items 467/450 OVER, the rest within. **Size 25,396 chars against the 23K one-shot draft: SC-004 missed by ~2.4K** (the reading contract is 1.5K of it). |
| **S3 missing dossier** | First build refused (exit 2) before writing: 6 of 15 selected NPCs had dossiers that failed verification (Glabbagool, The Flying Iron Owlbear, Sylvira Savikas, Jimjar, Sarith Kzekarit, Buppido), each with its state, the four per-NPC commands and the `--fallback-npc-lines` alternative. With the flag: 9 lines end `→ docs/npcs/<slug>.md`, 6 carry the fallback mark. **Secrets canary not run live:** no published dossier has authored Secrets; `tests/test_state_docs_no_secrets.py` covers it. |
| **S4 annotations** | world_state 3 later / 4 since / 0 unverified; campaign_state (final build) 12 later / 5 since / 3 unverified. Line text unchanged; `annotate --dry-run` reports the same hits and writes nothing. Examples: Bookwyrm dead (ch 65) under lines that still treat her as active; Gray Ghosts dead; a non-verbatim "red herring coin"; a citation naming a spell as a section. The quickstart's specific Jimjar and Kalan lines did not occur in this run's prose. |
| **S5 audit** | 443 items (365 judged, 78 without candidates), ~35 min on two boxes. 30 items failed on connection errors from spark2 and were judged on a rerun (spark later dropped off the network; the two-endpoint rerun refused before sending, per FR-023). Bloppblippodd SUPPORTED; Droki capture and Kalan's presumed death NOT FOUND, as expected. **Alkrist's confession NOT FOUND (unverified):** the judge wrote "Daral's present for Janussi" inside quotation marks where ch 061 says "gift to" — a correct rejection. Two check rules were added from this run (GM rulings): a verbatim span under a scene or section the chapter lacks is cited where it sits (`baf353c`), and a `Heading\nParagraph` span is narrowed to its longest verbatim piece (`2b4a1e1`). Re-checked from cache with no model calls: **30 → 67 → 90 SUPPORTED**, unverified 109 → 62. campaign_state's Audit section renders from `audit.json`. |
| **S6 UI** | Covered by `frontend/e2e/summary-native-state.spec.ts` (8 tests, mocked routes); not exercised against a live server. |
| **S7 session prep** | Not run: gm-session-prep has not adopted the contract yet (kostadis/campaigns#380). `TestSessionPrepContract` checks the documents' side of it. |

Not measured in this run: SC-001 scene coverage and SC-006 hand-verified facts (the experiment's `check_doc.py` / `known_facts.py` were not re-run).
