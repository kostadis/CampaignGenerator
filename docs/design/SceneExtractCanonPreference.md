# Scene-Extract Canon Preference — Design Plan

**For:** Claude Code, working in `~/src/CampaignGenerator`.
**Status:** Plan only. No code changes yet.
**Related:** `CleanedVttConfigResolver.md` (sibling), `/staged-consistency` skill, `session_doc/scene_extract.py`.

---

## TL;DR — what's broken

`session_doc/scene_extract.py` produces per-scene files with two sections:

1. `## Scene summary (from gm-assist, verbatim)` — copied verbatim from the file passed via `--summary` (today: `session-summary.md`).
2. `## Verbatim moments` — LLM-built from the VTT, with two sub-shapes:
   - **Verbatim quote blocks** (`> "..."` lines under `**GM** —`, `**Grygum** —`, etc.) — pure VTT speech.
   - **Paraphrase bullets** ("GM describes…", "Fembris points out…") — the LLM's own prose summarizing DM speech.

Today's bug: the **paraphrase bullets** in section 2 use the VTT's surface vocabulary (e.g. "the West Inner Ward theology library", "an ancient turtle librarian", "the servant Miss Hollypocket", "House of Rest") **even when the scene-summary block immediately above them in the same file uses the canonical names** (Immortal Chambers, Pizwog, gnome housekeeper, House of Rest and the Hearth).

The result is a single file that contradicts itself between section 1 (canonical) and section 2 (drift). Narration that draws from section 2 silently re-injects every name the recap-layer consistency check already corrected.

This is the *fix-propagation drift* mode the `/staged-consistency` skill description names. The verbatim quote blocks are defensible — they preserve table speech for fidelity. The paraphrase bullets are not — they are LLM prose that should honor the canon the scene summary just laid down.

---

## Concrete repro (current state)

In `/home/kroussos/campaigns/out-of-the-abyss/summaries/20260518/scene_extractions_new/`, produced by:

```
scene_extract GMT20260519-005755_Recording.transcript.cleaned.vtt \
  --summary session-summary.md \
  --output-dir scene_extractions_new \
  --party docs/party.md --gm-player Kostadis --batch --force
```

Same-file contradictions observed:

| File | Section 1 (canonical) | Section 2 paraphrase (drift) |
|---|---|---|
| `01_the_immortal_chambers_and_the_question_of_the_age.md` | line 11 — "Immortal Chambers" | line 23 — "the West Inner Ward theology library" |
| `01_the_immortal_chambers_and_the_question_of_the_age.md` | line 12 — "Pizwog, an ancient tortle librarian" | line 35 — "an ancient turtle librarian" |
| `02_dinner_at_the_refectory.md` | (n/a — session-summary regressed here too) | line 17, 91 — "House of Rest" without *and the Hearth* |
| `03_a_grim_awakening.md` | line 11 — copied from session-summary | line 20 — "the party asleep at the House of Rest" |
| `06_arriving_at_the_crime_scene.md` / `07_investigating_the_keeper_s_chambers.md` | "Janussi's ancient gnome housekeeper Miss Hollypocket" | "the servant, Miss Hollypocket" (LLM bullet **and** verbatim quote) |

Verbatim quote re-injections (defensible, do NOT auto-fix):

- `04_the_tour_of_the_bastion.md:54` — `"Fire and Tednimar. Anything you need to know about fire and lightning, breathing lizards, you'll find in there."` (Fembris in-character fumble; DM's actual table speech.)
- `06`/`07` — `"Janussi was found dead by great reader A'lai Aivenmore and the servant, Miss Hollypocket..."` (DM's actual table speech.)

---

## The narrow fix

`session_doc/scene_extract.py` already has the canonical names available — they're in the `--summary` file it's literally pasting into section 1 of each output file. The fix is **a prompt-level instruction** to the scene-extract LLM:

> When you write paraphrase bullets under `## Verbatim moments`, prefer the proper nouns and descriptions used in the scene summary block above. Verbatim quotes (lines beginning `> "..."`) must remain unchanged — table speech is sacred. Section headers (`**[...]**`) should also use the scene-summary's canonical names.

This is a one-line behavioral change in the system prompt. No new context to load — the LLM already has the scene summary in its prompt.

### Non-goals

- **Do not rewrite verbatim quotes.** The Fembris-fumble "Fire and Tednimar" must stay in the verbatim quote block because the player heard the DM say that at the table. The narration LLM downstream can choose to canonicalize when assembling prose; the extraction layer must preserve the original utterance.
- **Do not add a glossary or auto-substitution step.** The scene summary block is the canonical source for this session; that's the only canon list the extractor needs. A glossary would duplicate the recap-layer fix and is the wrong place to keep it (state lives in the recap, not in extractor code).

---

## What to change

**`/home/kroussos/src/CampaignGenerator/session_doc/scene_extract.py`** — the system prompt (find the multi-line `SYSTEM` / instructions constant near the top of the file; locate the section that tells the LLM how to format `## Verbatim moments`). Add the following clause:

> **Canon preference for your own prose.** When you write the short context bullets between header blocks (`- GM describes…`, `- Fembris points out…`) and when you compose section header text (`**[…]**`), use the proper nouns and descriptions exactly as they appear in the `## Scene summary` block above. If the scene summary calls a location "the Immortal Chambers" and the DM in the VTT calls it "the theology library," your bullet and header should say "Immortal Chambers" — the DM's words remain only inside `> "..."` quote blocks. Verbatim quotes are sacred and must be reproduced exactly from the VTT, including in-character fumbles, mispronunciations, and drift terms.

No CLI flag, no config option — the behavior is always-on. If a campaign needs the old behavior, they can pass a `--summary` document with VTT-vocabulary names; the extractor follows whatever canon the summary asserts.

---

## Optional follow-up — a check before narration

The scene extractor's fix is one half of the staged-consistency story. The other half: a check that runs on the scene extraction files before narration runs, comparing canonical names in section 1 against the prose in section 2, and flagging any divergence (excluding verbatim `> "..."` lines).

This is the same shape as `session_doc/check_consistency.py` but with a different system prompt — one that knows about the two-section structure of scene extracts. Tentative name: `check_scene_canon.py`. Wire into `/staged-consistency` as the post-extraction, pre-narration gate.

Not in scope for this design doc — flagged here so the architectural fit stays visible.

---

## Verification recipe

Once the prompt change ships:

1. Re-run the scene extractor against `summaries/20260518/`:
   ```
   scene_extract .../transcript.cleaned.vtt \
     --summary session-summary.md \
     --output-dir scene_extractions_new \
     --party docs/party.md --gm-player Kostadis --batch --force
   ```
2. `grep -n "theology library\|turtle librarian" scene_extractions_new/01_*.md` — expected: zero matches outside `> "..."` blocks.
3. `grep -n "House of Rest" scene_extractions_new/{02,03}_*.md` — expected: every match is followed by "and the Hearth," or sits inside a `> "..."` block.
4. `grep -n "Tednimar\|fire and lightning" scene_extractions_new/04_*.md` — expected: still present, but only inside `> "..."` blocks (verbatim preservation).

---

## Critical files for implementation

- `/home/kroussos/src/CampaignGenerator/session_doc/scene_extract.py` (system prompt only — find the instruction string that governs `## Verbatim moments` output)

That's it. One file.
