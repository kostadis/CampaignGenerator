# Research: Per-Item Source Custody (042)

Every decision below comes from reading the code in this worktree at `5b8d09f`, and from reading the real stormgiants review `~/storm-giant/stormgiants/docs/reviews/npc-review-6ee694eebf5b`, read only. Each decision names the file it rests on.

## R1 — Where custody is checked today

| Site | What it checks | Fate |
|---|---|---|
| `review/store.py::save_decisions` L579–582 | It re-hashes **every** `custody.sources` entry under the exclusive authority lock. Any difference raises `REVIEW_STALE_CUSTODY: source bytes changed`, which names nothing. | Replaced by a per-item check (R9). |
| `store.py::import_review_bundle` L915–916 | `raw["custody_digest"] != custody.custody_digest`. This compares two **records**. It reads no file. | Kept, and a per-item byte check is added (R10). |
| `npc_publish.py::_current_draft_signoff` L283–291 | `all(current == source.sha256 for source in custody.sources if relevant is None or source.path in relevant)`. Without a spec 039 dependency graph, `relevant is None`, so every source must be current. This is the root cause of #633. | Replaced by the item's dependency set, unioned with the graph (R13). |
| `review/cli.py::_document_section` L253–260 | A grounding-document page checks the document's own binding. | Already per item, so it is left unchanged. |
| `store.py::refresh_review`, `read_snapshot`, `retract_decision` | Rebind and generation; binding validity; withdrawal. | Unchanged (FR-008, FR-009, FR-014). |

`retract_decision` already never reads custody, so FR-009 holds today. It gets a regression test only.

## R2 — Compute the dependency set at check time, or record it at build time

**Decision**: compute it at check time, from data the review already holds. No new field is stored.

An item's dependency set is a function of three things:

1. its recorded bindings;
2. the review's custody record, which gives each source's path and recorded sha256 for the current generation;
3. the bytes of its NPC's evidence file(s).

Point 3 is the delicate one, because the evidence file itself may have changed. The rule is: **parse an evidence file only when its current bytes hash to the custody-recorded sha256.** Then the current bytes *are* the recorded bytes, and the `Source:` list read from them is exactly the list that would have been recorded at build time.

When the evidence file has changed, is missing, or cannot be read:

- The evidence file belongs to the item's dependency set (FR-003, FR-004), so **the item is stale whatever its summary list would have been**. The staleness verdict is therefore identical to the record-at-build design, on every input.
- For the *detail* only, the summary part falls back to all summary-role sources (R5). The refusal and the status may then list a changed summary that a build-time record would have left out. That is over-reporting on an item that is refused anyway. It never under-reports.

**Why not record it at build time**:

- **It changes the store's shape.** It would need a new item or custody field, a migration document and a one-shot migrator (XIII). Existing reviews, including the real stormgiants one this feature exists for, would get no relief until migrated.
- **The build-time data is the wrong data.** `_create_verified_dossier_review` (`review/cli.py` L559–608) receives `summary_paths` per dossier, and the full-range build passes every range summary, not the evidence-named ones. Custody then de-duplicates by path, so per-NPC summary membership is not even recoverable from custody. Recording "what the builder was given" would reproduce the whole-review coupling.
- **Check-time computation is already exact** by the argument above.

**Alternatives rejected**:

- **Parse the evidence file's current bytes unconditionally.** If the evidence changed, the current `Source:` list is not the recorded one. That is harmless for staleness, as shown above, but the refusal's file → item map would then claim a dependency that never held. Gating the parse on the custody hash keeps the detail honest.
- **Use the frontmatter `chapters:` list instead of `Source:` lines.** Mapping a chapter number to a summary path needs a filename convention. The `Source:` lines already name exact campaign-relative paths, which is what FR-003 specifies.

## R3 — The baseline hash is the custody generation's, not the binding's

**Decision**: compare each dependency's current bytes with `custody.sources[source_id].sha256`, the current generation. Never compare with `binding.custody_sha256`.

**Rationale**:

