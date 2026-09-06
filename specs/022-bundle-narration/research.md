# Research: Bundled Narration Generation

**Feature**: 022-bundle-narration | **Date**: 2026-09-05

Codebase findings and decisions that constrain the implementation plan.

## D1 — Reuse the established scene-batching vocabulary

**Decision**: Add `--batch-scenes` / `--no-batch-scenes` and `--batch-max-tokens` to `sd_narrate`. The default remains sequential. Typing `--batch-scenes` without `--scene` is the CLI's explicit all-plan selection; with `--scene`, it bundles exactly those indices in full-plan order.

**Rationale**: `scene_extract` already defines `--batch-scenes` as “send multiple scenes in one model exchange” and `--batch-max-tokens` as that exchange's output ceiling. Constitution XII requires one spelling for the same concept across sibling CLIs. “Bundled narration” remains the feature and UI language that distinguishes content consolidation from provider pricing.

**Alternatives considered**:

- `--bundle`, `--bundle-scenes`, and `--bundle-max-tokens`: clearer in isolation, but create a second CLI dialect for the same multi-scene/one-exchange operation.
- Reuse `--batch`: rejected because it already means provider Message Batches and changes submission/billing rather than prompt shape.

`--narrator` remains unchanged for sequential narration and is refused when combined with `--batch-scenes`. Its current filter-then-index behavior does not preserve the bundle contract's stable full-plan indices, while explicit `--scene` already provides a precise bundled subset.

## D2 — Keep provider Message Batches independent and composable

**Decision**: `--batch-scenes` without provider `--batch` makes one `stream_api` call. With provider `--batch`, the same bundled prompt is submitted as one `run_single_batch` item. The run report always records both choices separately.

**Rationale**: Today `sd_narrate --batch` submits one ordered batch item per scene because the sequential path depends on handoff state. Once content is bundled, there is one valid request item, and the metered backend can still apply its pricing mode. `client_from_args` and central selection validation remain the authority for backend compatibility.

**Alternatives considered**:

- Refuse the combination as `scene_extract` does: rejected because extraction's refusal is based on cached transcript economics that do not apply to the combined narration request; one bundled narration item still receives the provider discount.
- Let one flag imply the other: rejected because it would silently change either call count or billing intent.

## D3 — Factor shared context once; do not concatenate current prompts

**Decision**: Add bundle-specific prompt builders and templates. The bundle system prompt carries global narration rules, genre, shared style examples, party document, class roster, NPC spellings, campaign history, and run-wide options once. Each ordered scene packet carries its stable index, exact scene name, narrator, focus, source events and moments, narrator voice note, narrator-specific examples, and previous-narrator contrast sample.

**Rationale**: `build_narrate_system` currently varies by scene/narrator, while `build_narrate_prompt` repeats party, roster, NPC, and campaign context on every call. Concatenating N complete prompts inside one call would repeat the large shared blocks N times and erase much of the requested saving. Separate templates also leave sequential prompt bytes and behavior stable.

**Alternatives considered**:

- Concatenate existing system/user pairs: simplest mechanically, but repeats the expensive context within the same request.
- Refactor the existing base template for both modes: rejected for the first implementation because it expands the regression surface for the required unchanged sequential path.

## D4 — Replace precomputed handoffs with within-response continuity

**Decision**: Require scenes to be emitted in reviewed plan order. For scene N after the first, the model must treat the final prose line of its just-emitted scene N−1 as the handoff into N, ignoring any trailing table-speech audit comment. The response validator rejects out-of-order sections.

**Rationale**: The existing loop computes `handoff` only after a scene returns, so a single request cannot place that unknown generated line into the next input packet. Autoregressive generation makes the earlier generated section visible while the model writes the next one. Ordering is therefore part of correctness, not just presentation.

**Alternatives considered**:

- Omit handoff continuity: would save tokens but regress a deliberate narration-quality mechanism.
- Precompute a handoff from source text: invents a transition before the narration exists and changes its meaning.
- Accept out-of-order response sections and sort them: rejected because later prose could not have continued from the correct preceding generated section.

## D5 — Reuse deterministic scene sentinels with stricter order validation

**Decision**: Reuse `campaignlib.scenes.split_batched_response` and its column-zero paired protocol:

```text
<<<CG-SCENE 02 BEGIN: Exact Scene Name>>>
...narration only...
<<<CG-SCENE 02 END>>>
```

Scan the raw marker stream before calling the shared splitter. This preflight rejects unknown or duplicate indices, nesting, mismatched BEGIN/END indices, and response indices encountered outside request order. Only a clean marker stream reaches `split_batched_response`; its parsed result then supplies complete, empty, incomplete, and absent section states. Attribute by original 1-based plan index and compare the echoed scene name after whitespace normalization only.

