---
name: gap-review
description: Run the narration gap-review loop from a chat — status, serve the mobile reviewer, compose, assemble. Use when the user asks what is left to review, wants the reviewer started, wants scenes composed, or wants a chapter assembled. Written for driving from a phone via Remote Control, where typing shell commands is painful.
---

# Gap review, driven from a chat

`sd_narrate --gap-marking` leaves the GM's own descriptions unwritten and marked
(#454). This skill runs the loop that answers them (#455) without the GM typing
shell commands — the case it exists for is **a phone**, over Remote Control,
where SSH and a touch keyboard are the friction.

Everything here shells out to `sd_review`, `sd_compose` and `assemble`. **Do not
reimplement any of it in Python or in prose** — those CLIs are the engine and
this skill is a face on them, which is also why a wrong answer here is a bug in
one place rather than two.

**No model call belongs anywhere in this loop.** Ruling a gap is the human
checkpoint the whole feature exists to create. If asked to decide which gaps
matter, or to write a gap's passage into the record, refuse and say why — the
evidence is `experiments/20260907-phandalin-gm-gaps-selffill`, where a model
asked to resolve its own eleven markers discarded nothing and handed both of the
GM's Order-of-the-Gauntlet lines to a player character, on the one passage the
markers had protected.

## Assume a phone

**This is always driven over Remote Control** — the GM has stated it. So:

- **Answer in prose, not tables.** Column output is unreadable on a phone.
- **Lead with the answer**, then the detail. "Four gaps left in scene 1, none
  written" before any listing.
- **Give tappable URLs**, not instructions to construct one.
- **Do not ask them to type a path.** Find the session; confirm the *name* if
  ambiguous, which is a one-word reply rather than a path on a touch keyboard.

## Find the session first

Narrations live at `<campaign>/summaries/<YYYYMMDD>/narration/`.

```bash
ls -d ~/src/campaigns/*/summaries/*/narration 2>/dev/null | tail -5
```

Default to the most recent, and **say which one you picked** in the same
sentence as the answer. Only ask when two are plausible — composing the wrong
session writes files, so an ambiguous guess is worth one question, but a
lone obvious candidate is not.

## What is left? — the default question

```bash
sd_review status --dir <session>/narration
```

Report it as prose, not as a table dump. The two numbers mean different things
and conflating them is the mistake to avoid:

- **ruled** — the GM has decided about the gap. A phone pass drives this to
  complete.
- **written** — there is prose, or the gap is cut. This is what the assembly
  gate reads.

**A scene where every gap is ruled and none is written is a finished triage, not
an unfinished scene.** Say so in those terms.

Two flags in the output deserve to be surfaced without being asked:

- `REVIEW STALE` — the narration changed after the review was made. `sd_compose`
  will refuse it. The GM has to re-review that scene; nothing is lost, but more
  writing against it would be wasted.
- `record_unreadable` — the `.authored.yaml` does not parse. Name the file.

## Start the reviewer for a phone

```bash
sd_review serve --dir <session>/narration --port 8765
```

Run it in the background and hand back **one tappable URL** built from the
tailnet address, so it works away from home:

```bash
echo "http://$(tailscale ip -4 | head -1):8765/"
```

Do not make the GM assemble the URL from parts.

Tell them: **rulings save to disk as they make them; there is nothing to copy.**
If they were using an older copy-paste flow, that is what changed.

Say once, not every time, that the server is **unauthenticated** — anyone who
can reach the port can read and write the review. It is meant for a tailnet or
a home LAN.

## Compose a scene

```bash
sd_compose --scene <narration>.md          # one scene
sd_compose --dir <session>/narration       # every scene that has a record
```

Composing is safe and repeatable — it reads the narration and the record and
writes `.composed.md`. It **refuses** when the record was authored against a
different draft; relay that refusal rather than working around it, because the
alternative is placing the GM's prose against text it was never written for.

`--force` overwrites an existing `.composed.md`. That file is generated, so this
is not destructive — but do not pass it reflexively.

## Assemble the chapter

```bash
assemble <session>/narration --output <chapter>.md --require-composed
```

`--require-composed` refuses any scene still holding a gap marker and names
every one responsible. **Suggest the gate; do not quietly drop it** because a
scene is not ready — a marker that reaches an assembled chapter travels into the
release append and the chapter split.

If it refuses because a scene has both a `.scrubbed.md` and a `.composed.md`,
that is a real ambiguity: two passes, neither superseding the other. Ask the GM
which is final and pass `--use <filename>`. Do not choose.

## Export a scene by hand

Rarely needed: the served reviewer fetches scenes itself, and the GM works over
Remote Control with the server up. This is for a laptop that will be closed.

```bash
sd_review export --scene <narration>.md      # writes <stem>.review.json
```

## What to refuse

- **Deciding a gap.** Which gaps are right, what a passage should say, whether
  to cut one — all of it is the GM's. Offer to draft a passage *in the chat* if
  asked directly, and let them paste it into the reviewer; never write into
  `.authored.yaml` on their behalf.
- **`sd_narrate --reroll`** over a scene with authored prose, unless the user
  says so explicitly in that turn. It lifts a refusal that protects the only
  thing in this pipeline a human wrote from scratch.
- **Hand-editing a generated file.** `.md` and `.composed.md` are output. If a
  composed scene is wrong, the record is what changes.

## Where the detail lives

`docs/cli/gap_review_howto.md` — task-oriented, with every refusal decoded.
