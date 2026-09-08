# Quickstart: validating bracketed speaker labels

**Feature**: `specs/027-bracketed-speaker-labels` | **Date**: 2026-09-08

How to prove the feature works, end to end, without a model call or a campaign workspace. The
evidence set is four frozen scene extractions committed to this repo.

## Prerequisites

- The package editable-installed into the working venv (`uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`).
- No API key, no network, no campaign directory. This feature spends no tokens.

## The evidence set

`experiments/20260907-phandalin-gm-gaps-confirm/inputs/` — four sessions, four narrators, two
label conventions:

| File | Convention | Today | Expected after |
|---|---|---|---|
| `brewbarry_source.md` | bare | 4 characters counted | **unchanged** |
| `soma_source.md` | bare | 4 characters counted | **unchanged** |
| `valphine_source.md` | bracketed + joint | nothing | Brewbarry, Soma, Vukradin present |
| `vukradin_source.md` | bracketed | nothing | Vukradin, Soma, Brewbarry present |

`Valphine` is expected to stay unresolved in the two bracketed files: they write the short
form and the roster declares `Valphine Sotorra`. That is the documented out-of-scope case
(spec Assumptions), not a failure.

## 1. The defect, before you change anything

```bash
python -c "
from session_doc.io import scene_speaker_counts
from pathlib import Path
d = Path('experiments/20260907-phandalin-gm-gaps-confirm/inputs')
for f in sorted(d.glob('*_source.md')):
    print(f'{f.name:24} -> {scene_speaker_counts(f.read_text())}')
"
```

Expected today — two of four empty:

```text
brewbarry_source.md      -> {'Soma': 18, 'Brewbarry': 21, 'Vukradin': 12, 'Valphine Sotorra': 2}
soma_source.md           -> {'Vukradin': 19, 'Valphine Sotorra': 31, 'Soma': 5, 'Brewbarry': 10}
valphine_source.md       -> {}
vukradin_source.md       -> {}
```

Record the two non-empty results. They are the regression baseline for SC-004.

## 2. Unit level — the grammar

Each row of the worked-examples table in [`data-model.md`](./data-model.md) is one test case:
label in, class and presence out. The cases that must not be dropped:

- `[GM, as the banker]` → game master, nobody present.
- `[GM / Brewbarry]` → Brewbarry present, one turn.
- `[Brewbarry / Soma]` → both present, one turn each.
- `[GM / Brewbarry / Valphine]` → Brewbarry and Valphine present.
- `[scene tag — Vukradin demands a meeting]` → **nobody** present. This is the one that fails
  if resolution ever becomes containment rather than folded equality.
- `Vukradin (David)` → unresolved, still listed loudly.
- An indented `  **Brewbarry**` → not a label.

## 3. Integration — eligibility over the corpus

Run eligibility for each of the four sessions against the Phandalin roster and confirm:

- **SC-001** — all four yield a non-empty narrator pool.
- **SC-002** — for the bracketed sessions, every character with a labelled turn in a scene is
  listed as present in that scene.
- **SC-004** — the two bare-convention sessions produce output identical to the baseline
  captured in step 1. Diff it; do not eyeball it.
- **SC-005** — no roster character gains presence from any GM label form.
- **SC-007** — the three multi-character joint turns credit each character named.

## 4. The report — SC-003 and SC-008

Run the eligibility report for `vukradin_source.md` and read the two unresolved-label
sections:

- **SC-003** — every unresolved label is accounted for somewhere. Nothing vanishes.
- **SC-008** — the loud bucket (*"looks like a roster character but did not resolve"*) has not
  grown. Specifically, `[scene tag — Soma's Arcana check]` and `[scene tag — Vukradin demands
  a meeting]` must **not** appear there; they belong in the counted-not-listed line.

If those two beat markers show up in the loud bucket, Decision 3 in
[`research.md`](./research.md) was not implemented and the channel `#385` built is being
diluted.

## 5. Whole suite

```bash
python -m pytest tests/
```

The baseline at the time of writing is **5071 passed, 174 skipped**. Two existing files
exercise this code and are expected to change:

- `tests/test_plan_eligibility.py` — `test_scene_speakers_skips_bracketed_action_beats` asserts
  the old contract at the wrong level. Its *intent* (a beat marker creates no presence) must
  survive as an eligibility-level assertion; the parse-level assertion does not.
- `tests/test_plan_review_regressions.py` — asserts presence and counts come from one parse.
  Must still hold (FR-009).

## Done when

- All four sessions plan.
- The two bare-convention sessions are byte-identical to the baseline.
- No beat marker creates presence, and none has moved into the loud report bucket.
- The suite is green.
