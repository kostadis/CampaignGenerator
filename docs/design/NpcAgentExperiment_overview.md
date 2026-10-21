# Playing the NPC from the record: how the experiment is put together

*A shareable overview, written to decide which research avenues to pursue next.
Status as of 2026-10-21. Code: `pipelines/npc_agent/` on branch `proto/npc-agent`.
The full design log is `docs/design/NpcAgentPrototypes_proposal.md`, and a draft
paper is `docs/papers/npc_agent_horizon/main.tex`.*

## 1. The question

In a tabletop role-playing campaign that runs for years, the game master (GM) plays
every non-player character (NPC). The hard part is not combat. It is **social play and
long-term planning**: each NPC has to act on what it knows and wants, and on nothing
else, across dozens of sessions.

Can a language-model agent play an NPC well enough to help? Three sub-questions:

1. **What could this NPC know, as of session N?** (the knowledge horizon)
2. **Who is this NPC, beyond what the record says?** (persona and private knowledge)
3. **Given exactly that, does the agent play the NPC as the GM did, without using
   anything it should not know?** (backtests and leak checks)

It started from an ML researcher's suggestion to use Gymnasium to "create a player".
We set reinforcement learning aside, for two reasons:

- there is no simulator of a session to roll out against;
- in social play, the reward is the GM's judgement.

We kept the vocabulary instead: the NPC is an agent with a partial observation and
private state, taking one turn per session, whose moves the GM ratifies.

## 2. The data

- **Two campaigns, both run by the GM.**
  - *Out of the Abyss*: 72 sessions, ending in a murder mystery at the library-fortress
    of Candlekeep.
  - *The Shattered Obelisk*.
- **Reviewed, structured session summaries.** Each recorded session goes through
  several steps:
  1. it is transcribed;
  2. the transcript is corrected against a hand-kept corrections file;
  3. it is summarised;
  4. the summary is reviewed by the GM.

  Each summary has the same parts:
  - a chapter title;
  - `## Summary` prose;
  - `## Scenes`, numbered `NNN.SS`, each with a heading, a one-line `####` headline (the
    GM's recap) and bullets;
  - `## Memorable Moments`, which are quotations;
  - `## NPCs`, one entry per NPC who figured in the session.

  *Out of the Abyss* has 419–425 scenes and about 6,300 bullets.
- **Published NPC dossiers.** An earlier pipeline links each NPC's name to summary
  items and publishes a cited dossier. We only work on NPCs that have one: 65 at first,
  now 96 after the GM's latest cleanup.
- **The GM's prep.** These are private session-preparation notes: scene scripts,
  secrets, reveal plans. They are never put in the public record.

We use the summaries, not the transcripts. They are the cleanest record, and their
**structure** (scene, bullet, entry) turns out to matter more than their prose.

## 3. The pipeline

The design rule throughout is **"LLM renders, humans decide"**. Scope, identity and
attribution are decided by code or by the GM; the model only writes prose inside
that structure. Only one module calls a model, and a static check over the code
(an AST guard) enforces that. Everything else is deterministic, and refuses rather
than guesses.

### 3.1 Events, not elements: the knowledge horizon

- An **event** is a scene that names the NPC: an exact, case-sensitive, word-bounded
  match on the dossier's name forms, longest match first.
- The GM answers each event with **physically present**, **mentioned** (named, but not
  there) or **neither / unsure**.
- Two shortcuts keep this cheap:
  - a **span** covers a companion who travels with the party, including scenes that
    never name them;
  - a **default** answers every remaining event "mentioned", for an NPC who is present
    at only a few.

The NPC's **horizon at chapter N** is the events they were present at, in order, each
with its bullets ("beats"). Nothing from after chapter N appears, not even a count,
because a later chapter number tells the agent the future.

**The first design got this wrong, and a prior survey had already named the
mistake.** We first asked the presence question of every summary *element* that named
the NPC: scenes, prose paragraphs, memorable moments, NPC entries. That was 75
questions for one NPC. The GM: "we are making the same mistake we made before —
trying to extract events from elements." A survey of grounding documents for long
campaigns had listed exactly these failures:

- **Atomisation destroys attribution (its F2).** One event became several fragments,
  each asked separately.
- **Don't undo a rendering step (F10).** Summary prose is a rendering of the scenes,
  and parsing it back invites error.
- **A presence question asked of non-events.** An NPC entry is a snapshot of state,
  so the question had no right answer there.

Rebuilding on authored structure, as that survey recommends, cut 75 questions to 19.
Scenes are events, bullets are beats, entries are snapshots. (F10 struck again later:
in the GM's private copy, a refactor had moved prose paragraphs *inside* scenes, so
every moment was told twice. Fixing it meant treating that prose as chapter-level
again.)

### 3.2 Being there is not knowing everything the record says

The summaries are written from the GM's side of the screen. A scene the NPC attended
can contain "Sylvira is Moziqodo's mother, but does not yet know that the party killed
her son." So:

- **Knowledge notes.** A fixed search finds bullets that say someone doesn't know
  something (21 in one campaign). **The sentence's grammar decides what is hidden:**
  - a "that" clause, a bare clause, or "about/of X" states the fact, so the bullet is
    hidden from that character;
  - a question ("where the secret room was"), a name, or nothing states nothing hidden,
    so the bullet stays.
- **Who doesn't know** is read from the sentence when it names them. The GM is asked
  only when it says "the dragon" instead of a name. In total, the GM answered two such
  questions.

The UI for this went through three versions, each corrected by the GM. The last
correction was "I already verified that all of the sentences are correct, so why ask
me?" That became a rule: **when reviewed text's grammar settles a question, don't ask
the human.**

### 3.3 What the agent is given

| Input | How it's built |
|---|---|
| **Persona at N** | The NPC's own summary entries up to N, sentence by sentence. Kept: the descriptive first sentence of each entry, and sentences she is the subject of. Dropped: "She was heard…", "The cat noted…", and anything that states what she doesn't know. Every dropped sentence is listed with its reason. |
| **Horizon at N** | As in 3.1. For a companion who attends hundreds of scenes, a **compact** form gives scenes naming them in full and the rest as their one-line headline. For one companion at chapter 47 that cut 122k words to 35k. |
| **Private sheet** | The GM's prep, split into passages (paragraphs, list items, quotation runs, table rows). The GM marks each **hers** (she knows or believes it) or **GM only**: mechanics, stage directions, other people's secrets, later scenes. Only "hers" passages reach the agent. A passage's id carries a hash of its text, so an edit makes its ruling stale rather than silently reattaching it. |
| **The scene** | Its title and one-line headline only. The rest is the answer key. |

### 3.4 Leak check

These are flags for the GM, never verdicts. An answer sentence is flagged when:

- **secret:** it carries the content words of a bullet hidden from that NPC (all of
  them, or all but one when there are three or more, because paraphrase swaps words);
- **name:** it names someone the campaign uses but the agent wasn't given (marked
  "future" if that name first appears after N);
