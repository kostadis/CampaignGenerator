# Managed grounding reader and writer inventory

This inventory freezes the T001 integration surface before implementation. It was produced from exact path, label, file-I/O, and caller searches over `campaignlib/`, `pipelines/`, `session_doc/`, and `server/`, then checked against the `cg548` codebase-memory architecture index. Every entry below is backed by a repository call site.

## Classification rules

The managed bundle consists of `campaign_state.md`, `world_state.md`, `party.md`, `planning.md`, the canonical timeline selected for the bundle, and the complete generated `reference/` tree. The migration contract retains six compatibility aliases: the four document paths, timeline, and `docs/reference`.

- **Managed reader** means a call can receive one of those managed paths, whether by config label, conventional fallback, or an explicit CLI argument. It must use one operation-scoped snapshot when it reads one or more managed members.
- **Managed writer** means a call can replace a managed file or tree. Generated replacement must refuse with the draft/promotion workflow; a supported deliberate human edit must use the shared writer lock.
- **Path probe/router** means code tests existence, chooses a path, or launches a subprocess without reading member bytes itself. It must resolve the managed layout and propagate pending/reconciliation refusals, but must not create a second snapshot around a subprocess that captures its own inputs.
- **Unrelated mention/I/O** means the similar name denotes config, source summaries, NPC dossiers, review artifacts, notes, or an arbitrary nonmanaged destination. It stays on ordinary I/O.

Path classification is based on the resolved campaign path, not a filename substring. Thus an explicit `--context`, `--party`, `--input`, or `--output` is managed only when it resolves to a bundle member or compatibility alias.

## Package dependency direction

`pipelines.summary_native.promotion` contains strict records, filesystem
snapshots, pure gates, staging, history, and CLI adapters. It may consume
persisted claim report identities, but it must never import candidate
extraction or a model client. `pipelines.summary_native.claims` contains pure
selection, packet, check, and report modules; only `claims.extract` may import
the campaign model seam. Package `__init__` modules remain empty of optional
model imports. UI and HTTP adapters invoke the installed CLI and do not own
domain policy.

## Readers and path selectors

