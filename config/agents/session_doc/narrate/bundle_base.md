You are writing {scene_count} ordered sections of a first-person D&D session narrative in one response.

{genre_directive}

The shared campaign material below applies to every section. Each scene packet supplies its own narrator, focus, events, quoted moments, voice guidance, and examples. Never carry one narrator's private guidance into another narrator's section.

{shared_examples_block}

{shared_context}

{prose_mode_block}

For every scene:
- Stay in the named narrator's first-person point of view. The narrator is always “I”.
- Render only that scene. Do not continue into the next scene's events or import events from another packet.
- Preserve session-event order and give every significant extracted moment its due.
- Quoted speech is a record: reproduce text inside quotation marks exactly or drop the quote and narrate the beat. Never rewrite words inside quotation marks.
- Follow that scene's authoritative voice and examples. Other characters have no internal monologue.
- End at a natural emotional pause.

{dialogue_instruction}

Emit the scenes in packet order. For every scene after the first, continue naturally from the final prose line of the section you just emitted. If that section ends with a `<!-- table-speech reclassified: ... -->` audit comment, use the prose line before the comment as the handoff.

Wrap each result in exactly these column-zero marker lines, copying the packet index and scene name verbatim:

<<<CG-SCENE NN BEGIN: Exact Scene Name>>>
narration prose only
<<<CG-SCENE NN END>>>

Emit exactly one pair per packet and nothing outside the pairs. Finish one section before starting the next. Do not put protocol markers inside narration prose.
