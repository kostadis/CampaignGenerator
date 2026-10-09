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

## Validation (2026-10-09, Out of the Abyss copy, ch002–070)

Run on a scratch copy of the campaign (config + docs). Extraction on both Sparks with `qwen3.8-flash-next` (the GM's choice for this run); prose and proposals on `claude-sonnet-5-5` at medium effort through `claude-code`.

| Step | Result |
|---|---|
| **S0** one-shot baselines (main @ 1a75c64) | party **9,377** chars (66 s); planning **12,451** chars (43 s) |
| **S1** extract, two Sparks, qwen3.8 | 60 chunks in **955 s**; kept **2,788**, dropped 231 (uncited 200, malformed-row 24, level-not-in-cited-text 3, quoted-span-not-found 3, outside-chunk 1); **0 missing-party-subject**. Six outlier chunks flagged. Found and fixed: qwen3.8 writes `**[LEVEL] Daz**` (tag inside the bold); now parsed as a level row (b97ae15). Level rows confirmed: Party 2, 4, 7, 8, **9 [ch 063 / 063.06]** and the four PCs at 4 (ch 016) |
| **S2** party | 67 s; every section within budget; **level 9 cited on all four PCs (SC-001 ✅)**; 452 party notes → 273 to a PC, 139 whole-party, 40 to 13 companions, **0 unattributed**; "Thorin" reaches "Thorin Giantfriend" through the registry; annotations 13 later, 16 since, 2 unverified, 0 removed. Size **22,774** chars — **SC-006 ❌** (2.4× the one-shot) |
| **S3** thread-propose, empty registry | 16 s; 311 notes, 290 names, 275 seen once; **31 groups, 247 proposals (216 single) — SC-002a ❌** (target ≤ 104); 0 dropped. The groups made were sound (Drow Pursuit, Pudding King, Jimjar's True Nature, Janussi Murder Investigation); the prompt's "leave a note out rather than guess" keeps recall low |
| **S3** ratify round trip (copy only) | three groups ratified (one retitled, one split + set dormant), `check` 0 problems; re-run: **10 notes attached by exact name, no model**; 205 proposals (165 single). Found: a split-off note sharing a ratified member's name attaches anyway (**#529**) |
| **S4** planning | default settings **refuse** (6 NPCs without a usable dossier, each named with its state and the fix commands — as world_state); with `--fallback-npc-lines` 41–42 s. Threat Tracker = sentinel (no arc scores configured); 15 NPC entries, 20 factions written; Active Plots: ratified open threads newest first, `### Dormant threads`, then 301 unratified notes verbatim. Annotation flagged Buppido's plan (open from ch 007) with `ℹ since:` Buppido dead ch 018. Size **73,105** chars — **SC-006 ❌**, almost all of it the unratified block; the rest is near the one-shot's size |
| **Secrets canary** | marker added to `alaundo-the-seer.md`'s `## Secrets`; Alaundo is in planning (4 mentions) and the marker is in **no** draft, report or recorded prompt (**SC-003 ✅**) |
| **SC-007** | party + planning from cached notes ≈ **110 s**, zero extraction calls ✅ |

**GM rulings (2026-10-09):**
- **Unratified notes:** they move to `reference/threads_unratified.md`. Rebuilt, planning is **20,340** chars and the reference file 53,613. Active Plots keeps the heading with the count (301) and pointers. `check-pointers` resolves every pointer.
- **Size:** party (22.8K) and planning (20.3K) are both accepted as built; SC-006 is amended to bound each by its budgets.
- **Proposals:** precision over recall; the one-third target in SC-002a is dropped.
