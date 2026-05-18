# Plan: improve voice rendering in `session_doc.py`

## Context for you (fresh Claude)

You are editing `~/src/CampaignGenerator/session_doc.py`, a ~1800-line script that generates rotating-POV first-person narrative recaps of D&D sessions. The pipeline has five passes; **Pass 5 (per-character narration) is what we're fixing.** Earlier passes plan sections, extract per-character moments, and produce structured inputs. Pass 5 calls Claude once per character/scene with a system prompt + user prompt and emits ~3–5 paragraphs of first-person prose.

The current output is mechanically correct (first-person, no DC numbers leaking through, scene-scoped) but **all characters sound the same** — a generic literate-fantasy voice. The architectural root cause is that the prompt structure ranks voice below several other constraints:

- The "VOICE" section in `NARRATE_SYSTEM_BASE` (lines ~337–342) is 6 lines of abstract instruction with zero examples, while `PROSE_MODE_INSTRUCTION` (lines ~546–698) is ~150 lines of detailed BAD/GOOD pairs for mechanics translation. The model spends its attention on what's specified in detail.
- Per-character `voice_note` (player-authored, the most character-specific signal in the pipeline) is loaded by `load_voice_files()` at line 400 and injected into the user prompt at position ~6 of ~9 sections by `build_narrate_prompt()` around line 983. It's buried.
- `--examples-dir` (style references) loads a single global blob at lines 1277–1290 and injects it via `EXAMPLES_BLOCK` (line 351) into every narration pass. Every character sees the same examples, so all voices regress toward the *average* of the example pool.
- Each Pass 5 call is independent. The only cross-section signal is a single `handoff` quote (line 1750), so rotating-POV contrast between sections is left to chance.

## Goals

Make voice the *primary* concern of Pass 5, by structural changes — not by adding more "be distinctive" instructions. Specifically:

1. Per-character style examples (so each voice trains against its own target).
2. Hoist `voice_note` into the system prompt with strong priority framing.
3. Pass the previous narrator's identity + a short fingerprint into the next pass, so contrast is explicit.
4. (Optional Phase 4) A lightweight voice-only critic pass.

## Important constraints

- **Do not change** the mechanics-translation rules in `PROSE_MODE_INSTRUCTION`. They're load-bearing and not in scope.
- **Do not change** Pass 1–4 (plan, extract, scene structure). Pass 5 only.
- **Preserve prompt caching**: keep the order stable so the long, static prefix (NARRATE_SYSTEM_BASE + PROSE_MODE_INSTRUCTION) stays cacheable. Per-character content goes *after* the static stuff in the system prompt, not before.
- **Keep all existing flags working.** Add new flags additively; do not rename or repurpose `--voice-dir` or `--examples-dir`.
- **No new abstractions** for hypothetical future needs. Concrete, minimal changes only.

## Phase 1 — Per-character style examples

**Goal:** allow `--examples-dir` to contain per-character files that get routed only to that character's narration pass, while preserving the existing "global examples" behavior as a fallback.

**Changes:**

1. In the examples-loading block (lines 1277–1290), additionally scan the directory for files matching `{character_name}.md` or `{character_name}_examples.md` (case-insensitive, match on first-name lowercase to mirror `get_voice_note()` at line 415). Build a `per_char_examples: dict[str, str]` keyed by lowercased first name. Files that match a character name go into the dict; files that don't match continue to feed the existing global `examples_text` so behavior is backwards-compatible.

2. Add a helper `get_char_examples(per_char_examples, narrator) -> str | None` modeled exactly on `get_voice_note()` at line 415.

3. In the narration loop, around line 1709 where `voice_note` is fetched, also fetch `char_examples = get_char_examples(per_char_examples, narrator)`.

4. Modify `build_narrate_system()` (line 714) to accept an optional `char_examples: str | None` parameter. When present, append a *second* examples block to the system prompt after the global `EXAMPLES_BLOCK`, with a heading like `STYLE REFERENCE — {narrator}'s VOICE SPECIFICALLY` and language framing it as "Match this voice. The global examples above show overall quality; these examples show how *this character* sounds in particular — prioritize matching these."

5. Plumb `char_examples` through the existing call site at line 1738 (`build_narrate_system(...)`).

**Verify Phase 1 before stopping:**

- Run `python session_doc.py --help` and confirm no flag was lost.
- Run an existing test invocation (ask the user for one — likely something like `python session_doc.py recap.md --examples-dir docs/examples --voice-dir docs/voices ...`) with `--per-scene-output` to get per-scene files. Diff the prompts (the script prints prompt sizes; the user may have a debug flag). Verify the static prefix length is unchanged for cache stability.
- Ask the user to drop a single character-named file into their examples dir and re-run. Confirm only that character's narration receives the extra block.

**STOP. Hand control back to the user.** They will read actual narration output from a real session and decide whether the change improved Vukradin/Valphine/etc. voice differentiation before you continue. Do not start Phase 2 unautomously.

