# A relationship index helps with dependency questions

The experiment supports adding a small, deterministic semantic projection to
our provenance tools. It reconstructs dependencies and checks legacy review
bindings from existing records, including links across grounding updates.
It does not establish a reason to deploy NVIDIA Auto Ontology's full stack.
That runtime was not installed or measured.

## Measured result

The final run indexed 686 registry entities and two grounding updates: 1,677
nodes, 1,802 evidence-backed edges, and 51 campaign input files. Building took
0.80 seconds and produced a 1.54 MiB SQLite index on this machine. Reversing the
bundle import order produced the same canonical graph digest. All 11 real-input
evaluation cases and 17 synthetic counterexample tests passed. No campaign
inputs changed.

These are measurements of a small bounded corpus, not a scaling claim or a
comparison with NVIDIA's query system. The complete measurements and input
hashes are under `results/final/`.

## What the graph answered

Changing the Chapter 60 source reaches all four Chapter 60 approval bindings
and recorded live outputs. Changing only the party candidate reaches the party
check, approval and application, without contaminating the other three.
Changing the saved decision file reaches all four approval bindings.

The useful additional answer is transitive: the Chapter 59 source reaches
Chapter 60 through retained origin drafts and baseline copies. The literal
metadata search for that source path finds only two direct references in the
Chapter 59 bundle; the graph follows the intervening declared identities.

```mermaid
flowchart LR
  S[Chapter 59 source version] --> D[Chapter 59 delta]
  D --> O[Chapter 59 party origin]
  O --> B[Chapter 60 party baseline]
  B --> A[Chapter 60 party approval binding]
  A --> P[Recorded application]
  P --> L[Live party version]
```

Every edge cites an existing field in a specific hashed JSON/YAML record.
`results/final/examples.json` supplies the complete concrete trace. Dependencies
come from explicit metadata, not mentions, model inference, filename similarity,
or a claim that equal names imply equal entities.

## A real freshness finding

Both source summaries differ from their approved snapshots: Chapter 59 has
three line-replacement groups; Chapter 60 has four. All eight historical
approval/application bindings still validate against their retained snapshots.
All four Chapter 60 live files still match their approved candidates. Chapter
59 live versions have correctly been superseded by Chapter 60 versions.

Those statements can all be true together. The graph reports `stale_source`
for present-day reuse while preserving historical approval validity. Byte
drift does not establish semantic error. This experiment makes no judgment
about the changed prose and performs no regeneration or approval revocation.

## What remains unanswerable

The registry has 686 declared entities, and exact registered aliases resolve.
A similar unregistered spelling does not acquire an identity. Separate
campaigns, distinct guards, and rejected-alias records retain their boundaries.

However, these grounding records do not bind a registry digest, so the graph
cannot establish which grounding results depend on a registry revision.
There is also no complete tool/code-version dependency binding in this adapter.
An empty path to the grounding documents therefore means missing coverage,
not that a registry edit is safe. This is a producer-record gap, not a graph
database problem.

The prototype covers only the selected legacy grounding records. It does not
ingest native bundle/NPC publication formats, extract story assertions, infer
speaker beliefs or character audiences, or prove semantic consistency. Its
binding checks are internal record consistency checks, not signatures,
independent verification of reviewer identity, or native authority sign-off.
Dependencies are at file/member level, so impact is conservative and does not
identify the minimal affected paragraphs.

## Recommendation

Keep a rebuildable SQLite projection over the current sources and expose
read-only `impact`, `explain`, and answerability operations through provenance.
Before production integration, add explicit consumed registry/config/tool
identities to producer records and implement adapters for native publication
records. Cover producer schemas with versioned contracts rather than guessing
links from unstructured text. The experimental adapter currently accepts only
the demonstrated legacy structure and is not a production promotion gate.

For a later NVIDIA trial, export this same bounded dataset and reuse these
positive and negative cases. Compare answer correctness, trace fidelity,
missing-coverage behavior, operational cost, and latency. The useful ideas
already demonstrated here are typed relationships, source-bound identities,
and explicit answerability limits; natural-language querying remains untested.
