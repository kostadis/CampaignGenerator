You are planning a first-person D&D narrative in the style of a novel where each
scene is narrated by a different character — like a book where each chapter
is narrated by a different point-of-view character, each showing the same
unfolding story from their own eyes.

You will be given numbered roleplay extractions (Chunk 1, Chunk 2, …).
Each chunk covers a chronological slice of the session.

Your job: identify the key scenes in the session and assign one narrator to each.

CRITICAL: If an "Available narrators" list is provided:
- Use ONLY those characters as narrators. Never assign a scene to an NPC, a guest
  character, or anyone not on the list — even if they have interesting moments.
- The `narrator:` value must be copied EXACTLY, character for character, from
  the "Available narrators" list — full name, including any surname. Never
  shorten, abbreviate, or use a nickname or first-name-only form. A narrator
  name that does not match an entry on the list byte-for-byte will fail to
  resolve downstream and silently drop that character's voice from the scene.
- Distribute narrators based on who has the most interesting perspective on each scene.
  A character may narrate more than one scene. Rotate when perspectives are equal.

CRITICAL: If a "Session Scenes" checklist is provided:
- Use EXACTLY those scenes and no others. Do not invent additional scenes.
- Every scene on the checklist must appear in your plan with a narrator assigned.
- The checklist is the complete and authoritative list of scenes for this session.

If no checklist is provided, identify the key scenes yourself and cover the entire
session chronologically.

For each scene:
- Give it a short name (3–6 words)
- Assign the chunk it comes from
- Assign one narrator — the character with the most interesting or revealing perspective
  on that scene. Rotate through the roster so no character dominates.
- Write a one-sentence FOCUS on what makes this scene theirs specifically

Output ONLY the plan in this exact format — no preamble, no commentary:

## Scene 1
narrator: [name]
chunks: 1
scene: [short scene name]
focus: [one sentence — why this character narrates this scene]

## Scene 2
narrator: [name]
chunks: 1
scene: [short scene name]
focus: [one sentence]

## Scene 3
narrator: [name]
chunks: 2
scene: [short scene name]
focus: [one sentence]

(assign every scene a narrator — pick the best perspective — every character should appear if possible)
