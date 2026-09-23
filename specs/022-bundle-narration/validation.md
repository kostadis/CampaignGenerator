# Validation: Bundled Narration Generation

**Feature**: 022-bundle-narration  
**Validated**: 2026-09-06  
**Worktree**: `/home/kostadis/src/CampaignGenerator/workrees/narration-bundle`

## Readiness gate

The specification checklist passed before implementation: 16 requirements were checked and none were incomplete. Python resolved `campaignlib` from this feature worktree, not the primary checkout.

## Automated validation

| Check | Command | Outcome |
|---|---|---|
| Focused feature matrix | `.venv/bin/python -m pytest tests/test_narration_bundle_split.py tests/test_narration_bundle_cli.py tests/test_narration_bundle_report.py tests/test_sd_narrate.py tests/test_narrate_input_delivery.py tests/test_narrate_template_contract.py tests/test_editor_pipeline.py tests/test_editor_service_integration.py tests/test_session_editor_config_service.py -q` | **Pass:** 336 passed in 4.86s. Run outside the restricted socket sandbox because FastAPI `TestClient` needs an AnyIO portal. |
| Sequential regression | `.venv/bin/python -m pytest tests/test_sd_narrate.py tests/test_narrate_input_delivery.py -q` | **Pass:** 58 passed in 0.90s. |
| Parser/report fixture gate | `.venv/bin/python -m pytest tests/test_narration_bundle_report.py tests/test_narration_bundle_split.py -q` | **Pass:** 22 passed in 0.33s. |
| Legacy narration knob compatibility | `ANTHROPIC_API_KEY=test .venv/bin/python -m pytest tests/test_narrate_genre_file.py -q` | **Pass:** 26 passed in 0.55s. |
| Structural boundaries | `.venv/bin/python -m pytest tests/test_retrieve_render_isolation.py tests/test_no_prefix_identity.py tests/test_layering.py tests/test_backend_seam_guardrails.py -q` | **Pass:** 470 passed, 162 skipped in 26.93s. |
| Frontend production build | `cd frontend && npm run build` | **Pass:** Vue type checking and Vite production build completed. |
| Bundle browser scenario | `cd frontend && npx playwright test session-narration-bundle.spec.ts --config=playwright.system.config.ts` | **Pass:** 8 passed in 11.0s using `/usr/bin/google-chrome`. The temporary config only supplied `launchOptions.executablePath` and was removed afterward; the locally cached Playwright revision expected by 1.55.0 was absent. |
| Diff hygiene | `.venv/bin/python -m py_compile session_doc/sd_narrate.py session_doc/narrate.py server/routers/scene_editor.py && git diff --check` | **Pass.** |
| Full repository regression | `ANTHROPIC_API_KEY=test .venv/bin/python -m pytest tests/ -q` | **Baseline remains non-green:** 4,769 passed, 171 skipped, 31 failed in 166.97s. None of the 31 failures exercise files changed by this feature. They cover existing `/tmp` git-root assumptions, an ensemble-router path literal, local `dgxlib` behavior, unrelated backend-selection response drift, and tests that invoke `python` when this environment exposes only `python3`. The two failures initially attributable to this feature's new knob snapshot were fixed and the owning 26-test suite passes. |

The full run needed undeclared repository test dependencies (`pymupdf`, `numpy`, and the MCP v1 API expected by the code). These were installed only in the ignored worktree `.venv`. `ANTHROPIC_API_KEY=test` satisfies credential-presence assertions; the suite's mocked tests made no metered API call.

## Representative sequential-versus-bundled quality gate

The reviewed three-scene fixture in `tests/fixtures/narration_bundle/` was exercised through the sequential regression path and the bundled parser/CLI path. It contains an Alice → Bob → Alice narrator change, three distinct verbatim quotes, a raw source set, and a reviewed override for scene 2.

| Review dimension | Evidence | Result |
|---|---|---|
| File shape | Both paths use `_narration_output_path`, `_format_narration_output`, and `_write_narration_output`. The report test locks filenames, YAML frontmatter, session identity, trailing newline, and atomic replacement. | Pass. |
| Attribution | Plan indices 1–3 reconcile exactly to Arrival/Alice, The Bargain/Bob, and Departure/Alice. Unknown, duplicate, renamed, nested, mismatched-END, and out-of-order sections are rejected before writes. | Pass. |
| Quotes | The three returned quotes match their own extraction verbatim: “The water remembers us.”, “One coin. No names.”, and “Do not look back.” No quote crosses a scene boundary. | Pass. |
| Voice isolation | Prompt-delivery tests prove each narrator's voice and examples occur only in that narrator's indexed packet, including the Alice → Bob → Alice transition. Shared material occurs once. Fixture inspection found no narrator/source reassignment. | Pass for implementation isolation. |
| Continuity | The bundle-wide prompt requires each section to use the preceding returned section as its prose handoff while preserving plan order. Raw-order validation prevents a normalized response from hiding reordered prose. | Pass. |
| Tail completeness | The complete fixture closes scene 3 with non-empty prose. Partial fixtures classify empty, incomplete, and absent tails; only complete sections are retained and every missing index is reported. | Pass. |
| Review boundary | Output contains no transport markers. Structural guards and browser tests confirm no assembly, approval, or promotion follows bundle completion. | Pass. |

