# Specification Discovery: Issue #548

Date: 2026-10-10. Baseline: `5e63e852f3f45dd9bfd9c6b4e62a83cbec43cbc0`.

## Scope and method

Read parent #548 and children #521/#517. Used codebase-memory-mcp with a fresh `cg548` index of this worktree for symbol discovery and snippets; inspected fixture text to distinguish implemented contracts from proposed behavior. Astra authored the specification; GPT-5.6-Sol performed bounded discovery and independent review. No campaign data or runtime source was changed.

This is the preliminary specification inventory, **not the later five-example feasibility spike**. Planning subsequently located the original campaign and recorded its evidence in [spike.md](spike.md); the user approved reconstructed fixtures with historical replay limits on 2026-10-10. The spec requires that spike before detailed #517 design/implementation. The repository does not contain the original paired evidence needed to claim reproduction of all five Phandalin failures.

## Existing contracts and gaps

- `pipelines/summary_native/review/documents.py:create_document_review` creates exact draft sign-off items. `_check_document` validates draft identity, outline, pointers, required references, timeline/run record, audience and dependency freshness.
- `prepare_document_promotion` binds an immutable proposal to a current accepted review decision and its dependency identities. `promote_document_bundle` rechecks it under the authority lock, refuses existing destinations, and writes targets and receipts through the authority transaction mechanism. This is reusable review/publication infrastructure; it is **not evidence of replacement of an existing live four-document generation with atomic reader visibility**. It does not perform semantic cross-document comparison.
- `review/models.py:ReviewItem` already represents claims, evidence locations, diagnostics, categories, severity, rationale, proposed actions, audience, scope, and revision binding. `review/verification.py` adapts NPC findings; its mechanical checks and explicit audience/supersession metadata are narrower than a general grounding claim comparison.
- `authority.py:BaseRecord` supports paired `claim_key`/`normalized_value` attributes. `_detect_automatic_conflicts` checks explicitly structured subject/claim/value relationships with overlapping effective scope. It cannot infer those attributes or choose a recency winner from prose.
- `authority_inputs.py:resolve_planning_precedence` handles existing structured planning authority. Reusing its authority vocabulary does not make arbitrary prose claims deterministically comparable.
- The #548 implementation must bind a complete four-document check and all support artifacts to promotion, add safe replacement and generation visibility, and preserve exact review/freshness gates across existing publication paths.

## Five-example preliminary inventory

| Example from #517 | Evidence found in repository | What can be concluded now | Required spike work |
|---|---|---|---|
| Earthstone task assigned to wrong party | `tests/fixtures/summary_native/authority/docs/authority.yaml`, `docs/summaries/chapter-054.md`, and `notes/earthstone-plan.md` under that fixture | A draft GM ruling has anchored rejected/replacement prose and scope metadata. It is a synthetic correction example, not normalized cross-document claim pairs or a reproduced original campaign failure. | Obtain original paired claims or explicitly label a curated substitute; establish whether attribution is already encoded as comparable reviewed fields. Test a correct-attribution control. |
| Eastern Heart refugees called a hostile Talosian faction | No matching original fixture found in inspected repository | Hostility and faction membership inferred from prose require GM judgment. Generic Talosian text is not evidence of this failure. | Obtain original assertion and authority; represent candidate extraction and GM disposition. Mechanical checking is allowed only if reviewed categorical assertions actually exist. |
| Sridar promoted from plausible collector to conspirator | No matching original fixture found | A change of certainty/meaning cannot be proven by keyword overlap or a resolving citation. | Obtain original evidence; test uncertainty preservation and overstatement with a GM-reviewed candidate and a positive control. |
| Petra's superseded 500 gp proposal retained as active debt | Experiment narration mentions a pending payment, but no paired superseding ruling was found | A pending-payment mention alone establishes neither an accepted debt nor its supersession. | Obtain superseding source and exact affected claim; determine whether status, time, and supersession are explicit enough for a mechanical rule. |
| Leilon immediate despite Cassian/manifold-first ruling | Scattered experiment mentions do not supply the joined claim/ruling pair | No current fixture demonstrates the asserted priority conflict. | Obtain authoritative ordering and the conflicting planning claim; distinguish an explicit structured priority conflict from prose requiring interpretation. |

The initial partition is therefore: **no original case yet proven mechanically catchable end to end from this repository**; Earthstone offers reusable structured ruling infrastructure, while the other four lack paired evidence. This does not preclude deterministic checks after humans supply normalized authority; it prevents claiming those checks already follow from original on-disk prose.

## Planning entry conditions

1. Preserve the issue's sequence: deliver #521's foundation first; complete the #517 spike before committing to its normalized claim representation and detection scope.
2. Record each example's exact evidence, missing inputs, repeatable result, positive control, and human versus mechanical responsibility. If original evidence remains unavailable, keep that acceptance limit explicit instead of treating synthetic data as original-corpus proof.
3. Decide the supported generation-reading and recovery contract with every affected consumer accounted for. Existing file transactions do not by themselves prove atomic visibility of several files to readers.
4. Map existing document sign-offs and rulings into the bundle gate; avoid a second approval store. Checks discovered after sign-off must require disposition before publication.
5. If candidate extraction needs a model, identify explicit selection/cost controls and the human checkpoint. The promotion gate remains deterministic; guarded no-model code must not acquire model calls.
6. Assess all thirteen constitution principles by name in planning, including same-feature application reachability and an explicit migration if storage layout changes.

## Spec Kit resolution

`specify preset resolve spec-template` resolved `.specify/templates/spec-template.md` from the core layer. Sequential numbering selected `037-promotion-gate`. `.specify/feature.json` points at `specs/037-promotion-gate`; it is intentionally ignored by repository policy and remains available locally to downstream commands.

No pre-specification hook is registered. The sole post-specification hook is the optional `speckit.agent-context.update`; it is offered in the completion report and was not run automatically.
