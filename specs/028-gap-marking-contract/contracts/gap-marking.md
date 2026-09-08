# Contract — gap marking

What the mode promises, in the two places it is observable: the assembled prompt, and the render
beside it.

## The option

| Surface | Spelling | Type | Default |
|---|---|---|---|
| `sd_narrate` | `--gap-marking` | store_true | off |
| `session_doc.yaml` | `narrate.gap_marking` | bool | `false` |
| Session Doc Editor | a toggle in the Stage-④ knobs | off |

One spelling, one meaning, one default (Principle XII). `sd_narrate` is the only renderer, so
the "whole family" is one script; the UI toggle ships in this feature, not a follow-up
(Principle XI).

## The prompt

| # | Guarantee |
|---|---|
| **P1** | With the mode off, the assembled prompt is byte-identical to the pre-feature prompt. All 256 `build_narrate_system` combinations, both render paths, prose mode either way. |
| **P2** | With the mode on, no fragment of the assembled prompt instructs that GM description becomes experienced fact. |
| **P3** | With the mode on, the prompt asks for `[GM NARRATION — TO BE WRITTEN: …]` on its own line, and says the markers are required output rather than commentary. |
| **P4** | With the mode on, the prompt retains "a GM turn that only confirms or adjudicates is table operation and is dropped". |
| **P5** | P2–P4 hold identically in the per-scene and bundle paths. |
| **P6** | With the mode **on**, the rule about the GM appears **once**: the contract exactly once, the absorbing clause zero times. |

**P6 binds gap-on only, and the narrowing was found in implementation.** As first written it
bound both modes. It cannot: `writing_brief.md` and `prose_mode.md` each carry the absorbing
clause, so gap-off with prose mode on has always delivered it **twice**. That duplication is
part of the state `#454` describes, and P1 forbids touching it — deduplicating would move the
gap-off prompt for every render a GM never opted into. `test_gap_off_keeps_its_pre_existing_duplication`
pins the count at 1 and 2 so the asymmetry reads as a decision rather than an oversight.

P1 is the one that can be proven mechanically and completely; P2–P6 are assertions over the
assembled string. None of them is a claim about what the model *does* with the prompt — that is
what re-confirmation is for.

## Refusal

| Condition | Behaviour |
|---|---|
| Mode on, contract fragment missing or unreadable | **Refuse**, naming the path. Never render. |
| Mode on, bundle path | Render, with the contract (Q2 ruling). |
| Mode off, contract fragment missing | Refuse at import, as any template drift does today. |

The refusal on a missing contract is deliberately the opposite of the genre file's ruling, which
warns and renders on. A missing genre costs register; a missing contract costs attribution, and
rendering without it is the failure the feature exists to remove.

## The record

A completed render writes `session_doc_scene_NN_<slug>.knobs.json` carrying:

| Field | Meaning |
|---|---|
| `gap_marking` | whether the mode was on |
| `gap_contract` | the fragment's path |
| `gap_contract_sha256` | digest of its bytes |

Identity, never a copy — the `#276` ruling that put a 16,303-character genre paste into a file
applies to any document a run wants to be able to name later. Written by the CLI so a terminal
render and a UI render record the same thing (research D8).

## What is out of scope

- Answering a gap. The marker is produced and survives into the per-scene file; `#455` gives it
  a place to be answered and `#456` an editor.
- Gating `assemble` on zero open gaps. `#455`'s.
- Enforcing at render time that the model obeyed. Markers are checkable after the fact, which is
  what the record and re-confirmation are for.
