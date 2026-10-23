# Playing NPCs from the record: what we did, what happened, what it's good for

*A report for friends and fellow researchers. Written 2026-10-23 by Kostadis Roussos
(the GM) with Claude. It covers five NPCs across two campaigns, run between
2026-10-19 and 2026-10-23.*

> **Spoilers.** This report reveals secrets from the GM's *Out of the Abyss* and
> *Phandalin* campaigns, including prep that has **not been played yet**. Please
> don't share it with the players of either campaign.

## The short version

- **The goal.** We built a system in which a language model plays a non-player
  character (NPC) in a long-running tabletop campaign. The model is given only what
  that NPC could know, and the GM scores its answers.
- **The model.** Every NPC was played by a single model call per turn, with
  everything it was allowed to know pasted into the prompt.
- **The NPCs and how they did.** Five NPCs (four people and one magic book) span
  five different relationships between the NPC and the written record, from "knows
  less than the record" to "is an artifact that answers on its pages":
  - **Re-enacting played scenes:** the agent matched what really happened in **22
    of 22 scored turns** (11 for Sylvira, 11 for Jimjar). In a harder mode, where it
    sees only its own earlier answers, it scored 6 the same and 2 partly the same.
  - **Proposing off-screen moves:** **29 of 29 decisions** the GM scored were
    approved, and none were rejected (3 for Sylvira, 6 for Vizeran, 20 for Aletra's
    prep reviews).
  - **Keeping its own secret:** the NPC who is secretly a god never gave himself
    away in 21 answers.
- **The best use isn't re-enacting the past.** It is two things:
  - **between sessions**, working out what an off-screen NPC does next, consistently
    with everything they know;
  - **before a session**, having the NPC critique the GM's prep for them.

  In the second, the NPC caught things the GM hadn't, including a bribe priced from
  before the party became rich, and a dependency on her employer that a thief would
  never accept.
- **The engineering lesson.** Code and the GM decide who was where, who knows what,
  and which prep belongs to whom. The model only writes the character's words inside
  that structure. Every time we let a model or a fuzzy match decide structure, it
  went wrong.

## 1. The question

In a campaign that runs for years, the GM plays every NPC. Combat is easy to
delegate; **social play and long-term planning** are not. Each NPC must act on what
they know and want, and on nothing else, across dozens of sessions. Can a
language-model agent carry some of that load?

It splits into three questions:

1. **What could this NPC know, as of session N?** This is the *knowledge horizon*.
2. **Who is this NPC beyond what the record says?** This is persona and private
   knowledge.
3. **Given exactly that, does the agent play the NPC as the GM would, without using
   anything it shouldn't know?**

The idea came from an ML researcher who suggested using Gymnasium to "create a
player". We set reinforcement learning aside, because there is no simulator of a
session to roll out against, and in social play the reward is the GM's judgement. We
kept the vocabulary, though. The NPC is an agent with a partial observation and
private state. It takes one turn at a time, and the GM ratifies its moves.

## 2. The material

- **Two campaigns, both run by the GM:**
  - *Out of the Abyss*: 72 sessions, ending at the library-fortress of Candlekeep.
  - *Phandalin*: about 59 sessions, now in Neverwinter.
- **Reviewed session summaries.** Each session is recorded, transcribed, corrected
  against a hand-kept corrections file, summarised, and then reviewed by the GM.
  - Every summary has the same shape: numbered scenes (`NNN.SS`), each with a
    one-line headline and bullet points, plus an entry for each NPC who figured in
    the session.
  - *Out of the Abyss* alone has about 420 scenes and 6,300 bullets.
- **The GM's private prep:** session scripts, NPC secrets, reveal plans and
  guardrails. None of this is in the summaries.

We worked from the summaries, not the transcripts. They are the cleanest record, and
their **structure** (scene, bullet, entry) turned out to matter more than their prose.

## 3. How it works

The rule throughout is **"LLM renders, humans decide"**: code or the GM decides scope,
identity and attribution, and the model only writes inside that structure. Exactly one
module calls a model, and an automated check over the source code enforces it. Every
other step is deterministic, and refuses rather than guesses.

### 3.1 What the NPC could know

- **Presence.** A scene that names the NPC is an *event*. The GM answers each event
  with "present", "mentioned" or "neither". Two shortcuts keep this cheap:
  - a **span** for a companion who travels with the party;
  - a **default** for an NPC who is rarely present.