This deterministic gate validates file equivalence, grounding, attribution, prompt isolation, ordering, and complete-tail handling without spending model tokens. Subjective prose quality still depends on the chosen frontier model and campaign material. Before release to a production campaign, run Scenario 9 from `quickstart.md` against one human-reviewed session and block that model/configuration if a reviewer finds voice flattening, invented quotes, scene leakage, weak transitions, or tail compression.

## Functional requirement audit

| Requirements | Evidence | Result |
|---|---|---|
| FR-001–FR-002, FR-005 | `--batch-scenes`, explicit full-plan/subset selection, plan-order normalization, and the pre-call scope banner are covered by CLI tests. | Pass. |
| FR-003–FR-004 | The current-scene button remains and the separate dialog materializes every literal scene index, identity, narrator, count, and replacement state; empty server scope refuses. | Pass. |
| FR-006–FR-008 | Shared formatter preserves artifacts; scene packets carry matching source and narrator guidance; shared context occurs once and within-response handoff preserves continuity. | Pass. |
| FR-009–FR-011 | Stable index/marker reconciliation rejects ambiguous structure; valid partials retain exactly K complete sections and report N−K missing sections with exit 3. | Pass. |
| FR-012 | Selected sources, overrides, narrator declarations/guidance, scope, output ceiling, and explicitly supplied input paths are checked before client construction. Refusals finalize a zero-exchange report. | Pass. |
| FR-013–FR-014 | Versioned atomic reports carry requested/written/missing/rejected counts and exchange state; the SSE route validates its nonce report, streams status, and reloads disk-backed scene and pipeline state. | Pass. |
| FR-015–FR-018 | Structural guards preserve the review checkpoint, sequential remains default, current-scene narration remains available, and targeted reruns touch only the selected scene. | Pass. |
| FR-019–FR-021 | Content bundling and provider Batch are separate flags and UI concepts; capacity refusal makes no client; the CLI/dialog display replacements and report them durably. | Pass. |

## Success criteria audit

| Criteria | Evidence | Result |
|---|---|---|
| SC-001–SC-002 | The call matrix proves one live call or one provider-batch item for N bundled scenes, with shared context delivered once. | Pass. |
| SC-003–SC-004 | Shared formatter tests and exact marker/index reconciliation preserve artifact shape and reviewed identity for every written scene. | Pass. |
| SC-005 | CLI and editor scenarios split one response into ordinary per-scene files without manual transport handling. | Pass. |
| SC-006 | The 58-test sequential regression passes and browser coverage retains the current-scene action. | Pass. |
| SC-007 | K-of-N, zero-of-N, incomplete, empty, and absent fixture cases preserve valid files and name all missing scenes. | Pass. |
| SC-008 | Banner, JSON report, activity row, SSE terminal payload, and UI status expose mode, scope, exchange count, and outcome. | Pass. |
| SC-009 | No bundle path invokes approval, assembly, promotion, or a downstream stage. | Pass. |

## Story and constitution audit

All four stories are independently covered: US1 by the CLI/call matrix, US2 by command-builder/router/browser tests, US3 by prompt/protocol/structural tests and the representative review above, and US4 by sequential and partial-recovery tests.

The post-design constitution check remains satisfied:

- Disk remains truth through existing per-scene drafts plus an atomic run report.
- Reviewed plan/extractions define explicit scope; the human checkpoint remains.
- Narration performs no retrieval and all model calls use the existing client facade.
- Verbatim rules remain in the prompt contract and quote evidence remains scene-local.
- The CLI owns parsing, reconciliation, calls, and writes; the UI invokes and displays it.
- State is discoverable after navigation through files, reports, sidecars, and activity rows.
- The UI sends literal indices and shows a copyable CLI command.
- Existing option vocabulary and config ownership are reused; configuration is additive.

## Residual limitations

- A live same-model prose comparison was not run because no production campaign/session and backend were supplied. The deterministic quality gate passed; the live human prose review described above remains a release operation for each chosen model/configuration.
- The repository-wide suite has 31 unrelated existing failures as recorded above. The feature-focused, sequential, structural, build, and browser gates all pass.
- Capacity preflight uses the configured projected-output ceiling. It cannot predict a provider's effective context window beyond information already exposed by the selected backend, so an upstream provider may still reject a request whose input context is too large.
