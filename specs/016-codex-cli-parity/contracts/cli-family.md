# Contract: Production CLI Family

## Canonical vocabulary

The only accepted spelling is `codex-cli`. The canonical backend tuple is declared
once in `campaignlib.selection` and consumed by:

- the shared CLI registrar;
- the plural-endpoint parser used by `facts_to_state`;
- the three forwarding dispatcher parsers;
- server request and persistence models;
- the config API that feeds UI selectors.

Help text describes `codex-cli` as using the saved Codex subscription login. No
command invents an alias or provider-specific fallback.

## Production inventory

| Family | Commands | Count |
|---|---|---:|
| Session document | `check_consistency`, `enhance_summary`, `scene_extract`, `sd_agent`, `sd_consistency`, `sd_plan`, `sd_narrate`, `vtt_voice_compare` | 8 |
| Prep, ingest, search, integration | `prep`, `transform`, `dnd_sheet`, `query`, `scabard_sync` | 5 |
| Grounding | `planning`, `party`, `make_tracking`, `distill`, `campaign_state`, `npc_table`, `grounding_sections`, `thread_registry` | 8 |
| Ensemble | `synthesise_world_state`, `synthesise_polish`, `extract_facts`, `facts_to_state`, `narrate_chapter`, `polish`, `ensemble`, `ensemble_batch`, `ensemble_extract` | 9 |
| **Total** |  | **30** |

Current parser structure consists of 26 shared-registrar commands, one direct
plural-endpoint command (`facts_to_state`), and three hand-written forwarding
dispatchers (`ensemble`, `ensemble_batch`, `ensemble_extract`). At runtime,
shared-registrar `sd_agent` is also a dispatcher, yielding 26 direct model-bearing
commands and four dispatchers. The exact list is a baseline;
the guardrail discovers production usage so a future command cannot remain absent.

## Direct command contract

Every direct command must:

1. register the canonical backend vocabulary;
2. preserve model omission versus explicit model intent;
3. resolve its legacy model default through the shared helper;
4. reject Codex plus provider message `--batch` before model work;
5. call only the shared API seam;
6. preserve its selected inputs, stage boundaries, context order, output path,
   checkpoint, retry/resume rules, and normal presentation;
7. treat adapter failure as non-transient for provider fallback purposes.

The helper's model rule is:

| Backend | `--model` omitted | `--model` explicit |
|---|---|---|
| `codex-cli` | Pass no model; adapter uses `CG_CODEX_MODEL`, then subscription default. | Forward unchanged after compatibility validation; reject `claude-*`. |
| Any existing backend | Restore that command's exact legacy default behavior. | Preserve existing explicit behavior. |

Command-specific model mode flags are applied before final resolution. They do not
gain a hidden Codex translation.

## Dispatcher contract

`sd_agent`, `ensemble`, `ensemble_batch`, and `ensemble_extract` do not start a
Codex child merely to validate the backend. They forward:

- canonical backend;
- explicit compatible model intent, or model omission;
- endpoint and plural-endpoint settings that remain applicable;
- application-level concurrency, selected work, resume, and review controls;
- provider batch only through the generic validator, which refuses Codex.

Every model-bearing child must receive the same resolved selection. Empty explicit
work selection remains empty and is never expanded to all.

## Interaction-shape coverage

The acceptance suite assigns every direct command one or more shapes:

- ordinary text;
- ordered/cache-marked system text blocks;
- streaming-shaped full final response;
- sequential requests;
- independent fan-out;
- application-grouped scenes;
- brokered polish loop.

At least one representative fixture per family executes through the real shared
Codex adapter with a mocked child process. The remaining commands prove parser,
model-resolution, request-shape, and artifact-path parity without requiring live
subscription authentication.

## Batch vocabulary

| Control | Meaning with `codex-cli` |
|---|---|
| `--batch` | Refused before work; Anthropic provider message batching only. |
| `--batch-scenes` | Preserved application-level grouping. |
| Ensemble local fan-out/concurrency | Preserved orchestration behavior. |
| Resume/skip/force | Preserved owning workflow behavior. |
| HTML review | Preserved human checkpoint. |

## Automated guardrails

Tests must fail when:

- production discovery and the 30-command capability inventory differ;
- a registrar or dispatcher declares a backend tuple independently;
- a direct model-bearing command bypasses shared model-intent resolution;
- a dispatcher drops backend/model intent from a child;
- help omits or duplicates `codex-cli`;
- Codex provider batch reaches model work;
- an existing backend's default or help changes unintentionally;
- a capability lacks a direct/transitive UI invocation and has no explicitly
  recorded constitutional exemption.
