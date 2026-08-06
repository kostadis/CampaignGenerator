"""Cross-campaign, provenance-aware search over the campaign workspace.

The read-only seam (Constitution V) between "what is written on disk across six
campaigns" and "what a Claude session is allowed to believe about it." Every hit
comes back wrapped in a provenance envelope naming its owning campaign, its trust
tier, whether it is machine-generated (and by which stage), its chapter, and any
correction the GM has recorded against it.

Three hard constraints, each statically guarded by a test:

- **Never writes.** Not to campaign content, not to identity stores, not to a
  cache or an index (FR-031, FR-032; ``tests/test_provenance_readonly.py``).
- **Never calls an LLM.** No ``anthropic``, no ``campaignlib.api``, anywhere
  under this package (FR-033; ``tests/test_provenance_no_llm.py``).
- **Never imports ``server/``.** This is engine, not face (Constitution VI;
  ``tests/test_layering.py``).

It also never *infers*. Tiers come from hand-authored manifest globs, chapters
from a hand-authored filename regex, corrections from a hand-authored record.
Nothing is derived from a directory-name heuristic or a file's contents — that
would be the tool making the scope decisions this feature exists to keep with
the GM (Constitution II).

Module map (see ``specs/007-cross-campaign-search/plan.md``):

    manifest.py        ProvenanceManifest models + loader; workspace-root resolution
    corrections.py     CorrectionRecord models + loader + the path-and-subject matcher
    tiers.py           Glob -> TrustTier classification, with ambiguity reported
    scan.py            Scanner interface; the rg and stdlib-Python implementations
    identity.py        Read-only adapter over campaignlib.registry
    backends.py        Backend roster + honest per-machine probes
    envelope.py        ProvenanceEnvelope + deterministic total-order ranking
    search.py          Orchestration: scope -> scan -> classify -> annotate -> rank
    cli.py             The `provenance` console script (the engine)
    provenance_mcp.py  The `provenance_mcp` server (the outward seam)
"""
