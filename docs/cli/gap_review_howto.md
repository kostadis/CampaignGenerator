# Reviewing gaps — start here

`sd_narrate --gap-marking` leaves the GM's own descriptions unwritten, marked:

```
[GM NARRATION — TO BE WRITTEN: Aurelan arrives out of breath, pats himself down
and straightens his clothing before he speaks.]
```

This is how you rule on them — **on a phone, at work, offline** — and how the
result becomes a finished scene.

## The shape of it

Three files per scene. Only the middle one is yours.

```
session_doc_scene_NN_<slug>.md             generated — the draft, with markers
session_doc_scene_NN_<slug>.authored.yaml  YOURS — rulings and prose
session_doc_scene_NN_<slug>.composed.md    generated — the two merged
```

Same rule as the tape's `transcript_corrections.yaml`: **the record is the truth
and the composed document is output.** Never hand-edit a generated file; the
next run destroys it and nobody can review what you changed.

## The easy way: serve it

```bash
sd_review serve --dir <session>/narration
```

Open `http://<this machine>:8765/` on the phone — over a tailnet it works from
anywhere. Pick a scene; **your rulings save straight to
`<scene>.authored.yaml` as you make them.** Nothing to copy, nothing to paste,
and the record is on disk the moment you rule.

Two refusals protect you, both loud:

- a review made against a **different draft** of the narration is refused —
  reload the scene
- a save that would **drop prose already on disk** is refused. That is what a
  stale tab looks like: a review opened this morning, saving over an evening at
  the desk.

If the save fails — closed laptop, dropped tailnet — the bar says **NOT SAVED**
and *Copy review* is still there. Your rulings are in the page either way.

The unauthenticated server is meant for a tailnet or a home LAN. It serves one
campaign's prose and holds no credential, but anyone who can reach the port can
read and write the review.

## The offline way: put the file on your phone — once

Only needed if you want to review with your machine switched off. **Check it
runs scripts first**: a file manager's preview will render the page perfectly
and execute nothing, so every button is dead. That is what happened the first
time this was tried.


Copy `session_doc/review/reviewer.html` to the device however you like: mail it
to yourself, drop it in a file service, use a cable. Save it somewhere you can
open it again.

**You only ever do this once.** The page is not regenerated per session — that
is the whole design. A session arrives as data you paste in.

Re-copy it only when the repo's copy changes; the page will tell you if it is
older or newer than an export you paste.

## Review a scene

At a machine, export the scene:

```bash
sd_review export --scene summaries/20260825/narration/session_doc_scene_01_bank.md
```

That writes `session_doc_scene_01_bank.review.json` — 14–26 KB, small enough to
paste. Get it onto your phone's clipboard however suits you.

Then, on the phone, offline:

1. Open the reviewer. Paste. **Load scene.**
2. Work down the scene. Each gap shows what the source establishes there, and
   every scene's **full GM turns are folded away at the foot** — open them and
   rule against the source rather than from memory.
3. For each gap: **Right gap — mine to write**, or **Cut from the chapter**.
   Optionally say the *marking* was wrong: **Wrong scope**, or **Model should
   have written it**. That second row never changes the chapter; it is feedback
   on the contract.
4. Write the passage if you want to, or leave it for your desk.
5. Any of the model's own paragraphs can be edited too — *edit this passage*.

### Ruling everything and writing nothing is a finished session

The bar shows **two** figures: *ruled* and *written*. Driving **ruled** to
complete on a train and leaving eight passages for later is a successful review,
not a half-done one. That is what the two numbers are for.

### Draft with any model

**Copy as prompt** puts the scene, the outstanding gaps and their source GM
turns on your clipboard, phrased as a request to draft them. Paste it into
whatever chat you use — it is deliberately not tied to one. Paste the prose back
into the gap's field.

Nothing here resolves a gap for you. You copy one out; you paste one back.

## Land the result

**Copy review** gives you the record's content. Put it in the scene's
`.authored.yaml` — by hand, for now — then:

```bash
sd_compose --scene summaries/20260825/narration/session_doc_scene_01_bank.md
sd_narrate --gap-marking …   # only after this, and only if you must
assemble summaries/20260825/narration --output chapter.md --require-composed
```

## Every refusal, decoded

**`Refusing: … has no gap markers, so there is nothing to review.`**
The scene was narrated without `--gap-marking`, or genuinely has no GM
description in it. `--allow-no-gaps` exports it anyway.

**`Warning: no scene extraction found …`**
The export has no GM turns to show at the foot, so you would be ruling from
memory. Name it with `--extraction`.

**`This export is version N and this page understands M.`**
The reviewer on your phone and the one in the repo have diverged. Copy the
current `reviewer.html` across.

**`That is not valid JSON — if you pasted it on a phone it may have been
truncated.`**
Exactly that. Paste again. The page refuses rather than rendering half a scene,
because half a scene looks whole.

**`This browser will not let the page save anything.`**
`localStorage` is unavailable under `file://` here. Your rulings will not
survive a reload — **copy the review before you leave the page.**

**`Refusing to compose: the record was authored against a different draft.`**
The narration changed after you reviewed it. Composing anyway would place your
prose against text it was never written for. Re-review, or restore the draft the
record names.

**`Refusing to assemble — these scenes still have gaps nobody has written or
cut.`**
`--require-composed` doing its job. Every scene holding it up is named.

**`Refusing to assemble: a scene has two final variants.`**
A `.scrubbed.md` and a `.composed.md` for one scene. Neither supersedes the
other, so name one with `--use`.

**`Refusing to narrate over work you wrote by hand.`**
A record has prose in it and re-narrating would strand it. `--reroll` proceeds
and tells you what happens to the record first — nothing is deleted, but it will
refuse at compose time until you review the scene again.

## What this deliberately does not do

- **Resolve a gap for you.** Asked to resolve its own eleven markers, the model
  discarded nothing and gave both of the GM's Order-of-the-Gauntlet lines to a
  player character — on the one passage the markers had protected. No module in
  this layer may call a model, and a test walks the AST to make sure.
- **Send anything anywhere.** The reviewer makes no network request of any kind.
- **Write your review back to disk.** The clipboard is the boundary for now.
