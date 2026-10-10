# Research: Shared Review and Identity Adjudication

## R1 — Delivery boundary and authority

**Decision:** Deliver the common review engine together with NPC verification, then duplicate adjudication, then grounding-document review in the same feature. Astra owns planning; Sol orchestrates and codes. The user selected a dedicated LAN/Tailscale capability server and registry identity merges without mandatory summary edits.

**Rationale:** #547 explicitly orders the consumers. #546 is merged at the worktree base `9feedcf`; summaries govern events and claims. Identity normalization is a different operation from factual correction.

**Alternatives considered:** A standalone empty review framework, another review page in the main app, and obligatory summary rewrites were rejected by issue requirements or user decisions. Transport job resume (#519), graph editor (#535), and wholesale narration-review migration remain excluded.

## R2 — Existing review transport cannot be the access boundary

**Decision:** Introduce `pipelines/summary_native/review/` as the CLI domain, with a dedicated FastAPI adapter and packaged static viewer. Use the existing bounded subprocess seam for all HTTP domain operations. Existing Vue screens launch/manage the service and open its page; they do not duplicate adjudication.

**Evidence:** Codememory located `session_doc.review.serve.serve`; its current implementation binds `0.0.0.0` and explicitly describes unauthenticated read/write access. It is a narration-specific service, not a capability server. `sd_review` is an unrelated scene export/apply contract. `server/subprocess_runner.py` already provides bounded JSON execution and redaction; `server/routers/summary_native.py` uses it for authority commands. `pyproject.toml` already packages pipeline resources and depends on FastAPI/Uvicorn/Pydantic. No new database or production framework is needed.

**Alternatives considered:** Reusing the unauthenticated handler, adding public routes to the full application, or exposing an arbitrary filesystem tree would violate the selected access boundary. A second Vue adjudication screen would recreate the split workflow.

## R3 — Private access and capability lifecycle

**Decision:** Require an explicit bind address and advertised origin. Allow explicit private LAN binding or loopback behind a configured Tailscale Serve origin. No automatic publishing or wildcard binding. Use a high-entropy review capability, revocable grant, same-origin browser writes with a custom CSRF header, strict Host/Origin validation, no CORS, and no external viewer resources. Provide TLS certificate options for direct serving; plain HTTP on a LAN is supported only as an explicitly selected trusted transport and does not provide confidentiality.

**Rationale:** The capability is a bearer credential for exactly one review, not account authentication. Restrict the server to reading its prepared review and recording decisions there; it cannot apply source changes or select arbitrary files. Tailscale Serve is private to the tailnet; Funnel is public and is not a supported launcher mode. See [Tailscale Serve documentation](https://tailscale.com/docs/features/tailscale-serve) and [Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel). Browser writes require explicit origin checking and a non-simple custom header, following [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

**Alternatives considered:** IP reachability alone, wildcard CORS, GET mutations, bearer tokens in query strings, remote Markdown images, and trusting arbitrary proxy headers are rejected. Security contract and tests are release requirements, not a claim that unimplemented code is secure.

## R4 — Durable review, stable identity, and revisions

**Decision:** Persist strict versioned review manifests, immutable item revisions, and immutable decision events under `docs/reviews/`. Item identity names a subject and occurrence independently of line numbers; a separate digest binds exact content, relevant evidence, rule revision, scope, audience, and disposition. Reconcile regenerated occurrences conservatively. If unique continuity cannot be established, create a new item and stale the old one; never guess an approval transfer.

**Rationale:** Text or line numbers alone are unsafe identifiers. Whole-campaign hashes would invalidate unrelated approvals. Full source hashes still bind source mutation, while excerpt/dependency hashes establish review continuity. The authority writer lock/journal serializes decision saves and shared ruling writes. Request IDs make lost-response retries idempotent; expected item and decision revisions prevent last-write-wins.

**Alternatives considered:** Browser-local truth, line-number keys, a database, and a single mutable decisions document without history fail durability or audit requirements. Browser pending text is transient and never counted as saved.

## R5 — Mechanical verification and semantic judgment

**Decision:** Keep `npc_verify.verify` deterministic and preserve its existing codes/advisories. Add a queue adapter plus small scoped checking functions for reruns. No new automatic model call. GM-authored/imported semantic findings use the same queue; deterministic ordinal/number discrepancies are only advisory candidates. The seven taxonomy categories describe findings, independently of the original diagnostic and its assignment basis.

**Evidence:** Current `npc_verify.verify` validates citations/quoted spans/manual edit usage and has typography, status-word, and attribution advisories. `_npc_verify` currently runs a whole selected dossier and writes verification outputs. None certifies entailment. A targeted rerun must not call whole-dossier verification and merely hide its other results.

**Alternatives considered:** Automatic semantic approval, counting valid citations as support, or adding an expensive model gate are rejected. Human no-change approval can settle a semantic question; it cannot waive a broken citation or claimed-verbatim mismatch.

## R6 — Extend shared rulings deliberately

**Decision:** Migrate the live authority ledger to version 2 with discriminated `review_decision` records, retaining existing ruling/note shapes and source-replacement behavior. A review decision links to an immutable common decision event and, when appropriate, a typed identity or source proposal/receipt. Only applied source rulings affect source truth. Review acceptance does not become an independent factual overlay. Identity mutations have a dedicated adapter and exact reviewed target set.

**Rationale:** FR-014 requires #546 integration, but its `RulingRecord` requires a maintained-summary source and replacement text. Forcing a registry change into that shape would violate its contract. All authority readers must explicitly handle the new audit-only record type without treating it as planning content or a source correction. The migration preserves old receipts, ledger snapshots, and history; historical version decoding is not live-state fallback.

**Alternatives considered:** Parallel competing ruling stores, pretending registry YAML is maintained-summary prose, and silently broadening `canon.yaml` are rejected. Authority source proposal/apply remains summary-only.

## R7 — Transactions and regeneration

**Decision:** Extend the existing campaign authority transaction mechanism to support explicit create/replace/delete targets with before/after existence and hashes. Preview deterministic identity outputs in a staging area, then approve and commit exact bytes. Never run a model inside the writer lock. Mark affected generative drafts stale and record explicit regeneration work; regenerated prose needs a fresh review/sign-off.

**Evidence:** `authority_apply.py` already provides locking, immutable snapshots, pending-transaction refusal and forward recovery, but its current writer only installs after-bytes (`after_exists=True`); it cannot safely implement deletion/rename by simply accepting new targets. Rename is represented as reviewed destination creation and old-path deletion, both covered by recovery. Model-produced output must never be silently replayed as if deterministic.

**Alternatives considered:** Ad hoc chained renames, source write followed by best-effort registry write, broad rebuilds, and claiming cross-file filesystem atomicity are rejected. Unexpected bytes require attention, never forced overwrite.

## R8 — Grounding review and promotion

**Decision:** Register the four existing draft document types as whole-document sign-off items plus any findings. Export exact bound decisions. Add a narrow reviewed-bundle promotion adapter only where current workflows use manual copies; reuse existing outline, pointer, freshness and audience checks. Preserve NPC publication's existing checks and require document sign-off separately from item resolution.

**Evidence:** Existing tests copy drafts into `reviewed/<name>` to emulate GM promotion; the summary-native CLI has `npc-publish` and `check-pointers`, not a generic grounding promotion command. A plan must not claim a nonexistent promotion command is already integrated.

**Alternatives considered:** Implicit promotion when progress reaches 100%, rewriting generator pipelines, or treating one resolved finding as whole-document acceptance are rejected.

## R9 — Bounded scope support and registry compatibility

**Decision:** Keep entity registry schema v1. Applicable merges require both identities and all retained aliases to be explicitly persistent/global, compatible types, and no unresolved distinct/rejected-alias guard. A requested chapter/scene/location-limited alias is preserved as a blocked proposal with `REVIEW_SCOPED_ALIAS_UNSUPPORTED` and zero identity/dependent mutation pending #483. Nonpersistent entities or mismatched scopes also refuse. This is the safe-refusal boundary expressly permitted in the spec, not a claim to implement #483.

**Evidence:** Sol traced `campaignlib.registry.Registry`, `entity_registry.registry.cmd_merge` and consumers. V1 has flat string aliases and entity-wide scope; `alias_to_canonical`, `canonical_to_aliases`, `explicit_aliases_by_type`, and `known_names` cannot carry per-alias scope. Existing `cmd_merge` directly saves, discards loser scope and only warns on type mismatch. Reviewed application builds a pure candidate registry and stages exact bytes; it must not call that mutating command. Subject audit identity retains immutable before/after names and review-local IDs; historical records must not require a removed loser to remain canonical.

**Alternatives considered:** Implementing full per-alias scope would resolve decisions #483 explicitly leaves open and require a coordinated migration of every consumer. Encoding a local alias as a global string would silently misidentify entities. Neither is acceptable here.

**Consumer regression inventory:** summary-native duplicate grouping/validation/build, CLI NPC name selection, npc_forms/npc_link, annotate, state_sections, key_npcs; entity_registry.resolve and registry MCP; provenance identity/expansion; ensemble facts_to_state/synthesise_facts/synthesise_world_state/synthesise_polish and known-name selection; campaignlib.npc/grounding planning; normalize_bible_headings. Existing global projection behavior remains, and no scoped record is introduced that those consumers can flatten. Existing inferred first-name behavior does not authorize a merge and must not enlarge an identity proposal's reviewed alias set.