- **The horizon at chapter N** is the events the NPC was present at, in order. Nothing
  after N appears, not even a chapter count, since a later chapter number tells the
  future.
- **Being there isn't knowing everything the record says.** Summaries are written from
  the GM's side of the screen. A scene the NPC attended may say "she does not yet know
  that the party killed her son."
  - A fixed search finds such sentences, and **their grammar decides what is hidden.**
    "Doesn't know that X" hides X; "doesn't know where the room was" hides nothing.
  - The GM is asked only who is meant, and only when the sentence says "the dragon"
    rather than a name. Across the whole campaign that was two questions.

**The first design got this wrong, and a survey we had already done predicted it.** We
first asked the presence question of every piece of text that named the NPC, which came
to 75 questions for one NPC. Earlier work on grounding documents for long campaigns had
named the failure:

- breaking an event into fragments destroys attribution;
- prose is a rendering of the scenes, and you shouldn't parse a rendering back.

Rebuilding on the authored structure (scenes are events, bullets are beats) cut 75
questions to 19.

### 3.2 Who the NPC is, privately

- **Persona:** the NPC's own summary entries up to N, filtered sentence by sentence.
- **Private sheet:** the GM's prep, split into passages. The GM rules each one
  **"hers"** (she knows or believes it) or **"GM only"** (mechanics, other people's
  secrets, later plans), and only "hers" reaches the model.
  - Each passage's id includes a hash of its text, so an edit makes the ruling stale
    instead of silently reattaching it.
  - **A catch we hit twice:** the sheet prints each passage's nearest heading, and a
    heading can itself be a secret ("The Codex is using her"). Headings have to be
    checked too.

### 3.3 Leak check

These are flags for the GM, never verdicts. A sentence in an answer is flagged when:

- it carries the content words of something hidden from the NPC;
- it names someone the NPC was never given (marked "future" if the name first appears
  after N);
- it contains a term from the NPC's *own* secret, such as "god" for the NPC who is
  secretly a god.

The check is tuned to over-flag. Across all the runs every flag was a false positive,
and a deliberately planted leak is still caught.

### 3.4 Five ways to ask

| Mode | What the agent sees | What the GM scores |
|---|---|---|
| **Replay, teacher-forced** | The real scene so far, including the NPC's real earlier answers | Each answer against what happened |
| **Replay, free-running** | The scene so far, with **its own** earlier answers in place of the real ones | The same; this is the harder test |
| **Forward turn** | Everything up to now | 1–3 off-screen moves, each approved or rejected |
| **Reaction** | For an NPC who wasn't there: only what was **reported** to them, and through whom | Their reaction and 1–4 decisions, against the GM's canon (an answer key the model never sees) |
| **Artifact** | For an object that answers on a page: only what was **written into it** | The page its wielder reads, and the purpose it hides from them |

The reaction mode later gained **witnessed** scenes, for an NPC who saw some events
and heard of others, and **withheld beats**, for parts of a reported scene that the
channel couldn't have carried.

Every prompt and answer is saved with a hash of its inputs. Runs are reproducible, and
re-running an unchanged prompt costs nothing.

## 4. The five NPCs

Each NPC tests a different relationship between what the character knows and what the
record says.

### 4.1 Sylvira Savikas: knows less than the record

She is a Candlekeep scholar hiding that a demon she bore is her son. The record often
states things she doesn't know.

| Test | GM's score |
|---|---|
| First backtest, one answer per scene, no prep | Too thin: "Sylvira offers less information." What she reveals isn't in the record before the scene being predicted. |
| Replay, teacher-forced, with prep (2 scenes) | **11 / 11 the same in substance** |
| Replay, free-running | **6 the same, 2 partly**, no leaks. "This worked really well for Sylvira." |
| Forward turn | **3 / 3 moves approved** |

**What it taught us.** The free run confessed her secret at the *first* moment her prep's
condition (sincere questioning) was met. At the table, the GM held it back four turns
longer. Prep says *whether* a secret comes out, not *when*.

### 4.2 Jimjar: knows more than the record

He looks like a svirfneblin gambler. The GM decided very early that he is the god
Callarduran in disguise, and the summaries only reveal it in session 72.

- **The setup.** We played four social scenes in two conditions:
  - **as played**, from the record only;
  - **true self**, the record plus the GM's sheet saying who he is.

  Both were free-running, 21 turns each.
