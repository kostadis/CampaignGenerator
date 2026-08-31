# Contract: Production CLI Reasoning-Effort Family

## Canonical invocation

Every production command that can use or forward `codex-cli` exposes the same
optional argument:

```text
--codex-reasoning-effort {minimal,low,medium,high,xhigh,max}
```

Help text must state:

- the option applies only to `--backend codex-cli`;
- `CG_CODEX_REASONING_EFFORT` is the fallback;
- omission sends no CampaignGenerator override;
- model support varies and `gpt-5.6-sol` supports `max`;
- unsupported model/value combinations fail without downgrade or fallback.

The choices and help are declared once and reused by the shared registrar and
hand-written dispatcher parsers.

## Resolution contract

| Effective backend | Explicit option | Environment | Result |
|---|---|---|---|
| `codex-cli` | valid value | any | Explicit value; source `explicit`. |
| `codex-cli` | absent | valid nonblank value | Environment value; source `environment`. |
| `codex-cli` | absent | unset or whitespace | No override; display `Codex default`; source `omitted`. |
| `codex-cli` | invalid/empty explicit value | any | Fail before child; list accepted values. |
| `codex-cli` | absent | invalid nonblank value | Fail before child; name `CG_CODEX_REASONING_EFFORT`. |
| other backend | explicit value | any | Fail before model work; option is Codex-only. |
| other backend | absent | any | Ignore Codex environment; existing backend behavior is unchanged. |

CLI resolution uses the same effective-backend semantics as existing model and
batch validation, including `CG_BACKEND` fallback. An explicit value is never
silently treated as omission.

## Production inventory

| Family | Commands | Count |
|---|---|---:|
| Session document | `check_consistency`, `enhance_summary`, `scene_extract`, `sd_agent`, `sd_consistency`, `sd_plan`, `sd_narrate`, `vtt_voice_compare` | 8 |
| Prep, ingest, search, integration | `prep`, `transform`, `dnd_sheet`, `query`, `scabard_sync` | 5 |
| Grounding | `planning`, `party`, `make_tracking`, `distill`, `campaign_state`, `npc_table`, `grounding_sections`, `thread_registry` | 8 |
| Ensemble | `synthesise_world_state`, `synthesise_polish`, `extract_facts`, `facts_to_state`, `narrate_chapter`, `polish`, `ensemble`, `ensemble_batch`, `ensemble_extract` | 9 |
| **Total** | | **30** |

The discovery baseline is 26 direct model-bearing commands and four runtime
dispatchers: `sd_agent`, `ensemble`, `ensemble_batch`, and `ensemble_extract`.
`facts_to_state` is the hand-written direct parser outside the shared registrar.
Tests discover these categories from production source and compare them with
the inventory so a future command cannot be silently omitted.

## Direct-command contract

Every direct command must:

1. obtain the option through the shared registrar/helper;
2. validate explicit and environment values before starting `codex exec`;
3. preserve existing model, batch, work-selection, cache, retry, timeout,
   overwrite, output, and checkpoint semantics;
4. construct the Codex client through `client_from_args`;
5. reach the single Codex adapter for direct, streaming, or brokered calls;
6. report the actual model/effort identity before model work;
7. treat a Codex failure as non-transient and never select a fallback.

`check_consistency` and `enhance_summary` receive the setting through this same
contract; neither owns a special implementation.

## Dispatcher contract

Each dispatcher must:

- accept the same option and choices;
- reject explicit wrong-backend use before starting a child process;
- append an explicit value to every applicable model-bearing child command;
- omit the child flag when the parent omitted it, allowing the final adapter to
  resolve the inherited environment and preserve `environment` provenance;
- retain the setting across fan-out, retry, resume, and multi-stage child
  construction without broadening the selected work;
- never send it to a stage whose effective backend is not `codex-cli`.

## Codex child transport

When a value resolves, the separated argv contains exactly one configuration
override equivalent to:

```text
codex exec ... -c 'model_reasoning_effort="max"' ...
```

When no value resolves, the argv contains no `model_reasoning_effort` key.
Argument ordering may follow the existing command builder, but all current
isolation arguments remain present, including:

- `--ephemeral`;
- `--ignore-user-config`;
- `--ignore-rules`;
- `--strict-config`;
- read-only sandbox and isolated working directory;
- existing tool, app, agent, web-search, and project-document disables;
- saved ChatGPT login enforcement and metered credential stripping.

## Compatibility and failure behavior

- CampaignGenerator validates only the canonical six-value vocabulary.
- Codex validates whether the chosen model supports the chosen value.
- A nonzero child result identifies the selected model and effort in the
  `CodexCliError` diagnostic.
- No successful artifact is created from a rejected or empty result.
- No retry changes model, effort, backend, or omission state.
- An older Codex binary that rejects a canonical configuration value fails
  clearly under `--strict-config`; isolation is not weakened to accommodate it.

## Automated guardrails

Tests fail when:

- any discovered production surface lacks the canonical option or forwarding;
- a parser copies the value tuple/help instead of consuming the shared helper;
- a dispatcher drops an explicit effort from any child;
- a non-Codex backend receives the option;
- omission still adds a Codex override;
- the existing isolation argv changes unexpectedly;
- `max` with `gpt-5.6-sol` does not reach the fake Codex child unchanged;
- `enhance_summary` or `check_consistency` bypasses the shared behavior;
- a Codex-capable UI reachability entry cannot select/inherit effort and show
  final run identity.
