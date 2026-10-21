"""npc_agent — prototypes toward an agent that plays an NPC.

Design and the prototype series: ``docs/design/NpcAgentPrototypes_proposal.md``.

Prototype 1 (this package today) is deterministic: it lists the summary items
that name an NPC with a published dossier, checks that list against the
dossier's own frontmatter, and, given the GM's presence ruling, builds the
NPC's knowledge horizon at a chapter. Who was present in a scene is an
attribution decision, so code never makes it: the GM rules, code reads.

No model call anywhere (guarded by ``tests/test_npc_agent_no_llm.py``).
"""