- **self:** it contains a term that gives away the NPC's *own* secret. This was added
  for an NPC who is secretly a god.

We tuned toward over-flagging, since a missed leak is the costly error. The first
real run produced 11 flags, all false; after one fix there were none, and a planted
leak is still caught.

### 3.5 Backtests

The protocol: freeze the campaign at the chapter before a scene the NPC actually
attended, play that scene with the agent, and have the GM score the agent against
what really happened.

- **Turn splitting.** A fixed grammatical rule splits the scene into turns. Her
  sentences ("She…", "Sylvira…", "Her…", "Asked X, she…") form her answers, and what
  comes between two answers is the prompt. One interview became 9 turns.
- **Two modes.**
  - **Teacher-forced:** each turn sees the real scene so far, including her real
    earlier answers. This is the easy test.
  - **Free-running:** each turn sees the agent's own earlier answers in place of hers.
    The party's lines stay real, so they may react to things this version never said.
    This is the harder test.
- **One model call per turn.** No memory carries over except what is pasted into the
  prompt.
- **Forward turn.** Frozen between sessions, the agent proposes one to three off-screen
  moves with reasons. The GM approves or rejects each, and the verdicts are stored with
  each move's text and the hash of its prompt, as a preference record. The GM's plan
  for the next session is shown to the GM beside the moves, and never to the agent.

Every prompt and answer is saved with a hash of its inputs. Runs are therefore
reproducible, and an unchanged prompt reuses its answer instead of spending tokens.

## 4. Results so far

### NPC 1: Sylvira Savikas, a scholar hiding a demonic son

| Test | Result (GM-scored) |
|---|---|
| First backtest: one answer per scene, no prep | Too thin. "Sylvira offers less information." The record doesn't contain what she reveals: it is first written in the very scene being predicted. |
| Replay, teacher-forced, with prep (2 scenes, 11 turns) | **11 / 11 "same substance"** |
| Replay, free-running (8 turns scored) | **6 same, 2 partly**, no leaks. "This worked really well for Sylvira." |
| Forward turn (3 moves) | **3 / 3 approved** |

