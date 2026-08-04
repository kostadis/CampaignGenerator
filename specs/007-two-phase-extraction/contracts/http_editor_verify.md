# HTTP Contract: Session Doc Editor — verification surface

Additions to `server/routers/scene_editor.py` (prefix `/api/editor`). Both
follow existing patterns exactly; neither reimplements pipeline logic
(Principle VI).

---

## `GET /verify`

Streams `sd_verify_quotes` over the configured artifacts.

**Mirrors**: `api_enhance` (`scene_editor.py:1011`) and `api_extract`
(`:1043`) — same `_build_*_cmd` → `stream_subprocess` → `_record_activity`
shape.

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `target` | `summary \| scenes \| both` | `both` | Which artifacts to check |
| `report_only` | `0 \| 1` | from `VerifyKnobs.report_only` | Suppress in-place annotation |

**No `batch` parameter.** Batch is an Anthropic Message Batches concept and
verification calls no model. Offering it would imply a cost this endpoint
cannot incur.

### Response

`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` —
identical headers to the existing stream endpoints.

### Errors

`_sse_error` with a remediable message, matching current behaviour:

| Condition | Message |
|---|---|
| No VTT resolvable | `No .vtt found in the session directory — set it on the Editor Config page.` |
| Artifact missing | `session-summary.md not found — run Enhance Summary first.` |
| Scene dir empty | `No scene extraction files found — run Extract Quotes first.` |

### Side effects

Calls `_record_activity(cfg, stage="verify", rc=rc, knobs={…}, outputs=[report_path])`,
so the run appears in the editor's activity record like every other stage.

---

## `GET /pipeline-status` — extended

Adds a `verify` key beside the existing `enhance` / `extract` / `plan` /
`narrate`.

```jsonc
{
  "enhance":  { "status": "ok",   "ago": "2h", "mtime": 1..., },
  "extract":  { "status": "ok",   "ago": "1h", "count": 12 },
  "verify": {
    "status": "warn",            // cold | ok | warn
    "ago": "5m",
    "mtime": 1...,
    "unverified": 8,             // headline number
    "near": 148,
    "verified": 336
  },
  "plan":     { … },
  "narrate":  { … }
}
```

**Status semantics** — reuses `_stage_status(output, inputs)` with the report as
output and `[vtt, summary, *scene_files]` as inputs:

| Value | Meaning |
|---|---|
| `cold` | No report — never verified |
| `ok` | Report newer than every artifact **and** `unverified == 0` |
| `warn` | Report is stale **or** `unverified > 0` |

Stale and has-findings both surface as `warn` because both mean *the GM has
unfinished business here*. The counts distinguish them; the frontend shows
which.

`unverified`/`near`/`verified` are read from the report's summary table. If the
report cannot be parsed, `status` is `warn` with counts `null` — an unreadable
report is not a passing one.

---

## Config: `PUT /config`

`VerifyKnobs` joins the existing `SessionEditorConfig` groups
(`server/session_editor_config_shared.py`), reachable through the existing
`GET`/`PUT /api/editor/config` routes. No new config endpoint.

```yaml
# <config>/session_doc.yaml
verify:
  threshold: 0.85      # near/unverified boundary — NOT calibrated for DeepSeek (D8)
  min_tokens: 4
  report_only: false
```

The schema is `extra="forbid"`, so an unknown key under `verify:` fails
validation on load rather than being silently ignored.

---

## Frontend

- A **Verify** action in the Session Doc Editor, beside Enhance / Extract.
- The header status strip gains a verify dot, labelled with the `unverified`
  count when non-zero.
- The count links to `quote_report.md`, opened through the existing Typora
  integration.

The UI shows **counts and staleness only**. Judging whether a finding is real,
and fixing it, happens in Claude or an editor — Principle IX. There is no
accept/reject control, because accepting a finding would mean rewriting a
quote, which FR-006 forbids.
