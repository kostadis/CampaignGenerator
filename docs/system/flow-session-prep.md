# Flow: Session prep

> Grounding docs (+ approved dossiers) → encounter/beat notes for the next
> session. [↑ index](index.md)

**Deep doc:** [`docs/cli/session_prep_workflow.md`](../cli/session_prep_workflow.md)

---

## What it does

Takes the campaign's long-lived grounding documents and produces the notes you
run a session from — encounter beats, lore tidbits, NPC behavior. The LLM drafts
*inside* a structure you've already approved; it does not decide scope.

## The sequence

```
docs/campaign_state.md + world_state.md + planning.md + party.md
        │
        │  (optional) RLM retrieval has already produced and you have approved
        │  docs/dossier_proposal.md  — see flow-rlm-retrieval
        ▼
pipelines/session_prep/prep.py  --mode single | pipeline   [--session BEATS.md]   [--require-proposal]
        │   require_approved_proposal()  ← gate (only when --require-proposal set)
        │   make_client()  → Anthropic | DGX | Claude Code
        │   stream_api / call_api   (voice/ + examples/ injected for style)
        ▼
prep beats / encounters / lore   → stdout (SSE to Web UI) + optional <output>.md log
```

**Inputs** (all human-verified Markdown): `docs/campaign_state.md`,
`world_state.md`, `planning.md`, `party.md`; per-NPC `voice/`; style `examples/`;
and — if RLM is in play — an **approved** `docs/dossier_proposal.md`.

**Modes** (`pipelines/session_prep/prep.py --mode`): `single` (default — one beat) or `pipeline` (three
sequential calls through the `lore_oracle` / `encounter_architect` /
`voice_keeper` prompts in `config/agents/`). These are the *only* two modes.
`--session BEATS.md` is a **separate** input flag, not a third mode: it repeats
the chosen mode once per beat in the outline file.

## The checkpoints

This flow embodies the system's core rule (extract → **human review** →
render):

1. The grounding docs are themselves products of the grounding-docs refresh
   (`pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/party.py`, `pipelines/grounding/planning.py`), each reviewed
   before it lands.
2. If RLM retrieval feeds this, running with `--require-proposal` makes
   `proposal_loader.require_approved_proposal()` hard-stop `pipelines/session_prep/prep.py` until you've
   marked `docs/dossier_proposal.md` approved — so a scope decision is never
   inherited unreviewed.

## Where it runs

CLI directly (`pipelines/session_prep/prep.py`), or the Web UI `/prep` router → `subprocess_runner` →
`pipelines/session_prep/prep.py`, streaming output as SSE. Same code either way.

## Related

- The retrieval that feeds the optional dossier: [flow-rlm-retrieval](flow-rlm-retrieval.md)
- Refreshing the grounding docs themselves: [`docs/cli/grounding_docs.md`](../cli/grounding_docs.md)
- The other big pipeline (after you play): [flow-post-session](flow-post-session.md)
