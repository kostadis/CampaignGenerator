# Comparison with NVIDIA Auto Ontology

Documentation reviewed 2026-11-04. This is an architectural comparison with the repository's documented behavior, not a measured NVIDIA runtime trial. NVIDIA Auto Ontology was neither installed nor run. Links below follow upstream `main` and may change.

| Dimension | Our prototypes | NVIDIA's documented system |
| --- | --- | --- |
| Purpose | Campaign artifact lineage and creature-mention identity | Semantic definitions and natural-language analytics over structured databases |
| Inputs | Registry records, generation/review bundles and raw campaign passages | Database metadata, tables, concepts and semantic relationships |
| Identity | Explicit encounter, time, group/member and ambiguity cases | Business identity, source keys, populations and relationship contracts |
| Provenance | Hash-bound generation dependencies and historical approval bindings | Semantic source mappings, query SQL and rows; semantic paths do not themselves establish generation/version lineage |
| Model calls | During experimental text resolution; saved lookups can be deterministic | Natural-language `ask_question` runs a text-to-SQL agent with sequential model calls; semantic discovery is separately exposed |
| Delivery | Standalone experimental scripts and SQLite projections | Application, authentication, database stack, REST and MCP |

Sources: [repository overview](https://github.com/NVIDIA/auto-ontology), [modeling guidance](https://github.com/NVIDIA/auto-ontology/blob/main/skills/nvidia-ontology-management/references/modeling.md), [semantic-path limits](https://github.com/NVIDIA/auto-ontology/blob/main/skills/nvidia-ontology-management/SKILL.md), and [MCP/query behavior](https://github.com/NVIDIA/auto-ontology/blob/main/docs/mcp.md).

NVIDIA's guidance explicitly rejects names or equal current row sets as sufficient proof of conceptual identity. The comparison therefore does not claim that its design relies on globally unique names. We found no demonstrated equivalent of our passage-level ogre/orc resolution fixture in the reviewed documentation, but absence from those documents is not proof that the platform cannot support it.

NVIDIA could serve as an analytics/query layer over correctly modeled creature instances, mentions and encounter memberships. It would not remove the need to extract, validate and review those relationships first. Its publication guidance also distinguishes a retained receipt from durable publication and describes limits of current certification/promotion APIs: [publication workflow](https://github.com/NVIDIA/auto-ontology/blob/main/skills/nvidia-ontology-management/references/publication.md).

Useful ideas to adopt are semantic contracts, explicit readiness/answerability checks, and a curated read-only agent interface. The immediate recommendation is to complete the smaller provenance/identity layer before adopting a database analytics platform. A future head-to-head trial should export the same bounded dataset and compare correctness, evidence fidelity, ambiguity, missing coverage, latency and operational burden. Current measurements support no NVIDIA performance claim.
