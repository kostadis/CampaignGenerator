# Resource lookup audit for issue #494

The 17 lookup sites below are the issue inventory. Record installed-mode verification in the final column as implementation progresses. A checkout-relative path is not sufficient evidence.

| # | Lookup site | Current use | Resource class | Planned owner | Verification |
|---:|---|---|---|---|---|
| 1 | `campaignlib/config.py:load_repo_file` | Checkout prompts by path and basename | Shipped read-only resource or campaign override | `campaignlib.resources` / campaign | `tests/test_config_env.py` and installed override/default smoke pass |
| 2 | `campaignlib/config.py:load_agent_prompt` | Checkout agent prompt by name | Shipped read-only resource or campaign override | `campaignlib.resources.agents` / campaign | `tests/test_agent_prompt_loader.py` and installed override/default smoke pass |
| 3 | `session_doc/narrate.py:_template_candidates` | Checkout prompt location in diagnostics | Shipped read-only resource or campaign override | `campaignlib.resources.agents` / campaign | `tests/test_narrate_template_contract.py` passes with packaged-default path |
| 4 | `campaignlib/wiring.py:_candidate_paths` | Checkout/CWD wiring fallback | External wiring | Mneme at user config path | `tests/test_wiring.py`, installed wiring smoke in `tests/test_installable_wheel.py`, and mneme `tests/integration/test_apply.py` pass |
| 5 | `pipelines/workspace/new_workspace.py:REPO_ROOT` | Checkout-root next-step commands | Campaign/user output plus installed command | Selected workspace / console entry points | Installed `new_workspace` creates a temporary campaign; `tests/test_new_workspace_layout.py` passes |
| 6 | `pipelines/rlm/mcp_server.py` | Root `.py` dispatch | Package-local command | Current interpreter console entry point | `tests/test_mcp_server.py` passes with compatible MCP 1.x; source dispatch uses the interpreter console path (MCP 2.x compatibility belongs to #493) |
| 7 | `pipelines/grounding/grounding_sections.py` | Root `.py` subprocess and import shim | Package-local command | Current interpreter module | Installed `grounding_sections --help` passes; synthesis dispatch uses `python -m` |
| 8 | `pipelines/grounding/event_spine.py` | Root import shim | Package-local module | Installed package import | Installed `pipelines.grounding.event_spine` import passes |
| 9 | `pipelines/grounding/thread_registry.py` | Root import shim | Package-local module | Installed package import | Installed `pipelines.grounding.thread_registry` import passes |
| 10 | `pipelines/grounding/build_recent_events.py` | Root import shim | Package-local module | Installed package import | Installed `pipelines.grounding.build_recent_events` import passes |
| 11 | `server/routers/connections.py` | Root import shim | Package-local module | Installed package import | Installed `server.routers.connections` import passes |
| 12 | `server/routers/scene_editor.py` | Root import shim | Package-local module | Installed package import | Installed `server.routers.scene_editor` import passes |
| 13 | `session_doc/review/serve.py:PAGE` | Adjacent HTML filesystem path | Shipped read-only resource | `session_doc.review` | `tests/test_reviewer_selfcontained.py` installed-resource check passes |
| 14 | `pipelines/ensemble/ensemble_extract.py` | Sibling `.py` subprocess | Package-local command | Current interpreter module | Installed `pipelines.ensemble.ensemble_extract` import and `tests/test_ensemble_dispatch.py` pass |
| 15 | `pipelines/ensemble/ensemble.py` | Sibling `.py` subprocess | Package-local command | Current interpreter module | Installed `ensemble --help` and `tests/test_ensemble_dispatch.py` pass |
| 16 | `pipelines/ensemble/ensemble_batch.py` | Sibling `.py` subprocess | Package-local command | Current interpreter module | Installed `ensemble_batch --help` and `tests/test_ensemble_dispatch.py` pass |
| 17 | `server/main.py` | Checkout frontend build | Web build artifact | Source checkout `frontend/dist` | `npm run build` passed; disposable source-checkout `./start` served HTTP 200 |

Additional checkout-relative runtime lookups discovered during implementation belong here before release verification.
