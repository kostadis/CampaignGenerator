# Grounding Documents — When and How to Refresh

Grounding documents are the AI's memory of your campaign. Every tool that calls
Claude — session prep, narration, planning — reads these files first. Stale grounding
docs mean hallucinated completed quests, wrong NPC states, and plot threads that
were resolved three sessions ago still being treated as active.

They are inputs, not outputs. The scripts generate them; you review and keep them.

> **Building them from a local ensemble extraction instead of the per-tool
> Claude path?** See [`local_grounding_docs.md`](local_grounding_docs.md) — the
> extract-once-locally runbook (facts_to_state.py → dossiers → synthesis), with
> the exact commands and provenance of the Out of the Abyss run.

---

## The Four Documents

| Document | Script | UI Page | What it tracks |
|---|---|---|---|
| `campaign_state.md` | `campaign_state.py` | Campaign State | Completed encounters, resolved threads, current NPC states, active quests |
| `world_state.md` | `distill.py` | Distill World State | Living canon — geography, factions, history, how the world currently is |
| `party.md` | `party.py` | Party Document | Party roster, arc scores, backstory, relationships, current emotional state |
| `planning.md` | `planning.py` | Planning Document | Active threats, NPC intentions, plot threads ordered by urgency |

These four files are loaded into every session prep and narration call in this order:
`campaign_state.md` first (most specific), `world_state.md`, `party.md`, `planning.md`.
The order matters — more specific facts override general ones.

---

## When to Refresh

### After every session: `campaign_state.md`

The most volatile document. Every session resolves something, activates something new,
or changes an NPC's state. Run this after each session once you have the session summary
appended to your summaries file.

**UI: Grounding Docs → Campaign State**

```bash
python campaign_state.py summaries.md \
    --track-file docs/tracking.txt \
    --output docs/campaign_state.md
```

The `--track-file` is a list of trackable events from the adventure module
(generated once by `make_tracking.py`). It ensures the model flags anything
in the adventure that hasn't shown up in summaries yet.

---

### Every 3–5 sessions: `world_state.md`

World state is the slower-changing layer — geography, faction alignments, historical
facts, how the world works. It doesn't need to be regenerated after every session
unless a major world event occurred (a city fell, a faction was destroyed, a secret
was revealed that changes the shape of the world).

**UI: Grounding Docs → Distill World State**

```bash
python distill.py summaries.md --output docs/world_state.md
```

---

### When the party changes: `party.md`

Regenerate when:
- A character levels up significantly
- An arc score threshold is crossed
- A major backstory moment triggers
- A meaningful relationship shifts (with an NPC or between characters)
- A new character joins or a character departs

**UI: Grounding Docs → Party Document**

```bash
python party.py \
    --character docs/characters/soma.md docs/characters/vukradin.md \
    --summaries summaries.md \
    --arc-scores docs/arc_scores/soma_arc.md \
    --output docs/party.md
```

---

### Before planning a session arc: `planning.md`

Run `planning.md` when you're preparing a major session or the start of a new arc —
not necessarily after every single session. Its value is in synthesis: it reads
your NPC dossier files (which you review and edit) and produces a structured threat
tracker and NPC dossier section.

This is a **two-phase** process — see [planning_pipeline.md](planning_pipeline.md) for
the full workflow. The short version:

1. **Build dossiers** (once per set of new sessions): extracts per-NPC information
   from session summaries into individual files in `docs/npcs/`
2. **Review dossiers**: open each file, correct errors, fill in motivations and secrets
   the model couldn't infer
3. **Synthesize**: combine edited dossiers with arc score mechanics into `planning.md`

**UI: Grounding Docs → Planning Document**

```bash
# Phase 1: extract dossiers
python planning.py --summaries summaries.md --build-dossiers --dossier-dir docs/npcs/

# Phase 2: synthesize (after reviewing docs/npcs/*.md)
python planning.py \
    --npc docs/npcs/*.md \
    --arc-scores docs/arc_scores/*.md \
    --output docs/planning.md
```

---

## Recommended Order When Refreshing Multiple Docs

When running a full refresh (e.g. after several sessions accumulate):

1. **`campaign_state.md`** — most current facts; run first
2. **`world_state.md`** — can run in parallel with campaign_state; uses same summaries
3. **`party.md`** — benefits from campaign_state being current (arc score context)
4. **`planning.md`** — run last; reads NPC dossiers you've edited by hand

---

## Incremental vs. Full Resync

All four scripts extract intermediate files to disk before synthesizing. This means
you can re-synthesize without re-extracting — useful when you've edited a dossier
file or want to tweak the synthesis prompt.

| Situation | What to do |
|---|---|
| New sessions added to summaries | Re-run normally (extraction + synthesis) |
| Edited a dossier, want updated planning.md | `--synthesize-only` with `--extract-dir` |
| Extraction files are stale or corrupt | Delete `*_extractions/` dir, re-run |
| Re-synthesize world_state after editing extractions | `python distill.py --synthesize-only --extract-dir docs/distill_extractions --output docs/world_state.md` |

The **Synthesize Only** toggle in the UI maps to `--synthesize-only`.

---

## UI Workflow

Each grounding doc page in the UI runs the CLI script as a subprocess with live
streaming output. Path fields auto-populate from whatever was set in Session Config.

The UI pages support the most common configurations. For advanced options
(custom tracking files, multiple context files, splitting by chapter heading),
use the CLI directly.

---

## Further Reading

- [planning_pipeline.md](planning_pipeline.md) — detailed two-phase NPC dossier workflow
- [`docs/cli/cli_tools.md`](cli_tools.md) — full flag reference for all four scripts
- [`CLAUDE.md`](../../CLAUDE.md) — repo-wide conventions
