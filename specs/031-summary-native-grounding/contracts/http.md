# HTTP Contract: `/api/grounding/summary-native`

Router: `server/routers/summary_native.py`. Every run route shells out to
`console_script("summary_native")` and streams it with the existing SSE helper
(Principle VI). Defaults resolve from `GroundingConfigService` at the route edge.
Routes take sentinels (`""`, or `None` for ints), and no default literals are
allowed (Principle XII).

## Config

The config is stored in the existing `grounding.yaml` under a new strict group,
`summary_native`. It is edited through the existing `GET`/`PUT /api/grounding/config`
(a partial merge). No new config route is added. `--audit` defaults to the existing
`campaign_state.track_files`, which is not duplicated here (Principle XII).

```yaml
summary_native:
  summaries_dir: docs/summaries
  out_root: docs/summary_native
  canon_file: docs/summary_native/canon.yaml
  range_since: null
  range_until: null
  recent_chapters: 4
  recurring_min: 10
  parts: 0
```

## Read-only

| Method & path | Returns |
|---|---|
| `GET /chapters?summaries_dir=` | `{present: [int], files: [{chapter, path}], duplicates: [...]}`, filled from filename prefixes only, for the range picker |
| `GET /report?since=&until=` | the range directory's `validation_report.json` (404 if not run) |
| `GET /drafts?since=&until=` | `[{doc, path, status: draft|incomplete, bytes}]` |

## Runs (SSE, `GET`, same shape as `/api/grounding/run/*`)

| Path | argv |
|---|---|
| `/run/validate` | `summary_native validate --summaries-dir … --since … --until …` |
| `/run/build` | `… build … [--force]` |
| `/run/synth/{doc}` | `… synth <doc> … [--world-state] [--campaign-state] [--audit …] [--name …] [--recent-chapters N] [--recurring-min N] [--parts N] [--max-tokens N] [--dump-only] [--force] --backend/--model` from the selection. `recent_chapters`/`recurring_min`/`parts` fall back to config; `name`, `max_tokens`, `dump_only` are per-run |
| `/run/compare/{doc}` | `… compare <doc> --live docs/<doc>.md` |

**Refusals** (HTTP 400, before spawning):
- `from`/`to` unset in both the request and the config (Principle X: no silent
  "all" in the UI).
- `summaries_dir` unset.
- An unknown `doc`.

The CLI owns every other refusal and reports it through the stream.

## Deliberately CLI-only (Principle XI ruling)

`--registry`, `--canon` and `--out-root` have no per-run UI control. The routes never
pass them, so the CLI resolves its defaults: `docs/entity_registry.yaml`
auto-discovery, `<out-root>/canon.yaml`, and `grounding.yaml summary_native.out_root`.
These are campaign-layout paths, set once. Ruled by the GM (kostadis) on 2026-10-05,
in the `/speckit-analyze` remediation, option B. Recorded in plan.md's Constitution
Check.
