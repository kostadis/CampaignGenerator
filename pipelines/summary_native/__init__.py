"""summary_native — a fourth grounding-doc rendering path.

It parses already-reviewed structured session summaries directly (no
extraction pass), validates the whole directory in one pass, builds a
deterministic evidence corpus, and renders grounding-doc *drafts* from it.

Separation is deliberate (spec FR-011): this package imports nothing from
``pipelines/ensemble``. Mixing the two corpora would let an unreviewed
extraction leak into a path whose whole point is that its input was reviewed.
"""
