"""Incremental campaign updates (spec 039): carry published NPC history forward from new chapters.

This package is the ``summary_native delta`` family. Its public surface is empty until the
engine modules land; nothing is re-exported here.

Principle II (the human checkpoint is non-negotiable) names these checkpoints. No model
output in this package is applied, approved or published without one:

1. Chapter selection: a human-chosen input (explicit ``--source``, never a silent "all").
2. NPC census: a human rules on each unresolved, indirect or excluded name.
3. Contextual associations: a human approves each one.
4. Grounding edit proposals: a human approves each replacement before reconstruction.
5. Draft sign-off per item: exact-draft approval, never a model verdict.
6. Unchanged attestations: a human attests each "mentioned, unchanged" NPC.
7. Publication authorization: only an authorized, verified, signed-off draft is published.

Principle V: model calls go through ``campaignlib`` only; never import ``anthropic`` here.
"""

__all__: list[str] = []
