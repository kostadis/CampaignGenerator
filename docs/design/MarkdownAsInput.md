# Markdown as Input — text-parsing sweep, 2026-08-10

## Why this doc exists

A sweep of the codebase for "everywhere we parse text files to get specific
pieces of data" turned up **80** module-level `re.compile` parse constants
(`campaignlib/` 25, `session_doc/` 25, `pipelines/` 26, `entity_registry/` 2,
`server/` 2, `provenance/` 0) and ~40 named parse/extract functions.
`provenance/` is a genuine zero, not a directory the search skipped — it does
its regex work with inline `re.compile()` calls rather than module-level
constants, so there is nothing at module scope for this count to find there.
The original figure, ~66, undercounted for two separate reasons: part of it
came from truncated search output, and part of it predates #259 and #267,
which both landed after this document was first written and each added
`re.compile` constants of their own. That is a lot of parsing, but volume was
not the finding.

The finding is a single cause underneath five separate defects — plus a sixth
observation that is not a defect at all, but the thing most likely to be
mistaken for one. Both are worth stating plainly, because together they predict
where the next problem will appear *and* where the next well-meaning cleanup
will do damage.

---

## The through-line

**Markdown here began as *output*.** It was the readable artifact — documents a
GM opens and reads. Six campaigns each hand-authored a `party.md` in whatever
shape made sense to them, and six shapes cost nothing, because all six read fine
to a person. That was correct. Nothing was wrong with it.

**Then those files became *input*.** Pipelines started reading them back to
recover fields. And the moment a machine reads a document, the properties change:

- every dialect is a parser
- every parser is a guess
- the guesses drift apart silently, because nothing forces them to agree

Nobody decided this. It happened one reasonable commit at a time, and each
individual parser is defensible in isolation. The cost only shows up in
aggregate, which is why a sweep found it and code review did not.

The repo already has the instinct. `campaignlib.textproc.locate_quote` (14
callers) exists precisely because two pipelines had each grown a private copy of
"is this quote really a span of that text?" and a third was about to be written.
Its docstring records the reasoning. This document is that same argument,
applied four more times — and then, in C1, the argument's own limit: the cases
where two implementations of one job are correct.

### Three categories, three different fixes

| | Shape | Fix |
|---|---|---|
| **A** | Structure destroyed, then re-derived. A producer holds structured data, renders it to prose, a consumer regexes it back. | A format. Carry the structure; let markdown be output again. |
| **B** | One job, several implementations that disagree. No format problem — just drift. | Consolidation onto the existing canonical helper. |
| **C** | One job, several implementations that *look* like B, but produce deliberately different answers because their consumers differ. | Not consolidation. Legibility — reciprocal cross-references. |

Telling them apart matters. Category B is a cleanup. Category A is a design
change, and consolidating the parsers without fixing the format just produces
one better parser for data that should not be parsed at all. Category C is the
trap in between: it has the surface shape of B — same job, more than one
implementation — so a reader who has just learned to spot B reaches for B's
fix. That fix is wrong here. The divergence isn't drift; it's intentional, and
consolidating it would delete a real distinction rather than a redundant one.

> **Category C — deliberate divergence.** Two implementations that *look* like
> B, but produce deliberately different answers because their **consumers**
> differ. The discriminator is not how the output is computed — it is what the
> output is used for.
>
> **The fix is not consolidation. It is legibility: reciprocal
> cross-references** — each site names the other, states what it is *not*, and
> directs the reader to the correct one.

---

## A1 — the party roster

`session_doc/roster.py` reconstructs `{name, player, species, class, level,
subclass}` from **six** hand-authored `party.md` layouts and returns them
re-flattened into a prompt string. Structure exists at both ends of that
function and is missing only in the middle — which is the part stored on disk.

This one has its own document: **`docs/design/PartyRosterCanonicalFormat.md`**.
The short version, with the GM ruling applied (*the D&D Beyond character sheet
is canonical for all character-specific data*): the sheets already share one
format, the six dialects exist only in the derived `party.md`, and the code is
currently reading the derived copy in preference to the authoritative one — with
at least one live factual conflict as a result.

