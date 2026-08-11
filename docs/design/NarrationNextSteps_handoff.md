# Narration Work — What To Do Next, In Order

> **Written:** 2026-08-11, from a review of every open issue across `CampaignGenerator`,
> `campaigns` and `mytools` against the state of the narration pipeline on that date.
> **Question it answers:** the voice-critic gaps look like the top narration item — is
> anything else genuinely ahead of them? Two things are, and one of those is a decision
> rather than work.
>
> **What this doc owns:** the *order*, the blocking decision, and the cost/dependency
> reasoning. It does not restate detail its siblings own:
> - [`Issue245Followups_handoff.md`](Issue245Followups_handoff.md) — the #245 execution
>   record: per-WO change specs and acceptance criteria, the standing constraints that bind
>   every work order, the benchmark numbers, and the landed/not-landed status table.
> - [`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md) — the analysis:
>   the five-copies survey, findings F1–F11, designs D1–D8, verification per finding.
>
> Cite them; don't re-derive them. New execution status still goes in the #245 handoff's
> status table.

## 0. Re-verify before starting — this doc has a shelf life

Every claim below was measured, not inferred, but the tree moves. Three checks, all cheap:

```bash
# a) is the voice-critic edit still uncommitted?  (step 1 exists only if yes)
git -C ~/src/mytools status --porcelain dotfiles/claude/skills/voice-critic/

# b) is the genre still flattened for OOTA, and still duplicated into the profile knob?
python - <<'PY'
import yaml; from pathlib import Path
for n in ("Phandalin", "out-of-the-abyss"):
    d = yaml.safe_load((Path.home()/"src/campaigns"/n/"config/session_doc.yaml").read_text())
    g = (d.get("narrate") or {}).get("genre") or ""
    pk = ((d.get("profiles") or [{}])[0].get("knobs") or {}).get("narration_genre") or ""
    print(n, len(g), g.count("\n"), "| profile knob:", len(pk), pk.count("\n"))
PY

# c) which of these are still open?
gh issue list --state open --json number -q '.[].number' | tr '\n' ' '   # want: 276 249 250 245 220
gh issue list -R kostadis/mytools --state open --json number -q '.[].number' | tr '\n' ' '  # want: 125 120
```

If (b) reports OOTA with 0 newlines, nothing below has been done yet.

## 1. Commit the uncommitted voice-critic edit (minutes)

`mytools/dotfiles/claude/skills/voice-critic/SKILL.md` carries **+23/−1 uncommitted**, no
stash entry. It is WO-5's scan-C work — the taxonomy regex, the `filed … away` cross-model
note, the "scans are a floor, not a ceiling" caveat — and it exists only in the working
tree and its deployed `~/.claude` copy. Every change in mytools#125 builds on it, and a
stray `git checkout` loses it. This is the hazard class mytools#120 was filed about.

Branch, commit, PR, merge, then re-sync `~/.claude/skills/voice-critic/` from the tracked
source (the deployed copy is a **copy**, not a symlink — `rsync -a --delete
--exclude __pycache__`).

## 2. CG#276 fix 1 — one line, zero design debt

Gate the delimited `GENRE & REGISTER` block on **size**, not on `"\n" in g`
(`session_doc/narrate.py:35-48`), plus a test asserting a newline-free 16K genre still gets
the delimited form. OOTA renders become correct immediately, and nothing here has to be
undone whichever way §3 is decided. Golden regen per the #245 handoff's standing constraint 6.

## 3. ⚠ THE BLOCKING DECISION — where does the genre rulebook live? (GM ruling, not work)

**This is the ordering answer.** mytools#125's **D2** — the critic reads the *effective*
rulebook — targets `narrate.genre` in `session_doc.yaml`. Two open issues say that target
is not stable, and building D2 first means building it twice:

- **CG#276 fix 2** proposes deleting the key in favour of `narrate.genre_file:` pointing at
  `voice/_genre.md`, because the YAML value is a *paste* of that file and drifts silently.
- **CG#220** shows the same value is duplicated a second time into
  `profiles[].knobs.narration_genre`, with **one-way sync**:
  `activate_profile()` (`server/session_editor_config_service.py:240-252`) pushes profile →
  grouped; `update_config()` (`:160-183`) never writes back.

Together: **"the effective genre" is not currently well-defined.** The grouped value is
what renders read, but the next profile activation can silently replace it with the
profile's stale copy — so a critic reading `narrate.genre` may be reading something that is
not what the render used, and has no way to tell. Confirmed live: both Phandalin and OOTA
carry byte-identical values in both locations.

Three shapes, none picked:

| | Shape | Cost | What D2 then reads |
|---|---|---|---|
| **A** | `narrate.genre_file:` path; delete `genre:`; profiles hold the *path* | migration + editor/API change; kills both duplications | the file, resolved the same way the pipeline resolves it |
| **B** | Keep the paste, add a divergence check (`config check` warns when `narrate.genre` ≠ `voice/_genre.md`, and when profile knob ≠ grouped) | small; leaves three copies but makes drift loud | `narrate.genre`, with a staleness verdict alongside |
| **C** | Keep the paste, make the sync bidirectional (#220's own proposal) | fixes #220 only; genre stays a copy of `_genre.md` | `narrate.genre`, still possibly stale vs the file |

This is a scope/authority decision, which is the class the Pipeline Design Rule reserves for
the human — do not resolve it by picking a reasonable default. **A** is the one that matches
this repo's single-user migrate-and-delete convention and the reason `_genre.md` exists at
all, but it is the largest, and it touches the Session Doc Editor.

**CG#249 belongs in this cluster and is nearly free:** already implemented on `main`
(`KnobDrawer.vue:266-273` is the specified `rows="8"` textarea with the updated help text) —
verify a paste round-trip preserves newlines through save → reload, then close it. It is
what stops the UI re-flattening whatever gets decided above.

## 4. mytools#125, split in two

**4a — F1 alone, independent of §3, do it as soon as step 1 lands.** The critic's
voice-spec lookup is pre-#247, so on Phandalin all four narrators report "spec missing",
every suggestion is tagged `[no spec available — best guess]`, and the spec-conflict
category can never fire. It is a rule change of roughly ten lines in the skill, mirroring
`session_doc/voice.py:32-63` (exact key → first-name key → unique key continuing with `_`
or `-`; skip `_`-prefixed; refuse on ambiguity). Add the per-narrator resolution table
(design D1) in the same pass so a future miss cannot be silent. **This one changes output
the day it lands.**

**4b — D2/D3/D4/D5/D6/D8 after §3 is ruled and after step 5.** D2 needs a stable rulebook
location. D4 (doc-level budget ledger), D5 (assembled-doc mode) and D8 (fable's failure
profile as named categories) all want a corpus that does not exist yet — see step 5. D3
(delegate the mechanical layer to `voice_lint`, delete the duplicated regex) and D6
(table-speech spans as a review queue) are independent of both and can ride along with 4a
if convenient.

## 5. Run the #245 capstone verification — the real unrun item

Detail and command template: the #245 handoff's "Capstone verification" section. Its
precondition (WO-1 + WO-2 merged) has been met since 2026-08-11 and it has never been run.

Why it sits here rather than earlier: it needs **4a** to be worth anything. Its step 3 is a
`/voice-critic` re-score, and its item 2 asks specifically whether Vukradin's
sardonic-operator beats soften now that the spec is delivered — unanswerable with a critic
that cannot read the spec. Both outcomes are informative, and a persisting drift is a new
#245 finding rather than a shrug.

Why it precedes **4b**: it produces the first fable render with the full intended prompt
stack, which is the corpus D4/D5/D8 should be calibrated against instead of the opus-era
anecdotes currently in the skill (F5).

## 6. Independent tracks that outrank #125 on importance but do not block it

Named because "is anything else more important" and "is anything else *first*" are
different questions. These are a choice, not an ordering.

- **campaigns#154 + CG#272 — the verbatim record.** ~4,600 unrecorded edits across 46
  tapes, and 4 of 47 `.cleaned.vtt` files that `sd_corrections import` cannot handle today
  (leading blank line before `WEBVTT`; two concatenated `WEBVTT` headers; one genuine
  cue-deletion question the tool is right to refuse). This is the record every quote in
  every narration is measured against, so it outranks narration polish on importance — and
  it is a much larger lift. Note it partly contradicts the workflow documented in
  `docs/cli/transcript_corrections_howto.md`: the import path does not yet work on four
  real tapes. Fix CG#272's two parser limits before attempting the back-fill.
- **CG#250 — contradictory extraction input.** The renderer is handed the same span in two
  copies (one carrying the "Vucherdin" garble), beats duplicated across adjacent scenes, and
  brackets with no policy. **First establish what is actually left:** the issue is open while
  `ExtractionContract_implementation.md` says R1–R6 shipped, and `f012a84` reads as
  *detection* in `sd_verify_quotes` rather than repair of the smoothed layer. It matters
  here because critiquing a render that was fed self-contradictory input blames the wrong
  stage — a voice critique cannot tell "the model chose badly" from "the input disagreed
  with itself".

## 7. Cheap bookkeeping sweep — do it while waiting on §3

- **CG#249** — implemented; verify a paste round-trip and close.
- **campaigns#141 / #143 / #144** — the #248 roster parser landed (`a9a3951`) covering
  Hillsfar, out-of-the-abyss and stormgiants layouts. Run the roster extraction against each
  campaign's real `party.md`, confirm non-empty, close. These are probably verification, not
  work.

## 8. Evidence, so none of this gets re-derived

Measured 2026-08-11 on `~/src/campaigns/*` and `main`:

| Claim | Evidence |
|---|---|
| OOTA genre flattened | `narrate.genre` 16,303 chars / **0** newlines; `profiles[0].knobs.narration_genre` identical; `voice/_genre.md` 16,340 chars / 88 lines, whitespace-normalised similarity 0.999 |
| Phandalin genre healthy | 7,351 chars / 60 newlines in both locations; similarity 1.000 vs the file; contains "present tense" |
| Critic cannot resolve Phandalin specs | `voice/` holds `brewbarry_new_pipeline.md`, `soma_new_pipeline.md`, `valphine_new_pipeline.md`, `vukradin_new_pipeline.md`; the skill looks for `<key>_voice.md` / `<key>.md` |
| OOTA specs do resolve | `daz_voice.md`, `grygum_voice.md`, `thorin_voice.md`, `zalthir_voice.md` — which is why F1 stayed invisible |
| WO-3 landed but #249 open | `frontend/src/components/scene-editor/KnobDrawer.vue:266-273` |
| `voice_lint` duplicates the skill's scan | `session_doc/voice_lint.py:43-48` vs `voice-critic/SKILL.md:78`; console script at `pyproject.toml:86` |
| `voice_lint` filer rules are OOTA-only | `UNLICENSED_FILERS = ("thorin","zalthir")`, licensed grygum/daz — inert on Phandalin, where the one recorded cross-model reflex (`filed … away`, fable Vukradin 03) lives |
| Uncommitted skill edit | `git -C ~/src/mytools diff --numstat` → `23 1 dotfiles/claude/skills/voice-critic/SKILL.md` |

## 9. What this doc does not own

Per-WO change specs and acceptance criteria (#245 handoff), the standing constraints that
bind any work order — subscription backend only, never commit to main, golden regen,
worktree traps (#245 handoff §"Standing constraints"), findings and designs
(`VoiceCriticAlignment_proposal.md`), and the benchmark numbers (#245 handoff, source of
record). Read those before executing any step above.
