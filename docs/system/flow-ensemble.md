# Flow: Ensemble extraction → grounding docs

> The **modern** way the four grounding docs are (re)generated: extract every
> fact once on local Spark hardware, human-review scope, then call the API only
> for the final synthesis. [↑ index](index.md)

**Deep docs:** [`docs/cli/ensemble_workflow.md`](../cli/ensemble_workflow.md)
(end-to-end, with the Phandalin worked example) ·
[`docs/cli/ensemble_extraction.md`](../cli/ensemble_extraction.md) (`ensemble.py` flags)

---

## Why this exists (the economics)

`world_state.md`, `campaign_state.md`, `party.md`, and `planning.md` all derive
from the same chapter/session text. The **old path** ran the Claude API *inside
each* grounding-doc tool, re-extracting that text three or four times — ~2.5–3.4M
metered tokens per full refresh.

The ensemble path inverts that: **extraction is expensive and should happen
once.** It extracts atomic facts locally on the DGX Spark (≈free), aggregates to
per-entity dossiers, lets a human review scope, then spends the API only on the
final per-doc synthesis — **~280K tokens total**. This is the heaviest consumer
of the Spark / `dgxlib` stack (see [component-campaigngenerator](component-campaigngenerator.md)
→ backends); Stages 1–2 are pure local inference.

It is the same principle the whole system is built on — **LLM extracts → human
reviews → LLM renders** — applied to grounding-doc generation: cheap local
extraction captures everything, the human decides scope, the API only renders
the reviewed structure.

## The pipeline

```
docs/chapters/chapter_*.md
   │  ensemble_batch.py        (local, Spark — per-chapter fan-out, resumable)
   ▼
docs/ensemble/per_chapter/<stem>/merged.json     atomic facts per chapter
   │  facts_to_state.py --list  ◀── HUMAN CHECKPOINT: scope review (no model call)
   │  facts_to_state.py --known-only   (local, Spark)
   ▼
docs/ensemble/state_dossiers/*.md                per-entity current-state dossiers
   │  Stage 2e: merge type-duplicate dossiers (npc_X + monster_X)  ◀── human step
   ▼
docs/ensemble/merged_dossiers/*.md               ready for synthesis
   │  synthesise_world_state.py        →  world_state_draft.md
   │  campaign_state.py --synthesize-only  →  campaign_state_draft.md
   │  party.py --synthesize-only       →  party_draft.md
   │  planning.py --npc <cut>          →  planning_draft.md
   ▼
docs/*_draft.md   ◀── HUMAN CHECKPOINT: diff against the live doc, promote by hand
```

Two zero-token side tracks feed synthesis: `facts_to_state.py --types thread`
renders `threads.md` (plot threads, deterministic), and `build_recent_events.py`
renders a chapter-ordered `recent_events.md` — the **chronological spine** that
hands the synthesis model the timeline instead of making it reconstruct one
(an LLM weak spot).

## The four stages

| Stage | Tool | Runs on | Output |
|---|---|---|---|
| **1 — Extract** | `ensemble_batch.py` → `ensemble.py` per chapter, multiple lenses (a `plan.yaml` of passes) | **Spark (local)** | `per_chapter/<stem>/merged.json` |
| **2 — Bundle** | `facts_to_state.py` groups facts by `(type, subject)`, collapses to one dossier each | **Spark (local)** | `state_dossiers/` → `merged_dossiers/` |
| **3 — Synthesize** | `synthesise_world_state.py` + the `--synthesize-only` staging trick on `campaign_state.py` / `party.py` / `planning.py` | **API or subscription** | `*_draft.md` |
| **4 — Review** | human diff + promote | you | the live `docs/*.md` |

## Two ways to run synthesis (Stage 3)

- **API** — set `ANTHROPIC_API_KEY`, pass `--model claude-opus-4-8`.
- **Subscription** — every synthesis tool supports `--dump-input --dump-only`,
  which writes the assembled prompt (`*.md` + `*.md.system.md`) to disk *without*
  an API call. Pipe it to `claude -p --system-prompt "$(cat …system.md)"` (Claude
  Code CLI, billed to claude.ai) or paste into the web UI. This is the same
  Claude-Code backend idea as the rest of the system, applied to synthesis.

## The human checkpoints (why scope stays correct)

Extraction is deliberately greedy — it over-captures. Scope is decided by a human
at several gates, never by a model feeding the next model:

1. **`facts_to_state.py --list`** — prints the entity universe and the
   `[known]` vs `[location]`-scoped split; you confirm PCs/major NPCs are
   `[known]` and anonymous labels (guards, orcs) are location-scoped before
   spending any model time. No model call.
2. **Alias review** (`aliases.json`) and **type-duplicate merge** (Stage 2e) —
   human-supervised consolidation; the model never decides identity.
3. **`narrative_importance.yaml`** — GM `force_include` / `force_exclude` overrides
   on the `planning.py` importance cut.
4. **`*_draft.md`** — *all* synthesis lands in `_draft` files; you diff against
   the live doc and promote by hand. **Never write the live docs directly.**

## Where it fits vs. the other flows

- **Supersedes the per-tool grounding refresh.** `distill.py` / `campaign_state.py`
  / `party.py` / `planning.py` still exist and are reused here as *synthesis-only*
  stages, but the old "each tool re-extracts from the chapter bible" path is the
  expensive one this replaces. The legacy how-to is [`docs/cli/grounding_docs.md`](../cli/grounding_docs.md).
- **Orthogonal to RLM retrieval.** Ensemble mines *your own session history* into
  campaign state; RLM ([flow-rlm-retrieval](flow-rlm-retrieval.md)) retrieves
  *external reference* (monsters, adventure prose) from MemPalace / 5etools. They
  meet only in that both ultimately ground the same `prep.py` / narration calls.
- **Feeds session prep.** Its outputs *are* the grounding docs that
  [flow-session-prep](flow-session-prep.md) consumes.

## Prerequisites worth knowing

- **Per-chapter corpus** — `docs/chapters/chapter_NN_*.md`, glob-ordered.
- **A proper-noun consistency pass first** — transcription garbles each fork into
  a separate entity; fix upstream (the `vtt-spell-pass` glossary is the source of
  truth that generates `aliases.json`).
- **Known-names sources** (`*inventory.md`, `docs/npcs/.dedup_state.json`) so
  named NPCs become global dossiers and anonymous labels stay location-scoped.
- **Spark hosts** `spark` / `spark2` running; use IPs in shells where the
  hostnames don't resolve (WSL2/containers) or the client hangs silently.
