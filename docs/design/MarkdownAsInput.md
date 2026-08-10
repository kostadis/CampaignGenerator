# Markdown as Input — text-parsing sweep, 2026-08-10

## Why this doc exists

A sweep of the codebase for "everywhere we parse text files to get specific
pieces of data" turned up ~66 module-level `re.compile` parse constants
(`session_doc/` 23, `pipelines/` 22, `campaignlib/` 23, `server/` 1) and ~40
named parse/extract functions. That is a lot of parsing, but volume was not the
finding.

The finding is a single cause underneath five separate defects, and it is worth
stating plainly because it predicts where the next one will appear.

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
applied four more times.

### Two categories, two different fixes

| | Shape | Fix |
|---|---|---|
| **A** | Structure destroyed, then re-derived. A producer holds structured data, renders it to prose, a consumer regexes it back. | A format. Carry the structure; let markdown be output again. |
| **B** | One job, several implementations that disagree. No format problem — just drift. | Consolidation onto the existing canonical helper. |

Telling them apart matters. Category B is a cleanup. Category A is a design
change, and consolidating the parsers without fixing the format just produces
one better parser for data that should not be parsed at all.

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

---

## A3 — the UI recovers verifier counts by regexing a prose sentence

`session_doc/sd_verify_quotes.py` is the **deterministic, zero-token** quote
verifier. It holds exact per-verdict counts as structured data. It renders them
to markdown. Then `server/routers/scene_editor.py:724` parses them back:

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
strip silently loses the refusal count.

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

This is the smallest and cleanest of the five — worth doing first purely to
establish the pattern.

---

## B1 — two `parse_vtt`, same name, incompatible contracts

| | `session_doc/io.py:13` | `session_doc/vtt_voice_compare.py:91` |
|---|---|---|
| Signature | `(text: str) -> str` | `(vtt_path: Path) -> list[tuple[str, str]]` |
| Returns | one flattened dialogue string | `(speaker, text)` pairs |
| Speaker | left inline, **unparsed** | split on first `:` |
| Callers | 5 (`enhance_summary`, `scene_extract`) | 1 |

The information survives in both — `io.parse_vtt` keeps `Speaker: text` lines
intact, it simply never turns them into fields, so downstream consumers re-parse
attribution themselves. Given the standing rule that which form was *spoken* is
load-bearing and must never be silently rewritten (#223), the repo already
treats speaker attribution as precision data. Leaving it as an unparsed string
on the five-caller path is a latent version of the same hazard.

A reader who has seen one of these will mis-predict the other, because they
share a name.

**Fix.** One `parse_vtt(text) -> list[VttLine]` carrying `speaker` and `text`,
plus a thin `vtt_dialogue_text(lines) -> str` for the flattened form the current
five callers want. Rename rather than keep two functions sharing a name. Low
risk: the flattened output must stay byte-identical, which is a cheap test.

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

---

## Sequencing

| | Finding | Risk | Effort | Note |
|---|---|---|---|---|
| 1 | A3 `quote_report.json` | very low | small | pure win, no consumer behaviour change |
| 2 | B2 frontmatter | low | small | live correctness bug; **prerequisite for A1** |
| 3 | A2 `find_scenes_section` | medium | medium | 4 call sites; needs the loosest-rule ruling |
| 4 | B1 `parse_vtt` | low | medium | 6 call sites, byte-identical gate |
| 5 | A1 party roster | medium | large | own doc; 6 campaign migrations + conflict rulings |

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
