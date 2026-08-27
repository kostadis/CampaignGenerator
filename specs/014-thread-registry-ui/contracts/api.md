# Contract: `/api/projections/threads/*` (014)

Added to the **existing** projections router (`server/routers/projections.py`,
mounted at `/api/projections` by `server/main.py:55`). No new router, no new
config document — see plan "Structure Decision".

**Hard constraint**: no string literal matching `^(docs/|summaries/|summaries$)`
may appear in this file outside a docstring —
`tests/test_projection_routes.py::test_no_literals_in_router` AST-parses it.
Every path comes from `ProjectionConfigService.resolved()`.

## Reads (one-shot subprocess, `subprocess.run` + 400-with-stderr)

| Route | Shells out to | Returns |
|---|---|---|
| `GET /threads/registry` | `thread_registry list --json` | `{version, threads[], count}` |
| `GET /threads/proposals` | `thread_registry proposals --json` | `{proposals[], counts{}}` — **the whole set, unpaged and unfiltered**. Search and filtering happen in the browser (see `ui.md`); adding a query/paging parameter here would move "which candidates matter" into the server |
| `GET /threads/check` | `thread_registry check --json` | `{threads, problems[]}` — **200 even when problems is non-empty**; the CLI's exit 1 is data here, not a transport error |

`GET /threads/corpus?pattern=…&pattern=…` — resolve explicit glob patterns to
the concrete file list the harvest would read. **No config fallback**: patterns
are required, an empty list is a 400 (research D5, Constitution X). Matches are
confined to the workspace the way `ensemble.py::list_chapters` does
(`if cwd not in r.parents: continue`). Returns
`{"files": [{"path": "…", "size": N}], "count": N}` — **file names only, no
chapter numbers** (GM ruling, research D20). The engine's `chapter_of()` is
neither imported here nor wrapped in a verb, so the subprocess seam stays the
only way this router reaches the engine. The chapterless-candidate warning D4
motivated lives on the candidate card and in the accept form instead.

## Harvest (SSE — the one long-running operation)

```
GET /threads/run/propose?corpus=<glob>&corpus=<glob>…
```

- `corpus: list[str] = Query(default=[])`, empty → **400**, copying
  `run_recent_events`' wording: *"corpus is required — pass at least one
  --corpus glob."* Never a 422, never an implicit "all".
- Streams `thread_registry propose --corpus …` through `stream_subprocess`.
- **No selection resolution, no backend flags, no `--model`.** This is
  deterministic; reaching `resolve_selection` here would imply otherwise.

## Writes (one-shot subprocess; the CLI's stderr is the error body)

Each returns `{"ok": true, "stdout": "…"}` on success, or **400** whose
`detail` is the CLI's own message verbatim (FR-021, research D7).

| Route | Body | Shells out to |
|---|---|---|
| `POST /threads/rule` | `{norm, status, note?, thread?}` | `thread_registry rule …` |

| `POST /threads/ratify` | `{norm, id, title, opened, status?, tracker?, notes?, log:[{chapter,change,summary,quote?}]}` | **one** call: `thread_registry ratify --norm <norm> --plan -`, the body forwarded as the plan JSON on stdin (GM ruling, research D18) |
| `POST /threads/log` | `{id, chapter, change, summary, quote?}` | `thread_registry log …` |
| `POST /threads/status` | `{id, status, chapter?}` | `thread_registry set-status …` |
| `POST /threads/alias` | `{id, alias}` | `thread_registry alias …` |

`POST /threads/ratify` is a **single** subprocess call, so it has no
partial-apply state and no per-step report: **200** on success, **400** with the
CLI's own message when the engine refuses, and nothing is ever half-written.
This is the whole reason the GM chose the atomic verb over route-side
sequencing (research D18) — the alternative needed a 207 and a step-by-step
response body the page would have had to render.

Validation performed at the route edge (before any subprocess):

- `log` must be non-empty **and** every `chapter` an `int >= 1` — a chapterless
  accept is refused here with a message naming the field, so the GM is not
  handed `check_registry`'s wording for a form problem.
- `norm`, `id`, `title` non-empty.

## Changed existing routes

`GET /sections` — unchanged in shape; the payload gains `missing` because the
CLI emits it (research D11). The router still returns the parsed payload
verbatim.

`GET /api/config/status` — **~~replace `api_key_present` with a per-backend
`credentials` map~~ WITHDRAWN, 2026-08-26.**

That was the narrow fix from #341. The GM ruled the predicate away entirely
(#342, PR #343), and **FR-034 now forbids exactly what this section used to
specify** — "no global 'is a key set' probe may exist… including one derived
under a different name." A per-backend map is that probe under another name.

What PR #343 does instead: `api_key_present` is deleted from the payload, which
becomes `{"cwd": "…"}`. Nothing replaces it. See `data-model.md` §6b, which was
withdrawn the same way.

## Module docstring

Rewritten. The current text ("There is no route for thread triage … adding a
write route for proposals would move a judgment checkpoint into the interface")
becomes false when this ships. The replacement must state the reversal, its
date, and the constraints that preserve the principle (one candidate per
ruling, every field shown before it is written, no bulk control).
