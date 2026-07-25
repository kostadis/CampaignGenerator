# Quickstart: Validating Model Selection Resolution

Ten runnable checks that prove the feature works end to end. Each maps to a spec requirement and a
success criterion. Run from a campaign workspace with the server up.

## Prerequisites

```bash
cd /home/kroussos/src/CampaignGenerator
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"   # console scripts must be installed
./startup                                                # server on :5000
cd /path/to/campaign                                     # a real campaign workspace
```

`ANTHROPIC_API_KEY` set. A reachable DGX endpoint (`spark`) for the local-backend checks.

## V1 — The platform backend reaches all six routers (FR-008, SC-001, SC-006)

The headline bug: four routers ignore the backend today.

```bash
curl -s -X PUT localhost:5000/api/config/runtime \
  -H 'content-type: application/json' -d '{"default_backend":"dgx"}'
```

Then trigger one run per router from the UI (or via its `/run/*` endpoint) and inspect the
persisted command in each run log:

```bash
grep -h '^\$' ~/campaigns/<campaign>/logs/*.md | tail -20
```

**Expect**: every command carries `--backend dgx`. **Today**: `npc_table`, `query`,
`session_prep`, `dnd_sheet`, `make_tracking` and the connection-graph extract carry none and bill
the metered API.

## V2 — Exactly one `--model` per command (C1, FR-006)

The two-owner defect.

```bash
grep -ho '\-\-model' ~/campaigns/<campaign>/logs/*_distill.md | wc -l   # per file
```

**Expect**: `1` for every run log. **Today**: a Grounding run under a non-Anthropic backend emits
two.

## V3 — No router reads another service's config (C4, FR-005, SC-009)

Static check — the cross-service import is the violation:

```bash
grep -rn "SessionEditorConfigService" server/routers/grounding.py
```

**Expect**: no match. **Today**: `server/routers/grounding.py:72`.

## V4 — A service override wins, and only for that service (FR-003, SC-004)

```bash
curl -s -X PUT localhost:5000/api/grounding/selection \
  -H 'content-type: application/json' -d '{"model":"Qwen3-Next-80B","backend":"dgx"}'
curl -s -X PUT localhost:5000/api/config/runtime \
  -H 'content-type: application/json' -d '{"default_model":"claude-opus-5","default_backend":"anthropic"}'
```

Run Distill (Grounding) and Session Prep.

**Expect**: Distill runs `Qwen3-Next-80B` on `dgx`; Session Prep runs `claude-opus-5` on
`anthropic`. Neither observes the other's choice.

## V5 — Clearing an override restores inheritance (FR-013, SC-007)

```bash
curl -s -X DELETE localhost:5000/api/grounding/selection
curl -s localhost:5000/api/grounding/selection/resolved
```

**Expect**: `model_origin: "platform"`, `model: "claude-opus-5"`. No global setting was touched.

## V6 — An incompatible override refuses the run (FR-009, FR-011, SC-008)

The clarified reversal. Leave a DGX model on Grounding, switch the platform to Anthropic:

```bash
curl -s -X PUT localhost:5000/api/grounding/selection \
  -H 'content-type: application/json' -d '{"model":"Qwen3-Next-80B"}'
curl -s -X PUT localhost:5000/api/config/runtime \
  -H 'content-type: application/json' -d '{"default_backend":"anthropic"}'
curl -s -o /dev/null -w '%{http_code}\n' 'localhost:5000/api/grounding/run/distill'
```

**Expect**: `409`, a body naming the incompatibility and `"remedy": "clear_override"`, and **no**
new file in `logs/` — the subprocess never started. **Today**: 200, and the run proceeds on a
substituted model.

## V7 — The ensemble reversal (R8, spec Assumptions)

The same check against the service that used to substitute silently:

```bash
python -m pytest tests/test_ensemble_gates.py -k stale_model -v
```

**Expect**: the three `*_ignores_stale_model_for_anthropic` tests have been **rewritten** to assert
a 409 refusal and pass under the new name. A green run of the *old* assertions means the reversal
was silently undone — treat that as a failure, not a pass.

## V8 — Pre-run visibility (FR-012, SC-005)

```bash
for s in grounding party planning ensemble editor prep setup connections; do
  echo -n "$s: "; curl -s localhost:5000/api/$s/selection/resolved
done
```

**Expect**: every service reports `model`, `backend`, and both origins. Inheriting services always
report `platform`. No service errors.

## V9 — The run record proves what ran (FR-014, R7)

```bash
tail -40 "$(ls -t ~/campaigns/<campaign>/logs/*.md | head -1)"
```

**Expect**: the `command` line contains the resolved `--model` and `--backend`, no `*_API_KEY`
value, and a `result:` line. This should pass with **no new code** — it is inherited from
`specs/002`.

## V10 — Migration moved the backend, and nothing else (data-model.md § Migration)

```bash
grep -A3 '^runtime:' ~/campaigns/<campaign>/config/platform.yaml
grep -A5 '^backends:' ~/campaigns/<campaign>/config/session_doc.yaml
```

**Expect**: `platform.yaml` `runtime.default_backend` holds what `session_doc.yaml`'s
`backends.active` held before migration; `session_doc.yaml` still has its own `backends` block
intact as the editor's override. No new config file exists — in particular no `setup.yaml`
(FR-004).

## Full suite

```bash
cd /home/kroussos/src/CampaignGenerator && python -m pytest tests/
```

Must keep passing unchanged: `tests/test_default_model_resolution.py`,
`tests/test_ensemble_config_defaults.py::TestModelResolution`,
`tests/test_editor_service_integration.py::TestO3ModelResolution`,
`tests/test_retrieve_render_isolation.py`.

> Worktree caveat: the editable-install `.pth` hardcodes the main checkout, so `import campaignlib`
> in a worktree can resolve to main's copy. A green worktree run is not proof you tested the branch.
