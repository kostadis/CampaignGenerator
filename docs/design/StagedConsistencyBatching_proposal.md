# Grouped Stage 2 Consistency Audit

**Status:** Approved for implementation  
**Scope:** Codex `staged-consistency`, Stage 2 batch-review mode only  
**Decision:** One grouped model call; fail closed; never silently fall back

## Problem

Stage 2 checks every `scene_extractions_new/0*.md` file independently, then
consolidates the findings into one review page. Every check resends the same
canon, campaign state, world state, party data, prep, glossary, and supporting
context. The Codex subscription backend launches a fresh `codex exec` process
for every call, so no session state carries that context between scenes.

For `N` scenes, common context `C`, and scene documents `D_i`, the present input
cost is approximately:

```text
N * C + sum(D_i)
```

A grouped audit costs:

```text
C + sum(D_i)
```

The saving is `(N - 1) * C`. The Phandalin 2026-08-25 session has eight scene
files totalling about 100 KB, while the standard canon/state/party/glossary set
alone is about 337 KB before prep and other evidence. The repeated context, not
the scene text, is the dominant input cost.

## Goals and non-goals

The feature must:

- audit every explicitly selected Stage 2 scene in one Codex call;
- transmit common context once;
- preserve the existing advisory report, adjudication, standalone review page,
  explicit GM verdict, approved-fix, and propagation-sweep boundaries;
- make complete target coverage mechanically verifiable;
- expose enough telemetry to verify the token-saving claim;
- leave the existing one-document CLI behavior unchanged.

The first version does not:

- batch interactive review, because that mode can apply a correction before the
  next scene is audited;
- silently split an oversized run into groups;
- silently retry a failed grouped run per scene;
- add a Session Editor surface or configuration setting;
- let one generated scene extraction become evidence that another is correct.

The grouped path is deliberately an explicit-selection operation. The skill
enumerates the scene paths in order; an empty selection never means "all."

## CLI and data flow

`check_consistency` accepts one or more positional targets:

```text
check_consistency DOCUMENT [DOCUMENT ...]
```

One target follows the pre-existing prompt and report path. More than one target
activates grouped mode. Duplicate paths, directories, and missing files fail
before a model client is created.

Grouped mode assigns stable request-local identifiers (`D01`, `D02`, ...),
assembles the common context once, and sends this shape:

```text
Documents to Check
  D01 + path + body
  D02 + path + body
  ...
Campaign Context
  authoritative canon
  campaign/world/party state
  selected prep, glossary, transcript evidence, and other context
```

Target documents are peers under review. They may reveal a disagreement, but
neither target is an authority for choosing the fix direction. The grouped
prompt tells the model to resolve a disagreement only from higher-trust context;
otherwise it must surface a GM ruling.

For long correction glossaries, the engine also scans Markdown wrong/right
tables locally. Exact whole-token wrong forms that occur in a target become a
short, target-local review-anchor list. These anchors improve late-document
recall without retransmitting the full glossary. They are attention aids rather
than automatic verdicts; glossary exceptions and longest-match rules still
govern the judgment.

The CLI prints:

- selected-document and target-character counts;
- shared-context character count, including the system prompt;
- model-call count (one);
- repeated common-context characters avoided.

The character figures are deterministic observability, not a claim about the
provider's tokenizer.

## Response protocol

Every target must have one matched section, in request order:

```text
<<<CG-CHECK D01 BEGIN>>>
...findings using Location / Target text / Issue / Evidence / Suggested fix...
<<<CG-CHECK D01 END>>>
```

A clean target contains the exact word `CLEAN`. After the target sections, the
model must emit exactly one `CG-CROSS` section, either `CLEAN` or findings that
also name `Affected documents`.

The parser rejects the whole response when it contains any:

- missing, unknown, duplicate, out-of-order, nested, or incomplete section;
- malformed marker;
- empty section;
- finding missing a required field;
- target finding whose exact `Target text` excerpt does not occur in the target
  assigned to that section;
