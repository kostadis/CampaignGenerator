# Quickstart — validating the block model and the reviewer

Run from the repository root. Everything here is deterministic and spends nothing — this layer
calls no model, which is the point rather than a happy accident.

## 0. The corpus this validates against

Four narrations with markers already on disk, and the GM's rulings on all 31 of their gaps:

```bash
grep -c "GM NARRATION — TO BE WRITTEN" \
  experiments/20260907-phandalin-gm-gaps-confirm/*/response.md
```

Expected — **31** in total: brewbarry 6, soma 12, valphine 4, vukradin 9.

## 1. Parsing — P1, the one that matters

```bash
python -c "
from session_doc.blocks import parse_blocks, join_blocks
from pathlib import Path
p = Path('experiments/20260907-phandalin-gm-gaps-confirm/brewbarry/response.md')
text = p.read_text()
blocks = parse_blocks(text)
print(f'{len(blocks)} blocks, {sum(1 for b in blocks if b.kind == \"gap\")} gaps')
print('round-trips:', join_blocks(blocks) == text)
"
```

Expected: `13 blocks, 6 gaps` and `round-trips: True`.

**Round-tripping is the load-bearing check.** A parser that loses a blank line produces a
`.composed.md` differing from the narration everywhere, not only at the gaps — and the diff would
look like the compose step misbehaving.

Across all four scenes:

| Scene | Blocks | Gaps |
|---|---|---|
| brewbarry | 13 | 6 |
| soma | 25 | 12 |
| valphine | 9 | 4 |
| vukradin | 18 | 9 |

## 2. The record and composing — R, C

```bash
python -m pytest tests/test_block_model.py -q
```

Covering: an unknown `version` refused (**R2**); two entries for one id refused (**R3**); `mine`
and `authored` distinct (**R5**); a `critique` changing nothing (**R6**); composing twice
byte-identical (**C1**); an empty record reproducing the narration (**C5**).

**C3 by hand** — the check that makes the record self-invalidating:

```bash
# compose, then change one character of the narration, then compose again
sd_compose --scene <path>.md            # writes <path>.composed.md
printf '\n' >> <path>.md
sd_compose --scene <path>.md            # must refuse
```

Expected: a refusal naming the record and both digests. Same shape as
`transcript_corrections`' `was` check — a stale record fails loudly rather than composing
yesterday's prose against today's draft.

## 3. Export and the reviewer — W

```bash
sd_review export --scene <path>.md --out /tmp/scene.json
python -c "
import json; d = json.load(open('/tmp/scene.json'))
print('version', d['version'], '|', len(d['blocks']), 'blocks |',
      len(d['source_gm_turns']), 'GM turns |', round(len(open('/tmp/scene.json').read())/1024, 1), 'KB')
"
```

Expected: **14–26 KB** for a single scene. If it is materially larger, `--all-scenes` was used by
accident; 82 KB is the whole session and is not what gets pasted on a phone.

```bash
python -m pytest tests/test_reviewer_selfcontained.py -q
```

**W1** — the reviewer makes no network request of any kind: no external `src`/`href`, no `fetch`,
no remote import. **W2** — the version the page understands equals the exporter's constant. These
two are what make "works offline on a phone" a property rather than a hope, and W2 is the guard
that exists *because* the page is no longer regenerated per session.

### On the device — the part no test covers

Save the reviewer once. Then, with the phone **in airplane mode**:

1. Paste the export. The scene renders, prose and gaps interleaved.
2. Open a scene's GM turns at the foot and rule a gap against them.
3. Rule every gap without writing any prose. **Ruling reads as complete; writing reads as
   outstanding** (W5, SC-002a). This is a finished mobile session, not a half-done one.
4. Edit a paragraph the model wrote (W6).
5. Reload the page. Either the work is there, or you were told before you started that it would
   not be (FR-016).
6. Copy, and paste into any chat. It should read as a request to draft those passages.

Step 5 is the one to do first on a real device. `localStorage` under `file://` behaves
inconsistently across mobile browsers, and a GM who loses twenty rulings to a tab reload will not
use this twice.

## 4. The gate and the collision — G, V

```bash
python -m pytest tests/test_assemble_gate.py -q
```

- **G1/G2** — a session with an open gap refuses, naming **every** scene responsible
- **G4** — without the gate, assembly behaves exactly as it does today
- **V1/V3** — a stem with both `.scrubbed.md` and `.composed.md` refuses, naming both, and the
  message distinguishes it from `#429`'s "two files claim one scene"

## 5. The guards — X

```bash
python -m pytest tests/test_block_model_no_llm.py tests/test_gap_marker_pairing.py -q
```

**X1** walks the AST for an API client anywhere in this layer. **X2** ties the marker constant to
the prompt fragment that emits it — the binding `26ec5b0` did not have, which is why a deleted
prompt left its stripper, its tests and three out-of-repo skills standing with nothing failing.

## What none of this proves

That the gaps were ruled *well*. Only the GM can say that, and it is the whole reason this layer
refuses to call a model: asked to resolve its own 11 markers, the model discarded nothing and
gave both of the GM's Order-of-the-Gauntlet lines to a player character
(`experiments/20260907-phandalin-gm-gaps-selffill`).
