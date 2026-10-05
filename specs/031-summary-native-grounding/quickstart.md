# Quickstart & Validation: Summary-Native Grounding Docs

These are runnable checks that prove the feature end to end. Interfaces are in
[contracts/cli.md](contracts/cli.md) and file shapes are in
[data-model.md](data-model.md).

## Prerequisites

- The package is editable-installed into the server venv
  (`uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`), so that
  `summary_native` resolves as a console script.
- A campaign root containing `config/config.yaml` and a directory of structured
  summaries. The reference corpus is Out of the Abyss `docs/summaries/` (67 files).

## Q1. Unit and contract tests (no model, no network)

```bash
python -m pytest tests/test_summary_native_*.py -q
```
Expected: all pass. The no-LLM AST guard and the router default-literal guard are
included.

## Q2. Whole-directory validation reports everything in one run

```bash
cd <campaign-root>
summary_native validate --summaries-dir docs/summaries
```
Expected on the **unfixed** OOTA corpus: exit 1. `070-session-untitled.md L1
title-chapter-mismatch expected "# Chapter 70" found "# Chapter 66"`. Any other
problems appear in the same run. Nothing is written except `validation_report.*`.

Seeded check: `pytest tests/test_summary_native_validate.py::test_all_errors_one_pass`
covers a fixture with one instance of every blocking code across five files and
asserts that every finding appears in a single report.

## Q3. Range selection and the non-blocking out-of-range section

```bash
summary_native validate --summaries-dir docs/summaries --since 2 --until 40
```
Expected: exit 0 (if 002–040 are clean). The 070 mismatch is listed under "Outside
range — not blocking". `--since 1` exits 2 and names the chapters present (002…).

## Q4. Deterministic build is fast and byte-stable

After the GM fixes 070's title:
```bash
time summary_native build --summaries-dir docs/summaries
cp -r docs/summary_native/ch002-070 /tmp/snA
summary_native build --summaries-dir docs/summaries --force
diff -r /tmp/snA docs/summary_native/ch002-070 && echo BYTE-STABLE
```
Expected: under 2 minutes, 67 files and 409 scenes in `manifest.json`, and
`BYTE-STABLE` printed (SC-001, SC-002). Every dossier loads through
`read_dossiers` with zero missing chapter ranges (opt-in test
`CG_OOTA_SUMMARIES=… pytest -m oota`).

## Q5. Corpus separation refuses mixing

```bash
summary_native build --summaries-dir docs/summaries --out-root docs/ensemble
```
Expected: exit 2, "refusing to write a summary-native corpus into a directory holding
ensemble artifacts".

## Q6. Duplicates are listed for fixing at source, never merged

```bash
summary_native validate --summaries-dir tests/fixtures/summary_native/aliases
```
Expected: "Manshon" vs "Manshoon" and "Manshoon (Simulacrum)" vs "Manshoon" are
listed under "Possible duplicates — fix in the summaries", each with `file:line`.
"Staff of Power" as an item and as a spell is **not** listed (different
categories). After a `build`, the dossier count shows nothing merged.

Fix the typo in a copy of the fixture and re-run: that pair disappears. Add the
qualifier pair to `canon.yaml` under `not_duplicates:` and re-run: it is no longer
listed. Add an `accepted:` key and re-run: refused (the file cannot express a merge).

## Q7. Synthesis drafts + GM golden comparison

```bash
summary_native synth world_state --summaries-dir docs/summaries --backend claude-code --model claude-opus-5-5
# GM reviews drafts/world_state.draft.md, then:
summary_native synth campaign_state --summaries-dir docs/summaries \
  --world-state docs/summary_native/ch002-070/drafts/world_state.draft.md \
  --audit <tracking files> --backend claude-code --model claude-opus-5-5
summary_native compare world_state --summaries-dir docs/summaries --live docs/world_state.md
```
Expected:
- The drafts land under `drafts/`, and `git status docs/*.md` shows the live docs
  untouched (SC-007).
- `runs/<doc>/` holds the exact prompts, `selection.json` and `record.json` (SC-009).
- The campaign-state draft has an `## Audit: Tracking Claims` section with
  `NOT FOUND IN SUMMARIES` entries (SC-006).
- The GM compares the drafts against the issue #499 promoted drafts
  (`experiments/20261004-oota-ensemble-summary-prototype/` on branch `experiments/oota-ensemble-summary-prototype`, not on main; the promoted copies are the OOTA workspace's live `docs/*.md`) and judges them at least
  as good (SC-008, manual).

Incomplete-output check: `--max-tokens 512` produces `drafts/world_state.incomplete.md`
and exit 3, with a message naming the missing headings and `--parts`.

## Q8. UI parity

1. Start the app (`./startup`) and open **Grounding Docs → Summary-native**.
2. Run Validate with no range selected. Expected: the run is refused with "choose a
   chapter range".
3. Click "All chapters". The range fills in the first and last chapters present.
4. Run Validate and Build, then Synth world_state.

Expected: the files written are the same as a CLI run with the same arguments, and
the page shows the validation report (including possible duplicates) and the draft list.
