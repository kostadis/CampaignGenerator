---
name: campaign-recall
description: Answer a question about a campaign from its session summaries using zvec-grep (zg) semantic search, ordered chronologically by session filename. Returns verbatim source with provenance, never paraphrase. Invoke as /campaign-recall <question>, or use whenever the user asks what happened, who someone is, or where a thread stands in a campaign with a zg-indexed summaries directory.
tools: Bash, Read
---

# Campaign Recall

Answer a campaign question from the play record. `zg` finds the relevant passages;
**you** supply the two things vector search structurally cannot: chronological
order, and the ability to say a thing is not recorded.

## Why this skill exists

Measured behaviour of `zg` on a session-summary corpus:

- **Excellent** at locating facts from a natural-language question. "What happened
  to Droop the goblin after he fainted" returned the complete answer as hit #1,
  including a consequence buried in an NPC entry.
- **Blind to time.** Asked for "the most recent session," it returned session 6 of
  11. Similarity ranking cannot read `011-` in a filename.
- **Cannot report absence.** Asked about entities that appear nowhere in the
  corpus, it returned the nearest neighbours anyway — a chapter title line and an
  unrelated summary — with no signal that nothing matched.

Both gaps are repaired below, deterministically.

## What to do

### 1. Locate the index

```bash
zg --status
```

Run from the summaries directory, or `cd` to it first. Confirm **Coverage is
100%** before trusting any answer. A partial index fails silently: queries return
fewer results with no indication files are missing, which is indistinguishable
from "nothing matched."

### 2. Query

```bash
zg "<the user's question, in natural language>" --limit 8 --preview full
```

- Pass the question close to how the user phrased it. The index is semantic;
  keyword-ifying it throws away signal.
- `--preview full` is required. Output defaults to `none` when piped, which
  returns headings without bodies.
- If the first query is thin, reformulate **once** with different vocabulary
  rather than many times with the same.

### 3. Order the hits by session, from the filename

Session files are named `NNN[a]-session-<slug>.md`. The numeric prefix is the
**authoritative chronological order** — it is not in the embeddings and not in the
text. Sort hits by it before presenting anything.

- `001` … `011` sort numerically.
- A letter suffix sorts immediately after its number: `003a` follows `003`.
- A gap is meaningful, not an error. A file such as `009-session-not-written.md`
  records a session that was never written up — say so rather than silently
  skipping it.
- "Most recent", "latest", "current", "now", "where does this stand" all mean
  **the highest-numbered file that mentions the subject**, not the best-ranked hit.

### 4. Check for absence before answering

`zg` always returns its top-k. Hits are not evidence that the subject exists.

Confirm the subject actually appears, using exact search. **Use this exact form:**

```bash
zg --rg -i "<subject>" .
```

> **Do not add `-l`.** Managed `--rg` rejects it outright — *"-l changes rg output
> and cannot be used with managed --rg"*. The error goes to **stderr** and stdout
> stays empty, so a check that only inspects stdout reads the failure as "no
> matches." Observed: this reported Gundren, Glasstaff, Droop and Ruxithid all
> absent from a corpus containing every one of them. The same trap applies to any
> flag that changes rg's output shape (`-c`, `--files-with-matches`, `-o`).

**Verify the check before you trust a negative.** A broken absence check fails
toward a confident "Not recorded," which looks like caution and is the hardest
error here to notice. Before reporting any subject as absent, run the same
command against a term you *know* is in the corpus — a player character name, or
a word from a filename:

```bash
zg --rg -i "<a name certainly present>" .    # positive control: MUST return hits
```

If the control returns nothing, your command is broken, not the corpus. Fix the
command and re-run every absence check.

When the check is working and genuinely returns nothing, the answer is
**"Not recorded"** — say that plainly and stop. Do not summarise the semantic
near-misses as though they were an answer.

Confirm a negative with a **second term** where one exists — "mind flayer" and
"illithid", "nothic" and "Ssarnak". A single spelling missing is weaker evidence
than a concept missing.

Signs a hit set is noise rather than a match: previews are chapter title lines,
matched ranges are headings with no body, or the subject's name does not appear
in any preview.

### 5. Answer

- **Quote the record.** Prefer the source's own wording over your paraphrase. The
  point of this path is that no model rewrote the campaign on the way in.
- **Cite** file and line range, e.g. `008-session-08-02.md:209`.
- **Order the narrative** by session number, and say which session each fact is
  from.
- **State gaps explicitly.** If a thread stops, name the last session that
  mentions it: "last recorded in session 7; nothing since."
- **Separate established from believed.** "The record shows X" for events;
  "Sildar says X" for claims made by characters. The summaries mark this
  distinction — preserve it.

## What NOT to do

- **Do not answer from the module.** You may recognise names from a published
  adventure. That recognition is not evidence about this campaign. If the record
  does not say where someone is, they are not placed — regardless of where the
  published version puts them.
- **Do not fill a gap** with what is typical, likely, or canonical elsewhere. An
  unresolved thread left visibly unresolved is the correct answer.
- **Do not trust rank as recency.** Hit #1 is the most semantically similar, which
  is frequently the most vivid passage rather than the most recent or the most
  definitional.
- **Do not paraphrase quotes.** If you present something in quotation marks it
  must be verbatim from the file.
- **Do not silently drop a session** because it produced no hits.
- **Do not report "Not recorded" from a command that returned nothing without
  checking why.** Empty stdout means either no matches or a rejected flag. These
  are indistinguishable unless you look at stderr or run a positive control.

## Known weak spots

- **Definitional questions** ("what *is* the Obelisk") retrieve vivid moments
  rather than definitions. Widen `--limit` and read the `::NPCs` / `::Items`
  sections, which carry the reference-style entries.
- **Cross-session synthesis** ("what has changed since session 5") needs several
  queries, one per session range, then assembly in filename order.
- **Facts filed under another entity.** A fact about A is often recorded in B's
  entry — Voss's status lives under Ssarnak. If a subject query is thin, query
  the entity most likely to have been present.