**Rationale**: The existing splitter handles duplicate/punctuation-heavy names, preamble/trailing text, empty bodies, truncated tails, unknown indices, duplicate sections, nesting, and name mismatches without inference. It deliberately normalizes output into request order and treats a wrong END as stray text, so its returned structure cannot prove raw encounter order or matching END identity. The narrow raw preflight closes those gaps while retaining the mature section-state parser. Stable plan indices keep a filtered subset from being renumbered.

**Alternatives considered**:

- JSON output: truncation invalidates the whole document and prose escaping adds failure modes.
- Markdown headings or name-only delimiters: collide with narration content and cannot safely distinguish duplicate names.
- A new narration-specific parser: duplicates mature identity and partial-response logic.

## D6 — Distinguish partial output from untrustworthy identity

**Decision**: Any structurally valid response that does not complete the full selection writes its complete non-empty scenes, retains existing files for all others, names the missing set, and exits `3`. This includes a valid response with zero writable sections because every requested section is empty, incomplete, or absent. Unknown/duplicate/nested/mismatched-END/out-of-order/name-mismatched sections make the exchange unreconcilable; it writes none and exits `4`. Input and capacity refusals remain exit `1`.

**Rationale**: This matches the project's batched extraction semantics and preserves paid-for good work without guessing. `stream_api` and `run_single_batch` both return accumulated text when output reaches a ceiling, so sentinel parsing can recover closed sections on live and provider-batch paths.

**Alternatives considered**:

- Discard every partial response: needlessly repays for complete scenes.
- Write any section with a recognizable name: violates exact attribution and Constitution IV.
- Return exit `0` when any file was written: hides incomplete work from CLI automation and the UI.

## D7 — Prepare the complete selection before client creation

**Decision**: Build a `NarrationScene` record for every selected plan index before constructing a client or making a call. Resolve the exact extraction, scene body, narrator declaration, voice/examples, contrast sample, output path, existing-output status, and token estimate for all selected scenes. Any failure refuses the whole bundle with zero writes and zero model calls.

**Rationale**: The current loop discovers some errors only when it reaches a later scene, after earlier calls have spent tokens. Bundling cannot omit a bad scene and still claim it generated the explicit set.

**Alternatives considered**:

- Reuse the loop and append packets as it goes: risks partial preflight and makes selection reporting incomplete.
- Let missing narrator guidance become an empty block: weakens the existing all-selected-narrators preflight.

## D8 — Generalize the existing exact-source override

**Decision**: Make `--scene-extraction-file` repeatable in bundle mode. Each supplied file must be readable, eligible under `session_doc.io`, and reconcile to exactly one selected full-plan index/name. Duplicate or unmatched overrides refuse before the call. Selected scenes without an override continue to resolve from `--scene-extractions`. The existing one-file/one-scene invocation remains valid.

Reports label source provenance as `base` when resolved from `--scene-extractions` and `override` when supplied through `--scene-extraction-file`. Raw/smoothed is editor knowledge rather than a general CLI invariant, because callers may provide any eligible directory or exact file.

**Rationale**: The editor independently prefers a smoothed extraction for each scene and falls back to raw. A full session may therefore mix directories. Reusing the existing exact-source option follows Constitution XII and lets the CLI command represent the editor's real inputs.

**Alternatives considered**:

- Add `--scene-source N=FILE`: explicit but duplicates the existing exact-source concept.
- Point the bundle at the smoothed directory only: loses raw fallback scenes.
- Stage chosen files in a temporary directory: hides source identity and adds mutable intermediary state.

## D9 — Give the one exchange its own ceiling and never auto-group

**Decision**: `--batch-max-tokens` defaults to 32,000 and applies only to bundled narration. `--narrate-tokens` keeps its 16,000 per-scene meaning. The bundle projection is the sum of the existing per-scene estimates plus fixed delimiter overhead. If it exceeds the chosen bundle ceiling, refuse before the call and suggest raising the ceiling, narrowing `--scene`, or using sequential mode.

The UI stores only `narrate.batch_tokens` (default 32,000); bundle activation remains a per-run action. No model-specific limit table is introduced. When a backend exposes a reliable capacity, validate it centrally; for arbitrary or unknown model identifiers, state that capacity is unknown and let the existing backend seam enforce the actual limit.

**Rationale**: A 16,000 total ceiling is too small for several full scenes, while silently splitting violates the feature's one-exchange promise. The repository accepts arbitrary DGX, OpenRouter, Claude Code, and Codex model identifiers and has no canonical capacity registry, so scattered guessed limits would drift.

**Alternatives considered**:

- Multiply `--narrate-tokens` by scene count: changes a documented per-scene knob and can request an unsupported value silently.
- Automatically group like batched extraction: violates SC-001 and masks that the requested “one shot” did not happen.
- Hard-code capacities for known model names: incomplete, time-sensitive, and inconsistent across backends.

## D10 — Share file formatting and write atomically

**Decision**: Extract the existing narration filename/frontmatter/body assembly into one helper used by sequential and bundled paths. Write complete output with `campaignlib.atomic_write_text`. Run the existing unknown-name warning per split scene. Do not introduce a combined canonical narration file.

