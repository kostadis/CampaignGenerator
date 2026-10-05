# Session Log: 031 Summary-Native Grounding

## 2026-10-05 — T056: quickstart Q1–Q6 against the real Out of the Abyss corpus

Source: `/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/summaries` (67 files),
which was **read only**. Every run wrote under the session scratchpad
`--out-root`, never into the campaign. No summary file was edited.

| Check | Result |
|---|---|
| Q1 tests | `tests/test_summary_native_*.py`: 224 passed, 1 skipped (opt-in real-corpus test) |
| Q2 one-pass validation | exit 1. 8 blocking: seven files titled `# Session <date>` instead of `# Chapter N` (015, 016, 019, 054, 065, 067, 068), and `070-session-untitled.md` titled `# Chapter 66`. 38 non-blocking: gaps at 33 and 66, plus 36 possible duplicates. All reported in one run |
| Q3 range | `--since 2 --until 14` gives exit 0, with the later problems listed under "Outside range — not blocking". `--since 1` gives exit 2 and lists the chapters present |
| Q4 build (scratch copy with only the titles fixed) | 1.5 s; 67 files, 409 scenes, npc 590 / location 319 / item 394 / spell 301 / ability 1 (the same as the #499 prototype); 869 dossiers (prototype 868); `complete: true`; two builds **byte-identical** |
| Q5 corpus separation | An out-root holding `merged.json` is refused: "summary-native and ensemble corpora must never be mixed" |
| Q6 possible duplicates | 36 listed with every `file:line` (item 15, npc 8, spell 7, location 6). Examples: Naomi/Nomi Pathshutter, straight vs curly apostrophes (`Tasha's` ×13 vs `Tasha’s` ×1), Pygmywort/Pygmyworts, qualifier pairs |

### For the GM (not fixed by the tool, by design)

- Retitle the seven `# Session <date>` summaries to `# Chapter N`.
- Decide whether `070-session-untitled.md` is chapter 70 (fix its title) or
  chapter 66 (rename the file). Chapter 66 is also a gap.
- Work through the 36 possible duplicates. Fix each spelling in the summaries,
  or record genuinely distinct pairs under `not_duplicates` in
  `docs/summary_native/canon.yaml`.

### Earlier smoke test (US5, T051)

A server on port 5099 ran against a scratch campaign. These all worked through
the real routes: `/chapters`, the unset-range refusal, validate, build, and
`synth world_state --dump-only`. The world_state prompt was 596 KB, with 76
recent and 10 recurring dossiers (prototype: 673 KB, 75 + 10).

### Not yet done

- No real model synthesis has been run. SC-008 (GM judgment against the #499
  drafts) is pending the GM.
- The page was not clicked through in a browser. The routes and the frontend
  build were verified instead.
