# Contract: Batched Response Wire Protocol

**Feature**: 013-batched-scene-extraction | Governs FR-004, FR-005, FR-006, FR-010, FR-011

The format the model is asked to emit, and the rules for splitting it back into
per-scene content. Deterministic: no model call, no similarity matching (FR-004).

---

## 1. Sentinel syntax

Each requested scene is returned as:

```
<<<CG-SCENE {NN} BEGIN: {name}>>>
{moments}
<<<CG-SCENE {NN} END>>>
```

- `{NN}` — the scene's request index, zero-padded to 2 digits (`ScenePlanEntry.i`).
- `{name}` — the scene name, echoed for verification only.
- `{moments}` — the extraction body, in the format the per-scene mode already
  produces (`**[Speaker]** — *context*` / `> "quote"` / `**[scene tag]**` +
  bullets). Unchanged from `config/agents/scene_extract.md`.

Both sentinel lines must start at column 0 and occupy a line of their own.

### Why this shape (research D5)

| Requirement | How the shape meets it |
|---|---|
| Survive arbitrary scene names | Attribution is by `{NN}`; the name is checked, never matched |
| Survive duplicate scene names | Index is unique by construction (DM-1) |
| Survive the model's own markdown | `<<<CG-` appears nowhere in the extraction vocabulary |
| Express "the response stopped here" | An unmatched BEGIN **is** the incomplete signal |
| Survive a continuation seam | `_claude_code_generate` concatenates turns before the split runs; a seam inside a body is invisible to the split, and a seam that lands inside a sentinel line yields `incomplete` — degrading safely |

**Rejected**: markdown headings (collide with `**[scene tag]**`, cannot express
incompleteness); JSON (every verbatim quote becomes an escaping hazard, and a
truncated document yields *nothing*, defeating FR-010); name-only delimiters
(break on duplicates, and matching a re-worded name back to a request is
exactly the similarity-based identity assertion this repo forbids).

---

## 2. Parsing algorithm

Given a response and the group's requested entries:

1. Scan for BEGIN markers in order of appearance; record `(index, echoed_name, offset)`.
2. For each BEGIN, scan forward for the next `<<<CG-SCENE {same NN} END>>>`.
   - Found → section is **closed**; body is the text between the markers.
   - Not found → section is **incomplete**.
3. Reconcile against the requested indices (§3).
4. Strip each closed body; empty after stripping → **empty**, else **complete**.
5. Requested indices with no BEGIN → **absent**.

Text outside any BEGIN/END pair (preamble, commentary, trailing notes) is
**discarded**. It is never appended to an adjacent scene.

---

## 3. Reconciliation rules

The group fails — nothing from it is written (FR-005, DM-14) — if any holds:

| Failure | Condition |
|---|---|
| `UNKNOWN_INDEX` | A BEGIN carries an index not in this group's request |
| `DUPLICATE_INDEX` | The same index opens more than once |
| `NAME_MISMATCH` | The echoed name differs from the requested name after normalising surrounding whitespace |
| `NESTED_SECTION` | A BEGIN appears before the preceding section's END |
| `NO_SECTIONS` | No BEGIN at all, and the group requested ≥ 1 scene |

Name comparison normalises **only** leading/trailing whitespace and internal
whitespace runs. It is not case-folded, not punctuation-stripped, not
similarity-scored — a mismatch is a hard failure, never a re-assignment (DM-13).

Missing indices are **not** a group failure: an absent scene is unfinished work
(§4), not evidence the response is untrustworthy.

---

## 4. Section outcomes

| Outcome | Condition | Written? | Reported as |
|---|---|---|---|
| `complete` | Closed, non-empty body | **Yes** | counted in `scenes_written` |
| `empty` | Closed, blank body | No | `scenes_empty` — "returned no moments" |
| `incomplete` | BEGIN with no matching END | No | `scenes_missing` |
| `absent` | Requested, never opened | No | `scenes_missing` |

`empty` and `incomplete` must stay distinguishable (spec Edge Cases): the first
is a finished result — the transcript genuinely holds nothing for that scene, and
silence is the correct extraction — while the second is unfinished work. Writing
an `empty` scene as a file would make skip-if-exists treat unfinished work as
done on the next run.

---

## 5. Writing

Each `complete` section goes through the **same** path as the per-scene mode:

```
text = format_scene_output(entry.name, entry.body, section.body)
if snapshot_scene_for_rerun(entry.path, text):
    entry.path.write_text(text, encoding="utf-8")
```

This is what guarantees SC-006 (structurally indistinguishable files) and
FR-014 (force semantics preserved: `.prev` snapshot only when content differs,
`.reviewed` cleared, no write when identical) without reimplementing either.

---

## 6. Prompt-side obligations

`config/agents/scene_extract_batched.md` must state:

1. Emit **exactly one** BEGIN/END pair per scene given, in the order given.
2. Copy the index and name **verbatim** from the request line.
3. Emit nothing outside the pairs.
4. Emit a scene's pair even when the transcript holds nothing for it — with an
   empty body. Silence is a result; omission is indistinguishable from truncation.
5. Every verbatim ground rule from `scene_extract.md` applies **within each
   scene**: no merged utterances, no editorial insertions inside a `> "…"` span,
   no repairing transcript garbles, the transcript owns its own mistakes
   (FR-016, Constitution IV).

Rule 5 is the one under pressure: a model rationing one budget across N scenes
is exactly a model tempted to summarise the tail. The verifier gate
(SC-003/SC-004) exists because prompt instructions alone are not evidence.
