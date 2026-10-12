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
implemented on this branch (see [Prototype 1](#prototype-1--presence-candidates-and-the-knowledge-horizon)).

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
dossiers (27 for Out of the Abyss, 41 for Obelisk). Its sync script copies each
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
dossier**. Sylvira qualifies. **Ilvara and Vizeran do not** (Ilvara appears in
10 summaries but has no published dossier; Vizeran appears in none). They stay
in this document as design cases.

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
present / mentioned / unsure; code builds the horizon from the ruling.

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
| 1 | **Presence candidates and the knowledge horizon** | no | For an NPC with a published dossier: which scenes, prose paragraphs, moments and entries name them, what evidence each carries, and, given the GM's presence ruling, what the NPC had witnessed by chapter N |
| 2 | Consistency checks | no | An NPC acting after their death chapter; a name confusion matching a known `transcript_corrections` pair |
| 3 | Leak test | no (scoring) | Given an NPC's horizon at chapter N and a candidate line, does the line use something outside the horizon? First case: Sylvira and her son |
| 4 | Backtest | yes | Freeze at chapter N, ask the agent what the NPC does at their next appearance, compare with what happened. Scored by leaks (code) and the GM's blind ranking |
| 5 | Forward turn | yes | Between sessions, propose off-screen moves under the GM's written rules; each move checked against guardrail fail states, then ratified or rejected by the GM |
| 6 | Preference record | no | The GM's approve/reject on proposed moves, kept as preference pairs |

Prototypes 4 and 5 need GM prep (hidden state), which for most NPCs is private.
They run against `campaigns`, not `campaigns-public`.

## Prototype 1 — presence candidates and the knowledge horizon

Implemented in `pipelines/npc_agent/` as the `npc_agent` console script. No
model call (AST-guarded in `tests/test_npc_agent_no_llm.py`). Nothing is written
outside the output directory; the GM's ruling file is read, never written.

### Items

From each summary in the public layout:

| Item | Id | Level | Text |
|---|---|---|---|
| scene | `NNN.SS` (declared, or by position, verified above) | scene | the scene's own heading, `####` headline and bullets |
| prose | `NNN.pK` | chapter | the K-th paragraph of `## Summary` |
| moment | `NNN.mK` | chapter | the K-th block of `## Memorable Moments` (cut the way `npc-link` cuts them) |
| entry | `NNN.eK` | chapter | the K-th `## NPCs` observation whose heading is one of the NPC's forms |

An item is a candidate when one of the NPC's name forms (the dossier's
`aliases_used`) appears in it, by `npc-link`'s rules, reused from its own
code rather than restated:

- **Exact, case-sensitive, word-bounded**, through `npc_forms`' compiled pattern.
- **One matcher over every published NPC's forms, longest first.** `Manshoon`
  inside `— Manshoon (Simulacrum)` belongs to the Simulacrum's dossier.
- **A form owned by two NPCs is ambiguous and withheld.**
- **A single word in `npc-link`'s word list is generic and withheld** unless
  `canon.yaml link_rulings` says `safe`. The published layout carries no
  `canon.yaml`, so `--canon` takes one (Out of the Abyss rules `Stool` and
  `Spanner` safe; Obelisk has none, so `Droop`, `Thistle`, `Tuck` and `Wick`
  stay withheld, as they were for `npc-link`).
- An NPC's own `## NPCs` observation is theirs by its heading, whatever the
  form's status.

Each candidate carries its **signals**:

- `quoted`: a quote in the item is attributed to the NPC (`> — <form>`)
- `headline`: the NPC is named in a scene's `####` headline (the GM's recap)
- `named`: the NPC is named anywhere else

Signals are evidence for the GM's ruling. None of them marks an item present.

### Check against the published dossier

The candidate list is checked against the dossier's own frontmatter, written
by `npc-link` from the private copy:

- the set of `chapters` must match exactly;
- the number of moments and of the NPC's own entries must match exactly;
- the dossier's scene count may exceed the scene candidates here only by
  scenes in chapters where a prose candidate names the NPC (the refactor's
  heuristic placed that prose under one of them), and every scene the dossier
  body cites must be one of those two.

A mismatch is reported, never repaired, and the run exits 3.

**Result on the published data:** all **68** published dossiers check out
(27 Out of the Abyss with its `canon.yaml`, 41 Obelisk). Two mismatch kinds
turned up on the way and became rules above: per-NPC matching (Manshoon picked
up a Simulacrum quote) and generic words (the four Obelisk names). Without
`--canon`, Out of the Abyss reports `Stool` and `Spanner` as withheld and
mismatched, which is the expected answer.

Sylvira, for scale: 75 candidates (19 scenes, 23 prose paragraphs, 8 moments,
25 entries, 7 of them her own). Only 2 carry a `quoted` signal and 2 a
`headline` one; the other 70 name her in passing. That is the ruling burden for
one NPC, and why it belongs in a review artifact rather than chat.

### Usage

```bash
npc_agent candidates --campaign-dir ~/campaigns-public/out-of-the-abyss \
    --canon ~/campaigns/out-of-the-abyss/docs/summary_native/canon.yaml \
    --npc "Sylvira Savikas" --out-dir /tmp/p1
#  → sylvira-savikas.candidates.{md,json}, check_report.md, presence.template.yaml

# The GM copies presence.template.yaml, rules what they can, then:
npc_agent horizon --campaign-dir ~/campaigns-public/out-of-the-abyss \
    --npc "Sylvira Savikas" --chapter 67 --rulings presence.yaml
```

### The ruling file

GM-authored YAML. The tool writes a template beside its report and never
touches the real file.

```yaml
version: 1
npcs:
  Sylvira Savikas:
    "061.05": present
    "061.p07": present
    "058.05": mentioned
    "063.05": unsure
```

Values are `present`, `mentioned` or `unsure`. An unknown NPC, an item id that
is not a candidate, or any other value is refused.

### The horizon

`npc_agent horizon --npc NAME --chapter N` lists, for chapters up to N:

- **witnessed**: items ruled `present`, with their text and citation;
- **mentioned only**: items ruled `mentioned` (things that happened *about*
  the NPC, which they may not know);
- **unruled or unsure**: candidates with no ruling, or ruled `unsure`, kept
  separate so nothing is guessed;
- the NPC's **first and last chapter** in the corpus.

An NPC's knowledge includes more than what they witnessed (what they were
told), and less than the whole scene (they may have left). Prototype 1 does not
claim either; it gives the leak test (Prototype 3) a cited, GM-ruled floor to
work from.

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
- Whether Ilvara should get a published dossier, since she is the only NPC with
  a complete, closed arc to backtest against.
