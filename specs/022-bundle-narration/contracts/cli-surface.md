# Contract: `sd_narrate` Bundled CLI Surface

**Feature**: 022-bundle-narration | Governs FR-001, FR-002, FR-005, FR-013, FR-016–FR-021

## 1. New and generalized options

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--batch-scenes` | boolean flag | off | Generate the selected narration scenes together in one model exchange. |
| `--no-batch-scenes` | boolean flag | — | Explicitly retain the sequential per-scene path. |
| `--batch-max-tokens N` | positive integer | `32000` | Total output ceiling for the single bundled exchange. |
| `--run-report FILE` | path | `<per-scene-output>/logs/sd_narrate_bundle_latest.json` | Atomic machine-readable bundle outcome; the editor always overrides this with a unique path. |
| `--scene-extraction-file FILE` | repeatable path | none | Exact source override; once for current single-scene use or multiple times for a bundled set. |

`--batch-scenes` and `--batch-max-tokens` intentionally match the existing `scene_extract` vocabulary: on either CLI they mean multiple scenes carried by one model exchange and that exchange's output ceiling.

For an explicit `--run-report`, the report's `run_id` is the filename stem. The editor uses a server-generated nonce as that stem so it can validate the exact invocation without adding a second identifier option.

The existing options retain their meanings. In particular:

- `--batch` is provider Message Batches submission/pricing.
- `--narrate-tokens` is the per-scene ceiling for sequential mode.
- `--scene N [M ...]` selects full-plan indices.
- `--narrator NAME` retains its current filter-then-index behavior in sequential mode.
- no `--batch-scenes` means the current sequential loop.

## 2. Selection

| Invocation | Effective narration scope |
|---|---|
| `sd_narrate ...` | All plan scenes, sequentially, unchanged. |
| `sd_narrate ... --scene 3` | Scene 3 only, unchanged. |
| `sd_narrate ... --scene 2 5` | Scenes 2 and 5 sequentially, unchanged. |
| `sd_narrate ... --batch-scenes` | Explicit all-plan bundle. Typing the flag is the CLI “select all” action. |
| `sd_narrate ... --batch-scenes --scene 2 5` | One exchange containing exactly full-plan scenes 2 and 5, emitted in plan order. |

Bundled selections are non-empty, unique, range-checked, and normalized to full-plan order. The CLI prints the exact index, scene name, narrator, source file, destination file, and replacement status before it constructs a backend client.

`--batch-scenes` combined with `--narrator` exits `1` before client creation. Bundled subsets use stable full-plan `--scene` indices; this leaves the existing sequential narrator filter and its indexing behavior unchanged.

## 3. Provider batch composition

| Content mode | Provider `--batch` off | Provider `--batch` on |
|---|---|---|
| Sequential | N ordered `stream_api` calls | N ordered one-item `run_single_batch` calls; existing behavior |
| `--batch-scenes` | One `stream_api` call | One bundled `run_single_batch` item |

The run banner and report show `content mode: bundle|sequential` and `provider batch: on|off` separately.

## 4. Exact source overrides

In sequential mode, the existing contract remains: one `--scene-extraction-file FILE` requires exactly one positive `--scene N`, and the file must match that scene under `session_doc.io` identity rules.

In bundled mode:

- the option may repeat;
- each file must be readable UTF-8 and eligible under the same existing rules;
- each file must reconcile to exactly one selected plan index/name;
- two files may not claim the same selected scene;
- every non-overridden scene resolves from `--scene-extractions`;
- all resolution happens before the model call.

The order of repeated file options does not determine output order; the reviewed plan does.

## 5. Capacity and call-count guarantee

The CLI calculates:

```text
projected bundle output = sum(estimate_narration_tokens(scene moments))
                          + fixed marker overhead per scene
```

If the projection exceeds `--batch-max-tokens`, exit `1` before client creation. The message reports projection and ceiling and offers exactly three remedies: raise `--batch-max-tokens`, pass a smaller explicit `--scene` set, or omit `--batch-scenes` for sequential narration.

The CLI never auto-groups or silently falls back from bundle to sequential. Once a bundled model call starts, `exchange_count` is exactly `1`.

When a backend exposes a reliable model-capacity limit, a known incompatibility is also refused before the call. Unknown capacity is reported as unknown rather than guessed; the existing backend boundary remains authoritative for the actual request.

## 6. Refusals

| Condition | Result |
|---|---|
| Plan has no sections | Exit `1`, zero calls, zero writes. |
| Bundled selection has a duplicate or out-of-range index | Exit `1`, zero calls, zero writes. |
| Any selected scene has no exact source | Exit `1`, zero calls, zero writes. |
| Any selected narrator declaration/voice/example required by existing preflight is invalid | Exit `1`, zero calls, zero writes. |
| Repeated exact source is unreadable, ineligible, unmatched, or duplicates a scene | Exit `1`, zero calls, zero writes. |
| `--batch-scenes` is combined with `--narrator` | Exit `1`, zero calls, zero writes; use explicit full-plan `--scene` indices or sequential mode. |
| Projection exceeds bundle ceiling | Exit `1`, zero calls, zero writes. |
| `--batch-max-tokens` without `--batch-scenes` | Accepted but inert, with a note; sequential behavior is unchanged. |
| Multiple exact source files without `--batch-scenes` | Exit `1`; current single-source contract is retained. |

## 7. Response outcomes and exit codes

| Code | Meaning | Writes |
|---|---|---|
| `0` | Every requested scene returned complete and non-empty. | Every requested scene written atomically. |
| `1` | Input/capacity refusal or backend failure. | None from a refusal; prior successful files remain. |
| `3` | Structurally valid partial response. | Complete non-empty scenes only; missing scenes named. |
| `4` | Unreconcilable response identity/order. | None from this exchange. |

Existing outputs for an empty, incomplete, absent, or rejected scene remain untouched. A later current-scene or smaller bundle run can replace only those scenes.

A structurally valid response in which every requested section is empty, incomplete, or absent is still `partial`: exit `3`, zero writes, and every requested scene is named in `missing`. Every bundle attempt whose report destination can be initialized writes a terminal atomic report, including refusal and backend failure paths.

## 8. Human-readable run output

Before the call:

```text
[sd_narrate | content mode: bundle | provider batch: off]
  Requested: 3 scenes in plan order
  01  Soma — Arrival                  base      NEW
  02  Brewbarry — The Bargain         override  REPLACE
  03  Soma — Departure                base      NEW
  Projected output: 11,250 tokens / 32,000 ceiling
  Model exchanges: 1
```

After a partial response:

```text
  Written: 2/3
  Missing: 03 Soma — Departure (response incomplete)
  Existing files for missing scenes were not changed.
  Re-run: sd_narrate ... --batch-scenes --scene 3
  Run report: narration/logs/sd_narrate_bundle_latest.json
```

Output paths are printed for every written scene. The command never invokes assembly or marks narration approved.
