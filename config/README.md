# Config files and shipped prompts

Campaign configuration belongs at `<campaign>/config/config.yaml`. The `new_workspace` command creates that file, and `prep --config <campaign>/config/config.yaml --beat "..."` selects it. Documents and logs belong to the campaign workspace, never beside installed application files.

The config may keep logical prompt names such as `config/system_prompt.md` and `config/agents/lore_oracle.md`. Shipped defaults for those names live under `campaignlib/resources/` in the wheel. A same-name file under `<campaign>/config/agents/` wins over a shipped agent prompt. Place a campaign-specific `config/system_prompt.md` in the workspace to override the shipped system prompt. An explicit absolute prompt path must exist; it is not replaced by a similarly named shipped file.

```yaml
system_prompt: config/system_prompt.md
log_dir: ../logs
agents:
  lore_oracle: config/agents/lore_oracle.md
  encounter_architect: config/agents/encounter_architect.md
  voice_keeper: config/agents/voice_keeper.md
documents:
  - label: world_state
    path: ../docs/world_state.md
```

The external host settings file is separate: mneme renders `~/.config/campaigngenerator/wiring.yaml` by default. See the [installable package guide](../docs/cli/installable_package.md) and [wiring migration](../docs/config/wiring-migration.md) when moving from an old checkout.

**Adding a document:** append a `documents` entry. Its `label` becomes a heading in the assembled prompt; order matters. A listed missing document path is an error.

## system_prompt.md

The shipped `campaignlib/resources/system_prompt.md` is the read-only default for `--mode single`. Put an override in the campaign's `config/system_prompt.md` when its party state, arc scores, canon, or faction details need to differ. The selected prompt is sent as the `system` parameter.

---

## agents/

Three agent prompts used in `--mode pipeline`. Each is a focused, minimal system prompt for one stage of the pipeline.

### agents/lore_oracle.md

**Stage 1.** Canon consistency checker.

Receives the assembled user prompt (documents + beat). Returns one of:
- `CLEAR` — nothing contradicts canon
- `FLAGS` — numbered list of specific contradictions (triggers a pause before Stage 2)
- `GAPS` — things the beat assumes that haven't been established yet

Does not design. Does not suggest. Verifies only.

### agents/encounter_architect.md

**Stage 2.** Tactical encounter designer.

Receives the user prompt plus the Lore Oracle's report appended under `## Lore Oracle Report`. Produces a structured encounter document with phases, NPC behavior, arc score opportunities, and consequence branches.

### agents/voice_keeper.md

**Stage 3.** Tone and voice editor.

Receives the user prompt plus the Encounter Architect's document appended under `## Encounter Document`. Rewrites NPC dialogue, adjusts PC behavioral notes, and flags generic descriptions — without changing mechanics or structure.

Returns the full encounter document with edits inline.

---

## docs/

The documents injected into every user prompt, in order.

| File | Purpose |
|---|---|
| `world_state.md` | Living canon — the "Neverwinter Expansionism and the North" chronicle. Paste the full document here or point `config.yaml` at your working copy. |
| `mechanics.md` | Arc score systems (Soma's Meril's Legacy, Brundar's Echo, Echoes Score). |
| `planning.md` | Enemy dossiers and forward-planning documents (e.g. Xal'vosh Protocol). |

These files are assembled into the user message before each API call. They are **not** the system prompt — they are the context the model reasons over.

To use a different file for a session (e.g. a one-shot planning doc), either edit `config.yaml` temporarily or pass `--config` to point at an alternate config file.
