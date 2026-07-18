# Post-Session Workflow

After each session you have a Zoom VTT transcript, a `gm-assist.md` recap
from gmassisstant.app, and a story worth telling. This page is a short
umbrella — pick the entry point that matches how you want to work.

The recommended path is the **4-stage pipeline**:

```
gm-assist.md (human-authored)
    │
    ▼  Stage 1 — enhance_summary            ◄── Web UI: "Enhance Summary"
session-summary.md                           ◄── HUMAN REVIEW
    │
    ▼  Stage 2 — scene_extract              ◄── Web UI: "Re-Extract Quotes"
scene_extractions/NN_<slug>.md               ◄── HUMAN REVIEW
    │
    ▼  Stage 3 — sd_consistency + sd_plan + sd_narrate
                                              ◄── Web UI: "Plan & Check" + per-scene "Narrate"
narration/session_doc_scene_NN_<slug>.md     ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble                   ◄── Web UI: "Assemble Doc"
session_doc.md
```

Each LLM stage emits a reviewable artefact before the next one runs.
That's the point — see the global "LLMs render, humans decide" rule.

---

## I want to drive this from the web UI

Open [`docs/web/session_doc_editor.md`](../web/session_doc_editor.md). It's a TL;DR
button-by-button walkthrough of the Session Doc Editor that maps each
click to its stage above.

Quick start:

```bash
~/CampaignGenerator/start \
  --campaign-dir ~/campaigns/Phandalin \
  --session-dir ~/campaigns/Phandalin/summaries/20260407
```

Open <http://localhost:5000> → Session Workflow → Session Config →
Session Doc Editor. The header has a `Batch` checkbox that routes
Stage 1 / Stage 2 through Anthropic's Message Batches API for 50% off
when you don't need live streaming.

---

## I want to drive this from the CLI

Open [`session_doc_pipeline.md`](session_doc_pipeline.md). It
covers every flag, voice files, dialogue handling, the three live
LLM passes (now split across `sd_consistency` / `sd_plan` /
`sd_narrate`), and batch mode (`--batch` / `--submit-only` /
`--collect`) for the upstream `enhance_summary` and `scene_extract`
stages.

Minimal command-line tour:

```bash
SESS=summaries/20260414

# Stage 1
enhance_summary "$SESS"/*.vtt \
    --gmassist  "$SESS/gm-assist.md" \
    --output    "$SESS/session-summary.md"

# Stage 2
scene_extract "$SESS"/*.vtt \
    --summary    "$SESS/session-summary.md" \
    --output-dir "$SESS/scene_extractions/"

# Stage 3a — narrative plan (assigns one narrator per scene)
sd_plan \
    --scene-extractions "$SESS/scene_extractions/" \
    --characters "Vukradin, Valphine, Soma, Brewbarry" \
    --party docs/party.md \
    --session-summary "$SESS/session-summary.md" \
    --out "$SESS/narration/plan.md"
# REVIEW $SESS/narration/plan.md

# Stage 3b — per-scene narration (one file per scene)
sd_narrate "$SESS/session-summary.md" \
    --plan              "$SESS/narration/plan.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --voice-dir         voice/ \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --per-scene-output  "$SESS/narration/"

# Stage 4
assemble "$SESS/narration/" \
    --output "$SESS/session_doc.md" \
    --title  "Chapter 37 — A Gem of a Problem"
```

---

## Further reading

- [`docs/web/session_doc_editor.md`](../web/session_doc_editor.md) — Web UI walkthrough.
- [`session_doc_pipeline.md`](session_doc_pipeline.md) — Full CLI reference for the four stages, voice files, batch mode.
- [`gmassist_anchor.md`](gmassist_anchor.md) — Why the gm-assist recap is the authoritative event anchor.
- [`docs/player/voice_guide.md`](../player/voice_guide.md) — How players write voice files that shape their narrator's prose.
- [`docs/core/architecture.md`](../core/architecture.md) — Where everything lives and the rest of the codebase shape. The "Design rationale" section of [`session_doc_pipeline.md`](session_doc_pipeline.md) covers the 5-pass engineering notes (narrative bleed, chunk assignment, style transfer).
