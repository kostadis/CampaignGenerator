# CampaignGenerator

A D&D session-prep CLI that assembles campaign documents and session beats, then calls the Claude API to generate encounter design documents.

## Running the tool

```bash
python prep.py [options]
```

### Common invocations

```bash
# Single beat, interactive input
python prep.py

# Single beat, inline
python prep.py --beat "The party enters Icespire Hold"

# Pipeline mode (Lore Oracle → Encounter Architect → Voice Keeper)
python prep.py --mode pipeline --beat "The party enters Icespire Hold"

# Session arc: full numbered outline, interactive entry
python prep.py --session

# Session arc: inline outline
python prep.py --session "1. Travel to Hold 2. Confront Carver 3. Cryovain reveal"

# Copy assembled prompt to clipboard instead of calling API
python prep.py --clipboard --beat "..."

# Skip saving a log file
python prep.py --no-log --beat "..."
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `--beat` / `-b` | interactive | Single session beat |
| `--session` / `-s` | interactive | Numbered session outline |
| `--mode` / `-m` | `single` | `single` or `pipeline` |
| `--clipboard` / `-c` | off | Copy output instead of (or after) API call |
| `--config` | `config/config.yaml` | Path to config YAML |
| `--model` | `claude-sonnet-4-20250514` | Claude model to use |
| `--no-log` | off | Skip saving log file |

## Project structure

```
prep.py                     # CLI entry point
requirements.txt            # anthropic, pyyaml, pyperclip
config/
  config.yaml               # Paths to documents and agent prompts
  system_prompt.md          # Main system prompt (single mode) — the Campaign Architect
  agents/
    lore_oracle.md          # Stage 1: canon consistency checker
    encounter_architect.md  # Stage 2: tactical encounter designer
    voice_keeper.md         # Stage 3: tone and voice editor
docs/
  world_state.md            # Living canon document — source of truth
  mechanics.md              # Arc score systems
  planning.md               # Enemy dossiers and planning docs
logs/                       # Auto-generated timestamped session logs
```

## Pipeline mode

Three sequential API calls per beat:

1. **Lore Oracle** — verifies the beat against canon; returns CLEAR / FLAGS / GAPS
2. **Encounter Architect** — receives the beat + Oracle report; produces the full structured encounter document
3. **Voice Keeper** — receives the encounter document; tunes NPC dialogue and PC behavioral notes to match established voice

If the Lore Oracle response contains the word `FLAGS`, the user is prompted before continuing to Stage 2.

## Logs

Logs are saved to `logs/` as timestamped markdown files. Single-beat logs include the system prompt, user prompt, and response. Session logs include all beats and all pipeline stages in one combined file (stem: `session_arc`).

## Config

`config/config.yaml` controls all file paths. Edit it to point documents at absolute paths (useful on Windows/WSL where the docs live elsewhere).

## Transforming NotebookLLM dossiers

`transform.py` converts a NotebookLLM planning document into `prep.py` input format. The output is printed for manual review before being passed to `prep.py`.

```bash
# From a file → numbered session outline (default)
python transform.py dossier.txt

# From stdin → numbered session outline
python transform.py

# Extract as a single beat instead
python transform.py dossier.txt --single

# Save the output for later review
python transform.py dossier.txt -o beats/xalvosh_outline.txt
```

After reviewing the output, pass it to `prep.py`:

```bash
python prep.py --session   # paste the outline interactively
python prep.py --beat "…"  # paste the single beat inline
```

## Dependencies

```bash
pip install anthropic pyyaml pyperclip
```

`ANTHROPIC_API_KEY` must be set in the environment.
