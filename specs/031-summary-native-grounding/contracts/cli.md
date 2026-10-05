# CLI Contract: `summary_native`

One console script, `summary_native = "pipelines.summary_native.cli:main"` in
`pyproject.toml [project.scripts]`. It is run from the campaign root, and
`--config` is auto-detected via `find_default_config()` (Principle XII).

## Shared flags (every subcommand that reads summaries)

| Flag | Meaning | Default |
|---|---|---|
| `--summaries DIR` | directory of structured summaries (`*.md`) | `grounding.yaml summary_native.summaries_dir`; error if neither is set |
| `--from N` / `--to N` | inclusive chapter range (filename prefixes) | unset = whole directory |
| `--out-root DIR` | output root | `docs/summary_native` |
| `--registry PATH` | entity registry | auto-discover `docs/entity_registry.yaml` (`resolve_registry_arg`) |
| `--canon PATH` | hand-authored not-a-duplicate rulings | `<out-root>/canon.yaml` (absent = none) |
| `--config PATH` | campaign config | `<cwd>/config/config.yaml` |

The range directory is `<out-root>/ch<start:03d>-<end:03d>/`. For an unset range,
the start and end are the first and last chapters present.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | validation found blocking problems (report printed and written) |
| 2 | usage / refusal (bad range, missing input, mixed corpus, existing output without `--force`) |
| 3 | synthesis produced an incomplete document (`.incomplete.md` written) |

## `summary_native validate`

Scans every file, prints the full report, and writes
`validation_report.{md,json}` into the range directory. It writes nothing else and
makes no model call. Exit 0 or 1.

```text
summary_native validate --summaries docs/summaries --from 2 --to 40
```

Stdout shape:
```text
[summary-native] scanned 67 files (39 in range 2–40)
070-session-untitled.md  (outside range — not blocking)
  L1   title-chapter-mismatch   expected "# Chapter 70"  found "# Chapter 66"
...
[summary-native] 0 blocking problems in range; 1 outside range; gaps: none
```

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
built range directory and refuses otherwise.

| Flag | Applies to | Meaning |
|---|---|---|
| `--world-state FILE` | campaign_state, party, planning | GM-reviewed world-state draft to use as context (FR-020) |
| `--campaign-state FILE` | party, planning | GM-reviewed campaign-state draft |
| `--audit FILE…` | campaign_state | tracking / planning / module files treated as questions (FR-019) |
| `--party-config PATH` | party | `config/party.yaml` (existing flag name) |
| `--planning-config PATH` | planning | `config/planning.yaml` (existing flag name) |
| `--recent-chapters N` | all | default 4 (from config) |
| `--recurring-min N` | all | default 10 (from config) |
| `--name SUBJECT…` | all | force-include dossiers (reason `named`) |
| `--parts N` | all | 0 = single call; N = split the outline into N calls |
| `--dump-only` | all | write prompts and the record, make no model call |
| `--force` | all | overwrite an existing draft |
| `--backend --endpoint --model --max-tokens` | all | via `add_backend_args`, same as `synthesise_world_state` |

It writes `runs/<doc>/…` and `drafts/<doc>.draft.md`, or `.incomplete.md` with
exit 3. It never writes outside the range directory.

## `summary_native compare <doc> --live FILE`

Reports bytes, lines and the heuristic highest chapter for the draft and the live
file, and writes `drafts/<doc>.vs-live.diff`. It is read-only with respect to both
inputs.
