# Contract: `thread_registry` CLI (014)

The engine. Every registry write in the product goes through these verbs —
the web routes are argv builders around them (Constitution VI).

Existing verbs are **unchanged in behaviour**; the additions below are additive.

## Existing surface (for reference)

```
thread_registry [--registry PATH] propose --corpus GLOB [GLOB ...] [--out PATH]
thread_registry [--registry PATH] add --id ID --title T --opened CH
                                      [--status S] [--tracker T] [--notes N]
thread_registry [--registry PATH] log --id ID --chapter N --change C --summary S [--quote Q]
thread_registry [--registry PATH] set-status --id ID --status S [--chapter N]
thread_registry [--registry PATH] alias --id ID --alias A
thread_registry [--registry PATH] check
thread_registry [--registry PATH] render --output PATH
thread_registry [--registry PATH] speculate ...        # LLM; NOT exposed by this feature
```

`--registry` defaults to `stores.thread_registry`; `--out`/`--proposals`
default to `stores.thread_proposals`. Resolution happens once, before any work,
from `<config>/projections.yaml`.

## NEW — `ratify`: turn one proposal into canon, atomically (GM ruling, D18)

```
thread_registry ratify --norm KEY (--plan FILE | --plan - | --emit-plan)
                       [--proposals PATH] [--registry PATH]
```

One call does the whole accept: create the thread (or locate the matched one),
append every log row, and mark the proposal `ratified` with its `ruled_thread`
link. **There is no partial-apply window** — the registry is built in memory,
validated with `check_registry`, and written once via `atomic_write_text`.

`--emit-plan` prints the derived starting point as JSON and writes nothing:

```json
{"id": "buppidos-divine-plan", "title": "Buppido's divine plan",
 "status": "open", "opened": 30, "tracker": null, "notes": "",
 "log": [{"chapter": 30, "change": "opened", "summary": "…", "quote": "…"},
         {"chapter": 41, "change": "advanced", "summary": "…"}]}
```

`--plan` is **required** for a write — there is no "accept as proposed" flag.
The plan is JSON (a file or stdin) rather than repeated `--log
CH:CHANGE:SUMMARY` flags because summaries and quotes are prose and will
contain colons. The GM edits the emitted plan; the web form is the same object
rendered as fields (FR-008).

When the proposal carries `matches: <id>`, `id`/`title`/`opened` in the plan
are ignored with a note and the log rows are appended to the matched thread —
no second thread is created (FR-009).

Refusals (exit 1, nothing written):

| Condition | Message |
|---|---|
| No such proposal | `error: no proposal with norm 'X' — run propose first` |
| Missing `--plan` | `error: ratify needs --plan (use --emit-plan to derive a starting point)` |
| A log row without a real chapter | `error: log row 1 has no chapter — a thread's chapters are yours to decide, not the harvest's` |
| Resulting registry fails invariants | `error: refusing to save a registry that fails check` + the per-problem lines |
| Thread id already exists (and no `matches`) | `error: thread id 'X' already exists` |

**The one non-atomic seam, stated rather than hidden**: the registry and the
proposals file are two files. `ratify` writes canon first, then the ruling. If
the second write fails, the thread exists and the candidate stays `pending`; a
re-run then refuses with `error: thread id 'X' already exists`, which is a
readable, recoverable state — not a silent one. Ordering it the other way round
would risk a proposal marked ratified with no thread behind it, which is worse.

## NEW — `rule`: record a GM ruling on one proposal

```
thread_registry rule --norm KEY --status {ratified|rejected|deferred}
                     [--note TEXT] [--thread ID]
                     [--proposals PATH] [--adjudication PATH]
```

| Flag | Required | Meaning |
|---|---|---|
| `--norm` | yes | The proposal's normalised-title key. **Exactly one.** No `--all`, no repeated `--norm`, no glob — FR-007 is enforced by the argument shape, not by convention. |
| `--status` | yes | The ruling. |
| `--note` | no | Free GM text stored on the proposal. |
| `--thread` | no | On `ratified`, the thread id the ratification produced; stored as `ruled_thread`. `ratify` sets this itself; the flag exists for a GM reconciling a thread they created by hand. |
| `--proposals` | no | Defaults to `stores.thread_proposals`. |
| `--adjudication` | no | Defaults to `stores.thread_adjudication`. |

