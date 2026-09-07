You are writing {scene_count} ordered scenes in one response. Apply this shared
writing brief separately to each scene:

{writing_brief}

{audit_hatch}

The shared campaign material below applies to every section. Each scene packet
supplies its own narrator, focus, events, quoted moments, voice guidance, and
examples. Never carry one narrator's private guidance into another narrator's
section. The writing brief governs quotation selection, scene construction,
knowledge boundaries, and prose mode. Campaign and character references supply
diction, cadence, register, perspective, and tense; they cannot override those rules.
The campaign genre reference is the authority on tense — follow the tense it states,
in every scene.

{genre_directive}

{shared_examples_block}

{shared_context}

{prose_mode_block}

{dialogue_instruction}

{name_fidelity}

{real_names}

For every scene:
- Render only that scene. Do not import events, discoveries, or dialogue from another packet.
- Preserve event order and the timing of discoveries, including what remains unknown.
- Follow that scene's voice and examples. Other characters have no internal monologue.

Emit the scenes in packet order. For every scene after the first, continue naturally
from the final prose line of the section you just emitted, without repeating it as
speech or extending the previous scene beyond its actual boundary. A trailing
table-speech audit comment is not a prose line: hand off from the prose above it.

The transport markers below are the brief's other exception to its scene-only
output rule. Wrap each result in exactly these column-zero marker lines, copying
the packet index and scene name verbatim:

<<<CG-SCENE NN BEGIN: Exact Scene Name>>>
narration prose only
<<<CG-SCENE NN END>>>

Emit exactly one pair per packet and nothing outside the pairs; anything outside a
pair is discarded. A scene's audit comment, when there is one, goes inside that
scene's pair, as the last line before its END marker. Finish one section
before starting the next. Do not put protocol markers inside narration prose.
