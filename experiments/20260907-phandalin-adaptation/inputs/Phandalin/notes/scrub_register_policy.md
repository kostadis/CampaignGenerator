# Phandalin — scrub register policy

**Campaign-scoped rulings on what is NOT mechanical residue.** Read this BEFORE walking
candidates in a `/scrub` run (Phase 2), and append to it in Phase 6 whenever the GM rules
on a new class.

**Why this file exists:** none of what follows is scannable. `find_residue.py` matches
numbers, fixed table-speak phrases, and player names — it cannot match vocabulary at all,
by design (see the skill's hard invariant). So nothing but this document stops the next
run re-proposing every ruling below, one instance at a time.

It lives in `notes/` because it is a cleanup-pass reference, not campaign canon — do not
mine it into the mempalace.

---

## The register line

**Metagame *adventuring* vocabulary is in canon. The class to police is modern
technology.**

> "I am thinking the meta-game gaming MMO language is the kind of language adventurers
> would use. I mean 'you have quests' — pretending you don't is weird. Where we need to be
> careful is when the language refers to modern technology like computers etc."
> — GM, 2026-09-02 (ch02 scrub)

This is a *single policy*, not N independent rulings. Settle it once at the top of a run
and let it collapse the queue. Ch50 is the cautionary case: several rounds went by
proposing economics terms one at a time before the GM explained they were the campaign's
premise.

## Ruled IN CANON — never propose these

| Class | Examples | Ruled |
|---|---|---|
| Quest / adventuring vocabulary | quest, quest board, quest marker, exclamation mark, "the yellow bang", fetch quest | ch02 |
| Alignment talk | "What do you like? Lawful, super lawful?" | ch02 |
| Action economy as wry aside | "Talking is a free action, right?" | ch02 |
| Class names as professions | "they've been rogues and clerics. And rangers" | ch02 |
| A caster naming prepared spells | Goodberry / Longstrider / Ice Knife; swapping what is held ready | ch02 |
| Imported real-world economics | tax-free income; "fair-trade, conflict-free gold"; supply chain; revenue share; marketing; perpetuity; image and likeness | ch50, reaffirmed ch02 |
| Modern idiom that is neither tech nor a named entity | "bangers", "fat shaming" | ch02 |
| Self-covering real-world reference | the Princess Bride "mostly dead… / …is still alive" exchange | ch02 |
| Specific words ruled in canon outright | **cosplaying** | ch50 |
| Imported real-world **physics / scientific register** | potential energy; terminal velocity; "broadcast" | ch04 |
| Unattributed pop-culture idiom naming no entity | "Technically correct. The best kind of correct." (Futurama) | ch04 |

Rationale on two of these, in the GM's words:

- **Quest markers:** *"It's a map with markers. Maps have markers. So why not an
  exclamation point? A yellow bang?"*
- **Spell talk:** *"Of course a druid talks about their spells. Soldiers talk about their
  blades."*
- **Economics:** Vukradin importing real-world economics into Faerûn is the campaign's
  central conceit — KP's planar-efficiency project is the same premise from the other
  side. Chapter 07's title is literally "Conflict Free Gold".
- **Physics (ch04):** the same move as economics, from a different player. Soma reasoning
  about potential energy and terminal velocity to justify a Mold Earth rockslide is the
  table importing a modern *frame*, not modern *technology* — nothing is a device. Settled
  as one class rather than three instances; `broadcast` rode along on the same ruling as the
  borderline case (a word, not a machine).

## Ruled RESIDUE — still propose these

| Class | Examples | Ruled |
|---|---|---|
| Modern technology | **MMO** (scrubbed while "the quest marker" in the same line was kept) | ch02 |
| Named real-world entity | Freebird; Bud Light, Hollywood, Kickstarter, Blue Oyster Cult, Houston; SystemD; Zoomer; meth lab; Chinese wall | ch02, ch48, ch50 |
| Character level | "we're level one", "we're level 7?" | ch02, ch48 |
| Character-sheet talk | passive perception, ability scores ("she's got high wisdom"), saves ("give me a save 13") | ch02 |
| Player-level speech | "one of my characters" | ch02 |
| Out-of-fiction table reference | "the GM", "troll the GM" | ch02 |
| DM narration in a player's mouth | "Yeah, we see a little hallway with like a door at the end of it" | ch02 |
| Table shorthand for money | "50 GP" where the surrounding prose says "fifty gold pieces" | ch02 |
| Raw transcript artifact | a literal `[inaudible]` left in finished narration | ch02 |

## Coinages authored during scrub runs (`provenance: on_the_fly`)

These were invented in narration to replace an anachronism. They are canon now, and a
consistency pass must not read them as fabrications.

| Coinage | Replaced | Chapter | Note |
|---|---|---|---|
| **The Roc's Lament** | Freebird | ch02 | A Sword Coast tavern standard — the song patrons shout for and musicians dread. A *song title*, not an entity alias. |
| **Aurum Bee Vance** | Oral B. Vance | ch48 | A **mishearing**, NOT an alias. Belongs in the canonical entity's note; never register it as an alternate name. |
| Menzoberranzan **cadet house** | Chinese wall | ch48 | A drow institution for laundered agency. |
| **dreamlily** | meth lab | ch48 | A named narcotic. |
| "talks like a **shell-sprout**" | Zoomer | ch48 | Soma's idiom for the young. |
| **Jimble the Unmoved** | — | ch03 | Marginal-note coinage; a cleric of the old coastal sagas who pronounced companions dead rather than spend the prayer. Glosses "He's dead, Jim." |

## Ruled RESIDUE — additions from the ch02 re-render pass (2026-09-02, run 2)

| Class | Examples | Ruled |
|---|---|---|
| Raw roll results / roll canvass in dialogue | "Anybody do better than that?", "Four.", "Any more roles, guys.", "I said 14.", "Oh, 14. Nice." | ch02 r2 |
| Digits in dialogue for money | "the 50 gold pieces" -> "the fifty gold pieces" (same class as "50 GP") | ch02 r2 |
| Bare imperative addressed to the GM | **"Hit the door."** | ch02 r2 |

The last row is worth its own note. It carries no number and no fixed table-speak phrase,
so **no scanner pattern can ever reach it** — and it is genuinely ambiguous as in-fiction
dialogue. The `/scrub` recommendation was to keep it; the GM ruled it out. Ambiguous bare
imperatives go to the GM rather than being resolved by the reading pass.

Also reaffirmed unchanged in that run: **"Talking is a free action, right?"**, the
**Princess Bride** exchange, **quest / quest board**, and spelled-out money
("a couple hundred gold pieces") are all in canon.

**No new coinages.** `The Roc's Lament` was re-applied to re-rendered lines; it is still the
single ch02 coinage, still a song title and not an entity alias.

## In-world scholar persona

Phandalin's marginal-note persona is **Kostadinious the Sage**, the campaign's in-world
biographer. Never mint a new sage per note.

## When a scrub ruling collides with a fidelity ruling

`/voice-smooth` and `/session-summary-consistency` settle **what was said**. `/scrub` settles
**what belongs in narration prose**. They can disagree about the same span, and when they do
the disagreement is real rather than a mistake by either pass.

Precedent, ch04 (GM-ruled 2026-09-02): `"Got 11 insight on — do I think he's a surface ogre?"`
had just been ruled correct-to-tape by `/voice-smooth` — it was never a garble, only a missing
sentence boundary — and `/scrub` then flagged the bare number+skill as residue. **The GM ruled
the fidelity decision governs and scrub stood down.**

The default to propose, never to assume: a span that a *recent, explicit* fidelity ruling
settled is not re-opened by a scrub run. Surface the conflict as its own card, say which pass
ruled what and when, and let the GM choose — do not resolve it silently in either direction,
and do not leave it out of the manifest just because nothing changed.

## Coinages authored during scrub runs — ch04

**None.** Ch04's run produced no new canon: every approved change was a removal or a
plain-language restatement, and no anachronism needed an in-world replacement.

## The ren-faire register (ch08, 2026-09-04) — CAMPAIGN-WIDE

> "for the register of this adventure 'ren-faire except where there is pre-existing
> faerun words - e.g.: Tendays instead of week'"
> — GM, 2026-09-04 (ch08 scrub)

Two clauses, and the second governs the first:

1. **Default to a ren-faire register** — relaxed pseudo-medieval, not strict
   period diction. This is what licenses the campaign's existing in-canon classes
   (imported economics, physics, adventuring vocabulary) rather than contradicting
   them; those rulings all stand unchanged.
2. **Where Faerûn already has a word, use it.** `tenday`, not `week`. The Faerûn
   term outranks both the ren-faire default and the real-world word.

This is the first ruling that can be *partly* scanned — a fixed word list
(`week` -> `tenday`, and its siblings) is matchable, unlike every other row in this
file. It is still not in `find_residue.py` and adding a vocabulary category there
needs explicit GM sign-off per the hard invariant, so for now it is a reading-pass
rule like the rest.

**Precedence, settled the same day.** The napalm span (`"I mean, it smells like
napalm"`, Wade, ch08 s05, tape l.6287) sat inside verbatim player speech, which
this file's earlier precedent generally protects. The GM ruled **replace in-world**
-> `"it smells like a pitch fire"`. So the register rule can outrank locked player
dialogue; it is not automatically subordinate to it. Ask per instance — this did
not establish that every anachronism in a quote now gets rewritten.

`pitch fire` is ordinary description, **not** a coinage and **not** an entity.

### Applying it — what it did NOT catch

Checked across ch08's six narration scenes and found **zero** additional
candidates. Worth recording so the next run does not re-derive it:

- `minute` / `hour` are normal Faerûn units. **Tenday replaces *week*, nothing else.**
- An ordinal `second` ("no second lightning bolt") is not a time unit.
- Terms inside a `<!-- table-speech reclassified -->` hatch are already out of the
  narration and are never candidates.

### Open, campaign-wide

The existing corpus does not follow this rule yet: **13 uses of `tenday` against 29
of `week`** across `summaries/*/narration/`. The ruling post-dates that prose. A
sweep is justified but was out of scope for the ch08 run.

## Recap policy (ch08, 2026-09-04) — CAMPAIGN-WIDE

**Combat resumes are never cut.** Phandalin sessions routinely end mid-encounter,
and the next session opens by re-establishing live state (conditions,
concentration, whose turn it is). That is a precondition, not a duplication — the
previous chapter cannot have recorded a resolution it did not reach.

The test is the *previous* chapter's ending, not the current chapter's opening:

- previous chapter resolved → an opening retelling is a **recap**, and is a cut
  candidate;
- previous chapter ended on a cliffhanger → the opening is a **resume**, and stays.

Ruled on ch08, where three quote blocks re-establishing the harpies' charm looked
like a recap and were the setup for the session's first spell. See
`summaries/20250812-chapter-08/remove_recap_manifest.md`.

**Tooling caveat:** `find_recap.py` keys on a `## Voiced moments` heading this
campaign does not use, so it parses no Phandalin extraction and returns 0/N
regardless of content. Treat its output as *not run*, and do the three-surface
check (scene list, `## Summary` prose, enhanced-summary file) by hand.

**Standing default, reaffirmed on ch51 (2026-09-06):** when the previous
chapter resolved, cut its opening retelling by default. Drop real-world
scheduling chatter and unrelated modern-topic conversation that precede the
recap with it. Preserve current-chapter bookkeeping and live-state setup in the
next scene; the combat-resume exception above still governs unresolved
encounters.

## Table jokes carried into fiction (ch51, 2026-09-06) — CAMPAIGN-WIDE

Player-to-table jokes survive `/no-mech` when they contain usable character,
relationship, or scene texture. During `/scrub`, recast their modern phrasing
into the campaign's ren-faire/Faerûn register and incorporate the result into
fiction and canon. This is an explicit exception to treating their table-facing
delivery as residue; it does not protect raw rolls, rules procedure, VTT
operation, scheduling, character-sheet bookkeeping, or non-comedic table
administration.

Named real-world references inside a retained joke are still scrub candidates:
preserve the joke's fictional work, not necessarily its literal referent.

## NPC-label triage limitation (ch51, 2026-09-06) — TOOLING

This campaign labels NPC speech as `GM`, and its italic context does not use
`as <NPC>` stage directions. Consequently, `/no-mech`'s NPC-speaker-label
signal reports zero in-character NPC blocks even in scenes full of NPC speech.
Treat that signal as structurally unavailable for Phandalin and decide from the
full-scene reading; never use it to justify an all-mechanical cut.

## Magical-effect wording (ch51, 2026-09-06) — IN CANON

The exact phrases **passive charm** and **passive confusion** describe an
in-world magical effect. They are not roll callouts or passive-skill references,
despite the scrub scanner categorizing them that way. Keep both phrases. They
are also recorded in `notes/.scrub_state.json` as exact scanner ignores.

The ch51 `narration3` scrub introduced no new on-the-fly canon. Its replacements
used existing setting references (Kara-Tur, Leilon, Daggerford, Sending Stones,
and the Open Lord) or ordinary descriptive language.
