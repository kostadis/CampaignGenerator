# HTTP and UI Contract: Persistent Narration Wiki

The FastAPI layer is a transport adapter for `narration_wiki`. It contains no collection, measurement, ruling, proposal, or recovery logic.

## Process boundary

- Resolve the selected campaign and session through the application's established configuration boundary.
- Accept campaign identity and a session-relative selection, never an arbitrary executable or raw argument list.
- Resolve the console script with `console_script("narration_wiki")`.
- Construct a fixed argument vector from typed request fields.
- Execute `status` with a new bounded JSON helper in `server/subprocess_runner.py`.
- Execute every other command, including `index-check`, with `stream_subprocess(...)`.
- Pass `save_run_log=False` for narration-wiki streams. The helper keeps `True` as its backward-compatible default for existing routes.
- Never call `subprocess.run`, `Popen`, or `asyncio.create_subprocess_exec` directly from the narration-wiki router.
- On disconnect or browser cancellation, rely on the shared runner's process-group termination and SIGKILL fallback.
- Reload status from disk after success, refusal, failure, or cancellation.

The bounded status helper owns timeout, byte limit, return-code mapping, redaction, and process cleanup centrally. It does not create a diagnostic run log.

## Scope object

Every request identifies the same scope:

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001"
}
```

The router maps this to the configured campaign root and an existing selected-session directory. Empty values, traversal, absolute session paths, an unknown campaign, a campaign root selected as a session, and an escaping symlink are rejected before process launch.

## Status

```http
GET /api/narration-wiki/status
    ?campaign_id=toee
    &session_relative=sessions%2Fsession-42
    &iteration_id=iter-001
Accept: application/json
```

Success is `200 application/json` with the exact CLI `status --json` object.

The helper enforces:

- a short fixed timeout;
- a fixed maximum stdout byte count;
- exactly one JSON object and no trailing non-whitespace output;
- no feature-artifact or run-log write.

Mapped failures:

| CLI condition | HTTP status |
|---|---:|
| Invalid or empty request syntax | `400` |
| Unknown campaign, containment, symlink, or dependency refusal | `403` |
| Missing iteration | `404` |
| Lifecycle, stale state, or recovery conflict | `409` |
| Invalid persisted schema/artifact | `422` |
| Mutation/recovery or unexpected process failure | `500` |
| Status timeout or output bound exceeded | `504` |

The error body is `{"detail":"safe message","code":"stable_category"}` and excludes absolute paths, tracebacks, and arbitrary stderr.

## Streaming actions

All action endpoints use `POST` and respond with `text/event-stream`.

| Endpoint | CLI command |
|---|---|
| `/api/narration-wiki/collect` | `collect` |
| `/api/narration-wiki/measure` | `measure` |
| `/api/narration-wiki/index-check` | `index-check` |
| `/api/narration-wiki/conflict-rule` | `conflict-rule` |
| `/api/narration-wiki/pattern-rule` | `pattern-rule` |
| `/api/narration-wiki/proposal-stage` | `proposal-stage` |
| `/api/narration-wiki/proposal-apply` | `proposal-apply` |
| `/api/narration-wiki/proposal-rule` | `proposal-rule` |

Each body contains the scope fields plus only the command-specific fields below.

### Collect

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001"
}
```

### Measure

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "phase": "before",
  "proposal_id": null
}
```

`proposal_id` is required only for `after`.

### Index check

The body is the scope object with no additional fields.

### Conflict ruling

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "conflict_id": "seed-voice",
  "resolution": "Use the campaign-specific first-person convention.",
  "rationale": "The selected campaign rulebook is authoritative for this campaign."
}
```

### Pattern ruling

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "pattern_slug": "distinct-narrator-bookkeeping",
  "decision": "accept",
  "tier": "campaign",
  "named_portable_override": false,
  "rationale": null
}
```

`tier` is null for rejection. The override is permitted only for accepted portable placement and then requires rationale.

### Proposal staging

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "proposal_id": "proposal-001",
  "draft_relative": "proposals/incoming/proposal-001.yaml",
  "evidence_bindings": [
    {
      "source_ref": "narration/falrinth.md",
      "source_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "applies_to_kind": "rule",
      "applies_to_key": "bookkeeping-per-narrator"
    }
  ],
  "override_rationale": null
}
```

