# Config Files

## config.yaml

The central config. Points every component at its file.

```yaml
system_prompt: config/system_prompt.md   # used by --mode single

log_dir: logs/                           # where session logs are saved

agents:
  lore_oracle: config/agents/lore_oracle.md
  encounter_architect: config/agents/encounter_architect.md
  voice_keeper: config/agents/voice_keeper.md

documents:
  - label: world_state
    path: docs/world_state.md
  - label: mechanics
    path: docs/mechanics.md
  - label: planning
    path: docs/planning.md
```

Paths can be absolute or relative to wherever you run `prep.py`.
On WSL, absolute paths like `/mnt/c/Users/you/OneDrive/campaign/world_state.md` work fine.

## Separate work directories

To keep campaign data (docs, logs) outside the code repo, create a campaign-specific config file anywhere on your filesystem:

```yaml
# /home/you/campaigns/icespire/config.yaml

system_prompt: config/system_prompt.md          # code-side prompt (relative path ok)

log_dir: /home/you/campaigns/icespire/logs/

agents:
  lore_oracle: config/agents/lore_oracle.md
  encounter_architect: config/agents/encounter_architect.md
  voice_keeper: config/agents/voice_keeper.md

documents:
  - label: world_state
    path: /home/you/campaigns/icespire/docs/world_state.md
  - label: mechanics
    path: /home/you/campaigns/icespire/docs/mechanics.md
  - label: planning
    path: /home/you/campaigns/icespire/docs/planning.md
```

Then pass it with `--config`:

```bash
python prep.py --config /home/you/campaigns/icespire/config.yaml --beat "..."
```

Agent prompts and system prompt can stay code-side (relative paths resolve from where you run `prep.py`), or be copied per-campaign if you want to customise them independently.

---

**Adding a document:** append an entry under `documents`. The `label` becomes the heading in the assembled prompt (`## label`). Order matters — documents are injected in the order listed.

**Removing a document:** delete its entry. The tool will not error on missing optional documents; it only errors if a listed path doesn't exist.

---

## system_prompt.md

The system prompt used in `--mode single` (one API call).

This is the full **Campaign Architect** persona: identity, universe rules, party profiles, encounter design templates, consistency rules, and output formats. It is the primary prompt for single-beat and session-arc prep.

Edit this file to:
- Update party state after a session (Section IIb current party state)
- Update hidden arc scores (Section IX)
- Add confirmed canon events (Section IX)
- Adjust faction states or NPC locations

This file is never sent as a user message — only as the `system` parameter.

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
