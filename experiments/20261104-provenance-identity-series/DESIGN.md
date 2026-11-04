# Design and boundaries

## Two different kinds of relationships

Artifact provenance links source revisions, generated candidates, checks, saved decisions, approvals, applications and live outputs. A disposable SQLite projection imports declared dependencies with source-record hashes and JSON pointers. It distinguishes a historically valid approval from a currently stale source. Missing dependency coverage means unknown, not safe. This layer uses no model.

Narrative identity links mentions to possible individuals or groups. An opaque instance ID survives movement and renaming; a species label and a location are evidence rather than identity keys. The synthetic resolver demonstrates this over explicit time-bounded facts. The prose experiment then asks a model to propose relationships from exact marked occurrences in raw summaries.

These are separate prototypes. No automatic bridge promotes model proposals into the production entity registry. The current registry still requires unique canonical names/aliases, and its schema was not changed.

## Passage-level resolution

The frozen task includes 14 passage blocks, 22 marked references and 16 comparison cases from seven selected campaign summaries. References include offsets, exact surfaces, and display excerpts with target markers. Gold is held separately and never included in model requests.

The relation vocabulary distinguishes exact coidentity, established distinctness, different reference scopes without proven disjoint membership, explicit overlap/membership, ambiguity, and corrected nonreferents. Individual/group/kind granularity is recorded separately. This avoids treating three members as their entire faction or different locations as proof of different individuals.

Generation goes through `campaignlib.api`. The deterministic evaluator checks response coverage, relation vocabulary, granularity, exact quotation coverage of each marked occurrence, and contradictions between coidentity clusters and explicit distinctness. Quote coverage is not semantic proof. Proposals retain uncertainty and require the existing human authority process before becoming canonical.

## Reuse and invalidation

Inference belongs at new/changed evidence ingestion or explicit re-resolution. Ordinary lookups can read stored relationships. The prototype SQLite proposal cache keys the full supplied payload plus campaign, model, effort, instructions, registry/rulings revisions and pipeline version. Repeated ambiguity is a reusable result. Cache hits confer no approval; canonical requests require a separate reviewed decision ledger.

Because the model saw the complete passage batch, every passage is a dependency. Editing even one passage invalidates all 16 cached pair results. Registry/ruling revision fields are exercised as prototype inputs; the original text trial did not ingest those authorities. No automatic inference on misses, producer integration, or selective production invalidation is implemented.

An optional model that interprets a new natural-language question or writes an answer is a separate concern from stored mention identity. The cache experiment does not establish a complete model-free question-answering system.

## Remaining implementation work

Producer records need explicit consumed registry, configuration and tool identities. The provenance adapter needs coverage of native publication formats. Context resolution needs independent GM adjudication and broader fixtures, including newly introduced candidates and temporal continuity. Smaller encounter/candidate bundles must be accuracy-tested before using them to reduce invalidation. A read-only `resolve`, `explain`, `impact`, and `check_answerable` interface could expose approved facts and clearly marked proposals without merging their authority.
