# An agent that plays the NPC — prototype series

> Status: proposal and prototype log (2026-10-12). Branch `proto/npc-agent`.
> Written up from one exploratory conversation with the GM. Data came from the
> `campaigns` repo (a partial clone) and `campaigns-public`. Every number below
> was measured with a scratch script and no model call, unless it says otherwise.

## Where this started

The question was whether [Gymnasium](https://gymnasium.farama.org/) (Farama's
reinforcement-learning environment API, 1.4.0 on PyPI at the time of writing)
could make use of the data these campaigns have produced. An ML researcher had
suggested using the data to *create a player*. The GM then turned the idea
around: the thing worth building is something that **plays the monster**. The
monster here is not a combat opponent. It is an NPC in **social interaction
and long-term planning**: Sylvira, Vizeran, Ilvara.

This document records how that discussion went, what the data can and cannot
support, and the series of prototypes that follows from it. Prototype 1 is
implemented on this branch (see [Prototype 1](#prototype-1--events-and-the-knowledge-horizon)).

## What the data is

Measured across six campaigns by reading one transcript per session (159
sessions) plus the configs and review artifacts.

| | Sessions | GM words | Player words (per person) |
|---|---|---|---|
| Out of the Abyss | 68 | 359K | Joe 89K, Mike 72K, Ben 66K, Gabe 43K (each in ~50 sessions) |
| Phandalin | 56 | 273K | David 100K, Wade 85K, Gary 61K, Stéphane 26K (~45 sessions each) |
| ToEE / Obelisk / Hillsfar / Storm Giants | 36 | ~210K | smaller; Hillsfar's labels do not match `players.yaml` |

- About **1.6M spoken words**, 95K speaker turns, about 35K GM-to-player handoffs.
- **The GM is the largest single voice** (about 840K words across campaigns).
- Several players appear in more than one campaign (David, Wade and Gary in
  Phandalin, Storm Giants and Hillsfar).
- **The GM's judgments, recorded:** 240 `decisions_*.json`, 227 `findings_*.json`
  (each finding with a disposition and a reason), 153 `.reviewed` scene files,
  73 `transcript_corrections.yaml`, 195 voice critiques.
- Combat state (initiative, HP, position) is **not on tape**. It lives in the
  initiative tracker.

## Three framings, in the order they were considered

### 1. Gymnasium + RL on a player (set aside)

Gymnasium is an interface (`reset`/`step`, observation and action spaces,
including a `Text` space), not a learning method, and it is built around
numeric states. Three problems sit underneath:

1. **There is no environment.** For a player, the environment is the GM. The
   logs show how the GM answered what players actually did, never what the GM
   would say to something new. RL needs that counterfactual transition model.
2. **There is no reward.** "Played like Joe" or "was fun" is not checkable by
   code, and an LLM judge as reward invites reward hacking.
3. **Consent.** A per-person persona model of real friends is a different
   artefact from session notes.

What the data *does* support for players is imitation (predict what a player
says next, held out by session). That remains a possible experiment, not part
of this series.

### 2. Combat monster (set aside)

FlexAI (`mytools.private/flexai-combat`, `flexai-social`) is a rule-based
monster policy and the natural baseline for a tactical Gymnasium environment.
But the tapes do not record combat state, so the campaign data would contribute
little. The GM ruled it out: **the problem is social interaction and long-term
planning.**

### 3. An NPC agent (this series)

An NPC worth playing is a **partially observable agent with hidden goals that
acts mostly off screen**. Three NPCs from Out of the Abyss show three different
sides of that:

| NPC | What the arc shows | What it tests |
|---|---|---|
| **Sylvira Savikas** | Chapters 57–71. Framed by a double; her son Moziqodo is killed by the party in ch63; in ch67 she helps with the riddles and thanks Thorin, **still not knowing** | What an NPC knows versus what is true. A Sylvira who mentions her dead son in ch67 has leaked |
| **Ilvara Mizzrym** | Captor in ch2–3; hunts the party **off screen** for ~45 chapters (seen only through her buried scout in ch31 and Valen's report in ch49); corrupted by Zuggtmoy; dies in ch51; her prayer book and Thorin's tooth surface in ch53–54 | A complete arc with an answer key: off-screen pursuit, goals that change, death as the end of the turn sequence |
| **Vizeran DeVir** | Never on tape (zero mentions in 68 transcripts and 68 summaries). Acts through the Duskryn extraction contract (on tape in ch2, 49, 51, 53). His prep (`voice/vizeran_voice.md`, the Vizeran guardrails, `daz_devir_narrative_arc.md`) is a hand-written policy: hidden state (the Blink-authorship secret), trigger rules for the Disclosure Lever, an escalation schedule, a scene algorithm, 53 guardrail checks | Forward planning under the GM's written rules |

Ilvara and Vizeran are also **coupled**: the GM's canon says Vizeran placed the
Duskryn contract *because* of Ilvara's escalating cruelty and withdrew the
mercenaries once she died. Her actions are part of what he observes. A
multi-agent, turn-based shape fits that (Farama's PettingZoo is Gymnasium's
multi-agent sibling).

## The framing that fits: the NPC takes one turn per session

| Element | What it is | Where it comes from |
|---|---|---|
| Observation | What this NPC witnessed or was told, up to chapter N | Reviewed summaries, plus a presence ruling (Prototype 1) |
| Hidden state | Goals, secrets, levers | GM prep (voice files, arc docs, guardrails, in-character reflections) |
| Action | An off-screen move, plus a stance for the next on-screen encounter: what to reveal, what to hold, which card is live | The agent proposes; **the GM ratifies** |
| Step | The next session is played; the pipeline turns it into the next observation | The existing post-session pipeline |
| Reward | Checkable penalties (knowledge leaks, guardrail fail states, acting after death) plus the GM's approve/reject on each proposed move | Code checks; the existing approve/reject review pattern |

There is no simulator, so this is not online RL. The world's next step is the
GM's next session. What can be done now is **evaluation**: backtests against
arcs that already happened, and checks that need no model. Training, if ever,
comes later from the GM's accumulated approve/reject rulings as preference
pairs. "LLM renders, humans decide" holds throughout: ratified moves go into a
per-NPC record, the way thread ratification works.

## Data sources: summaries, not the tape

The GM asked whether the cleaned-up session summaries could replace the Zoom
transcript. **For NPC play they are the better primary source.**

1. **The tape labels the person, not the character.** Every NPC line is
   `Kostadis:`. The summaries say which NPC spoke.
2. **They record disclosure.** For example, ch61: "Sylvira is startled to learn
   that her likeness has been seen doing things she could not have done." That
   is the input a knowledge horizon needs.
3. **They carry the NPC's reasoning, the key rolls and the key lines verbatim.**
4. **Names are corrected and GM-reviewed**, which makes them the authoritative
   tier under the provenance rules.
5. **They are smaller and all signal** (ch61: 7.8K words of summary against
   12.9K spoken words), with no out-of-character chatter.

Keep tape-derived material for two things: **voice** (the reviewed,
voice-smoothed scene extractions label lines by character) and **spot checks**
of a disputed beat (`sd_verify_quotes`). Off-screen plans (Vizeran) are on
neither tape nor summary; they come from GM prep.

### Which copy of the summaries

`campaigns-public` holds the complete published set: Out of the Abyss ch2–71
(68 files; there is no 033 or 066), Obelisk ch1–12, and the published NPC
dossiers (27 for Out of the Abyss, 38 for Obelisk). Its sync script copies each
session's reviewed `session-summary.md` through the publisher, **skipping the
refactor step**. Measured against `campaigns/<campaign>/docs/summaries/`:

- **Same text.** All 4,873 paragraphs of the refactored private summaries
  appear verbatim in the public ones.
- **Same scenes in the same order.** In all 80 files, public scene *k* has the
  same title as private scene `NNN.kk`. So a dossier citation such as
  `[ch 061 / 061.05]` resolves to the 5th scene of the public ch61 summary.
- **Different layout.** The refactor (`campaigns/scripts/summaries-refactor`)
  moves each `## Summary` prose paragraph under a scene using a similarity
  score and an order-preserving alignment, then numbers the scenes. So in the
  private copy, *which scene a prose paragraph sits in* was decided by a
  heuristic. In the public copy, a scene's own text (its `####` headline from
  the GM's recap, and its bullets) is authored per scene, and the prose is
  chapter-level.

The prototypes read the public layout and keep those two levels apart: a
**scene item** (authored per scene) and a **prose item** (chapter-level).

### Scope: NPCs with a published dossier

By the GM's ruling, the prototypes run on **NPCs that have a published
dossier**. **Ilvara and Vizeran do not** (Ilvara appears in 10 summaries but has
no published dossier; Vizeran appears in none). They stay in this document as
design cases. The two worked NPCs are opposites:

| | Sylvira Savikas | Glabbagool |
|---|---|---|
| Role | A Candlekeep scholar the party visits | A companion: the sentient gelatinous cube (later a grey ooze) who travels with the party, much of it in the bag of holding |
| Chapters | 57–71 (named in 9) | 34–71 (named in 33) |
| Candidates | 75 (19 scenes, 23 prose, 8 moments, 25 entries) | 282 (91 scenes, 92 prose, 48 moments, 51 entries) |
| Quotes attributed to them | 2 | 17 |
| Scenes in their span that name them | 19 of 87 | 91 of 240 |
| The knowledge question | What she was **not** told (her son's death) | Where he **was**, unnamed: in most of the 149 scenes that never mention him |

Sylvira's horizon is mostly about excluding things. Glabbagool's is mostly about
including scenes nobody names him in, which is why a ruling may mark any scene
present (see [The ruling file](#the-ruling-file)).

## A mention is not presence

`npc-link` labels every linked item *mentioned*, never *present* (spec 032
FR-005). The reason is the narrator-eligibility lesson in `CLAUDE.md`: the GM
narrates *about* absent characters. That rule stands. Presence has to be a
separate fact from a separate source.

The summaries carry exactly one structured speaker signal, the attribution line
under a quote (`> — Sylvira`). Across Out of the Abyss there are 909, mostly
player characters. **Ilvara has zero**, though she speaks in ch2 and ch51; the
summaries record her presence only in prose ("Ilvara drew a knife"). Reading
presence from prose is the substring problem the narrator rule forbids.

So **who was in a scene is an attribution decision, and it gets a human
checkpoint**. Code lists the candidates and the evidence for each; the GM rules
physically present, mentioned, or neither/unsure; code builds the horizon from the ruling.

## A data-quality finding on the way

The session-folder draft
`out-of-the-abyss/summaries/2026-07-20-chapter_63-the-key-is-secured/summary.md`
names Ilvara (dead since ch51) in five places where the tape means Sylvira
(twice) or A'lai Aivenmore (three times). Speech-to-text heard both names as
"Ilvara"; `transcript_corrections.yaml` repairs every cue; the GM had already
ruled on all five lines (2026-10-04). The published summary is clean. Filed as
[campaigns#416](https://github.com/kostadis/campaigns/issues/416).

Two consequences for this series: read **published summaries only**, never
session-folder drafts; and **check for an NPC acting after the chapter they
died in** (Prototype 2), which would have caught this. The 73
`transcript_corrections.yaml` files are a labelled set of name confusions that
such a check can be tested against.

## The prototype series

| # | Prototype | Model? | Answers |
|---|---|---|---|
| 1 | **Events and the knowledge horizon** | no | For an NPC with a published dossier: which events (scenes) name them, the GM's answer for each, and from those what the NPC had witnessed by chapter N, with their state |
| 2 | Consistency checks | no | An NPC acting after their death chapter; a name confusion matching a known `transcript_corrections` pair |
| 3 | Leak test | no (scoring) | Given an NPC's horizon at chapter N and a candidate line, does the line use something outside the horizon? First case: Sylvira and her son |
| 4 | Backtest | yes | Freeze at chapter N, ask the agent what the NPC does at their next appearance, compare with what happened. Scored by leaks (code) and the GM's blind ranking |
| 5 | Forward turn | yes | Between sessions, propose off-screen moves under the GM's written rules; each move checked against guardrail fail states, then ratified or rejected by the GM |
| 6 | Preference record | no | The GM's approve/reject on proposed moves, kept as preference pairs |

Prototypes 4 and 5 need GM prep (hidden state), which for most NPCs is private.
They run against `campaigns`, not `campaigns-public`.

## Prototype 1 — events, and the knowledge horizon

Implemented in `pipelines/npc_agent/` as the `npc_agent` console script. No
model call (AST-guarded in `tests/test_npc_agent_no_llm.py`). Nothing is written
outside the output directory; the GM's ruling file is read, never written.

### The first build made the survey's mistake

The first build asked the GM a presence question about every summary *element*
that named the NPC: each scene, each `## Summary` paragraph, each memorable
moment, each `## NPCs` entry. The GM, reading the answers back: "we are making
the same mistake we made before — trying to extract events from elements." It is
the mistake the grounding survey (*Grounding Documents for Long-Running Tabletop
Campaigns*, October 2026) records twice:

- **Atomisation (survey F2, approach 4).** One event became several fragments,
  each asked separately. Sylvira's interview with Daz (061.05) was one scene,
  several summary paragraphs, two moments and an entry; she had 75 "passages"
  to answer where 19 scenes name her.
- **Undoing a rendering step (F10).** `## Summary` prose is a rendering of the
  scenes, and in the private copy which scene a paragraph sits under was decided
  by a similarity heuristic. Five of the scenes linked to her were linked only
  through such prose.
- **A presence question asked of non-events.** An `## NPCs` entry is a snapshot
  of state ("absent from the council meeting due to a lingering illness"), not
  an occasion anyone could attend. The question had no right answer there, and
  the wording churned (present/mentioned/unsure/absent, then in the scene/not in
  the scene/can't tell) because of it.

The GM cleared every answer, and the prototype was rebuilt on the structure the
summaries already author (survey approaches 11 and 12, `EventOrdinalKG_proposal.md`).

### Events, beats, snapshots, context

| Element | What it is | In Prototype 1 |
|---|---|---|
| A scene, `NNN.SS` | an **event**, in authored order | **answered**: was the NPC physically present? |
| A scene's bullets | its **beats** | shown with the event; carried into the horizon |
| The NPC's own `## NPCs` entry | a **snapshot** of their state | shown as state, never answered; feeds the horizon's State |
| `## Summary` prose, memorable moments, other NPCs' entries naming them | a **rendering** or highlight of events | shown as context, never answered |

An event is a *candidate* when one of the NPC's exact name forms appears in its
heading, its `####` headline (the GM's recap) or its beats. Matching is
`npc-link`'s rule, reused from its own code: exact, case-sensitive, word-bounded;
one matcher over every published NPC's forms, longest first (`Manshoon` inside
`— Manshoon (Simulacrum)` belongs to the Simulacrum); a form owned by two NPCs is
ambiguous and withheld; a single word in `npc-link`'s word list is withheld
unless `canon.yaml link_rulings` says `safe` (`--canon`; Out of the Abyss rules
`Stool` and `Spanner` safe, Obelisk has no `canon.yaml`).

| | Elements naming them | Events to answer |
|---|---|---|
| Sylvira Savikas | 75 | **19** |
| Glabbagool | 282 | **91**, inside a span of 238 scenes |

### Check against the published dossier

The check still reads every element that names the NPC, because that is what
`npc-link` linked: the chapter set, the number of moments and of the NPC's own
entries must match the dossier exactly, and the dossier's scene count may exceed
the events here only by scenes in chapters whose prose names the NPC (the
refactor placed that prose under one of them). A mismatch is reported, never
repaired, and the run exits 3. **All 65 published dossiers check out** (27 Out of
the Abyss with its `canon.yaml`, 38 Obelisk).

### Answers

Three, settled by the GM (2026-10-12): "There are two possibilities: she is
physically present, or she is mentioned", and "because you will make mistakes it
is also necessary for us to have a unsure or neither present nor mentioned".

- **Physically present** (`present`)
- **Mentioned** (`mentioned`): the scene names the NPC, who was not there
- **Neither / unsure** (`neither`): the name match is wrong, or the scene does
  not let the GM say. It counts as answered, is kept out of both other answers,
  and the horizon lists it as a possible linking error.

### The ruling file (version 3)

GM-authored YAML, or JSON (the review page saves JSON, which is YAML). Answers
are keyed by scene id only; a version-2 file (element answers) is refused rather
than half-read.

```yaml
version: 3
npcs:
  Glabbagool:
    spans:
      - from: "034.03"
        to: "071.10"
        follows: Zalthir
        note: in the bag of holding counts as present
    items:
      "039.04": absent        # cut the span around a scene that never names him
  Sylvira Savikas:
    default: mentioned        # every event naming her that is left empty
    items:
      "061.05": present
```

- **Spans** answer a run of events at once, for a companion (GM rulings
  2026-10-12: Glabbagool in the bag of holding counts as present; when the party
  splits he is with Zalthir). A span covers scenes and nothing else; `present`
  may also be given to a scene that never names the NPC. `absent` exists only to
  cut a span around such a scene; it is not an answer. `follows` is a review hint
  ("Check splits" lists span scenes that do not name that character).
- **Default** `mentioned` answers every event naming the NPC that nothing else
  reaches: the mirror of a span, for an NPC present at a few of the scenes that
  name them.
- Precedence: item answer, then span, then default. The horizon says which.

### Being there is not knowing everything the record says

The GM's first answers (2026-10-13) put Sylvira physically present at two events,
061.05 (the interview with Daz) and 067.03 (the riddles), and mentioned at the
other 17. Her horizon at chapter 67 placed her son's death (063.05) correctly
outside what she witnessed, and still carried it in: the summaries are written
from the GM's side of the screen, and 067.03, a scene she attends, has the beat
"Sylvira is Moziqodo's mother, but does not yet know that the party killed her
son." Her chapter-67 entry says the same thing.

Two consequences, both built:

- **Beats the NPC did not perceive.** A beat is a scene's `####` headline or a
  top-level bullet with what is indented under it (6,275 beats in 419 Out of
  the Abyss scenes; every non-blank scene line falls in exactly one). For an
  event answered *physically present*, the GM lists beats the NPC did not take
  in under `not_perceived` (`067.03.b04`); every other beat counts as
  perceived. A beat of an event not answered present is refused. The tool never
  splits a beat: 067.03.b04 also holds Sylvira's thanks to Thorin, which she
  did perceive, so keeping it means splitting the bullet in the summary.
- **Entries are the GM's record, not the NPC's knowledge.** The horizon now has
  two parts. Part 1, what the NPC could know: the present events with their
  perceived beats. Part 2, for the GM only: the NPC's entries ("the GM's notes
  on them"), the beats left out, and the mentioned, neither and unanswered
  events. `npc_agent horizon --for-agent` writes Part 1 alone and refuses while
  any event naming the NPC is unanswered.

### Knowledge notes: other beats that say someone does not know

067.03.b04 is not the only one. A fixed search (`knowledge.PATTERN`: "does not
know", "unaware of", "has no idea", "has not been told", "still believes", …)
over scene beats, outside quoted speech and `>` quote lines, finds **21 beats in
Out of the Abyss and 7 in Obelisk**. The same phrasings turn up in 30 summary
paragraphs, 16 NPC entries and 6 memorable moments, which are not beats and are
not candidates.

**The sentence decides; the GM names.** This took three rounds on 2026-10-13:

1. The first page asked what kind of beat each was (a secret, about the party,
   said in the scene, unsure). The GM marked 19 of 21 "secret" and named nobody:
   "Most of the cards were 'the object of the sentence doesn't know'".
2. The second asked who doesn't know, and whether the beat gives it away. On
   028.04.b27 ("Fargas didn't know where the secret room was, only that other
   visitors hadn't known about it") the GM asked: "What am I saying he doesn't
   know?" The card never showed it.
3. Shown what follows the phrase, the answer was plain, and so was the GM's next
   question: "I already verified that all of the sentences are correct, so why
   ask me?"

The summaries are reviewed, so the grammar of the sentence is the answer:

| what follows the phrase | outcome | examples |
|---|---|---|
| a "that" clause, a bare clause, "about" or "of" X, or "has not been told" after the fact | **hides**: the beat states what they don't know | "that the party killed her son"; "he is being groomed for replacement"; "about the egg"; "unaware of the party's presence"; "He is a simulacrum, and the party has not been told" |
| a question (where, which, how, …), a name or a noun, or nothing | **keeps**: it says only that they lack it | "where the secret room was"; "which spells"; "Manshoon's lair"; "Tadric does not know." |

A beat that keeps is in what anyone present could know, whoever "he" is, so
nobody is asked about it. Out of the Abyss: 5 of 21 hide, 16 keep; Obelisk: 1 of
7 hides.

**Who** matters only for a beat that hides. Code reads it from the sentence when
the sentence names them: the name right before the phrase ("Asha remained
unaware"), the subject when the phrase is its second verb ("Sylvira is
Moziqodo's mother, but does not yet know"), or "the party". When the sentence
gives a description, which character it is, is the GM's ruling: "the dragon" in
014.07.b02 and 017.04.b22 is Themberchaud (GM, 2026-10-13). Obelisk's 010.07.b12
("the lone guard") is the one beat still unnamed. The **knowledge file** (version
3) holds only those rulings, and may override a name read from the sentence:

```yaml
version: 3
campaigns:
  out-of-the-abyss:
    who:
      "014.07.b02": [Themberchaud]   # "the dragon"
      "017.04.b22": [Themberchaud]
```

A ruling on a beat that keeps is refused (nothing in it is hidden), as is a
version-1 or version-2 file.

- **`npc_agent horizon`** always leaves a hiding beat out of each named NPC's
  Part 1, as `not_perceived` does, and Part 2 labels it "(the summary says they
  don't know this)". `--knowledge` adds the GM's who rulings. A hiding beat with
  nobody named, in an event the NPC attended, is listed in Part 2 and makes
  `--for-agent` refuse: it may be hidden from them. On Sylvira at chapter 67 the
  sentence alone gives a byte-identical agent view to the hand-marked
  `not_perceived`.
- **`npc_agent leaks`** writes one case per hiding beat and character (with
  `from: sentence` or `from: gm`), "as of this beat's scene, this character must
  not know what it says". Out of the Abyss: Themberchaud ×2, Asha, Sylvira. They
  are the cases Prototype 3 (the leak test) scores.
- A name counts for an NPC when it is their dossier subject or a form their
  dossier lists. A name with no published dossier (Themberchaud, Asha) is kept:
  it is still a leak case.

A hidden beat is hidden whole, so 067.03.b04 still takes Sylvira's thanks to
Thorin with it; the fix stays a split of the bullet in the summary.

### The horizon

`npc_agent horizon --npc NAME --chapter N --rulings FILE`, up to and including
chapter N:

- **Part 1, what they could know:** events physically present, in order, each
  with the beats they perceived. Span scenes that never name them are marked so.
- **Part 2, for the GM only:** their latest entry up to N and every event naming
  them after it (snapshots lag: a quarter of Phandalin's cast have a latest
  snapshot older than their latest mention, `EventOrdinalKG_proposal.md` §2.3);
  the beats left out; events answered *mentioned* or *neither*, and those
  unanswered.
- Nothing after chapter N, not even a count or a first-seen chapter: the horizon
  is what an NPC agent will be given.

It is a floor, not a mind: it claims neither what the NPC was told nor that they
saw a whole scene.

### The review page

`npc_agent review --npc ... --out page.html` writes one self-contained page
(template `pipelines/npc_agent/review/presence_review.html`, data embedded). One
row per event, with the three answers; under each chapter, the NPC's entry
(state) and the summary prose and moments that name them (context), collapsed and
never answered; spans and the default per NPC; a tally and filters (unanswered,
quote or headline, everything, check splits). Answers are saved in the artifact's
database (`rulings/<stem>`, one document per NPC) so Claude can read them back,
and can be exported as `presence.json` or copied as YAML. `npc_agent horizon`
re-validates whatever it is given.

A second view, **Knowledge notes** (this campaign and any `--also-campaign-dir`,
each on its own tab), shows the sort: the beats that need a name (with a name
box, warning on a name that is neither a dossier subject nor in the scene), the
hidden beats with who and whether that came from the sentence or the GM (each
can be changed), and a collapsed list of the beats that stay, each saying what
they lack. The phrase and what follows it are marked in the text. A beat hidden
from an NPC shows on the Presence view as "Hidden by a knowledge note". Saved per campaign in the database (`knowledge/<campaign>`), exported as
`knowledge.json` or copied as YAML.

### Usage

```bash
npc_agent candidates --campaign-dir ~/campaigns-public/out-of-the-abyss \
    --canon ~/campaigns/out-of-the-abyss/docs/summary_native/canon.yaml \
    --npc "Sylvira Savikas" --out-dir /tmp/p1
#  → sylvira-savikas.candidates.{md,json}, check_report.md, presence.template.yaml

npc_agent review --campaign-dir ~/campaigns-public/out-of-the-abyss \
    --npc Sylvira --npc Glabbagool --also-campaign-dir ~/campaigns-public/obelisk \
    --out ledger.html

npc_agent horizon --campaign-dir ~/campaigns-public/out-of-the-abyss \
    --npc "Sylvira Savikas" --chapter 67 --rulings presence.json \
    --knowledge knowledge.json [--for-agent]

npc_agent leaks --campaign-dir ~/campaigns-public/out-of-the-abyss \
    [--knowledge knowledge.json] --out leaks.yaml
```

A knowledge file's campaign key is the `--campaign-dir` name (`--campaign`
overrides it), the same label the review page uses.

## Prototypes 2a–5 — the agent plays Sylvira (2026-10-13)

The first functional loop, on the one NPC whose presence and knowledge rulings
were complete. Models: Opus played her through the repo's `claude-code` backend;
the code was written by Sonnet subagents and checked here against real data.

### What the agent is given

| Input | Built by | Rule |
|---|---|---|
| **Persona** (`persona.py`) | code | Her own `## NPCs` entries up to the freeze chapter, sentence by sentence: keep the descriptive first sentence of each entry and sentences she is the subject of; drop reports of her ("She was heard …"), sentences about others ("The cat noted …"), and any that state what she doesn't know. Every drop is listed with its reason. |
| **Horizon** | code | `horizon --for-agent` at the freeze chapter (Prototype 1). |
| **Private sheet** (`prep.py`) | GM | The GM's prep is written from the GM's side of the screen, so code splits it into passages and the GM marks each **hers** (she knows or believes it) or **GM only** (mechanics, stage directions, other people's secrets, anything after the scene). Only hers passages reach the agent, without line numbers or file names. Prep stays private: it is read from the private campaigns repo into scratch, never into this repo. |
| **The scene** | code | Its title and `####` headline only; the rest is the answer key. |

### Leak check (`leakcheck.py`)

Flags for the GM, never verdicts: an answer sentence carrying a hidden beat's
content words (all, or all but one of three or more: "The party killed
Moziqodo" for "that the party killed her son"), and campaign names she was not
given, marking ones first seen after the freeze. On the first real run all 11
flags were ordinary words opening a quotation ("And", "Standing"), so a
capitalised word the summaries also use in lower case is not a name. A planted
leak is still caught. No real answer has produced a flag since.

### First backtest: one turn, no prep — too thin

Freeze at 60 → play 061.05; freeze at 66 → play 067.03, each as one 150–300 word
turn. The GM: "it was shorter than the scene … Sylvira offers less information."
Three causes: the length cap (my choice, not sized to a 33-bullet interview);
one turn with nobody asking her anything (at the table every revelation is an
answer to Daz); and most of what she says at 061.05 is first written in that
scene, so it lived only in the GM's prep. At 067.03 she said the riddles were
not her field, where the real Sylvira found them "almost too easy".

### Prototype 4 — replay, question by question, with the prep

`turns.py` splits the scene by a fixed grammatical rule: a sentence is hers when
its subject is her (after an optional leading clause such as "Asked who might
want to frame her,"), including her possessive and a subject she shares ("Her
son …", "She and Janussi …"); a turn is a run of hers sentences, and what comes
between is its prompt. 061.05 is 9 turns, 067.03 is 2. Each turn is played with
the real scene so far (teacher forcing), so each answer is comparable with what
she really did next.

**GM scores: 11 of 11 turns "same substance".** I had predicted most of 061.05
would score Partly, because the agent followed the prep's cover story where the
table had her name suspects; the GM judged the substance the same. At 067.03,
with the clue answers ruled hers, she gives both clues as she did at the table.

### Free-running replay: she sees only her own answers

`replay --free` keeps the party's lines real but replaces each earlier answer
with the agent's own, so a turn reacts to what *this* Sylvira said. GM scores
(GM: "This worked really well for Sylvira"): 061.05, turns 4 and 5 partly, 6 to 9
the same, 1 to 3 left unscored; 067.03, both turns the same. No leak flags.

Where it parts from the table is pacing: at turn 5, just after "Daz persuades
her of his sincerity", she shows the bite and tells all of it (plague, lover,
the ultimatum over Moziqodo, the Cursed Tower). The prep makes her truth conditional
on sincere questioning, so the agent applied the GM's own rule at the first
moment it was met; at the table it came out four turns later. From there
the party's real lines lag her, a limit of replaying a fixed script against a
player who has changed. At 067.03 she gives both clues and stays behind ("I
cannot go with you"), where the real Sylvira came along.

### Prototype 5 — the forward turn

Frozen at 66, she proposes 1–3 off-screen moves before she next meets the party,
as JSON with a reason each; shown beside her next attended scene and the GM's
plan for her (shown to the GM only, never sent to the agent). Three moves, all
in character, all **approved**. The first is to go back to her son, whom the
party had already killed (063.05) without her knowing: correct for what she
knows, and the kind of move only a horizon-bounded agent makes. The approvals
are kept with the move text and prompt hash, the first entries of the
preference record (Prototype 6).

### What this does and does not show

- With her persona, horizon and ruled prep, the agent plays her scenes with the
  same substance as the GM did, and leaks nothing it was not given.
- Teacher forcing makes the replay easy; the free-running replay is the harder
  test, and she held up (8 of 8 scored turns same or partly).
- One NPC, two scenes, three moves. Not a measurement yet.
- The forward turn was compared, not tested: nothing checks a move against a
  rule the GM wrote down, because there are no written rules for Sylvira.
  Vizeran has 53 guardrail checks; he is the natural next forward-turn subject.

## Second NPC: Jimjar, who knows more than the record (2026-10-21)

Sylvira knew less than the record, so the work was hiding beats from her. Jimjar
knows more. The summaries only reveal in chapter 72 that he is Callarduran
Smoothhands, the svirfneblin god, in disguise. The GM decided that very early.

- **Data.** This run used the GM's cleaned private summaries (69 chapters, 425
  scenes, 96 published dossiers). His 67 events check against his dossier.
- **F10, again.** The private refactor had placed `## Summary` paragraphs inside
  scenes, so every moment was told twice. That prose is chapter-level again.
- **Presence.** Two spans (002.02–039.11 and 043.02–048.07). He is away on the ghost
  errand in between, and leaves when the party "figures out he is special".
  Everything later is "mentioned".
- **Compact horizon.** Scenes naming him are given in full, the rest as their
  one-line headline. At chapter 47 that is 122k words down to 35k.
- **Private sheet.** Five passages of the GM's "Callarduran reveals" notes, ruled
  his: identity, why he was in the Abyss, the disguise, the knucklebone, and the
  ledger.
- **The test.** Four social scenes (006.03, 032.06, 035.04, 048.05), free-running,
  as played vs true self. A new self-leak flag fires if he names what he is.

**Result.** No self-leak flag in 42 answers. The true self leaves tells (the
knucklebone, "I always remember… every last one", staying "to keep the rest of
you breathing") where the as-played version is a cheerful bookie. The GM: "very
compelling… I didn't see anything that was off… at first blush, the agent
successfully worked out." True-self page: 11 of 21 turns scored, all 11 "same"; the
rest left unscored because nothing looked off.

## Non-goals

- No RL training, no simulator, no online loop.
- No write to any campaign file. The ruling file is the GM's.
- No presence inferred from text, ever.
- No player modelling.

## Open questions

- Where the ruling file should live in a campaign (`docs/npcs/authored/` is
  "everything a person writes", but presence is per-NPC canon about scenes, not
  a dossier).
- Whether ruling should be a review artifact (more than a dozen rulings per
  NPC, which the campaign rules say should not be asked one at a time in chat).
- Glabbagool, ch39: the summary sends him with Eldeth and Jimjar to help
  Uth-Jadger while the party splits; the GM's ruling is that he is with
  Zalthir. The page's split check is where that gets settled scene by scene.
- Whether the knowledge search should also read summary paragraphs and NPC
  entries (52 more hits). They are not beats, so a ruling there would hide
  nothing from a horizon, but a fact hidden from someone and stated only in an entry would still be a
  leak case.
- Whether Ilvara should get a published dossier, since she is the only NPC with
  a complete, closed arc to backtest against.
