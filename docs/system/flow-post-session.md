# Flow: Post-session

> Zoom `.vtt` → summary → scenes → per-character narration → assembled session
> doc. [↑ index](index.md)

**Deep doc:** [`docs/cli/session_doc_pipeline.md`](../cli/session_doc_pipeline.md) ·
entry-point guide: [`docs/cli/post_session.md`](../cli/post_session.md)

---

## What it does

Turns a recorded session into a polished narrative document. It is a chain of
LLM passes with a **human review point after each**, so an error in an early
pass never silently propagates into the prose.

## The sequence

```
summaries/<session>/session.vtt  +  gm-assist.md
        │
session_doc/vtt_summary.py    → session-summary.md
        │            + vtt_extractions/, vtt_roleplay_extractions/
        ▼  (human review)
session_doc/enhance_summary.py → enriched gm-assist        (cached system prefix; --batch capable)
        │
session_doc/scene_extract.py  → scene_extractions/NN_*.md  (per-scene verbatim; VTT cached in prompt)
        ▼  (human review)
session_doc/sd_consistency.py → consistency check across scenes
session_doc/sd_plan.py        → plan.md   (scene structure, pacing, arcs)
        ▼  (human review)
session_doc/sd_narrate.py     → narration/session_doc_scene_NN_*.md   (per-character, per-scene;
        │                                                   reads voice/<char>_voice.md)
        ▼  (human review)
session_doc/assemble.py       → session_doc.md   (final concatenation)
        ▼  (optional)
pipelines/ensemble/polish.py         → agentic refinement loop (read/edit/insert/finish tools)
```

Running alongside: `session_doc/quote_ledger.py` fuzzy-matches VTT roleplay quotes to the
extracted scenes and stores the mapping in `quote_ledger.db`, which the Web UI
uses to sync a replay scrubber.

## Why the `gm-assist.md` anchor matters

`gm-assist.md` is the **authoritative** human record of what happened; the VTT
is raw and noisy. `session_doc/enhance_summary.py`/`session_doc/scene_extract.py` treat the gm-assist as
the spine and use the VTT for verbatim color. See [`docs/cli/gmassist_anchor.md`](../cli/gmassist_anchor.md).

## Backends & batch

Any pass can run on Anthropic, DGX/vLLM, or Claude Code (see
[component-campaigngenerator](component-campaigngenerator.md) → backends). The
two heaviest passes (`enhance_summary`, `scene_extract`) support `--batch`
(Anthropic Message Batches) and prompt caching of the large VTT context.

## Where it runs

CLI per script, or the Web UI session-workflow + Session Doc Editor views (see
[`docs/web/session_doc_editor.md`](../web/session_doc_editor.md)).

## Related

- The pipeline that prepares the *next* session: [flow-session-prep](flow-session-prep.md)
- Feeding summaries back into grounding docs: [`docs/cli/grounding_docs.md`](../cli/grounding_docs.md)
