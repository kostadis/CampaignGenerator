# Phase 1 — Data model

No database, no schema migration, no change to any file's shape on disk. What follows is the
set of things this feature names, and the one file that gains a field.

## Entities

### Gap contract

The text instructing the model to mark rather than absorb GM material.

| Attribute | Value |
|---|---|
| Home | `config/agents/session_doc/narrate/gm_attribution_gap.md` (Q1 ruling) |
| Scope | Repository-wide. Not per campaign, not a config string |
| Identity downstream | SHA-256 of the file's bytes |
| Reaches the prompt via | `{gm_attribution}` in `writing_brief.md` |
| Selected by | gap-marking mode |

Its sibling `gm_attribution_absorb.md` holds today's sentence character-for-character and is
what the same slot receives when the mode is off. `gm_attribution_prose_{absorb,gap}.md` are the
same pair for `prose_mode.md`'s slot (research D3).

### Gap marker

A line the model emits in place of GM description.

```
[GM NARRATION — TO BE WRITTEN: one plain sentence stating what the source establishes there]
```

| Property | Value |
|---|---|
| Position | Its own line, in the flow of the scene |
| Survives assembly | **Yes** — it is content, not apparatus (research D5) |
| Stripped by `strip_audit_comments` | No, and must not be |
| Visible to the unknown-name scan | Yes, deliberately (research D6) |
| Consumed by | `#455`'s authored/composed document model |

### Gap-marking mode

| Surface | Spelling | Default |
|---|---|---|
| CLI | `--gap-marking` | off |
| Config | `narrate.gap_marking: bool` on `NarrateKnobs` | `False` |
| Route | `_build_narrate_cmd` passes the flag through | — |

`NarrateKnobs` is `extra="forbid"`, so the field is additive and a config written before this
feature loads unchanged and takes the default. **No migration** — Principle XIII is triggered by
a change to the *shape* of state, and adding an optional field with a default is not one. Nothing
is retired, nothing is relocated, no existing key changes meaning.

### Render record

`session_doc_scene_NN_<slug>.knobs.json`, beside the narration. Ownership splits (research D8):

| Field group | Written by | Examples |
|---|---|---|
| Render identity | `sd_narrate` | `model`, `backend`, `prose_mode`, `gap_marking`, `narration_genre_file` + digest, `gap_contract` + digest |
| Run outcome | the server, merged in | `status`, `exchange_count`, `written_count`, `missing_count`, `rejected_count` |

One file, two writers in sequence, never concurrently — the server merges only after the
subprocess it launched has exited. `_read_knobs_sidecar` keeps reading one file.

### Accepted-gap fixture

The 31 markers the GM ruled correct, frozen so re-confirmation has a criterion.

| Attribute | Value |
|---|---|
| Source | `experiments/20260907-phandalin-gm-gaps-confirm/{brewbarry,soma,valphine,vukradin}/response.md` |
| Counts | brewbarry 6, soma 12, valphine 4, vukradin 9 — **31** |
| Frozen at | `specs/028-gap-marking-contract/accepted_gaps.json` |
| Ruling | all 31 accepted, 2026-09-08 |

### Pre-feature prompt golden

`specs/028-gap-marking-contract/golden_pre_feature.json` — a copy of
`tests/golden/prompts/narrate_system_matrix.json` taken before any template edit. 265 entries.
The evidence for FR-005 (research D4).

## State transitions

None. Gap marking is a per-render setting read at render time; it does not put a scene into a
state, and it does not change what a scene file *is*. The authored → composed lifecycle that
would introduce states belongs to `#455`.