- `refresh_review` (store.py L772–828) re-hashes every source into the new generation. It revises only the items it marks stale.
- A *preserved* item, one whose context digest is unchanged, keeps a binding sha from an older generation. `read_snapshot` explicitly accepts that through `historical_match`.
- Comparing with the binding would refuse every preserved item forever after a refresh.
- This is also exactly today's baseline. Today's loop compares with `source.sha256` too. FR-002's "recorded when the review was built (or last refreshed)" is the custody generation.

## R4 — Source roles

The review builders (`review/cli.py` L429 and L571–580) name every source `f"{role}-{sha256(path)[:16]}"`. The role is one of `draft`, `evidence` or `summary-<n>`. On stormgiants this gives 164 `draft-*`, 164 `evidence-*` and 84 `summary-*`, 412 in all.

**Decision**: `custody.role_of(source_id)` classifies a source by its prefix:

- `draft-` → `draft`
- `evidence-` → `evidence`
- `summary-` → `summary`
- anything else → `other`

An `other` source is put into **every** item's dependency set. None exists today. If a future builder adds one, the check stays as strict as today rather than silently ignoring the file.

**Alternative rejected**: inferring the role from which items bind a source. An NPC with no finding items has an evidence file that no item binds, so it would be misread as a summary.

## R5 — Evidence → summaries (FR-003)

`npc_link.py` (L482–497) and `corpus.py` L411 write `- Source: <campaign-relative path> (line N)` under every entry, scene and moment. The delta path, `delta/npc_update.py` L355, writes `- Source: selected evidence`, which is not a path.

**Decision**: `custody.evidence_summary_paths(evidence_bytes, custody_paths) -> frozenset[str] | None`. It returns `None`, meaning the item falls back to every summary-role source, unless **all** of these hold:

1. at least one line starts with `- Source:`;
2. **every** such line matches `^- Source: (\S.*?) \(line \d+\)$`, and its path is a path in the review's custody;
3. every `## Chapter NNN` section contains at least one such line;
4. if the frontmatter has `chapters:`, its set equals the set of `## Chapter NNN` numbers.

Any irregularity sends the item to the fallback. One unparsable `Source:` line therefore cannot drop a dependency.

**Verified on stormgiants**: all 164 evidence files parse under this rule. The busiest summary, `024-session-uncle-joon.md`, is named by 19 NPCs. Chapter 010's summary is named by 8.

## R6 — Which evidence a draft sign-off depends on (FR-004)

A sign-off binds only its draft (`review/cli.py::_npc_signoff_items` L612–635). The evidence it was verified against must be found some other way, robustly.

**Decision**: `custody.npc_evidence(item, items, custody)` returns the **union** of three sets:

- (a) the evidence-role sources the item binds itself (claim and presentation items);
- (b) the evidence-role sources bound by any *other* item that binds the same draft source (sibling bindings, which the builder wrote from the same `SelectedNpcVerification`);
- (c) the layout path `<range>/evidence/<stem>.md`, derived from a bound `<range>/draft/<stem>.md`, **if that path is in custody**. Spec 039's `record_freshness` (`delta/npc_update.py` L577–581) relies on the same layout.

If the union is empty, the item depends on **every** evidence-role source and every summary-role source. That is today's strictness for that item.

**Why a union, not one of them**:

- (b) alone misses an NPC whose verification raised no finding. It has only a sign-off item, and no sibling binds its evidence.
- (c) alone trusts a convention. A custom selection may put evidence elsewhere. In that case the layout path is absent from custody and contributes nothing, so (b) still covers it.
- A union can only over-include, so neither source can make the other miss.

## R7 — Items outside the NPC domain

Grounding-document, duplicate-identity and claims reviews go through `save_decisions` too.

**Decision**: for an item whose domain is not `npc_finding`, the dependency set is **its bindings ∪ every custody source that no item in the review binds**. The FR-003 narrowing applies only to `npc_finding` items. For a review where every source is bound, this is per-item. For one with unbound sources, every item still checks them, as today. Neither case is weaker than today restricted to what the item depends on.

