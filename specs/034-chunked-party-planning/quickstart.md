# Quickstart: validating chunked party and planning

Validation runs on a **copy** of Out of the Abyss, never the live campaign. Spec 033's T061 copy (`oota/` in the session scratchpad) has the config, the summaries and the published dossiers. Commands run from the copy's root through the worktree's code:

```bash
PYTHONPATH=<worktree> ~/.venv/bin/python -m pipelines.summary_native.cli …
```

The `sn.sh` wrapper from T061 does this.

**Prerequisites:**
- Both Sparks are serving Qwen3-Next for extraction.
- `claude` is logged in for the prose step and `thread-propose`.
- A built corpus for ch002-070 exists (`summary_native build`).

## S0 — Baselines, before the one-shot path is removed

Run this from **main** (the one-shot path), on the copy:

```bash
summary_native synth party    --since 2 --until 70 --force
summary_native synth planning --since 2 --until 70 --force
```

Keep `drafts/party.draft.md` and `drafts/planning.draft.md` as the SC-006 size baselines. Record their characters and the scene-citation coverage.

**Expect:** two drafts. These numbers become the size ceilings, and the budget defaults in `schema.py` are lowered if the new drafts exceed them.

## S1 — Re-extract under the party grammar

```bash
summary_native extract --since 2 --until 70 --endpoints http://<spark1>:8001/v1 http://<spark2>:8001/v1
```

**Expect:**
- `0 cached` (the prompt changed);
- every chunk has all six sections;
- `drops.md` lists `missing-party-subject` and `level-not-in-cited-text` with counts;
- a `[LEVEL] **Party** — 9` row (or one per character) cited to ch 064/065 survives the check.

Spot-check five dropped level rows: each is a spell level or an unstated level.

## S2 — party (US1, SC-001)

```bash
summary_native synth party --since 2 --until 70 --force
```

**Expect:**
- `state/drafts/party.draft.md` opens with the reading contract.
- `### Zalthir`, `### Thorin Giantfriend`, `### Gyrgum`, `### Daz` appear in `party.yaml` order, and there are no other `###` character sections.
- Each section has a code-built `Level: 9 [ch 06x / …]`.
- `reference/party.md` has groups for the four PCs, `Companions` (Glabbagool, Jimjar, Ront, Prince Derendil, Stool, …) and `Unattributed`.
- `party_report.md` lists every unattributed subject.
- The annotations report exists.

Rebuild with `--force` and an unchanged input: the code-built lines are byte-identical.

## S3 — thread proposals and ratification (US3, SC-002a)

```bash
summary_native thread-propose --since 2 --until 70
```

**Expect** (with OOTA's registry empty):
- every thread note (about 560) is a member of exactly one proposal;
- the number of proposals is at most one-third of the notes;
- `propose_report.md` lists any dropped members.

Then, on the Threads page (or the CLI), ratify three proposals, editing at least one title and splitting one:

```bash
thread_registry ratify --key g-… --emit-plan > plan.yaml   # edit
thread_registry ratify --key g-… --plan plan.yaml
```

Re-run `thread-propose`. **Expect:** the ratified members are attached (`A attached to 3 ratified threads`) and no longer proposed. The split's remainder is a new pending group. A rejected group's notes come back as `single`.

## S4 — planning (US2, SC-002, SC-003)

```bash
summary_native synth planning --since 2 --until 70 --force        # refuses if dossiers are missing
summary_native synth planning --since 2 --until 70 --force --fallback-npc-lines
```

**Expect:**
- **Refusal:** the first run refuses (exit 2), naming each NPC without a usable dossier and its state, exactly as world_state does.
- **Threat Tracker:** the sentinel line (OOTA's `planning.yaml` configures nothing).
- **NPC Dossiers:** every block ends `→ docs/npcs/<slug>.md` or the fallback mark.
- **Active Plots:**
  - only the open ratified threads from S3 appear, newest first;
  - then `### Unratified thread notes (not yet ruled on)` with the count and every other thread note, verbatim.
- **Faction States:** at most 20 written, the rest named with a pointer.
- **DM Notes:** starts with the suggestions label.

Then set one ratified thread to `resolved` with `thread_registry set-status` and rebuild. It leaves Active Plots.

**Secrets canary:** add `CANARY-034` to a dossier's `## Secrets`, rebuild, and confirm `grep -r CANARY-034 state/` finds nothing.

## S5 — arc-score candidates (US4, SC-009)

Use a scratch copy of `planning.yaml` / `party.yaml` with one NPC arc score and one PC arc score, each pointing to a mechanic file. Rebuild both documents.

**Expect:**
- every kept candidate cites a checked note and quotes its trigger verbatim;
- `arc_report.md` lists the drops with reasons;
- no candidate states a value;
- a trackless character has no candidates.

## S6 — size, citations and timing (SC-004–SC-008)

- **SC-006:** characters of each draft (excluding reference files) ≤ the S0 baseline.
- **SC-004 / SC-005:** every citation in a code-built section resolves; ≥ 99% of prose citations resolve; ≥ 90% of quotations are verbatim, and the rest are annotated.
- **SC-007:** `synth party` + `synth planning` with cached notes finish in under 10 minutes, with zero extraction calls (run records).
- **SC-008:** every difference between the pre-annotation and final text of each draft is an annotation or a removal listed in `annotations.md`.

## S7 — web parity

- **From `/grounding/summary-native`:** run party and planning, including the fallback checkbox.
- **From `/grounding/threads`:** run "Propose groupings", ratify a group with an edited member list, and reject one.

Each action produces the same files as its CLI equivalent.

Record the results in this file under "Validation", as T061 did for spec 033.