Behaviour:

- Rewrites the named proposal in place, preserving every other proposal and the
  file's `note:` preamble.
- `--status deferred` **also appends** an entry to the adjudication bundle
  (creating it with `{"version": 1, "entries": []}` if absent). Appending, not
  overwriting — an in-flight conversation must not lose its input.
- Re-ruling a `deferred` proposal to `ratified`/`rejected` updates the status
  and leaves the bundle entry in place (the conversation happened; the record
  of it is not a lie).

Refusals (exit 1, message on stderr):

| Condition | Message |
|---|---|
| No such proposal | `error: no proposal with norm 'X' — run propose first` |
| Bad status | `error: bad ruling 'X' (allowed: ratified, rejected, deferred)` |
| Proposals file absent | `error: no proposals file at PATH — run propose first` |

## CHANGED — `propose` re-evaluates a ratified candidate (research D17b)

`propose()`'s short-circuit narrows from *"any prior ruling"* to **`rejected`
and `deferred` only**:

```python
if key in prior and prior[key]["status"] in ("rejected", "deferred"):
    proposals.append(prior[key]); continue
```

A `ratified` candidate falls through to the existing `matches`/`logged` filter
and is re-offered carrying only its **unlogged** chapters, keeping its
`ruled_thread` link. Without this, accepting a thread at chapter 41 hides
chapters 50–60 of that same thread forever, and FR-009 is unreachable through
the surface.

The engine's *"GM rulings are a one-way door"* comment stays, scoped to the
rulings it was about. A rejection is a door; an acceptance is not.

## NEW — thresholds on `propose` (research D15)

```
thread_registry propose --corpus GLOB [...] [--min-chapters N] [--min-evidence N]
```

Both default to **`1`** — today's behaviour, unchanged. They exist so a CLI
user can narrow a 986-candidate harvest, **not** so the product ships a default
that hides 97% of it. The web surface does not send them; it filters the view
instead and shows the hidden count (see `ui.md`).

## NEW — `--json` on the read verbs

```
thread_registry check --json
thread_registry list --json          # NEW verb: the registry, machine-readable
thread_registry proposals --json     # NEW verb: the proposal queue, machine-readable
```

Rationale: `get_sections` already establishes that the server consumes
`--json` rather than screen-scraping a human table (Constitution VI, FR-023).
The two new read verbs exist so the server has nothing to parse.

`list --json` →
```json
{"version": 1, "threads": [ {...Thread as on disk...} ], "count": 7}
```

`proposals --json` →
```json
{"proposals": [ {...Proposal...} ],
 "counts": {"pending": 12, "ratified": 3, "rejected": 1, "deferred": 2}}
```
Every proposal is returned; the payload is not pre-filtered. **Measured**: the
986-candidate OOTA harvest serialises to **484 KB** — nothing for a localhost
single-user server, and small enough that the page searches it in the browser
(research D16). The alternative, server-side paging or search, would put
"which candidates matter" in the server.

`check --json` →
```json
{"threads": 7, "problems": ["carver-march: log row without a real chapter number (None)"]}
```
Exit code stays 1 when `problems` is non-empty (unchanged).

## Hardening (research D12)

`save_registry` and the proposals writer switch to
`campaignlib.util.atomic_write_text`, matching `save_projection_config`. The
surface turns hand-typed invocations into rapid button presses; a torn canon
file is not an acceptable failure mode.

## What is NOT added

- No verb takes a list of proposals.
- No verb ratifies without the GM supplying the fields: `add`/`log` keep every
  required flag they have today, and `ratify` requires an explicit `--plan`
  rather than deriving one silently.
- `speculate` gains nothing and is not exposed to the web (it is the one model
  call in this file).