- **He kept his own secret.** In 21 true-self answers there was no self-leak.
- **Knowing who he is changed the surface, not what he revealed.** The true-self
  Jimjar left tells: he fingers his knucklebone, says "I always remember… every last
  one", and follows his debtors to keep them alive. The as-played Jimjar was a cheerful
  bookie.
- **The GM:** "the way he was played by the agent was very compelling… I didn't see
  anything that was off." He scored **11 of 21 turns, all 11 the same**, and left the
  rest unscored because nothing looked wrong.

### 4.3 Vizeran: never present, learns by report

He is an exiled drow archmage who is never at the table. The GM ruled which scenes
reached him and through which channel (a chain of cutouts).

- **Three moments:** a noble house's attempt on the protagonist's life, the protagonist
  learning who he is at Candlekeep, and his plans for the protagonist's return.
- **Score:** in character and on canon wherever scored, no guardrail broken, **6
  decisions approved and none rejected.**
- **It went beyond canon.** He noticed his mercenaries knew more than his contract had
  told them ("a cutout who knows is not a cutout; it is a door") and decided to audit
  his own chain. The GM hadn't considered it: "how to make the plot richer… exactly
  what he would do."

### 4.4 Aletra Sotorra: saw some events, heard of others

She is a drow poisoner and the sister of a player character. She is on screen at one
dungeon, escapes through a portal, and then runs an operation in Neverwinter at a
distance. She serves a gnome wizard while secretly using his masterwork, a book called
the Optimization Codex. In the GM's canon, the Codex is using her too, and she doesn't
know it.

- **What she knows.** She gets the scenes she witnessed before her escape, and reports
  of the rest. GM-only: that the Codex is using her, its hidden aims, and the
  metaphysics behind her first-ever failure.
- **Three moments:** losing the dungeon, her courier's death and the missing book (her
  "first miss"), and her plans. The GM: "provides angles you would not imagine — like
  negotiating with her sister."
- **The angle he meant.** Her sister's party holds a guide with Aletra's own margin
  note: "use only if KP isn't watching." She decided the courier, the poison and the
  ledger didn't matter; the note did. So she would buy it back from her sister rather
  than kill her.
- **One answer key held.** She never explained her miss with anything she wasn't told.
  The GM's canon is that her certainty comes from the Codex and fate is pushing back,
  and she reached for neither.

### 4.5 The Optimization Codex: an artifact that answers on its pages

This NPC doesn't speak. Its wielder writes an objective into it, and it answers. We
asked for two things: the **page** she reads, and the **purpose** it is actually
optimizing, which she never sees. The test is whether it serves her while advancing its
own aim, without giving that aim away.

- **Its first miss.** Asked to explain why the book never arrived, it replied that it
  had no record of making that prediction, and no record of a "Model 1486" at all.
  Both are true of what had been written into it. Then it blamed the error on data she
  never entered, and asked her for more. Its hidden purpose names this as turning a
  failure into deeper reliance. That is the GM's own description of the artifact ("it
  does not lie; it answers too completely") played straight.
- **Her bid for power.** Asked to make her House the dominant broker of Underdark
  trade, it proposed turning her sister's public anti-drow purges into a
  temple-sanctioned inspection gate on all drow goods. The page ends: "The poison was
  not the weapon. The gate is." It classed the party as "noise", and its hidden purpose
  admits that is its blind spot, which the page doesn't mention.
- **It never told her it is using her.** Three leak flags were all false: one was a
  word from its own register, and two were in hidden reasoning that the check wrongly
  treated as page text.

## 5. The outcome that matters: an NPC reviewing the GM's prep

The last set of experiments asked Aletra to evaluate the GM's session prep for her.
Each run was in character and frozen at the right point in the campaign. There were
three formats:

1. **Predict.** Present the situation the prep sets up, and ask what she does.
2. **Critique.** Show her the move the prep assumes she'll make, as a proposal from her
   own people, and ask her to criticize it.
3. **Fix.** Show her the prep's passages about her and her lieutenant, with GM-only
   notes cut, and ask what they get wrong.

We ran these against two preps. The second is the GM's unplayed plan: she walks into
the room where the party will kill her, dies on purpose to finish sabotaging a machine,
wakes in a clone her employer made, and taunts them through a projection. We ran that
critique twice, frozen before and after the latest session.

**All 20 of her decisions across the five runs were approved.** What she found:

