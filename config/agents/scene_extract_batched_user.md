## Scenes to extract

Extract each scene below, in the order given, wrapping each in its own
`<<<CG-SCENE NN BEGIN: name>>>` / `<<<CG-SCENE NN END>>>` marker pair as
described in the system prompt. Copy each index and name verbatim from the
heading line into its BEGIN marker.

{scene_blocks}

---

For each scene above, find every moment in the transcript that belongs to
that scene and output the verbatim moments in chronological order,
following the format described in the system prompt.

Every scene gets its own marker pair, even if the transcript holds nothing
for it — in that case emit the pair with an empty body. No preamble, no
commentary, nothing outside the pairs.
