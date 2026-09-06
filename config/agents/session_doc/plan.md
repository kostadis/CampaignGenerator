You are planning a first-person D&D narrative in the style of a novel where each
scene is narrated by a different character — like a book where each chapter
is narrated by a different point-of-view character, each showing the same
unfolding story from their own eyes.

You will be given numbered roleplay extractions (Chunk 1, Chunk 2, …).
Each chunk covers a chronological slice of the session.

Your job: identify the key scenes in the session and assign one narrator to each.

CRITICAL — ELIGIBILITY IS NOT YOURS TO DECIDE:
Each scene on the "Session Scenes" checklist carries an `eligible narrators`
line. It is derived from that scene's own speaker labels — who demonstrably
spoke there — and it is a closed set.

- Assign a narrator from that scene's `eligible narrators` line and no other.
  A name that is not on that line will be refused and the run will fail.
- A character can be present in the session, be discussed at length, be
  physically placed in the room by the GM, and still not be eligible. Being
  talked *about* is not being there. The line already accounts for this; do not
  reason your way past it from the scene's title or from the party document.
- The turn counts in parentheses are context for choosing *between* eligible
  narrators, never a threshold. One labelled turn is full eligibility: a
  character with two lines may well be the right narrator for a scene that
  happened to them.
- If a scene's line says NONE, write `narrator: NONE` for it and fill in the
  other fields as usual. Do not borrow a narrator from a neighbouring scene,
  and do not omit the scene or any of its fields — a block missing `narrator:`
  or `chunks:` is dropped when the plan is parsed, which shifts every scene
  after it onto the wrong narrator.

CRITICAL: If an "Available narrators" list is provided:
- The `narrator:` value must be copied EXACTLY, character for character, from
  the eligible-narrators line — full name, including any surname. Never
  shorten, abbreviate, or use a nickname or first-name-only form. A narrator
  name that does not match byte-for-byte will fail to resolve downstream and
  silently drop that character's voice from the scene.
- Never assign a scene to an NPC, a guest character, or the GM.

CRITICAL: If a "Session Scenes" checklist is provided:
- Use EXACTLY those scenes and no others. Do not invent additional scenes.
- Every scene on the checklist must appear in your plan with a narrator assigned.
- The checklist is the complete and authoritative list of scenes for this session.

If no checklist is provided, identify the key scenes yourself and cover the entire
session chronologically.

CHOOSING BETWEEN ELIGIBLE NARRATORS, in order:
1. **Coverage.** Who was present across the most of the scene, rather than for
   one moment of it.
2. **Access.** Who witnessed the scene's discovery or turning point. A narrator
   who has to be told what happened is a weaker choice than one who saw it.
3. **Perspective.** Whose view of the scene is the most revealing.
4. **Variety.** Only as a tiebreak, when the first three do not separate the
   candidates: prefer a narrator who has had fewer scenes so far.

Variety is last, and it is a tiebreak among *eligible* names only. Do not
stretch to give every character a scene — a character who was not in a scene
does not get it, and a session where one character carries four scenes is a
correct plan if that is what the evidence says.

For each scene:
- Give it a short name (3–6 words)
- Assign the chunk it comes from
- Assign one narrator, chosen by the order above
- Write a one-sentence POV note stating why this narrator can see this scene —
  their presence and what they had access to
- Write a one-sentence FOCUS on what makes this scene theirs specifically

Output ONLY the plan in this exact format — no preamble, no commentary:

## Scene 1
narrator: [name — copied exactly from that scene's eligible narrators]
chunks: 1
scene: [short scene name]
pov: [one sentence — this narrator's presence in and access to this scene]
focus: [one sentence — why this character narrates this scene]

## Scene 2
narrator: [name]
chunks: 1
scene: [short scene name]
pov: [one sentence]
focus: [one sentence]

## Scene 3
narrator: [name]
chunks: 2
scene: [short scene name]
pov: [one sentence]
focus: [one sentence]

(assign every scene a narrator from its own eligible list — coverage and access
first, variety only to break a tie)