Evidence bindings and override rationale are mutually exclusive. The router serializes each binding to the CLI option without evaluating whether it qualifies.

### Proposal application

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "proposal_id": "proposal-001"
}
```

### Proposal ruling

```json
{
  "campaign_id": "toee",
  "session_relative": "sessions/session-42",
  "iteration_id": "iter-001",
  "proposal_id": "proposal-001",
  "decision": "reject"
}
```

The request cannot carry evidence bindings or an override rationale.

## SSE grammar

The router preserves the established shared-runner stream:

```text
event: command
data: "<redacted invocation>"

data: "one stdout or stderr line\n"

event: done
data: {"returncode":0,"result":"success"}

```

Pre-launch streaming refusals use `sse_error_stream(...)` and end with a `done` event containing the nonzero return code and safe error text.

Rules:

- `command` occurs once before process output.
- Default `data` events preserve arrival order and contain JSON-encoded strings.
- `done` occurs once when the generator remains connected.
- A zero return code is success; all nonzero return codes are failure and use the CLI categories.
- No absolute path, secret, or unrestricted stderr reaches the browser.
- Disconnect may suppress the final event, but it still terminates the process group.

The browser uses a fetch/ReadableStream SSE client because native `EventSource` cannot send POST bodies. One `AbortController` owns each action. Starting another action while one runs is disabled.

## UI route and navigation

- Route: `/workflow/wiki`.
- Workflow step: `7`.
- Sidebar label: `③ Narration Wiki`.
- The page uses the existing application shell, colors, typography, buttons, cards, inputs, badges, and focus styles.
- The page introduces no independent theme tokens.

The operator flow is:

```text
select campaign/session/iteration
  -> collect
  -> baseline measure
  -> review seed conflicts and rule each one
  -> review pattern drafts and rule each one at Gate 1
  -> validate indexes and companion capability
  -> stage one proposal
  -> apply for comparison
  -> measure after
  -> accept and retain, or reject and restore, at Gate 2
  -> inspect persisted impact and status
```

Each action remains disabled until disk-derived status shows its preconditions. Failure or cancellation returns the UI to refreshed authoritative status rather than optimistic browser state.

## Page layout and scrolling

The sole supported viewport for this feature is exactly `1280x720`.

The application shell currently constrains outer overflow, so the narration-wiki page owns vertical and horizontal scrolling for content that exceeds its available region. The following content regions are explicitly resizable:

- manifest and collected evidence;
- measurement results;
- proposal diff and prior-ruling evidence;
- history and streamed command output.

Every resizable region uses the same page-level class with:

```css
box-sizing: border-box;
min-width: 320px;
min-height: 160px;
max-width: 100%;
resize: both;
overflow: auto;
scrollbar-gutter: stable;
```

Panel contents adapt to the panel's own size. Measurement tables retain an intrinsic minimum width, and diffs retain `white-space: pre` so horizontal overflow is real and inspectable. Gate controls remain reachable when neighboring panels are at their minimum dimensions.

## Browser verification

Pinned Playwright coverage runs at exactly 1280x720 and verifies:

1. workflow step and sidebar navigation reach the page;
2. existing shared CSS tokens/classes style the new page;
3. each command constructs the documented payload;
4. every POST stream processes `command`, output, and `done` events;
5. cancellation aborts the fetch and a status reload occurs;
6. a nonzero return code displays failure and a status reload occurs;
7. Gate 1 and Gate 2 controls follow disk-derived preconditions;
8. each named panel can be set to exactly 320x160;
9. overflowing panel content has `scrollWidth > clientWidth` and `scrollHeight > clientHeight`;
10. each panel scrolls to both maximum axes while Gate controls remain keyboard-focusable.

## Security invariants

- Request models reject unknown fields.
- Enums are closed and identifiers use the CLI grammar.
- The router owns all path resolution and argument ordering.
- User text is passed as one argument value, never through a shell.
- The fixed command is executed with `shell=False` through the shared helper.
- No endpoint accepts an executable name, environment override, absolute target path, or arbitrary extra arguments.
- Responses are `Cache-Control: no-store`.
