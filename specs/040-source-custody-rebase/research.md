# Research: Reviewed Source-Custody Rebase (spec 040)

Code baseline `3c3fbb9`. Every decision below was checked against the code at that commit; file references are to `pipelines/summary_native/` unless stated.

## R1. What a rebase *is*: a delta plan of kind `rebase`, not a parallel writer

**Decision.** A source-custody rebase is a spec 039 delta plan with `kind: "rebase"`:

- **Sources:** the explicitly selected corrected summaries (their current bytes).
- **Product:** `grounding` only.
- **Candidates:** the bound baseline's four documents, with only the GM-approved claim repairs applied.

It travels through the existing pipeline unchanged: `grounding check` → `grounding preview` (stage) → existing claims select/check → four exact document signoffs → `grounding apply` → `promotion.publish` → a new generation.

Only these pieces are new:

- inspection;
- old-byte recovery and snapshot;
- impact analysis;
- per-source decisions;
- the range label rule (R3);
- plan rebind (R6).

**Rationale.** `delta/grounding_candidates.py` already writes a `kind:"delta"` lineage record whose `baseline` names the parent generation by id and manifest digest. `delta/baseline.py:_delta_parent` already follows that link with each hop digest-verified, and `_custody_rows` already applies rows parent-first with the child's range-manifest `files[]` winning. So a rebase generation whose staged range manifest lists the selected chapters at their **new** digests *is* the custody override: no change to the resolver is needed.

Review binding, preview digest, journaled apply, recovery and receipts are all reused as they are. FR-012, FR-014, FR-016 and FR-017 come from existing code, not new code.

