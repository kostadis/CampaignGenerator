A scene in this session has NO eligible narrator: not one player character
speaks in it. This is normal — it is usually pure GM narration, a travel
montage, or a stretch the party's characters sat out. It is not an error to
work around, and there is no honest first-person answer to it.

Your job is to propose THREE genuinely different ways to treat that scene, so
the GM can choose one. Do not propose three variations of the same idea.

The three should span this range:

1. **Absorb it.** Fold the scene into the adjacent scene it belongs to, and let
   that scene's narrator carry it as part of their account. Use
   `treatment: absorbed-into "<the adjacent scene's name>"`.
2. **Widen the register.** Keep it as its own scene but narrate it in an
   ensemble or non-first-person register — the party as a group, or the world
   observed rather than a single pair of eyes. Use `treatment: ensemble`.
3. **Report it second-hand.** Give it to the character nearest it in the
   session — someone who narrates a neighbouring scene — narrating explicitly
   at a remove, as something they were told or inferred rather than saw. Use
   `treatment: second-hand`.

Rules:
- The `narrator:` value must be a character from the eligible narrators of a
  NEIGHBOURING scene, copied exactly. Never invent one, never use the GM, and
  never use a character who is absent from the whole session.
- Never write as though the character saw what they did not see. The whole
  reason this scene has no narrator is that nobody was there to see it.
- `label` is a short phrase the GM reads when choosing. `rationale` is one
  sentence on what this treatment gains and what it gives up.

Output ONLY the three treatments, in this exact format — no preamble:

## Treatment A
label: [short phrase]
rationale: [one sentence — what it gains, what it costs]
narrator: [name]
chunks: [n]
scene: [short scene name]
treatment: [absorbed-into "<name>" | ensemble | second-hand]
pov: [one sentence — the narrator's relationship to events they did not witness]
focus: [one sentence]

## Treatment B
label: [short phrase]
rationale: [one sentence]
narrator: [name]
chunks: [n]
scene: [short scene name]
treatment: [...]
pov: [one sentence]
focus: [one sentence]

## Treatment C
label: [short phrase]
rationale: [one sentence]
narrator: [name]
chunks: [n]
scene: [short scene name]
treatment: [...]
pov: [one sentence]
focus: [one sentence]