| Exact call site | Classification | Required change / owning task |
|---|---|---|
| `campaignlib/config.py:106-114 load_file`; `campaignlib/config.py:235-256 assemble_docs` | Managed reader when a selected config document resolves to a managed member; generic reader otherwise. A single `assemble_docs` can currently perform sequential reads across generations. | T029: partition selected paths, capture all managed bytes in one snapshot, preserve order/labels, and use ordinary `load_file` for nonbundle paths. A direct `load_file` of a managed path must use the same resolver or refuse rather than bypassing it. |
| `pipelines/session_prep/prep.py:43-46 assemble_user_prompt`; `:278`, `:404` callers | Managed multi-document reader through `assemble_docs`. | T029: capture the complete grounding input set once before any model or clipboard work. |
| `pipelines/grounding/npc_table.py:56-79` | Managed multi-document reader through configurable labels (default `world_state`). | T029: capture selected managed documents once before the model call. |
| `pipelines/summary_native/cli.py:871-884 _compare` | Managed reader for `--live`; the range draft is nonmanaged source. | T029: resolve and pin the one live member; write only the range-local diff. |
| `session_doc/check_consistency.py:146-175` (`campaign_state`/`world_state` from config and explicit `--context`) | Managed multi-document reader. Registry canonical context is unrelated authority data. | T030: resolve both defaults and explicit context paths, deduplicate by managed member identity, and capture one snapshot before model work. |
| `session_doc/sd_consistency.py:65-99` | Managed reader when any `--context` is managed; recap/session-summary inputs are nonbundle. | T030: capture all managed context paths together; retain ordinary reads for other context. |
| `session_doc/sd_plan.py:254-258` | Managed reader when `--party` resolves to managed `party.md`; `--session-summary`, VTT, and scene extractions are nonbundle. | T030: capture party bytes once before the planning call. |
| `session_doc/sd_narrate.py:772-775` and `:863-877`; also `:913-918 --known-lore` | Managed reader for managed `--party`, `--context`, or `--known-lore`; the roster in `config/party.yaml`, players config, plans, recaps, and scene files are unrelated. | T030: collect every managed prompt input into one operation snapshot before narration/batch work. Keep existing structured refusal behavior. |
| `session_doc/scene_extract.py:493-509` | Managed path is selected by `--party`; the file is used as a gate while speaker identity comes from config. | T030: recognize managed party selection and capture/check it with the operation snapshot; do not classify `config/party.yaml` as bundle data. |
| `session_doc/enhance_summary.py:365-380` and prompt construction in `_build_prompts` | Managed reader when `--party` is managed; VTT, gm-assist, players, and party config are unrelated. | T030: capture party bytes/status once before preflight and model work. |
| `pipelines/rlm/mcp_server.py:87-97 _doc_index`, `:126-142 _resolve_doc/_read_doc`, document resources, and `:231-235 read_document` | Managed direct reader for a managed config label or explicit managed path. It currently reads each request independently. | T031: resolve one pinned generation per tool/resource operation and return structured migration/pending/reconciliation errors. Arbitrary nonbundle document reads remain supported. |
| `pipelines/rlm/mcp_server.py:219-226 get_party` | Managed fallback bypass: reads configured party first, then directly reads `docs/party.md`. | T031: remove the independent fallback read; resolve the compatibility alias through the same snapshot boundary. Add the targeted regression required by T041. |
| `server/platform_config_service.py:1075-1120 discover_campaign_paths` | Managed existence/path probe, not a content reader. | T031: report managed current paths only after bundle inspection; surface migration/pending/reconciliation state instead of probing retired loose paths as independent files. Other discovery remains unchanged. |
| `server/routers/ensemble.py:68-73 GROUNDING_DOCS`, `:291-294 _is_live_doc` | Managed path classification/protection seam. | T031/T032: replace fixed loose-path identity with the shared resolver so both current paths and six compatibility aliases are recognized. Keep draft rejection. |
| `server/routers/ensemble.py:392-406 _default_party_context` | Managed fallback selector for `world_state` and `campaign_state` after preferring range-local drafts. It does not read bytes itself; launched CLIs do. | T031: resolve managed fallbacks and refuse unhealthy bundle state. Preserve draft preference because drafts are deliberately nonmanaged. Reader integration in the launched `party` command supplies the snapshot. Add T041 fallback regression. |
| `server/routers/ensemble.py:996-1204 run_synthesize` | Router/subprocess path selector. Explicit `context` can contain managed members; `out` can target a managed member and is currently blocked only for four loose paths. | T031/T032: resolve managed input/output identities, pass stable managed paths to integrated CLIs, and refuse every managed generated output including current/alias forms. |
| `campaignlib/projection_config.py:76-93 ProjectionInputs.party` | Config declaration that defaults to managed `docs/party.md`; no bytes are read here. Actual projection consumers must be inventory-tested when they resolve this field. | T031: classify the resolved value through the common path boundary. Do not wrap YAML config load/save as a grounding snapshot. |
| `server/grounding_config_shared.py:288-353` | Grounding service configuration I/O, not managed bundle content I/O. `summaries` is a source-timeline pointer and per-run `output/context` may later resolve to managed paths. | T031/T032: preserve config I/O; classify resolved run paths at the router/CLI boundary. Never treat the `grounding.yaml` file itself as a managed member. |
| `pipelines/integrations/kanka/kanka_mcp.py:137-160`; `pipelines/integrations/kanka/kanka_push.py:269-278` | Managed reader only when explicit `input` resolves to managed `world_state.md`; Kanka API reads/writes are external and separate. | T031: read managed input through one snapshot before preview/apply; arbitrary exported files remain ordinary. |

## Writers