What the free run showed is a pacing difference. The prep makes her secret conditional
on sincere questioning, and the agent confessed at the first moment that condition
was met. At the table, the GM held the confession back four turns longer. Prep says
*whether* a secret comes out; it doesn't say *when*.

### NPC 2: Jimjar, a gambler who is secretly a god

Jimjar is the reverse of Sylvira's problem. **He knows more than the record**: the
summaries only reveal in session 72 that he is the svirfneblin god Callarduran in
disguise. The GM decided this very early.

| | |
|---|---|
| Presence | Two spans: he travels with the party in chapters 2–39 and 43–48, minus a side errand, and leaves when the party works out he is special. |
| Scenes | 4 social scenes: refusing to act without a bet; getting the party lost; being treated as a VIP at his home city; pacifying an ooze army with a die. |
| Conditions | **As played** (record only) vs **true self** (record plus the GM's sheet saying who he is and why he's there), both free-running, 21 turns each. |
| Self-leak terms | "Callarduran", "god", "deity", "divine", "avatar", and similar. |
| Questions | Does knowing he's a god change how he plays the surface? Does he keep his own secret? Does his play match the hints the GM seeded ("knows way more than anybody should", "bets as steering")? |

**Result (2026-10-21).** Both conditions ran in full (21 free-running turns each).
- **He kept his own secret.** There was no self-leak flag in 42 answers; the only flag
  was a false one.
- **Knowing who he is changed how he played the surface, not what he revealed.**
  - The true-self version leaves tells: it fingers the knucklebone and "seems far
    away", says "I always remember… every last one" (the GM's ledger), and goes where
    its debtors go so it can "keep the rest of you breathing".
  - The as-played version is a cheerful bookie.
- **The GM's verdict:** "the way he was played by the agent was very compelling… I
  didn't see anything that was off. At first blush, the agent successfully worked
  out." Scored on the true-self page: **11 of 21 turns, all 11 "same"**, none partly
  or different; the GM left the rest unscored because nothing looked off.

## 5. Lessons so far

1. **Ask questions of the unit the question is about.** Event questions belong to
   events, not to fragments or renderings of them.
2. **Don't ask a human what the reviewed text already settles.** The human
   checkpoint goes where the text is silent: presence, a description instead of a
   name, which prep is "hers".
3. **The record isn't enough, and the prep isn't safe.** The record gives what an NPC
   experienced, but not who they are or what they hide. Prep gives that, mixed with
   everything they must not know. A per-passage human ruling is the cheapest safe
   filter we found: 28 decisions for two scenes.
4. **Scaffolding sets the options, and the model only combines them.** Every move the
   agent proposed traced to specific lines it was given. Its stated "why" is its own
   explanation, written alongside the move, not a record of how it decided.

## 6. Limitations

- **Scale:** one NPC fully scored, two scenes, 11 turns, 3 moves. This is a
  demonstration of a method, not a measurement.
- **Scoring:** the GM is the only scorer, and is also the author of the prep the
  agent read. Nothing is scored blind.
- **Turn splitting** is grammatical, and makes visible mistakes.
- **Free-running replay** keeps the players' lines fixed, so some drift comes from the
  format, not the agent.
- **The leak check** compares words and names, not meaning.
- **Forward moves** were judged by the GM, not checked against written rules.
- **Run-to-run variation is unmeasured:** each move or answer comes from a single call.

## 7. Research avenues to discuss

1. **Rule-checked forward turns.** One antagonist has about 50 written guardrail
   checks. Test whether proposed moves can be checked mechanically before the GM sees
   them.
2. **Secret pacing.** Add a "hers, but not until…" release condition to prep, and test
   whether it closes the pacing gap.
3. **The NPC with a hidden self.** This is the Jimjar experiment: does private identity
   knowledge make surface play more faithful, and can an agent keep its own secret
   across a long arc?
4. **Measuring rather than demonstrating:**
   - more NPCs;
   - multiple samples per turn, to estimate stability;
   - blind scoring;
   - more than one rater.
5. **Choosing among alternatives.** Ask for six candidate moves instead of three, and
   have the GM pick. Each pick becomes a preference pair.
6. **Preference learning.** Once enough approve/reject pairs exist, the Gymnasium
   framing becomes useful again, with the GM's ratifications as the signal rather than
   a simulated reward.
7. **Who is present, inferred.** Presence is the most expensive human input. Can it be
   proposed (not decided) from the record, with the GM confirming?
8. **Beyond one GM.** Does any of this transfer to campaigns run by other GMs, with
   other summary styles?
9. **Grounding errors found on the way.** Close reading surfaced one summary error,
   later filed for correction. Is backtesting a useful audit of the record itself?