**Rationale**: One writer guarantees the same files, metadata, and assembly behavior in both modes. Atomic replacement prevents an interrupted write from leaving a partial file that looks complete on disk.

**Alternatives considered**:

- Keep duplicate write blocks: likely to drift in frontmatter or naming.
- Save the raw combined response as the narration source of truth: breaks current review/assembly and file discoverability.

## D11 — Persist a structured outcome for accurate UI audit

**Decision**: Bundled `sd_narrate` writes an atomic JSON run report, defaulting under the narration output's `logs/` directory and overridable with `--run-report`. It contains a run identifier, requested/replaced/written/missing/rejected scenes, output paths, projection/ceiling, provider-batch state, exchange count, status, and exit code. A human-readable summary remains on stdout. Every preflight refusal and backend failure path finalizes the report before exit; a report path that cannot be initialized is itself a refusal before client creation.

The editor generates a nonce for each request, supplies a unique session-local report path, and retains the resulting report as run history. This avoids races between simultaneous tabs or identical selections; standalone CLI users may keep the convenient default “latest” path.

**Rationale**: Return code alone cannot tell the router which files a partial response wrote, and pre-existing files cannot be treated as newly generated. The report also makes the run discoverable after navigation.

**Alternatives considered**:

- Scrape stdout: brittle and couples the server to prose formatting.
- Compare pre/post mtimes or hashes: fails to represent byte-identical replacements and loses explicit missing/rejected reasons.
- Mark every selected existing file on partial completion: records false provenance.

## D12 — Use an explicit editor scope dialog and a dedicated SSE endpoint

**Decision**: Keep `GET /api/editor/narrate/{n}` unchanged. Add `GET /api/editor/narrate-bundle` requiring one or more repeated `scene` query parameters. The UI opens a bundle dialog containing every plan-ordered scene's index, name, narrator, and existing-output replacement state. Only the dialog's explicit run action sends those literal indices. The route revalidates uniqueness, range, plan order, and every scene's preferred source before building a copyable CLI command.

The route wraps `stream_subprocess(..., emit_done=False)`. After the subprocess generator finishes, it reads and validates the nonce-scoped report, performs report-derived sidecar/activity updates, then emits one route-specific `done` SSE payload containing the run status, raw return code, written/requested counts, missing scene identities, and any report-validation error. The frontend therefore has structured K/N and recovery data and closes only after all completion work. Disconnect handling stays with `stream_subprocess`.

If the current raw extraction has unsaved edits, save it before opening/running the bundle by the same rule as current-scene narration. Every terminal outcome refreshes the entire scene list and pipeline status.

**Rationale**: The loaded scene list already carries the required scope preview. A dedicated GET SSE route preserves the existing native EventSource lifecycle and streamed command event. Requiring indices satisfies Constitution X; absent parameters cannot turn into implicit all.

**Alternatives considered**:

- An endpoint where no indices means all: constitutionally prohibited implicit blast radius.
- `window.confirm`: cannot present the scene/replacement table clearly.
- POST streaming: possible, but would add a second streaming transport and abort lifecycle for data that fits safely in repeated query parameters.

## D13 — Preserve current modes and keep an unrelated token-override defect out of scope

**Decision**: The no-flag sequential loop, current-scene route, per-scene generated handoff, output paths, and assembly gate stay behaviorally unchanged. Documentation and the editor's stale note that provider batching always means “one scene at a time” are updated to explain both modes.

The current help text claims that a first-line `tokens: N` in a scene file overrides `--narrate-tokens`, but the CLI does not parse that override. This plan does not silently repair or use that undocumented implementation gap for bundle sizing; it should be addressed as separate work unless implementation discovers an existing tested path.

**Rationale**: The user explicitly requires one-at-a-time narration to remain. Fixing an adjacent token override changes established behavior without a requirement or validation baseline.

**Alternatives considered**:

- Repair the override while touching token sizing: rejected as unrelated scope with independent semantics.

## D14 — Quality is a release gate, not an assumption

**Decision**: Add prompt delivery/contract tests that prove shared blocks occur once, every selected scene receives its own source and narrator guidance, no scene receives another narrator's private guidance, all load-bearing dialogue/prose/scene-anchor rules remain present, and marker/order instructions are exact. Before release, run the same representative session sequentially and bundled; compare file shape, source quote handling, narrator attribution, coverage, continuity, and late-scene completeness.

**Rationale**: Consolidating scenes changes the model's attention and output-budget conditions. Structural unit tests prove routing and attribution; a representative human review catches voice flattening or tail compression that deterministic tests cannot judge.

**Alternatives considered**:

- Trust frontier-model capacity without comparison: repeats the less-capable-model assumption in the opposite direction.
- Ask another model to judge quality: adds a token-spending precision decision instead of retaining the human checkpoint.
