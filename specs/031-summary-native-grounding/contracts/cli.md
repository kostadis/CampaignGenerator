# CLI Contract: `summary_native`

One console script, `summary_native = "pipelines.summary_native.cli:main"` in
`pyproject.toml [project.scripts]`. It is run from the campaign root, and
`--config` is auto-detected via `find_default_config()` (Principle XII).

## Shared flags (every subcommand that reads summaries)

| Flag | Meaning | Default |
|---|---|---|
| `--summaries-dir DIR` | directory of structured summaries (`*.md`). Not `--summaries`, which `party.py`/`planning.py` use for a single FILE (Principle XII) | `grounding.yaml summary_native.summaries_dir`; error if neither is set |
| `--since N` / `--until N` | inclusive chapter range (filename prefixes). `--since` matches `planning.py`'s chapter lower bound; `--from`/`--to` are taken (`sd_review`, `registry`) | unset = whole directory |
| `--out-root DIR` | output root | `docs/summary_native` |
| `--registry PATH` | entity registry | file or campaign dir. Default: `grounding.yaml summary_native.registry`, else auto-discover `docs/entity_registry.yaml` under the campaign root. An explicitly set path that does not exist → exit 2 |
| `--canon PATH` | hand-authored not-a-duplicate rulings | `grounding.yaml summary_native.canon_file`, else `<out-root>/canon.yaml`. The default may be absent (no rulings); an explicitly set path that does not exist → exit 2 |
| `--dup-threshold R` | similarity ratio at or above which two same-category headings are listed as a possible duplicate | `grounding.yaml summary_native.dup_threshold` (0.88) |
| `--config PATH` | campaign config | `<cwd>/config/config.yaml` |

The range directory is `<out-root>/ch<since:03d>-<until:03d>/`. For an unset range,
the start and end are the first and last chapters present.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | validation found blocking problems (report printed). `validate` and `build` also write it; `synth` exits 1 too when the range has blocking problems, and prints the report without writing it |
| 2 | usage / refusal (bad range, missing input, mixed corpus, existing output without `--force`) |
| 3 | synthesis produced an incomplete document (`.incomplete.md` written) |
| 4 | the model call failed in a part (`synth` only). `record.json` keeps `check.error`; stderr names the part, the exception and the record path. No draft is written |

## `summary_native validate`

Scans every file, prints the full report, and writes
`validation_report.{md,json}` into the range directory. It writes nothing else and
makes no model call. Exit 0 or 1.

```text
summary_native validate --summaries-dir docs/summaries --since 2 --until 40
```

Stdout is the same markdown as `validation_report.md` (an excerpt):
```text
# Validation report

- Summaries directory: docs/summaries
- Range: 2–40
- Files scanned: 67
- Files in range: 39
- Gaps: none

## In range

### docs/summaries/070-session-untitled.md

missing-title  expected "# Chapter 70"  found "# Session 2025-04-14"  — no `# Chapter N` title line

L12  title-chapter-mismatch  expected "# Chapter 71"  found "# Chapter 66"  — title chapter disagrees with the filename prefix; fix the summary

## Outside range — not blocking

(none)

## Summary

- Blocking problems: 2
- Files failing: 1
- Non-blocking findings: 0
```
A finding with no line number omits the `L<n>` token. An unreadable file is an
`unreadable-file` finding, not an abort.

## `summary_native build`

Runs `validate`, then exits 1 if anything blocks. Otherwise it writes `manifest.json`,
`chronology.md`, `memorable_moments.md` and `dossiers/`.
- It refuses to write into a directory holding another corpus (exit 2).
- `--force` rewrites an existing summary-native range directory. Without it, an
  existing manifest makes it exit 2.
- It makes no model call.

## Possible duplicates (part of `validate`)

There is no separate subcommand. `validate`, and therefore `build`, lists
non-blocking `possible-duplicate` findings under "Possible duplicates — fix in the
summaries". Each one gives the category, both spellings, and every `file:line` for
each. Stale `canon.yaml` rulings are listed too. The GM fixes the summary files, or
adds the pair to `canon.yaml` under `not_duplicates`, and re-runs.

## `summary_native synth <doc>`

`<doc>` is one of `world_state`, `campaign_state`, `party`, `planning`. It requires a
built range directory and refuses otherwise. Before rendering, it re-runs validation and compares
every in-range file's sha256 against `manifest.json`. On any mismatch it exits 2 with
"summaries changed since build — run `summary_native build --force`" (FR-005b).
Blocking validation problems in the range exit 1 instead (as `validate`/`build`).
It also compares the sha256 of the entity registry `build` would use now (the
configured `summary_native.registry`, an explicit `--registry`, or the auto-discovered `docs/entity_registry.yaml`; absent =
none) with the one recorded in `manifest.json` (`canon.registry_sha256`); on mismatch
it exits 2 with "entity registry changed since build — run `summary_native build
--force`". `canon.yaml` changes do not make a corpus stale: they affect validation
findings only, never the corpus.

| Flag | Applies to | Meaning |
|---|---|---|
| `--world-state FILE` | campaign_state, party, planning | GM-reviewed world-state draft to use as context (FR-020). Any other doc exits 2: "--world-state does not apply to world_state" |
| `--campaign-state FILE` | party, planning | GM-reviewed campaign-state draft. Any other doc exits 2 ("--campaign-state does not apply to …") |
| `--audit FILE…` | campaign_state | tracking / planning / module files treated as questions (FR-019); default `grounding.yaml campaign_state.track_files` |
| `--party-config PATH` | party | default `<config dir>/party.yaml`; resolved against the campaign root. Missing/invalid/empty roster (one error line), or a missing sheet/backstory/arc-score file, exits 2. Refused for other docs |
| `--planning-config PATH` | planning | default `<config dir>/planning.yaml`; an absent *default* file means no arc scores, an absent *explicit* path exits 2. With no arc score configured the `## Threat Tracker` body must be exactly `_No arc scores configured._` or the run is incomplete (exit 3, "threat tracker must be empty: no arc scores configured"). Planning selects NPC dossiers only. Refused for other docs |
| `--recent-chapters N` | all | default 4 (from config) |
| `--recurring-min N` | all | default 10 (from config) |
| `--name SUBJECT…` | all | force-include dossiers (reason `named`) |
| `--parts N` | all | 0 = single call; N = split the outline into N calls |
| `--dump-only` | all | write prompts and the record, make no model call |
| `--force` | all | overwrite an existing draft |
| `--backend --endpoint --model --max-tokens` | all | via `add_backend_args`, same as `synthesise_world_state` |

It writes a new `runs/<doc>/<run_id>/…` per invocation (never touching earlier
runs) and `drafts/<doc>.draft.md`, or `drafts/<doc>.incomplete.md` with exit 3. An
incomplete run keeps any existing `.draft.md` and prints
`previous draft kept: drafts/<doc>.draft.md (from run <id>)`; an existing
`.incomplete.md` never blocks a run. A backend/model pair that cannot work together
exits 2 with a message. It never writes outside the range directory.

## `summary_native compare <doc> --live FILE`

Reports bytes, lines and the heuristic highest chapter for the draft and the live
file, and writes `drafts/<doc>.vs-live.diff`. It is read-only with respect to both
inputs.
