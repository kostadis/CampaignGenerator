# Contract: Run Identity and Reporting

**Feature**: `021-claude-code-effort`

What a `claude-code` run must say about itself. This contract is the whole of User Story 3, which is P1 because the reporting gap is a live defect: today a run can execute at a lower effort than the operator pinned, and nothing anywhere says so.

---

## The identity object

Assembled once per run, before the child spawns.

| Field | Example |
|---|---|
| `effective_model` | `claude-opus-5` |
| `effort_sent` | `high`, or `None` |
| `source` | `explicit` / `environment` / `clamp` / `inherited` |
| `override_sent` | `true` / `false` |
| `thinking_on` | `false` |

---

## The four reported states

| Source | Banner text |
|---|---|
| `explicit` | `model=claude-opus-5 effort=max (explicit) thinking=on` |
| `environment` | `model=claude-opus-5 effort=high (CG_CLAUDE_CODE_EFFORT) thinking=off` |
| `clamp` | `model=claude-opus-5 effort=high (compatibility clamp — thinking is off, and the provider refuses xhigh/max without it; your settings.json effortLevel was not used) thinking=off` |
| `inherited` | `model=claude-fable-5 effort=inherited from your ~/.claude/settings.json (CampaignGenerator sent no override) thinking=on` |

**Three rules the wording must hold:**

1. **`clamp` says why.** It is the engine overriding a level the operator set elsewhere. Reporting it as a bare `high` reproduces the original defect in new packaging — the operator sees a number and reads it as their own choice.
2. **`inherited` claims no value.** The child resolves `effortLevel` from a file this process does not read. Printing a guess would be an Optimistic Lie in the one record built to prevent them.
3. **`thinking` is always shown.** It is what makes the top two levels legal, so an operator debugging a refusal needs it in the same line, not inferred from its absence.

---

## Where it appears

| Surface | Requirement |
|---|---|
| Command output | One banner, before model work, on every `claude-code` run (FR-018) |
| Existing sidecars / logs / run summaries | Wherever the effective Claude Code model is already recorded, the effort state and source join it (FR-019) |
| UI progress and result views | `StreamOutput.vue` surfaces the banner; `ConnectionGraph.vue` and `SelectionPanel.vue` show the resolved state (FR-021) |
| Failure paths | Error, interruption, and timeout keep the effort state in diagnostic output and in saved failure metadata **where such metadata already exists** — this feature adds no new failure-metadata store |

---

## Bounding the output

**One banner per run, not one per call.** #359 learned this the expensive way: a per-call print flooded streamed polish output, and the fix was a single identity banner. A dispatcher fanning out to 40 children must not emit 40 banners into one stream.

Emit at run start, from the identity object, once. A child started by retry or resume inherits the same identity and does not re-announce it.

---

## Structured errors keep their identity

A refusal (bad value, wrong backend, effort/thinking conflict) must remain recognisable to the same error-handling paths that already classify `claude-code` failures. Adding effort must not convert a typed refusal into an untyped `RuntimeError`, and must not weaken the existing `is_error` / non-zero-exit / non-JSON-output branches in `_claude_code_generate`.

---

## Verification

The measurable claim is SC-008: *an operator who has pinned one of the two highest levels in their own Claude Code settings can determine, from a single run's output alone and without external help, which level that run used and why.*

Concretely, with `effortLevel: xhigh` in `~/.claude/settings.json` and no CampaignGenerator selection, a default run on a clamp-eligible model must make all three facts readable from its own banner: the run used `high`; the operator's `xhigh` was not used; and the reason was that thinking is off.

That exact scenario is un-answerable from today's output, which is the defect this contract closes.