**Status: code shipped, migrations deliberately not** (#265). `dnd_sheet.py`
emits YAML frontmatter and a `**Subclass:**` line; `roster_from_config` and
`player_map_from_config` read it; `sheet_frontmatter` is a deterministic,
zero-token importer for sheets that predate the change. `PartyCharacter` is
untouched — `sheet:` was already the reference, and the draft that added
`species`/`class_level` to it stays superseded. **Nothing changes behaviour
today**: 15 sheets on disk, 15 with a parseable `## Identity`, **0 with
frontmatter**, so both readers return `None` everywhere and all call sites fall
back to `party.md`. Per the GM ruling the six campaign migrations and their
conflict rulings are a separate follow-up (**#293**), and the fallback stays
until then.

Two things the corpus contradicted in this document:

- **The call sites are four, not three.** `enhance_summary.py` calls
  `extract_player_character_map` too, alongside `sd_narrate`, `polish` and
  `scene_extract`.
- **"The sheet is canonical" is right as a ruling and wrong as an
  implementation.** All four toee sheets carry `**Player:** kostadis1` — the
  D&D Beyond *account handle*, not the person — while `party.md` has the real
  names. A "sheet wins" rule applied mechanically would map that whole campaign
  to one player and collapse its player→character map. This is why the importer
  refuses to auto-resolve conflicts even toward the authoritative source: it is
  authoritative about the character, not about who plays them.

Also found and filed separately: no single base directory resolves `sheet:` for
all campaigns (Phandalin, stormgiants and toee resolve from the `party.yaml`'s
own directory; out-of-the-abyss from the campaign root), and
`pipelines/grounding/party.py` passes `Path.cwd()`, so which sheets are found
depends on where the CLI was run — **#291**.

---

## A2 — four `## Scenes` scanners, three different verdicts

Four independent answers to "does this document have a Scenes section, and what
is in it":

| Site | Match rule | `## Scenes (12)` | `## scenes` |
|---|---|---|---|
| `session_doc/io.py:185` `extract_scene_text` | `line.strip() == "## Scenes"` — **exact string** | miss | miss |
| `campaignlib/lineage.py:236` `_SCENES_SECTION_RE` | `^##[ \t]+Scenes\b.*?` — case-**sensitive**, trailing text ok | hit | miss |
| `pipelines/ensemble/summary_map.py:152` `parse_summary_scenes` | `_H2_RE` + `.strip().lower() == "scenes"` | miss | hit |
| `campaignlib/scenes.py:14` `parse_gmassist_scenes` | `_TOP_HEADING_RE` + lowercased compare | miss | hit |

`extract_scene_text` is the strictest: a heading of `## Scenes (12)`, or two
spaces after the `##`, yields empty — and its callers cannot distinguish that
from a genuinely empty scene.

This one carries extra weight. Scene boundaries are a **known-hard precision
decision** in this repo: inferring them was already investigated and closed as a
dead end (#227 — 87% accuracy, not the 99% the use required). Four regexes each
independently guessing at a boundary the project has already ruled cannot be
inferred reliably is exactly the wrong number of guesses.

**Fix.** One `campaignlib.scenes.find_scenes_section(text) -> (section, span) |
None`, built on the `_H2_RE`/`_H3_RE` already living in
`campaignlib/textproc.py`. Adopt the **loosest** rule — the strict variants are
silently dropping real sections, which is the failure that costs something.
Keep `parse_summary_scenes`'s `None`-vs-`[]` contract ("unstructured" vs
"empty") as the shared one; it is the only one of the four that distinguishes
them, and the distinction is load-bearing.

**Open ruling.** Loosening means `extract_scene_text` begins finding sections it
currently misses. That is the intended fix, but it is a behaviour change on live
corpora — audit for non-bare `## Scenes` headings before landing it.

**Status: fixed** (#262). `campaignlib.scenes.find_scenes_section` is the single
rule and all four sites call it; `_TOP_HEADING_RE`, `_SCENES_SECTION_RE` and
`_SCENES_HEADING_RE` are gone. `parse_summary_scenes`'s `None`-vs-`[]` contract
became the shared one, as proposed.

**The audit the open ruling asked for, answered.** Across 16,896 files: 570
`## Scenes` occurrences, **566 bare and unanimous under all four old rules**, 0
lowercase headings anywhere. The 4 divergent ones are all in a single generated
`consistency_report.md` — a filename `session_doc/io.py` explicitly skips. So
loosening changed the output of **no file any caller reads**. The hazard was
latent, not live; the consolidation is insurance against future drift rather
than a bug fix.

Two multi-section behaviours were kept apart on a GM ruling rather than
harmonised: `extract_scene_text` reads the first `## Scenes` section only,
`parse_gmassist_scenes` accumulates across every one. Both were accidents of
statement order in the old line loops, in *opposite* directions, and both are
now pinned by tests that say so out loud. One more wart is pinned rather than
fixed: no scanner has ever treated `#` as a section boundary, so an intervening
H1 lands inside the preceding scene's body. Making H1 a boundary would change
what every scene body contains — out of scope here, and now visible.

---

## A3 — the UI recovers verifier counts by regexing a prose sentence

`session_doc/verify_quotes.py` is the **deterministic, zero-token** quote
verifier. It holds exact per-verdict counts as structured data —
`VerificationReport.refusal_counts` is a typed property:

```python
@property
def refusal_counts(self) -> dict[Rule, int]: ...
```

(An earlier revision of this document attributed that property to
`ConflictScan`. It does not live there — `ConflictScan` carries only a
`refused` **int**, with no per-rule split, which is part of why the prose line
below is the only place the breakdown ever existed.)

It renders that dict to a prose sentence:

```python
f"**Refused by the extraction contract (#250)**: {n_ref}"
```

Then `server/routers/scene_editor.py:724` and `:754` parse it back:

```python
_REPORT_ROW_RE = re.compile(
    r"^\|\s*\**(verified|near|unverified|unscored|exempt)\**\s*\|\s*\**(\d+)\**\s*\|",
    re.MULTILINE)

_REPORT_REFUSED_RE = re.compile(
    r"^\*\*Refused by the extraction contract[^*]*\*\*:\s*(\d+)", re.MULTILINE)
```

The first parses a markdown table — bad but survivable. The second parses **a
prose sentence containing an issue number**:

> `**Refused by the extraction contract (#250)**: 16 — R1 4, R3 12.`

Reword that line, or renumber the issue, and the Session Doc Editor's status
strip silently loses the refusal count. The shape is `dict[Rule, int]` → prose
→ `dict` — a producer holding a typed dict, deliberately throwing the types
away to render a sentence, and a consumer rebuilding a dict by pattern-matching
the sentence. And the rebuild is **lossy**: the regex recovers the total and
drops the per-rule split, so `R1 4, R3 12` is computed, rendered, and then
unavailable to the UI at all. **#259 is what created this path** — `refusal_counts` and the
sentence it feeds didn't coexist with `_REPORT_REFUSED_RE` before that PR
landed — so this finding is live, not archaeology.

(#259 also gave `verify_quotes.py` a contract layer — `Rule`, `Refusal`,
`editorial_brackets`, `find_bracket_refusals`, `scan_section_conflicts`,
`verify_artifact_contract` — so a reader diffing the file against an older
checkout shouldn't be surprised it grew by 462 lines; none of that growth is
what this finding is about.)

The `None`-vs-`0` handling in `_parse_quote_report_counts` is genuinely good
defensive design — "no unverified quotes" and "we could not tell" must not look
alike to the status strip, since one is a reason to look and the other is a
reason not to. But the reason that defence is needed at all is that the channel
is prose.

**Fix.** Have `sd_verify_quotes` write `quote_report.json` beside the `.md`
(counts, refusals by rule, artifact paths). The server reads the JSON; the
markdown stays a human-readable report that nothing parses. Keep the regex path
for one release so existing campaign directories do not blank out, then delete
it. No effect on the verifier's zero-token / no-LLM guarantee.

This is the cleanest of the five defects — the producer already holds the
structured value, so nothing has to be re-derived to fix it. Only C1 is cheaper,
and C1 adds no code at all.

**Status: fixed** (#264). `report_json` sits beside `render_report`;
`sd_verify_quotes` writes `quote_report.json` alongside the `.md`; the server
prefers it and keeps the regex as a one-release shim. `render_report`'s output
is unchanged, and the JSON carries the per-rule breakdown the regex could never
recover. The `parse_scene_quotes` ↔ `parse_scene_summary_spans` C1 pair was
documented in the same change.

---

## B1 — three VTT readers, two relationships, two categories

#267 added a third parser to what was a two-way naming collision. The two
relationships this now describes are not the same shape, and treating them as
one problem was itself an artifact of the naming coincidence: once
`campaignlib/vtt.py` exists, this finding splits into a Category C pair and a
Category B pair.

| Site | Signature | Returns | Speaker | Callers |
|---|---|---|---|---|
| `campaignlib/vtt.py` `parse` | `(text: str) -> Transcript` | lossless, cue-addressable (`Cue.index`, `.timing`, `.lines`, `.text`, `.with_text()`) | inside `cue.text` as `"Name: words"`, unparsed | `session_doc/sd_corrections.py:52`, `campaignlib/transcript_corrections.py` |
| `session_doc/io.py:13` `parse_vtt` | `(text: str) -> str` | one flattened dialogue string | left inline, unparsed | 5 (`enhance_summary`, `scene_extract`) |
| `session_doc/vtt_voice_compare.py:91` `parse_vtt` | `(vtt_path: Path) -> list[tuple[str, str]]` | `(speaker, text)` pairs | split on first `:` | 1 |

**`campaignlib/vtt.py` `parse` ↔ `io.parse_vtt` is Category C**, and
`vtt.py`'s own module docstring says so:

> """Structural WebVTT parsing — cues you can address, edit, and write back.
>
> ``session_doc/io.py:parse_vtt`` is the *lossy* reader: it throws away cue
> numbers, timings and structure and hands back speaker dialogue, which is all
> the generation stages need. This module is the lossless one. It exists because
> the extraction contract (#250, R4) makes ``*.transcript.cleaned.vtt`` a
> **generated** file, and generating one means being able to rewrite a single
> cue's text and re-emit everything else byte-for-byte.
> """

Both readers earn their keep — `io.parse_vtt`'s five callers are generation
stages that genuinely want flattened dialogue, not a `Transcript` of `Cue`
objects, and forcing them onto the structural type would just move the
flattening into every caller. This pair should **not** be consolidated. But
the cross-reference only runs one direction: `io.parse_vtt`'s own docstring
says nothing about `campaignlib.vtt`. A reader who meets the lossy reader
first has no signpost toward the lossless one, or toward why both exist.

**`io.parse_vtt` ↔ `vtt_voice_compare.parse_vtt` is still Category B.** Same
name, no shared docstring language, no cross-reference in either direction,
and no consumer-shaped justification for the divergence the way the C pair
has one — this reads as two people independently writing a VTT
speaker-line splitter, not a deliberate design choice.

The original fix proposed for this section — invent one
`parse_vtt(text) -> list[VttLine]` carrying `speaker` and `text`, and rename
both existing functions onto it — is now obsolete. `campaignlib.vtt` already
owns the structural representation that proposal was reaching for. It landed
for an unrelated reason (#267, the extraction contract's generated-file
requirement), but it makes the invented type unnecessary.

**Revised fix.**

- `vtt_voice_compare.parse_vtt` derives its `(speaker, text)` pairs from
  `campaignlib.vtt.parse(...).cues` — split each `cue.text` on the first `:` —
  instead of running its own regex pass over the file. That deletes the
  Category B divergence without inventing a new representation.
- `io.parse_vtt` gains the reciprocal cross-reference to `campaignlib.vtt`, so
  the Category C pair is documented at both ends, matching the `norm_subject` /
  `normalize_npc_key` template (see C1 below).

Speaker attribution is still precision data (#223) — which form a name took
when spoken must never be silently rewritten — and leaving it unparsed inline
on `io.parse_vtt`'s five-caller path remains a latent version of that hazard.
Neither half of the revised fix changes that; it is outside this sweep's
scope.

**Status: fixed** (#263). `vtt_voice_compare.parse_vtt` is now `speaker_pairs`,
built on `campaignlib.vtt.parse(...).cues` — the name collision is gone along
with the duplicate reader, and NOTE handling came for free. `io.parse_vtt`'s
output is byte-identical, and it gained the reciprocal cross-reference.

**The colon guard is deleted, which is the proof.** `campaignlib/vtt.py`'s
`render()` no longer refuses to emit a generated NOTE containing a colon. That
guard existed *only* because this one reader would have misread it as dialogue:
a live generator was carrying a restriction to work around a defect in a
single-caller tool. `GENERATED_MARK` kept its value deliberately — changing it
would make NOTE blocks in tapes already on disk unrecognisable and break the
`parse → render → parse` fixed point. `VttError` itself stays; only the colon
branch went.

Per the GM ruling, a malformed tape now **fails loudly and names the defect**
rather than degrading quietly: `_diagnose_vtt_error` counts `WEBVTT` headers and
reports "joined recordings" or "fragment". Running it over the corpus found two
real ones (`campaigns#159`): a tape that is two recordings concatenated, with
**363 duplicate cue indices** — and #250 R4 keys `transcript_corrections.yaml`
on cue index, so a correction there would be ambiguous — and a `.cleaned` tape
missing its first 128 cues, the opening 28 minutes. The parser accepting the
concatenated shape at all is filed as **#287**.

---

## B2 — three frontmatter parsers, one lying about its contract

| Site | Returns | Parser | Callers |
|---|---|---|---|
| `campaignlib/textproc.py` `split_frontmatter` | `(dict, body)` | **YAML** | 21 |
| `session_doc/assemble.py` `parse_frontmatter` | `(dict, body)` | **hand-rolled `k: v` split** | 1 |
| `session_doc/scrub_mechanics.py` `split_frontmatter` | `(raw_block, body)` | none (offset find) | 2 |

`assemble.parse_frontmatter` is the problem. It advertises the same
`(dict, body)` contract as the 21-caller canonical version but splits on `:`
instead of calling YAML — so lists, quoted strings, colons inside values, and
anything nested parse differently, with no error. It also carries its own
`_FRONTMATTER_RE` (assemble.py:29), separate from textproc.py:13.

Five frontmatter regexes exist repo-wide: textproc.py:13, assemble.py:29,
npc.py:8, io.py:50, plus `scrub_mechanics`'s offset find.

**Fix.** Delete `assemble.parse_frontmatter`; call
`campaignlib.textproc.split_frontmatter`. **Keep**
`scrub_mechanics.split_frontmatter` — returning the raw block *including
delimiters* is a legitimately different job, since it round-trips the block back
out unchanged — but rename it `split_frontmatter_raw` so the differing contract
is visible at the call site.

This becomes load-bearing under A1: sheet frontmatter must be parsed by the YAML
implementation, never the `k: v` one.

**Status: fixed** (#261). `assemble.parse_frontmatter` and its `_FRONTMATTER_RE`
are deleted; the one caller uses `campaignlib.textproc.split_frontmatter`.
`scrub_mechanics.split_frontmatter` is now `split_frontmatter_raw`, and the two
carry reciprocal docstrings naming each other and saying why neither does the
other's job — the `norm_subject` / `normalize_npc_key` template from C1.

**Four frontmatter regexes remain, not five**: `textproc.py:13`,
`npc.py:15` (`_DOSSIER_FRONTMATTER_RE`), `io.py:60` (`_SCENE_FRONTMATTER_RE`),
plus `scrub_mechanics`'s offset find. The three that remain are matchers over
the same delimiter, not competing *parsers* — only `assemble`'s claimed a
`(dict, body)` contract it did not honour, and that is the one that went.

---

## C1 — deliberate divergence, four pairs

Not every "two implementations, one job" pair this sweep turned up is Category
B. Four of them produce different answers **on purpose**, because the two call
sites want different things from the same input. Collapsing any of these into
one implementation would delete a real distinction, not a redundant one — so
unlike A and B, the fix here is not a code change. It is making each pair
findable from either end.

| Pair | Cross-referenced | Consumer difference |
|---|---|---|
| `campaignlib/textproc.py` `norm_subject` ↔ `campaignlib/npc.py` `normalize_npc_key` | **both sites** | identity key vs display/lookup rewriter |
| `campaignlib/vtt.py` `parse` → `session_doc/io.py` `parse_vtt` | one site (vtt.py) | lossless structural vs lossy dialogue reader |
| `session_doc/verify_quotes.py` `parse_scene_summary_spans` / `parse_scene_quotes` | one site (D4) | pairing-only vs becomes-a-finding |
| `session_doc/scrub_mechanics.py` `split_frontmatter` / `campaignlib/textproc.py` `split_frontmatter` | **neither** | raw block round-trip vs parsed dict |

Two of the four already do this correctly. Two do not, and the
"cross-referenced" column is the whole finding: a diverging implementation is
fine, a *silent* diverging implementation is not — it is indistinguishable
from Category B drift until someone reasons it out from scratch, and that
reasoning is exactly the work a docstring should have already done.

### The worked template: `norm_subject` / `normalize_npc_key`

Both docstrings state their own scope and name the other function, in both
directions. This is the gold standard the other pairs should copy.

`norm_subject` (`campaignlib/textproc.py`):

> """Identity normalizer for entity keys: lowercase, strip all non-alphanumerics.
>
>     This is the AGGRESSIVE identity comparison used to decide whether two
>     strings name the same entity (e.g. "Ilvara Mizzrym" and "ilvara-mizzrym!"
>     both normalize to "ilvaramizzrym"). Contrast with
>     ``campaignlib.npc.normalize_npc_key``, which is a display/lookup text
>     rewriter (keeps spaces, only strips a narrow punctuation set) and is NOT
>     an identity key — do not use it for entity-identity comparisons.
>     """

`normalize_npc_key` (`campaignlib/npc.py`):

> """Lowercase, strip punctuation, collapse whitespace — for alias-key lookups.
>
>     LLM-emitted variants like "Harbin (Townmaster)" must match flat aliases
>     like "Harbin Townmaster". Without normalization the parens block lookup.
>
>     This is a display/lookup TEXT REWRITER (keeps spaces), not an identity
>     key. For entity-identity comparisons use ``campaignlib.textproc.norm_subject``.
>     """

Neither function is wrong. Neither should be deleted. A reader who lands on
either one is one sentence away from the other, and from the reason they
differ.

### `parse_scene_summary_spans`: the same divergence, half-documented

`session_doc/verify_quotes.py`'s `parse_scene_summary_spans` deliberately
parses inline `"…"` quotes in the `## Scene summary` half of a document —
exactly what `parse_scene_quotes` refuses to do, per research D4 (inline
quotes in prose are not reliably dialogue). The reasoning is written down, but
only at one end:

> """Quoted spans in the `## Scene summary` half — **for pairing only**.
>
>     This deliberately parses inline `"…"`, which `parse_scene_quotes` refuses
>     to do, and the difference is what the spans are used for. There they would
>     become findings, and calling the GM's own hand-authored gm-assist phrasing
>     "unverified" would be both wrong and an insult to the checkpoint that
>     produced it (research D4). Here they are only ever the *other copy* of a
>     span, so the worst a mis-parse can do is fail to notice a conflict.
>     """

`parse_scene_quotes` does not point back. A reader who meets it first, watches
it refuse inline quotes, and later meets `parse_scene_summary_spans` doing
exactly that has no signpost — they have to reconstruct the D4 argument
independently, which is what writing this pair up for this document required
doing.

### Why Category C gets a name instead of a footnote

Three functions in this codebase are named `split_frontmatter` /
`parse_frontmatter` and return `(something, body)`:

- `campaignlib/textproc.py` `split_frontmatter` — canonical, YAML, 21 callers
- `session_doc/assemble.py` `parse_frontmatter` — genuine drift, Category B, tracked as #261
- `session_doc/scrub_mechanics.py` `split_frontmatter` — deliberate divergence, Category C

**Nothing in the code distinguishes the last two from each other.** Both read,
from the outside, as "another frontmatter splitter near the canonical one."
Writing the B2 finding above required reasoning `scrub_mechanics`'s case out
from scratch — it round-trips the raw block *including delimiters*, which the
21-caller version cannot do, and that is a real requirement, not a bug. Its
docstring gives no hint of this:

> """Return (frontmatter_block_including_delimiters, body). Empty frontmatter ok."""

No mention of `textproc.split_frontmatter`. No statement of why this file
needs its own splitter. A reader has to already know the codebase's
frontmatter history to tell this apart from `assemble.parse_frontmatter`'s
bug — and B2's fix for this specific pair (rename to `split_frontmatter_raw`)
only makes the *difference* visible at the call site; it does not say *why*
the difference exists. That gap is what a reciprocal cross-reference closes,
the same way it closes the other two open pairs above.

That a B-shaped bug and a C-shaped design choice can sit in the same file
family, using the same name, with nothing in the code to tell them apart, is
the argument for treating Category C as a named thing with a mechanical
remedy rather than a footnote on Category B. The remedy is uniform and cheap:
one cross-reference sentence in each docstring, both directions.

---

## What the sweep also corrected

Running the roster parser against all six real `party.md` files — rather than
reading it — produced two facts that reading had missed.

**#248 is stale.** It reports that `extract_character_roster` "parses empty for
Hillsfar / obelisk / out-of-the-abyss / stormgiants / toee". As of this sweep,
every one of the six campaigns parses a non-empty roster. Its proposed fix —
extend `roster.py` with one branch per catalogued layout — is also the opposite
direction from where A1 lands.

**A defect not visible by reading.** `extract_player_character_map`
(`campaignlib/npc.py`, 10 callers) returns `{}` for three of six campaigns,
while `extract_character_roster` succeeds on all six:

| Campaign | roster | player_map |
|---|---|---|
| Phandalin | 4 characters | **`{}`** |
| Hillsfar | 4 characters | **`{}`** |
| out-of-the-abyss | 4 characters | **`{}`** |
| obelisk / stormgiants / toee | ok | ok |

Two parsers, one file, different layout coverage: the roster handles six
layouts, the player-map handles two. `scene_extract.py:390–401` feeds the map to
`normalize_vtt_speakers`, so with an empty map the VTT enters scene extraction
carrying **real player names** — `Wade Brown:` rather than `Soma:` — and the
model infers attribution instead of being told it.

That is Category B producing a live data-quality defect in narration input, and
it is the clearest single argument in this document.

**That defect is fixed** (#260, PR #274 — `campaignlib/party_md.py`, one parse
and two projections), which is why A1 above could refactor `npc.py` freely: the
two functions had only just been unified onto a single parse, so a 6-of-6
byte-identical gate on both was cheap to state and load-bearing to check.

### The method, since it kept paying

Every finding here was gated on byte-identical output captured **before** the
change, and the gates earned their cost three separate times — catching an
implementation that had two behaviours backwards, a "correction" of mine that
made divergence worse rather than better (2 diffs → 27), and a test asserting
behaviour the code had never had. In each case reading the code supported the
wrong conclusion and running it did not.

One caveat has to travel with that, and it is filed as **#286**: six test files
defend against worktree import shadowing with a module-level `pytest.skip`,
which contributes exactly **one** entry to the skip count no matter how many
tests it hides. A green full-suite total from a worktree is therefore not
evidence for a change — roughly 200 tests can vanish behind a `+1`. It produced
one false verification during this sweep, reported and corrected. Always also
run the specific files a change touches, and report *that* number.

---

## Sequencing

**All six shipped, 2026-08-12** — A3 (#264), B2 (#261), B1 (#263), A2 (#262),
A1 (#265) as five PRs off `main`, with C1's four pairs riding along inside the
issue that already touched each file. The order below is the one that was
followed, with A2 and B1 swapped after the audit demoted A2 from
"needs a ruling" to hygiene.

Per-finding status notes are inline above. What is deliberately **not** done,
tracked at **#293**: A1's six campaign migrations and their conflict rulings,
then — once every campaign has run one release on the new path — deleting A3's
and A1's compatibility fallbacks. #293 is itself blocked on **#291**, since no
single base directory currently resolves `sheet:` for all six campaigns.

| | Finding | Risk | Effort | Note |
|---|---|---|---|---|
| 1 | A3 `quote_report.json` | very low | small | pure win, no consumer behaviour change |
| 2 | C1 reciprocal cross-references | very low | small | docstrings only, no behaviour change; 2 open pairs (`io.parse_vtt`↔`campaignlib.vtt`, `parse_scene_quotes`↔`parse_scene_summary_spans`) — `norm_subject`/`normalize_npc_key` is already done, the `split_frontmatter` pair rides along with B2 below |
| 3 | B2 frontmatter | low | small | live correctness bug; **prerequisite for A1** |
| 4 | A2 `find_scenes_section` | medium | medium | 4 call sites; needs the loosest-rule ruling |
| 5 | B1 VTT readers, Category B half | low | medium | `vtt_voice_compare.parse_vtt` rebuilt on `campaignlib.vtt.parse(...).cues`, not a new representation — `campaignlib/vtt.py` (#267) already supplies the structural type the original proposal invented |
| 6 | A1 party roster | medium | large | own doc; 6 campaign migrations + conflict rulings |

C1 is sequenced this early because it is strictly cheaper than everything below
it — docstring text, zero call sites touched, no test surface — and it is the
fix most likely to be skipped if left for "later," since nothing forces it the
way a live bug does.

B2 sits ahead of its risk ranking because A1 depends on frontmatter being parsed
by the YAML implementation.

The `player_map` defect found above is filed separately at `priority:high` — it
is subsumed by A1, but it is independently shippable and it is degrading live
output now.

---

## The general rule this suggests

When a producer in this codebase holds structured data and a consumer needs it,
the structure should travel in a machine channel — YAML frontmatter, a `.json`
sidecar, a typed config — and markdown should be what humans read. The two can
live in the same file; frontmatter above, prose below, one review.

Markdown as input to something that produces readable text. Not markdown as the
place structure goes to die and get regexed back out.
