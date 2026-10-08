# HTTP Contract: party, planning and thread proposals (Principle XI parity)

The routes build argv and stream CLI output over SSE via `subprocess_runner`, as spec 033 does. No pipeline logic lives in a router, and defaults resolve at the route edge from `grounding.yaml`, with no literals in the router.

| Route | CLI | Change |
|---|---|---|
| `GET /api/grounding/summary-native/run/synth/{doc}` | `synth <doc>` | **party / planning now use the chunked path.** `parts`, `world_state` and `campaign_state` are removed; a request carrying one gets a 400 with the CLI's refusal text. `fallback_npc_lines` is accepted for `world_state` and `planning` (400 otherwise). `name`, `recent_chapters` and `recurring_min` are accepted for `world_state` and `planning` (400 for `party`). `party_config` and `planning_config` are unchanged. Prose backend/model/effort come via `resolve_selection(... service="summary_native.prose")` |
| `GET /api/projections/threads/run/group-propose` | `summary_native thread-propose` | **New.** `since until` (required; 400 without), `max_input_chars`, `max_tokens`, `dump_only`, plus the backend/model/effort selection via `service="summary_native.prose"` |
| `POST /api/projections/threads/ratify` | `thread_registry ratify --key … --plan -` | **Extended.** The body carries either `norm` (as today) or `key` (group proposal) plus the plan. For `key`, the route edge requires `members` (non-empty, a subset of the proposal's) and a log with integer chapters ≥ 1 |
| `GET /api/projections/threads/plan?key=…` | `thread_registry ratify --key … --emit-plan` | **New.** Read-only. Returns `derive_plan` for the editor to start from |
| `POST /api/projections/threads/rule` | `thread_registry rule` | **Extended.** Accepts `key` as well as `norm` |
| `GET /api/projections/threads/proposals` | — (reads the file) | **Extended.** Group proposals are returned with `kind`, `title`, `thread`, `members[]` and `source`, beside name-keyed ones |
| `GET /api/grounding/summary-native/state` | — | **Extended.** Per range: party/planning draft presence, `missing_dossiers` for planning, and `threads: {ratified_in_range, open, unattached, ambiguous, pending_groups}` read from `state/threads/` and the proposals file |
| `GET /api/grounding/summary-native/drafts` | — | **Extended.** Lists `reference/party.md`, `party_report.md`, `planning_npcs_report.md`, `arc_report.md` and `threads_report.md` |

## Pages

**`SummaryNative.vue`.** The party and planning steps become the same component as the world_state/campaign_state steps:
- prose model and effort; Run / Dump-only / Force;
- for planning only, the per-run, never-persisted "Write fallback lines for NPCs without a published dossier" checkbox;
- refusal lists rendered as for world_state.

The Parts control and the upstream-draft pickers are removed. The planning step shows the thread counts from `/state` and links to the Threads page.

**`Threads.vue`:**
- **A "Propose groupings" step:** range (prefilled from the summary-native page's current range), model/effort, Run / Dump-only. It streams the CLI and refreshes the proposals list.
- **Group proposals:** each shows its kind, suggested title or target thread, and its members (chapter, tag, name, text, citation).
- **The ratify editor:**
  - starts from `/threads/plan`;
  - lets the GM edit the title, status, members (unticking a member splits the proposal) and aliases;
  - posts the plan.
  - It has no one-click accept (the existing SC-004 rule).
- **Reject / Defer:** as today, by `key`.

## Config

`grounding.yaml summary_native.prose` gains the strict `party_budgets` and `planning_budgets` maps. Their keys are limited to the section names in `schema.DEFAULT_PARTY_BUDGETS` / `DEFAULT_PLANNING_BUDGETS`, with values ≥ 1. They are read and written through the existing grounding config routes.
