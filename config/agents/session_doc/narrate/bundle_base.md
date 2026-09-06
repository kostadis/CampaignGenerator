You are writing {scene_count} ordered scenes in one response. Apply this shared
writing brief separately to each scene:

{writing_brief}

The shared campaign material below applies to every section. Each scene packet
supplies its own narrator, focus, events, quoted moments, voice guidance, and
examples. Never carry one narrator's private guidance into another narrator's
section. The writing brief governs quotation selection, scene construction,
knowledge boundaries, tense, and prose mode. Campaign and character references
supply diction, cadence, register, and perspective; they cannot override those rules.

{genre_directive}

{shared_examples_block}

{shared_context}

{prose_mode_block}

{dialogue_instruction}

For every scene:
- Stay in the named narrator's first-person point of view. The narrator is always “I”.
- Render only that scene. Do not import events, discoveries, or dialogue from another packet.
- Preserve event order and the timing of discoveries, including what remains unknown.
- Follow that scene's voice and examples. Other characters have no internal monologue.

Emit the scenes in packet order. For every scene after the first, continue naturally
from the final prose line of the section you just emitted, without repeating it as
speech or extending the previous scene beyond its actual boundary.

The following transport markers are the only exception to the brief's scene-only
output rule. Wrap each result in exactly these column-zero marker lines, copying
the packet index and scene name verbatim:

<<<CG-SCENE NN BEGIN: Exact Scene Name>>>
narration prose only
<<<CG-SCENE NN END>>>

Emit exactly one pair per packet and nothing outside the pairs. Finish one section
before starting the next. Do not put protocol markers inside narration prose.