## R8 — Does the verifier depend on summaries the evidence does not name?

This checks that the GM ruling in FR-003 is sound against the code, `npc_verify.py`:

- **`check_quotes`** passes or fails on `npc_check.check_quote(..., context.evidence)`, which is evidence only. `summaries_text` only appends the hint "(verbatim in the summaries, not in this NPC's evidence)" to a failure that already exists.
- **`check_citations`**: a citation passes only when it is in `context.evidence.targets`, which come from the evidence's chapters. Each of those chapters names its summary under R5's rule 3.
- **Status, history, manual and number**: evidence and draft only.

**Conclusion**: a summary the evidence does not name cannot change a pass verdict. The ruling matches the verifier.

**Known limit, out of scope (#628)**: the evidence file is itself derived from summaries. If a summary is corrected so that it now *should* mention an NPC whose evidence does not name it, nothing here stales that NPC. Reporting which dossiers a summary fix affects is #628.

## R9 — Carrying the refusal detail

**Decision**:

- `ReviewStoreError.__init__(message, code=None, *, detail=None)`, where `detail` is a JSON-safe dict built only by `custody.refusal_detail`.
- `cli.py`'s refusal handler (L971–973) passes `data=getattr(exc, "detail", None)` to `_emit`. In text mode, `_emit` prints the message, then one line per changed file: `  <state> <path>: <npc> — <item ids>`, and then the remedy. With `--json` the detail is the envelope's `data`.
- `delegated.submit_decisions` (L394–400) re-wraps errors to say how many batches were saved. It must copy `detail` across. `carry`, `policy` and `noise decide` therefore show the same detail.
- **Local routes**: `server/routers/review_routes.py::_error` (L209–227) relays `payload.get("data")` when it is a dict.
- **Capability service**: `review/web/app.py::safe_command_error` (L78–101) maps `REVIEW_STALE_CUSTODY` to 409. The fixed message stays "Review state changed. Reload before trying again." for the other stale codes. For custody it adds `detail`, rebuilt from a **whitelist**: `changed_files[].{path,state,items[].{item_id,npc}}`, `stale_items[]`, `remedy.command`, all strings or ints, length-capped. The capability surface relays nothing it has not shaped itself. The viewer already shows locators and evidence paths, so paths and item ids are not new exposure.
- `viewer.js` L77 renders the detail list under `save-state`, and shows the reload button. `ReviewLauncher.vue` L20 puts `body.data` into `result` on refusal, so the `<pre>` shows it.

The refusal **message** stays one line and starts `REVIEW_STALE_CUSTODY:`. Callers that parse the code prefix keep working (FR-005).

## R10 — Import (FR-010)

`import_review_bundle` never reads source bytes today. Its digest comparison is a record-level check: it catches a bundle exported from a copy whose custody diverged at the same generation, for example two copies refreshed independently. A local file edit never triggers it.

**Decision**:

- **Keep** the digest comparison. FR-014 keeps the review-wide record for audit, and removing the comparison would weaken cross-copy protection, which the precision rule forbids.
- **Add** the per-item byte check, under the lock. It covers the items for which the import would append a *decision* event, which are the non-withdrawal events in `missing`. The refusal is the FR-005 detail with `operation: "import"`.
- A bundle whose only new events are withdrawals imports even when those items are stale (FR-009).

This contradicts FR-010's wording "instead of against the whole review's custody digest". It is reported to the orchestrator rather than resolved silently.

## R11 — Withdrawals (FR-009)

`retract_decision` takes the lock and checks decision revisions only. The decision is to leave it unchanged and add a test: a withdrawal on an item whose draft has changed succeeds and records the reviewer and time.

## R12 — NPC label and grouping

- **Label**: spec 041's rule, `subject_ref.registry_name`, falling back to the draft stem without `npc_`. It moves from `delegated._draft_stem_name` and `_occurrence` into `custody.npc_label(item)`. `delegated` imports it, so the two features spell an NPC the same way (XII). On stormgiants no item carries `registry_name`, so labels are stems such as `bob_saget`.
- **Group key**: the item's bound draft-role path. It is stable and unique per NPC. An item with no draft binding groups under its locator path.

## R13 — Publishing (FR-011, FR-012, FR-013)

1. **Freshness**: `_current_draft_signoff` first finds the ledger records whose sign-off item matches `draft_path`. Today it computes custody for every record, then matches. For the matched item it calls `custody.dependency_sets` and checks:
   - with a dependency graph: `deps ∪ {custody sources whose path is in graph.dependencies(graph_item)}`. The graph can widen the set, never narrow it (FR-011);
   - `dependency_graph.item_stale(...)`, which stays.
2. **Reason**: a new `signoff_freshness(...) -> SignoffFreshness(current: bool, changed: tuple[ChangedFile, ...], review_id, generation)`. `_current_draft_signoff` stays a `bool` wrapper, because tests call it that way. The default `signoff_checker` returns the richer object. `_plan_summary_native` accepts either a `bool` or a `SignoffFreshness`, so the test seam `lambda p, d: True` still works. Held reason: `NPC_DRAFT_SIGNOFF_STALE: sources changed since review <rid> was built: <path> (<state>)[, …]; run \`summary_native review refresh <rid> --expected-generation <n>\`, then re-verify and re-sign`.
3. **The compose check fires first** for US4 scenario 1. `_plan_summary_native` refuses `"draft changed after composition; …"` when the GM header's draft sha differs from the current draft. That message names no file. The plan appends the draft's display path so that FR-013 holds on this path too.
4. **FR-012**:
   - The published body is `item.body`, read once in `_plan_summary_native` from the GM dossier. That dossier's header names the exact draft sha that was checked and signed. Nothing re-reads the draft or the GM file between the plan and the write, so the written content is already bound to the checked bytes.
   - What is missing is a hold when the draft moved after the check. `publish().write()` therefore re-hashes the draft immediately before `_put(it.target, …)`. If it differs from `it.draft_sha256`, the NPC is held: `NPC_DRAFT_CHANGED_AT_WRITE: <path> changed after its sign-off was checked; nothing was written for this NPC`. The others continue.
   - `PublishItem` gains `draft_path`.
   - A residual window remains between that re-hash and `_put`, because editors do not take the authority lock. It is harmless: what is written is still the signed content.
5. **Receipt**: the `held` receipt gains `custody_changed: [{path, state}]` when custody caused the hold. It is additive.
6. **Cost**: a per-`plan_publish` digest cache, keyed by path, replaces re-hashing all custody per record per NPC. The pre-write re-hash always reads fresh.

## R14 — The remedy command (FR-005, FR-008)

The remedy is `summary_native review refresh <review> --expected-generation <generation>`, spelled exactly as `cli.py` L132–133 defines it (XII). For a **draft-role** change the detail adds a note: a refresh rebinds the sign-off, but its recorded `draft_sha256` is the old one, so `_sign_npc_draft` then refuses `REVIEW_NPC_SIGNOFF_STALE` until the draft is re-verified in a new review. That is existing behaviour, and the note stops the remedy being misleading.

## R15 — Test environment and the stormgiants replay

- **Environment**: `PYTHONPATH=<worktree> ~/.venv/bin/python -m pytest … --basetemp=$HOME/.cache/pytest-042`. `~/.venv` has pytest. The editable install would otherwise shadow the worktree. The `/tmp` tmpfs has run out of inodes before. There is no xdist.
- **Replay**: `custody.py` takes an injectable `state(source) -> FileState` provider, so the replay simulates a change without writing.
  - The live checkout has already drifted from custody generation 5: 5 drafts, 1 summary and 4 evidence files.
  - So the replay is **relative to a baseline**: stale set with no simulated change = B; for a simulated change of file f, the newly stale items must equal exactly {items whose dependency set contains f} \ B.
  - It runs this for every draft, and for `docs/summaries/010-session-the-seer.md`.
- **Measured**: there are 781 items. The mean is 4.8 items per NPC, and the maximum is 19 (`npc_bob_saget`).