| Exact call site | Classification | Required change / owning task |
|---|---|---|
| `pipelines/grounding/distill.py:105`, `:182` | Generated writer; arbitrary `--output` can replace managed `world_state.md`. | T032: reject any managed target with draft/promotion instructions before extraction/model work; nonmanaged drafts remain supported. |
| `pipelines/grounding/campaign_state.py:237`, `:322` | Generated writer; arbitrary `--output` can replace managed `campaign_state.md`. | T032: same generated-target refusal, including aliases/current paths. |
| `pipelines/grounding/party.py:278`, `:446` | Generated writer; arbitrary `--output` can replace managed `party.md`. | T032: same generated-target refusal. |
| `pipelines/grounding/planning.py:950`, `:1062-1063` | Generated writer; arbitrary `--output` can replace managed `planning.md`. Dossier writes at `:286-301` are unrelated NPC dossier output. | T032: reject managed planning target; retain nonmanaged document and dossier writes. |
| `pipelines/ensemble/synthesise_world_state.py:736-738` | Generated writer with required arbitrary output; documentation discourages live output but code does not prohibit it. | T032: reject resolved managed targets before model work. |
| `server/routers/ensemble.py:1053-1057` | Existing generated-write guard, but based on only four fixed loose paths. | T032: route guard through shared managed identity so aliases, `current`, and generation-live members cannot bypass it. |
| `pipelines/integrations/kanka/kanka_mcp.py:116-133 kanka_pull`; `pipelines/integrations/kanka/kanka_sync.py:225-237` | Generated/external-sync writer when explicit output is managed. | T032: reject managed output and direct the result to a draft/export path; returning markdown without output remains supported. |
| `pipelines/workspace/new_workspace.py:227-283` (`placeholder` at `:137`) | Bootstrap writer/config author, not a post-migration live writer. It creates loose placeholders and config paths in a brand-new workspace. | Migration/setup follow-up under T031/T032: initialize a pristine managed baseline (or leave it explicitly migration-needed) consistently with the migrator; do not silently manufacture six independent live files after managed setup exists. Existing external file arguments remain references, not copied members. |
| `pipelines/rlm/mcp_server.py:385-422 write_note/append_note` | Unrelated writer: containment restricts it to `notes/`. | No bundle change. Keep regression proving notes cannot resolve into managed targets through traversal/symlinks. |

## Related paths that are not managed members

These exact-name collisions must not be swept into the bundle boundary:

- `config/party.yaml`, `config/planning.yaml`, `config/players.yaml`, `config/grounding.yaml`, `config/projections.yaml`, and platform/ensemble configs are authored service configuration.
- `mechanics.md` is still a generic configured document and MCP resource, but it is not one of the four promoted outputs or either support alias in this feature.
- Source summaries and the selected timeline's build/run records are dependencies retained and hashed by promotion; their source locations are not rewritten as live document aliases except for the one canonical timeline alias defined by migration.
- Entity registry, authority ledger, review storage, NPC dossiers, narration/scene files, projection drafts, planning notes, thread tracks, logs, and Kanka state remain outside managed membership.
- Comments, help text, type names, and UI document keys are not readers or writers unless they lead to an existence probe, byte read, or byte write listed above.

## Closure criteria for T041

T001 is an audit, not proof that conversion is complete. T041 must check every row above against the final shared API and fail release if a managed path still reaches raw `read_text`, `write_text`, `open`, copy/replace, or existence-based fallback outside that API. At minimum, targeted tests must exercise:

1. `mcp_server.get_party` with a missing/unset config entry and the compatibility alias present;
2. ensemble draft-first party context with fallback to both managed live members;
3. explicit session-doc `--context`/`--party` current and alias forms;
4. Kanka explicit managed input and output;
5. all five generator outputs (four grounding CLIs plus ensemble synthesis) against alias and `current` targets;
6. platform path discovery during pending migration and unresolved activation;
7. one operation selecting several config documents while publication contends, proving all bytes carry one generation identity.

The bypass scan should be path-aware. A blanket ban on `read_text`/`write_text` would incorrectly flag the unrelated paths above and would not catch a helper that hides a detached-alias fallback.
