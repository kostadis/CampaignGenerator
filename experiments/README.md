# Narration gap-marking experiments — 2026-09-07

Frozen evidence for [NarrationGapEditor_proposal](../docs/design/NarrationGapEditor_proposal.md).
**Evidence only.** No campaign canon, no chapter revision, no production change.

These continue the archive in
[campaigns#237](https://github.com/kostadis/campaigns/pull/237)
(`experiments/narration-adaptation-20260907/`), whose two experiments —
`20260907-phandalin-adaptation` and `20260907-phandalin-scene-composition` — are
the source of every prompt and reference used here and are **not** copied into
this repo. Runners that reference them as `../20260907-phandalin-*` will not
resolve from this location.

**Do not execute these runners here.** They are preserved records, complete with
their original absolute paths (`/home/kostadis/CG-find-bug`,
`/home/kostadis/phandalin`) and their write-once guards. For another trial, use a
fresh directory and explicit paths.

| Directory | What it establishes |
|---|---|
| `20260907-phandalin-fable-medium` | The archived Astra calls replayed on `claude-fable-5-1` / medium, messages byte-identical. Fable is ~40–55% longer on every arm; median paragraph 17 words against Astra's 9. |
| `20260907-phandalin-spark-deepseek` | The same messages on `DeepSeek-V4-Flash-0731` at the DGX Spark. The effort dial does not exist on that backend; the scene contract was not followed. `FINDINGS.md` carries the three-renderer comparison. |
| `20260907-phandalin-fable-gm-gaps` | First gap-marking run (effort `low`). 17 markers; no GM staged as a character; supplied heading kept. |
| `20260907-phandalin-gm-gaps-medium` | The effort isolate at `medium`. 11 markers — the same material cut at one gap per beat rather than three fragments. **The contract carried into the proposal.** |
| `20260907-phandalin-gm-gaps-hermetic` | One sentence added: don't lean on what you withheld. Narration leaks 2 → 0; dialogue up 12%. A tested option, not the v1 contract. |
| `20260907-phandalin-gm-gaps-selffill` | Fable resolving its own 11 gaps. It reassigned two GM lines to a player and marked nothing. `FINDINGS.md` — the reason the ruling is not delegated. |
| `20260907-phandalin-gm-gaps-confirm` | The medium contract, unchanged, over four scenes / four narrators / four sessions. `FINDINGS.md` — the generalization result. |

Every runner records its own `case.json` (frozen input hashes), per-arm
`run.json` (attested model, effort, effort source, response hash), and raw
unedited responses. Attestation is what the adapter sent, not a provider echo —
the same limit the archived Codex records carry.

Read `20260907-phandalin-gm-gaps-confirm/FINDINGS.md` first; it is the result the
proposal rests on.