**Alternatives rejected.**
- *A separate rebase writer that copies the generation and edits `external_dependencies`.* This duplicates promotion and bypasses the claims and signoff gates the issue says must stay enforced.
- *Folding the rebase into the pending ch043 delta.* There is then no standalone path (the spec's edge case "repair stands alone"), and two unrelated decisions (new-session content and old-source corrections) end up in one review.
- *Extending the document-drift adoption record.* That record covers live-document prose; this is a different decision about a different subject (spec Assumptions).

## R2. Old-byte providers and custody snapshots

**Decision.** Three providers, tried in a fixed order, and each candidate's bytes are verified against the pinned digest:

1. **Retained snapshot.** `docs/summaries/delta/custody/objects/<sha256>` is a content-addressed store written by this feature. It is write-once: an existing object is never rewritten, and it is verified on read.
2. **Git object.** The campaign's own repository is searched for a blob with the exact content. Lookup uses the blob's SHA-1 over the content, but it is confirmed only by recomputing the SHA-256. This is read-only: `git cat-file` / `git rev-list --objects --all` are run as subprocesses with `cwd` at the campaign root, and no checkout or ref change happens.
3. **Explicit file.** `--old-bytes CHAPTER=PATH` supplies the bytes directly, and they are verified the same way.

Recovered and current bytes are both written to the snapshot store. Each `snapshots.json` row records `{chapter, path, role: old|current, sha256, provider, provider_detail}`.

**Rationale.** The survey found summaries are custody-pinned by hash only (manifest `external_dependencies`, range `files[].sha256`, lineage `CustodyRef`); no byte copy exists. Git is how the ToEE operator actually recovered all four. A content-addressed store makes a retry idempotent and lets the next rebase skip Git.

**Refusals.** Any of these refuses for that chapter: no provider found the bytes; a provider's bytes hash differently from the pin; the Git repository is absent; or two providers' bytes disagree. The disagreement case can only come from a wrong provider, because each is verified against the same pin. The refusal message lists every provider tried.

## R3. Range label for non-contiguous rebases

**Decision.** A rebase plan stages a range labelled by the **span** of the selected chapters (for example `ch016-042`), with:

- `manifest.json` `files[]` = only the selected chapters;
- `range.gaps` = every unselected chapter number in the span;
- `kind: "custody_rebase"`.

`stage_for_promotion`'s contiguity refusal stays for `kind: delta` plans and is relaxed only for `kind: rebase`, which then must write explicit gaps.

**Rationale.** `promotion/manifest.py:build_bundle_selection` reads the drafts' `range:` header and the manifest; `_custody_rows` reads only `files[]`. So an explicit gaps list makes the label honest without a promotion schema change. The existing `STAGED_MARKER` refusal already prevents staging over a full-build range directory with the same name.

**Alternatives rejected.**
- *A contiguous label without gaps.* It would claim chapters 18–37 were selected.
- *A new non-`chSSS-UUU` directory name.* That would mean changing the promotion range contract.

## R4. Impact: what proves "affected"

**Decision.** Impact is computed per selected source, deterministically and with no model:

1. **Changed regions.** A line diff of old vs current bytes (byte spans) gives the changed regions. Each scene/entry heading section (the `[ch NNN / ENTRY]` target vocabulary) is marked *changed* when its bytes differ, *removed* when its heading is gone, and *unchanged* otherwise.
2. **Affected lines.** Every line of the four baseline documents (and, when a pending plan is bound, its candidates) carrying a `[ch NNN / ENTRY]` citation into a selected chapter is classified as follows:
   - **affected:** the entry is changed or removed;
   - **affected (whole-chapter):** the citation has no entry granularity, i.e. the entry is the chapter itself;
   - **unaffected:** the entry is unchanged.
3. **Retained claim annotations.** Where the baseline retained a claims check report, each annotation whose `source_sha256` equals the old digest and whose byte span intersects a changed region is listed as an affected claim.
4. **Unknown-impact members.** `canon_events_timeline.md` and `reference/**` are whole-file members with no per-source map. They are listed as *unknown impact* whenever they contain a citation into a selected chapter, or contain no citations at all.
5. **External consumers.** Published NPC dossiers (`docs/npcs/*.md`) whose text cites a selected chapter are listed as follow-up consumers (FR-008). They are read-only.

**Rationale.** Citation targets are the only dependency index on every line, because `claims/selection.py:_CITATION` is how claims selection itself discovers sources. `ClaimAnnotation` carries `source_sha256` and the byte span (`claims/models.py:159`), which allows span-level precision when the data exists. The survey found no record that maps timeline or reference members to sources, so the spec makes them unknown-impact by design rather than inferring by similarity.

**`adopt-unaffected` precondition (FR-009).** All of the following must hold for that source:

- zero affected document lines;
- zero affected retained annotations;
- every unknown-impact member ruled.

Any remaining affected line forces `adopt-with-repairs`, `hold` or `reject`. This is how "semantic changes cannot be accepted through hash replacement alone" is enforced in code, not by convention.

## R5. Repairs: who writes them and how they apply

**Decision.** Repairs reuse spec 039's grounding edit model (`delta/grounding_edits.py`): stable host-owned ids, exact before/after bindings, category, reason and evidence. There are two ways to author a repair:

- **GM-authored:** `delta rebase repair add` takes a line ref, replacement text and reason.
- **Model-proposed:** `delta rebase propose --backend --model` reads only the affected lines, the old/new diff of the selected chapters, and the retained annotations for them. This is a draft and is never auto-approved.

A repair is approved, rejected or held with `delta grounding decide`, so there is one decision vocabulary and one reviewer rule. A **hold** keeps the line byte-identical and appends one `⚠ held: superseded by correction to ch NNN — see rebase <id>` marker line under it. The marker is additive (it never rewrites the line), in the same spirit as `annotate`.

**Rationale.** The edit model already rejects malformed, overlapping and stale edits (039 FR-006), so reusing it inherits those guarantees. Constitution II: the model removes only the drafting decision, and the GM decides.

## R6. Rebinding the pending delta

**Decision.** `delta plan rebind --plan ID --baseline GENERATION` writes plan revision r+1. In it, `grounding_baseline_ref` points at the rebase generation, which must be the active one and must have that plan's old baseline as its lineage parent. It also writes `rebind-r<N>.json` recording:

- the old and new baseline refs;
- the rebase id;
- each NPC binding carried, with its old plan digest;
- each grounding artifact invalidated.

**Grounding.** Approved ch043 edits are re-applied onto the new baseline documents only when their exact `before` bytes are still present and do not overlap a repaired line. Edits that overlap a repair are marked stale and must be re-decided. Candidates, check report, document signoffs and the publication binding are invalidated, because their bindings include `plan_sha256` and candidate digests. They then rerun through the existing commands.

**NPC.** `review_binding._npc_stale_reasons` currently treats any `plan_digest` change as stale (`review_binding.py:275`). The rebind adds one narrow rule there: an NPC binding whose `plan_sha256` equals the digest recorded as `carried_from` in a rebind record stays valid, provided the new revision's NPC projection matches the old one byte-for-byte. The NPC projection is: sources, NPC baselines, products, backend and model. `grounding_baseline_ref` is the only field allowed to differ.

Published members' receipts are untouched, and `run resume` already skips members with receipts.

**Rationale.** The plan id excludes the baseline (`plan.py:_derive_plan_id`) while `plan_digest` includes it. A revision therefore keeps the run's identity and invalidates exactly what bound the old baseline.

**Alternative rejected.** Excluding `grounding_baseline_ref` from every NPC binding digest would silently change the digest of every existing binding, which would be a state-shape break (Principle XIII).

## R7. Bounded reads and model input (FR-007, FR-018, SC-007)

**Decision.** Rebase inspection reads every pinned source's bytes (integrity-only), and the receipt counts these reads separately. Reads are bounded as follows:

- **Parsing:** only selected chapters are parsed for impact.
- **Model input** (propose only): limited to affected lines, the selected chapters' diffs and their retained annotations.
- **Claims gate:** extraction already runs only on explicitly selected chunks (`claims/extract.py:extract_candidates` refuses unselected chunk ids). The rebase run selects chunks for the repaired lines and the changed sources, and reuses cached runs by input digest.

The receipt reports:

- `integrity_reads`;
- `parsed_historical` (= the selected chapters);
- `cached_evidence_reused`;
- `model_input_sources`;
- `model_calls`;
- `unselected_stale_remaining`;
- `followup_consumers`.

## R8. Better stale errors (FR-002)

**Decision.** `claims/selection.py:_discovered_rows` keeps its first-failure raise. Its message gains the chapter, path, expected digest and actual digest (or `missing`), plus the hint `run: summary_native delta rebase inspect`. The `CLAIMS_SOURCE_STALE` code is unchanged, so existing callers and tests keyed on the code still match.

The all-sources report belongs to `rebase inspect`, which walks `_custody_rows` for the active generation and hashes every row. That is integrity-only.

## R9. UI parity (FR-019, GM ruling 2026-11-09: CLI + UI now)

**Decision.**
- **Routes.** New routes in `server/routers/summary_native_delta.py` under `/rebase` build argv for the new leaves, through the same `build_delta_argv` helper.
- **Page.** A new Vue view, `frontend/src/views/grounding/SourceRebase.vue`, is routed beside `grounding-delta`. It shows the inspection table, per-source diffs, affected and unknown-impact lists, decision controls (reviewer required, no default) and the preview/apply step.
- **Backing files.** Decisions are posted to the CLI and persisted as files. The page holds no state that is not a file.

## R10. Migration

**Decision.** No breaking state change, so no migration CLI.

- New files only: the `custody/` store, `rebase/<id>/` records and `rebind-r<N>.json`.
- `DeltaPlan` gains an optional `kind` (default `"delta"`), and existing plan files load unchanged. Its digest canonicalization omits `kind` when it is the default, so existing plan digests, and therefore existing review bindings, are byte-stable. A test pins this.
- `DeltaLineageRecord` gains an optional `rebase` block with the same digest-stability rule.

The operator runbook (FR-020) is `docs/cli/source_custody_rebase_howto.md`, with a ToEE-shaped walkthrough.
