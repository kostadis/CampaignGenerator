# Specification Evidence — Issue #547

Date: 2026-10-09

## Workspace and workflow

- Worktree: `/tmp/campaigngenerator-547`
- Branch: `codex/547-review-adjudication`
- Base: `9feedcf35ce8f7dc8083b75b595231dae483a2a2`, current main including PR #550 / issue #546.
- Active template resolved by `specify preset resolve spec-template`: `.specify/templates/spec-template.md` (core layer).
- Feature numbering: sequential, next after 035 is 036.
- No before-specify hook. After-specify has one optional agent-context refresh; it is offered, not automatically run.
- Astra authored the specification. User selected GPT-5.6-Sol for orchestration and coding; Sol independently reviewed requirements. No application code changed.

## Source issues read

- #547: parent scope, ordering, ruling integration, and open design choices.
- #520: shared phone review, decisions, private capability hosting, grounding documents.
- #523: seven-category verification failure queue and selective reruns.
- #522: identity merges, distinct decisions, preview, safe application, scoped aliases.
- #483: open scoped-alias dependency; GM must decide scope.
- #506: citation validity is not entailment; second/third simulacrum regression.
- #394: real-phone access, cross-device state, saved/pending/failed/stale feedback.
- #369: durable findings and a reusable viewer, replacing browser-only/copy-paste decisions.
- Constitution 2.0.0 and spec 035: disk truth, human gates, summary authority, interface parity, explicit selections, deliberate migration.

## Code discovery

Root used codememory-mcp `search_graph` and `get_code_snippet` against project `home-kostadis-src-CampaignGenerator`:

- `pipelines.summary_native.npc_verify.verify`: mechanical citation, quote, authored-edit checks; typography/status advisories. No semantic entailment guarantee.
- `pipelines.summary_native.duplicates.load_rulings`: accepts only duplicate-exclusion and link rulings, rejecting merge/alias keys.
- `entity_registry.resolve.resolve_name`: identified the current identity-resolution entry point for later planning.

The index targets the original checkout, not this worktree. Root cross-checked verifier and duplicate loader in the new worktree; findings are discovery evidence, not a claim that the index reflects all newly merged authority code. The how-to's “Why canon.yaml cannot merge” section confirms the existing fix-at-summary policy; #547 explicitly asks for a new decision on that policy.

Sol's independent audit used read-only direct inspection after reporting that codememory was not exposed in its tool set. Root performed the requested codememory discovery above.

## Review outcomes

- Shared NPC-first delivery, grounding documents, phone continuity, seven taxonomy categories, selective reruns, identity preview, and freshness all covered.
- Tightened decision-save concurrency/retry behavior, rule-revision freshness, lossless diagnostics, reproducible apply reports, and explicit versus inferred semantic checks after Sol review.
- Approved decisions retain #546 ruling integration; registry application requires an explicit extension rather than treating registry mutation as a summary patch.
- User selected a dedicated LAN/Tailscale capability-URL server.
- User then selected merge-policy option A: registry identity resolution is sufficient; summary edits are required only for incorrect facts and use the separately reviewed #546 correction workflow. FR-015 and story 3 now cover accurate summary wording and factual contradictions explicitly.
- Final specification checklist: 16/16 passed; no unresolved clarification markers remain.
- Full implementation planning and all-principle constitution assessment belong to the next phase after specification approval.

## Planning workflow evidence

- Read speckit-plan and ran setup-plan from the isolated worktree. Template resolution succeeded; the script returned feature identifier 036-review-adjudication, while verified Git branch remains codex/547-review-adjudication.
- No before-plan hook; after-plan contains only optional agent-context refresh.
- Astra authored plan/research/data model/contracts/migration/quickstart; Sol independently researched registry and authority integration and reviewed contracts.
- Codememory found narration serve and NPC verifier entry points; newly merged authority symbols were absent from the older index, so direct worktree reads verified those primitives.
- Research resolved the registry scope boundary: registry v1 remains, persistent/global merges only; scoped requests block pending #483. Evidence-bound distinct decisions stay in review/authority state and never become global registry guards.
- Official Tailscale and OWASP references support the private access and browser request controls documented in research/security contracts.
- Planning creates documentation only. No application implementation, live campaign mutation, service start, schema migration, or runtime acceptance result is claimed.

### Final planning review

Sol's final review identified two ambiguities, both corrected: semantic review digests exclude containing-file custody hashes while mutation proposals bind current full hashes; phone duplicate review selects locally prepared immutable canonical alternatives, with custom choices requiring a new local preview and renewed approval.

All 12 Markdown artifacts were checked for unresolved template/clarification placeholders, balanced code fences and valid relative links. Checks passed; Git whitespace validation passed. All thirteen constitution principles are assessed before/after design in plan.md. Runtime/security/phone acceptance remains future implementation work. No tasks.md was generated in this planning phase. Optional agent-context hook was offered, not executed.

## Task generation

- Ran setup-tasks in the feature worktree and used its resolved template content. Read the design contracts, migration and quickstart along with spec/plan and constitutional gates.
- Generated 66 unchecked tasks: setup 2, foundation 9, US1 15, US2 12, US3 15, US4 7, cross-cutting gates 6. Fifteen tasks carry documented parallel markers.
- Sol audited scope/dependencies. Incorporated early recovery CLI/UI support for independently usable US1; explicit authority record-reader/conflict/tip compatibility checks; first-slice renderer/asset security tests; and migration operator verification instructions.
- Validated sequential IDs, checkbox syntax, story labels, concrete file paths, counts and relative document links. Git whitespace validation passed. No before_tasks or after_tasks hooks are registered.
- No production code was changed or application tests run by task generation.