## Phase 2 — Hoist voice notes into the system prompt

**Goal:** move `voice_note` from buried-in-user-prompt to top-of-system-prompt-after-static-block, framed as the authoritative voice spec. This raises its salience and makes it cacheable per-character (the prefix above it doesn't change).

**Changes:**

1. Modify `build_narrate_system()` (line 714) to accept an optional `voice_note: str | None` parameter. When present, append it to the *end* of the system prompt (after `PROSE_MODE_INSTRUCTION`, after `SCENE_ANCHORED_DIRECTIVE`, after per-character examples from Phase 1) under a heading like:

   ```
   AUTHORITATIVE VOICE SPEC — {narrator}
   The following notes are written by {narrator}'s player. They override
   any conflicting style guidance above. Match the cadence, vocabulary,
   and tics described here. When in doubt about how a sentence should sound,
   refer to this section first.

   {voice_note}
   ```

2. Update `build_narrate_prompt()` (line 946) to **remove** the voice-note injection at lines 983–985. Voice notes now live only in the system prompt. The user prompt becomes focused on per-scene content.

3. Plumb `voice_note` into the `build_narrate_system()` call at line 1738.

**Reasoning to preserve in code (no comment needed unless non-obvious):** the system prompt order is now `static prefix (cacheable across all narrators) → per-character examples → per-character voice note`. The static prefix stays byte-identical across calls; the per-character portion changes per call but is consistent within a single character's runs, so re-narrating the same character also caches well.

**Verify Phase 2 before stopping:**

- Confirm voice notes appear exactly once in the assembled prompt (not in both system and user). Easiest check: grep the generated prompt-dump for the heading.
- Run a single-narrator re-narration (`--narrator <name> --plan-file ... --scene ...`) and visually compare the new output against a saved old output for the same scene.

**STOP. Hand control back to the user.** Same as Phase 1 — wait for them to read the output and decide whether to proceed.

## Phase 3 — Previous-narrator contrast signal

**Goal:** give each Pass 5 call a brief signal about what the *previous* narrator sounded like, so the current section is encouraged to pull away from that voice instead of converging on a house style.

**Changes:**

1. In the narration loop (around lines 1700–1750), track the previous section's narrator name and the last paragraph of the previous narration (not just the existing single-line `handoff`).

2. Modify `build_narrate_prompt()` (line 946) to accept `prev_narrator: str | None` and `prev_voice_sample: str | None`. When present, inject a small block in the user prompt, *just before* the handoff line:

   ```
   ## Previous Section's Voice (for contrast — do NOT imitate)

   The previous section was narrated by {prev_narrator}. A sample of their
   voice:

   > {prev_voice_sample}

   {narrator}'s voice should sound clearly different from {prev_narrator}'s.
   Lean into what makes {narrator} distinct — their rhythm, their concerns,
   their particular way of speaking — and away from anything that would
   make these two sections feel written by the same hand.
   ```

3. The "sample" should be ~3–5 sentences from the end of the previous narration. Re-use the existing logic that strips the last line for `handoff` but extend it to capture a paragraph.

**Verify Phase 3 before stopping:**

- Run a full-session narration. Read sections 1, 2, and 3 in sequence. Ask: do they sound more clearly different from each other than they did before Phase 3? This is subjective; that's the point — voice quality has no automatic check, so this requires human judgment.

**STOP. Hand control back to the user.**

## Phase 4 (optional) — Voice critic pass

**Goal:** after a narration is generated, run a short follow-up call asking Claude to flag sentences that read as generic or that conflict with the voice spec. Output a list of suggested re-writes; do *not* auto-apply them. Human reviews and picks.

This is structurally bigger than Phases 1–3 (new pass, new prompt, new output artifact). Do not start it unless the user explicitly asks for it after seeing Phase 1–3 results. If asked, propose the design in writing first and wait for approval before coding.

## What you should not do

- Do not add a "voice score" or any numeric metric. Voice quality is not numerically meaningful at this scale.
- Do not refactor the prompt assembly into a class hierarchy or template engine. Keep it as f-strings and `.replace()`.
- Do not delete `PROSE_MODE_INSTRUCTION` or shrink it to "make room" for voice content. It is doing necessary work.
- Do not change `--voice-dir`'s file-naming convention. Players have existing files.
- Do not add backwards-compatibility shims for the parameter additions to `build_narrate_system()` / `build_narrate_prompt()`. Make them optional with `None` defaults; that's enough.

## How to start

1. Read `~/src/CampaignGenerator/session_doc.py` end-to-end before touching anything. The file is ~1800 lines but the relevant region is roughly lines 295–1012 (Pass 5 prompts + helpers) and lines 1700–1770 (the narration loop).
2. Ask the user for a sample invocation that currently works, plus the path to a recent session's output, so you can diff before/after.
3. Implement Phase 1. Stop. Wait.
