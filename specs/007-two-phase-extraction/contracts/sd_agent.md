# CLI Contract: `sd_agent`

Stage-scoped orchestrator. Runs one stage's generation step, then that stage's
checks. **Stops at the stage boundary** — it never runs the next stage, because
that boundary is a human checkpoint (Principle II, FR-018).

## Synopsis

```bash
sd_agent --stage {summary|scenes} --session-dir DIR [generation flags] [check flags]
```

## Stages

```
--stage summary   enhance_summary  →  sd_verify_quotes  →  sd_consistency  →  STOP
--stage scenes    scene_extract    →  sd_verify_quotes                     →  STOP
```

`--stage scenes` runs no consistency check: `sd_consistency` compares a *recap*
against campaign grounding docs, and per-scene extraction files are not a recap.

## Arguments

| Flag | Default | Description |
|---|---|---|
| `--stage {summary,scenes}` | — | **Required.** Which stage to run |
| `--session-dir DIR` | — | **Required.** Session workspace; inputs and outputs resolve beneath it |
| `--vtt FILE` | first `*.vtt` in session dir | Transcript. **Passed to both generation and verification**, so they cannot disagree (D9) |
| `--gmassist FILE` | `gm-assist.md` | Stage 1 input |
| `--context FILE…` | — | Grounding docs for `sd_consistency`. Omitted ⇒ consistency step skipped, and the run says so |
| `--threshold F` | `0.85` | Forwarded to `sd_verify_quotes` |
| `--report-only` | off | Forwarded to `sd_verify_quotes` |
| `--skip-generate` | off | Check an artifact that already exists — re-verify without re-spending tokens |
| `--dry-run` | off | Print the commands and exit. Nothing runs, nothing is spent |
| *(backend selection)* | — | `--backend/--endpoint/--model/--fast/--batch` via `campaignlib.add_backend_args`, forwarded to the **generation** step only |

### Flag forwarding is enumerated, not passed through (D12)

Only the flags listed above are forwarded. There is no `--extra-args` escape
hatch. `ensemble_batch` grew implicit forwarding and silently dropped
`--similarity` for a month (`EnsembleGroundingInvestigation.md` #197); the fix
there was to make the hop visible, so this tool starts visible.

## Behaviour

Prints each command before running it — the `/ensemble/setup` "command bar"
pattern, so any step is reproducible by hand and a dropped flag is legible:

```
[sd_agent | stage: summary | 3 steps]
────────────────────────────────────────────────────────────
① generate      enhance_summary <vtt> --gmassist gm-assist.md --output session-summary.md --backend dgx --model deepseek-…
② verify quotes sd_verify_quotes --vtt <vtt> --summary session-summary.md --out narration/quote_report.md
③ consistency   sd_consistency session-summary.md --context docs/campaign_state.md … --out narration/consistency_report.md
────────────────────────────────────────────────────────────
```

No secret ever appears in a printed command.

### Failure semantics (FR-019)

| Step outcome | Effect |
|---|---|
| Generation exits non-zero | **Stop.** Checking an artifact that was not produced reports nonsense |
| `sd_verify_quotes` exits `1` (findings) | **Continue.** A finding is the tool working |
| `sd_verify_quotes` exits `2` (could not run) | Continue to consistency, but mark the run degraded and say which check did not happen |
| `sd_consistency` fails | Report it; the artifacts from earlier steps stand |

Final exit: `0` if every step ran, `1` if any check produced findings, `2` if any
step could not run.

## Summary block

```
────────────────────────────────────────────────────────────
① generate       ok      session-summary.md (38.2 KB)
② verify quotes  8 unverified, 148 near, 336 verified  → narration/quote_report.md
③ consistency    6 issues                              → narration/consistency_report.md

Next: review narration/quote_report.md and narration/consistency_report.md,
      then apply corrections. Nothing was auto-corrected.
      This run STOPPED at the stage boundary — scene extraction is a separate step.
```

The last two lines are load-bearing: they tell the GM that the artifact is a
draft (Principle I) and that the human checkpoint was preserved, not skipped.

## Non-goals

- **No auto-correction.** Explicitly out of scope per the GM's decision; see
  `spec.md` Assumptions.
- **No cross-stage chaining.** `--stage summary` never triggers scene extraction.
- **No pipeline logic.** Every step is a subprocess of an existing CLI. `sd_agent`
  makes no `stream_api`/`call_api` call, keeping it outside
  `tests/test_retrieve_render_isolation.py`'s concern and Principle VI's.