- text outside the protocol markers.

Only a fully valid response is normalized into readable Markdown. Markers and
request-local identifiers are mapped back to the actual paths locally; the model
never controls that mapping. The output file is atomically replaced only after
validation. A backend, timeout, empty-result, or protocol failure returns
nonzero, preserves any prior report, creates no sources manifest or review page,
and performs no automatic fallback.

## Staged-consistency integration

The Codex skill retains its stage ordering and its review-mode question.

- Interactive Stage 2 continues to call `consistency-check` once per scene and
  permits review between calls.
- Batch-review Stage 2 explicitly enumerates sorted `0*.md` files, excluding
  `.prev` and `.scaffold`, and passes every path to one `check_consistency` call.
- The grouped report is still advisory. Codex adjudicates findings against
  transcript and campaign evidence before constructing review cards.
- The existing Stage 2 page remains one page with one consent unit per finding,
  stable `s2-NN` ids, and the same approve/reject/discuss semantics.
- The sources manifest records every selected path plus grouped telemetry.
- Approved fixes and the final propagation sweep remain downstream of the human
  decision JSON.

The implementation spans CampaignGenerator and the symlinked Codex skill in the
`mytools` repository. One CampaignGenerator issue is the umbrella tracker for
both changes.

## Constitution check

- **Disk is Truth / Human Checkpoint:** the model still produces an advisory
  report; the GM remains the only authority that approves edits.
- **Verbatim is Sacred:** grouped context does not authorize quote rewriting;
  quote-level fixes retain transcript evidence and editorial-note requirements.
- **CLI is the Engine:** multi-document orchestration is implemented in the CLI;
  the skill invokes it rather than reimplementing prompt or parsing logic.
- **Extract Once, Synthesize Deliberately:** consolidation is allowed only after
  a recall/attribution gate. The batched quote feature demonstrated that wider
  context can initially reduce depth and increase confident identity drift.
- **Explicit Selection:** the skill materializes every selected scene path.
- **UI Parity:** the operator explicitly scoped v1 to the Codex batch-review
  workflow. The Session Editor's existing single-document action is unchanged.

## Verification and shipping gate

Automated tests cover:

- single-document backward compatibility;
- one call for several documents with common context appearing once;
- exact document ordering and path attribution;
- exact-match glossary anchors without substring false positives;
- every protocol rejection class;
- preservation of an existing report on grouped failure;
- rejection of duplicate/missing targets before a model call;
- unchanged provider-batch and Codex error behavior.

The manual quality gate uses temporary copies of the eight Phandalin 2026-08-25
scenes. Reinsert the seven already-adjudicated defects recorded in that session's
Stage 2 report, then compare the old per-scene path with grouped mode against the
same context.

The feature ships only if grouped mode:

1. detects all seven seeded defects, including early, middle, and late scenes;
2. misses no human-accepted Critical or Moderate baseline finding;
3. attributes every finding to the correct target or explicit cross-target set;
4. produces one complete Stage 2 review page and preserves the human gate;
5. reports one common-context transmission instead of eight.

### Measured implementation validation

The final quality run used temporary copies of all eight Phandalin 2026-08-25
scene extractions, the full production context set, and the previously accepted
defects reinserted. It completed in one Codex call and reported:

- 98,727 target characters;
- 524,411 shared-context characters, including the system prompt;
- 3,670,877 repeated common-context characters avoided versus eight calls.

The grouped result found every seeded manifestation: `Oral and Vance`, both
early and late `Valfinier` occurrences, `Bourd bear`, `Bourd laid bare`,
`Shapal`, `Pero`, and `Mark Gordon`. The exact-excerpt validator attributed each
finding to the file that actually contained it. The benchmark drove two final
safeguards now covered by tests: mandatory independent prose and verbatim passes,
and target-local exact glossary anchors for reliable recall across long batches.
