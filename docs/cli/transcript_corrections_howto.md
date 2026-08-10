# Transcript corrections — how to actually use it

> Task-oriented walkthrough for the GM. The ruling behind it is **R4** in
> [`docs/design/ExtractionContract_proposal.md`](../design/ExtractionContract_proposal.md)
> (issue #250). This page is the operator's manual.

## What changed, and why you should care

A session has two transcripts: `*.transcript.vtt` straight from Zoom, and
`*.transcript.cleaned.vtt`, which is the one everything downstream reads.

Until now the cleaned one was **hand-edited, by a model, with no record**. On
Phandalin ch46 that came to **74 substitutions** nobody could enumerate. Most
were fine — `Blueberry` → `Brewbarry`, `Cryovane` → `Cryovain`,
`sir Kaelin` → `Ser Kaelen`. Two were not:

| cue | tape said | cleaned says | |
|---|---|---|---|
| 168, 206, 414 | `Brynn and Giles` / `Brennan Giles` | `… Slipper-Shine` | a surname nobody spoke, added three times |
| 215 | `the Telosians have been defeated` | `the Talosian have been defeated` | spelling fixed, grammar broken |

Neither was reviewable, because nothing listed the edits. Every quote-verbatim
guarantee in the pipeline is measured against this file.

**Now the cleaned tape is generated.** The raw file is the archive and is never
written. `transcript_corrections.yaml` is the record. `sd_corrections` turns
one into the other.

---

## Step 0 — capture what is already there

Do this **once per session that already has a hand-edited `.cleaned.vtt`**:

```bash
cd ~/Phandalin/Phandalin/summaries/20260623
sd_corrections import --dir .
```

That diffs raw against cleaned and writes one entry per differing cue:

```yaml
- id: cue-0168
  cue: 168
  was: 'Kostadis Roussos: Alright, Brynn and Giles are actually in the temple, so let''s just put them where they belong.'
  now: 'Kostadis Roussos: Alright, Brynn and Giles Slipper-Shine are actually in the temple, so let''s just put them where they belong.'
  recorded: 2026-08-10
  verified: false
  note: reverse-engineered from an already-edited transcript; not reviewed
```

**Every imported entry lands `verified: false`, and that is correct, not a
bug.** Nobody reviewed these when they were made — that is the entire reason
the import exists. `--verified` exists but do not reach for it unless you have
genuinely read all of them.

Then read the file and fix it. Deleting an entry is how you *revert* an edit:
drop `cue-0168` and the next `apply` puts `Brynn and Giles` back the way it was
spoken.

---

## Step 1 — regenerate

```bash
sd_corrections apply --dir .
```

Reads raw + record, writes `*.transcript.cleaned.vtt`. Deterministic: running
it twice produces identical bytes, so nothing downstream sees a spurious
change. `--dry-run` reports without writing.

**It is all-or-nothing.** If any correction no longer fits the tape, nothing is
written and every failure is named. A half-repaired tape is worse than an
unrepaired one, because the record then describes a file that does not exist.

---

## Step 2 — check, whenever you like. It is free

```bash
sd_corrections check --dir .
```

Calls no model, writes nothing, and answers two separate questions:

| | question | what a failure means |
|---|---|---|
| **complete** | are all the cleaned tape's cues explained by the record? | somebody edited the tape without writing it down |
| **current** | is the file on disk what `apply` would write? | just run `apply` — header-only staleness is **not** a finding |

It also lists the unreviewed backlog. That is a to-do list, not an error.

Exit codes: `0` nothing to report, `1` findings, `2` could not run.

---

## Adding a correction by hand

This is the normal case once a session is imported. Say
`sd_verify_quotes` flagged a span and you traced it to cue 224:

```yaml
- id: cue-0224-lathander
  cue: 224
  was: 'Gary Young: I mean, the town has been protected by the strength of the pandemic.'
  now: 'Gary Young: I mean, the town has been protected by the strength of Lathander.'
  recorded: 2026-08-11
  verified: true
  note: Zoom misheard Lathander; the tape reads it correctly 10x elsewhere.
```

Then `sd_corrections apply --dir .`.

**`was` must match the cue exactly**, speaker prefix included. That is checked
on every apply, and it is the property that makes the record self-invalidating:
if the raw tape is ever replaced, a correction written for the old one fails
loudly instead of pasting yesterday's repair over today's words.

**One entry per cue.** Two corrections on one cue are refused — the second's
`was` describes a tape the first already changed, so which wins would depend on
file order.

---

## Things that will bite you

**Cue index, not file line.** A correction that adds a header shifts every line
number in the document and moves no cue index at all. If `check` says a cue "is
not in the transcript (it has 1,244 cues)", you probably pasted a line number.

**The generated NOTE header is not yours.** `apply` rewrites it every time and
strips the one it wrote last. Author notes elsewhere in the file are preserved;
a prose block explaining your edits is now redundant, because the record
explains them better.

**Line endings become LF.** Raw Zoom tapes are CRLF. The generator normalises
and says so in the header — a declared change rather than the silent one the
hand-edited files were already making.

**Nothing here calls a model.** Deciding *which* mishearings deserve fixing is
a scope decision, and the whole point of #250 is that the pipeline does not
make those. `sd_corrections` applies what you wrote down.

---

## Troubleshooting

| message | what it means |
|---|---|
| `cue N does not say what \`was\` claims` | The record is stale, or you edited raw. Compare the two texts it prints; usually the fix is updating `was`. |
| `cue N is not in <file> (it has M cues) — a file line number, perhaps?` | Exactly that. |
| `the two transcripts do not carry the same cue indices` | `import` refuses to pair positionally — one file is not an edit of the other. Check you passed the right pair. |
| `transcript ... is already a .cleaned.vtt` | Point `transcript:` at the raw archive. The cleaned file is output. |
| `N cue(s) ... are NOT explained by the record` | Someone hand-edited the generated file. `import --force` captures it, `apply` discards it. Read the diff before choosing. |
| `generated NOTE line contains a colon` | An internal guard. `vtt_voice_compare` has no NOTE rule and would read that line as dialogue. |
