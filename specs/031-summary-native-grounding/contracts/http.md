# HTTP Contract: `/api/grounding/summary-native`

Router: `server/routers/summary_native.py`. Every run route shells out to
`console_script("summary_native")` and streams it with the existing SSE helper
(Principle VI). Defaults resolve from `GroundingConfigService` at the route edge.
Routes take sentinels (`""`, or `None` for ints), and no default literals are
allowed (Principle XII).

## Config

The config is stored in the existing `grounding.yaml` under a new strict group,
`summary_native`. It is edited through the existing `GET`/`PUT /api/grounding/config`
(a partial merge). No new config route is added.

```yaml
summary_native:
  summaries_dir: docs/summaries
  out_root: docs/summary_native
  canon_file: docs/summary_native/canon.yaml
  range_from: null
  range_to: null
  recent_chapters: 4
  recurring_min: 10
  parts: 0
  audit_files: []
```

## Read-only

| Method & path | Returns |
|---|---|
| `GET /chapters?summaries_dir=` | `{present: [int], files: [{chapter, path}], duplicates: [...]}`, filled from filename prefixes only, for the range picker |
| `GET /report?from=&to=` | the range directory's `validation_report.json` (404 if not run) |
| `GET /drafts?from=&to=` | `[{doc, path, status: draft|incomplete, bytes}]` |

## Runs (SSE, `GET`, same shape as `/api/grounding/run/*`)

| Path | argv |
|---|---|
| `/run/validate` | `summary_native validate --summaries … --from … --to …` |
| `/run/build` | `… build … [--force]` |
| `/run/synth/{doc}` | `… synth <doc> … [--world-state] [--campaign-state] [--audit …] [--parts] [--force] --backend/--model` from the selection |
| `/run/compare/{doc}` | `… compare <doc> --live docs/<doc>.md` |

**Refusals** (HTTP 400, before spawning):
- `from`/`to` unset in both the request and the config (Principle X: no silent
  "all" in the UI).
- `summaries_dir` unset.
- An unknown `doc`.

The CLI owns every other refusal and reports it through the stream.
