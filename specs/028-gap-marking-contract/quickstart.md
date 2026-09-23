# Quickstart — validating the gap-marking port

Run from the repository root. Steps 1–4 are deterministic and cost nothing. Step 5 spends tokens
and is the only part that can answer whether the contract *works* on this prompt.

## 0. Freeze the two fixtures, before touching a template

```bash
cp tests/golden/prompts/narrate_system_matrix.json \
   specs/028-gap-marking-contract/golden_pre_feature.json
```

Order matters: after the first template edit this file can no longer be produced, and it is the
whole evidence for P1. See [research.md](./research.md) D4.

The accepted-gap fixture comes from the confirmation runs:

```bash
grep -c "GM NARRATION — TO BE WRITTEN" \
  experiments/20260907-phandalin-gm-gaps-confirm/*/response.md
```

Expected — **31** in total:

```
.../brewbarry/response.md:6
.../soma/response.md:12
.../valphine/response.md:4
.../vukradin/response.md:9
```

## 1. The contradiction, before you change anything

```bash
python -c "
from session_doc.narrate import build_narrate_system
p = build_narrate_system(examples_text=None)
print('absorbing sentence present:',
      'GM descriptions become experienced facts' in p)
"
```

Expected today: `True`. That sentence is what the contract has never been tested against.

Confirm it reaches both render paths:

```bash
grep -c "{writing_brief}" config/agents/session_doc/narrate/base.md \
                         config/agents/session_doc/narrate/bundle_base.md
```

Both `1`.

## 2. P1 — the gap-off half did not move

```bash
python -m pytest tests/test_prompt_golden_pre_feature.py -q
```

Every gap-off combination equals its entry in the frozen pre-feature golden, byte for byte —
256 single-scene combinations plus the standalone constants, in both render paths and with prose
mode either way. This is the assertion that makes "the mode is off by default" a safe claim
rather than a hope.

A failure here names the combination and the differing region; it is never a reason to
regenerate the frozen file.

## 3. P2–P6 — the prompt states one rule

```bash
python -m pytest tests/test_gap_marking_prompt.py -q
```

Covering, for both render paths and with prose mode on and off:

- gap on → no instruction that GM description becomes experienced fact (**P2**)
- gap on → the marker is requested, on its own line, as required output (**P3**)
- gap on → the adjudication-is-table-operation rule survives (**P4**)
- gap on, prose mode on → **P2** still holds, i.e. the second copy of the sentence is governed
  by the same switch
- the GM rule appears exactly once in the assembled prompt (**P6**)

## 4. Refusal, and the record

```bash
# a missing contract refuses rather than rendering without it
mv config/agents/session_doc/narrate/gm_attribution_gap.md /tmp/ && \
  sd_narrate --gap-marking … ; mv /tmp/gm_attribution_gap.md config/agents/session_doc/narrate/
```

Expected: a refusal naming the path, and no output file.

```bash
cat <session>/narration/session_doc_scene_01_*.knobs.json
```

Expected: `gap_marking`, `gap_contract` and `gap_contract_sha256` present — from a **terminal**
run, not only a UI one. That is the Q3 ruling made visible.

## 5. Re-confirmation — the part that costs tokens

Per-scene, `claude-fable-5-1` at effort `medium`, because that is what was tested. A model or
effort change invalidates the transfer.

Re-render the four confirmation scenes and compare against `accepted_gaps.json`:

- **Expected to shift**: exact counts and marker boundaries. The prompts have no common
  structure, so nothing about position transfers.
- **Reportable, individually**: a gap the GM accepted that has vanished, and a gap appearing
  where the GM ruled the scope wrong. Neither is settled by counts.
- **Expected to hold**: dialogue lines outnumber narration lines two to four times over, as in
  every confirmation run; and no GM description arrives as a player character's speech,
  perception, memory or inference.

Then the same four scenes as a **bundle**:

```bash
sd_narrate --batch-scenes --gap-marking …
```

This has no prior evidence at all — the Q2 ruling admits the bundle path on the strength of
per-scene runs, and [research.md](./research.md) D7 records that gap. A bundle that marks
materially fewer gaps than the per-scene run of the same scenes is the finding, not a rounding
error.

## What none of this proves

That the model obeys the contract on a scene nobody has looked at. Steps 1–4 prove the prompt
says the right thing; step 5 proves it behaved on five renders of four scenes. The standing
check is the record from step 4 plus the GM reading the gaps — which is the feature, not a gap
in it.