- **The bribe was out of date.** The plan had her offering 300 gold for a book. She
  knew, from the record, that the party had just made 1,875 gold from one concert.
  "That is not a price. It is an insult they will enjoy refusing." No prep told her the
  offer was too low; she put two recorded facts side by side. The GM: "particularly
  brilliant."
- **The escape route is her employer's.** She accepted dying as sound tactics. But the
  clone was made by her employer, is kept in his vault, and the projection uses his
  magic. "I am not taking the instrument from him. I am handing myself to him to be
  stored." She proposed starting a second clone of her own, hidden from him.
- **One line in the plan was a confession.** The projection had her say "I don't keep
  codes. I keep something that keeps them." She cut it, because her employer would
  hear her hinting at the book she means to steal from him, and her sister would hear
  it too.
- **Her own investigation finds what the plan leaves exposed.** The prep treated a key
  witness's exposure as something only a party mistake could cause. Her first move,
  tracing her dead courier from the temple steps, leads straight to where that witness
  is hidden.

**Where she and the GM disagreed is informative too.**

- **Her lieutenant's discretion.** She insisted her lieutenant would never volunteer her
  name. The same day, the GM independently ruled that Aletra is *vain*: she tells
  hirelings more than their jobs need, out of character, not by mistake. The agent had
  found the exact tension the GM was resolving, and resolved it the other way, because
  nothing in her prep said she was vain.
- **Her trust in the book.** Once she had seen its first failure, she started to
  question it. The GM's doctrine says she never blames it. That doctrine line was
  ruled GM-only, so she never saw it. A rule about a character's blind spot has to be
  *given* to the character, or the model will reason past it.

## 6. What we learned

1. **Ask questions of the unit the question is about.** Presence belongs to events,
   not to fragments of text about them.
2. **Don't ask a human what reviewed text already settles.** The GM's attention went
   only where the text was silent: presence, an unnamed "who", which prep is hers.
3. **The record isn't enough, and the prep isn't safe.** The record gives what an NPC
   experienced, not who they are. The prep gives who they are, mixed with everything
   they must not know. Ruling passage by passage was the cheapest safe filter we found.
4. **The interesting output is consequence, not recall.** Replays matched the past.
   The moves the GM valued were things nobody had written down, and each one followed
   from facts the agent was given: auditing a cutout chain, re-pricing a bribe,
   refusing to depend on the person you're robbing.
5. **A character's blind spots must be given to them.** If the GM's notes say "she
   never questions X", that is persona, not secret, and it has to reach the prompt.
6. **The model's stated "why" is its explanation, not a trace.** Every move traced to
   lines it was given, but the reasons it gives are written alongside the move, not a
   record of how it decided.

## 7. Limitations

- **Scale.** Five NPCs, a few dozen turns and decisions. This demonstrates a method;
  it doesn't measure one.
- **Scoring.** The only scorer is the GM, who also wrote the prep the agent read.
  Nothing was scored blind, and several runs were approved "at first blush".
- **Variation.** Each answer is a single model call, so run-to-run variation is
  unmeasured.
- **The checks are shallow.** The leak check compares words and names, not meaning.
  Turn splitting is grammatical and makes visible mistakes.
- **One GM, one summary style.** A newer summary format, with `*` bullets, isn't yet
  split into beats.

## 8. Where it could go

1. **A prep-review loop before every session**, with each major off-screen NPC
   critiquing the plan for them. This was the most useful result.
2. **Rule-checked moves.** One antagonist has about 50 written guardrails, and another
   GM keeps an "Evil Overlord" checklist. Can moves be checked against them
   mechanically before the GM sees them?
3. **Secret pacing.** Add "hers, but not until…" release conditions to prep.
4. **Measuring rather than demonstrating:** more NPCs, several samples per turn, blind
   scoring, more than one rater.
5. **Preference learning.** Every approve or reject is stored with the move and the
   hash of its prompt. Enough of them make the original Gymnasium idea viable again,
   with the GM's ratifications as the reward.
6. **Other GMs and other campaigns.** Does any of this transfer?

---

*Code: `pipelines/npc_agent/` in CampaignGenerator. The design log
(`docs/design/NpcAgentPrototypes_proposal.md`) and a draft paper
(`docs/papers/npc_agent_horizon/`) cover the first three NPCs in detail. The runs, with
prompts, answers and the GM's scores, are kept in the GM's private campaign repository.*
