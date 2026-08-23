# Contract: Editor API & Config

**Feature**: 013-batched-scene-extraction | Governs FR-007a, FR-017, FR-018, DM-17–DM-20

## 1. Config — `ExtractKnobs` (`<config>/session_doc.yaml`)

`extra="forbid"`, so both new fields must be declared in the model.

```yaml
extract:
  tokens: 8192          # UNCHANGED — per-scene ceiling
  batch_scenes: null    # NEW — null = follow backend default; true/false = GM pinned
  batch_tokens: 32000   # NEW — batched ceiling
```

| Field | Type | Default | Rules |
|---|---|---|---|
| `tokens` | int | `8192` | Unchanged. Existing pin test stays green (FR-017b) |
| `batch_scenes` | `bool \| None` | `None` | Tri-state: `None` defers to the backend default (DM-18) |
| `batch_tokens` | int | `32000` | Plain `int`, no server-side constraint |

**On the `1000` floor**: it is a **UI affordance, not a server constraint**.
`KnobDrawer.vue:239`/`:271` set `min="1000"` on the existing token inputs, and
neither `ExtractKnobs.tokens` nor `NarrateKnobs.tokens` carries a pydantic
`Field(ge=…)`. `batch_tokens` follows that precedent exactly — a plain `int` on
the model, `min="1000"` on its input. Adding a server-side floor to this one
field would make it the only validated token knob in the file, which is a
divergence, not a hardening.

**Why `batch_scenes` is tri-state**: `None` is "I have not pinned this — follow
the backend", which is genuinely different from `False` ("per-scene, even on the
subscription"). Collapsing them to a plain bool would make the pre-selection
unrepresentable and force the UI to guess.

Read/written via the existing `GET`/`PUT /api/editor/config`. **No migration**:
both fields default cleanly, so an untouched campaign gains the subscription
pre-selection and the 32K batched ceiling with no per-scene behaviour change.

## 2. Resolved-config payload

`ResolvedEditorConfig` gains one **derived, read-only, TOP-LEVEL** field:

| Field | Type | Meaning |
|---|---|---|
| `batch_scenes_effective` | bool | The resolved default per DM-18, for the UI's initial checkbox state |

**It must NOT live under `extract`.** `ResolvedEditorConfig.extract` *is* the
persisted `ExtractKnobs` model (`server/session_editor_config_service.py:136`),
which is `extra="forbid"` — declaring a derived field there would make it known,
persisted and `PUT`-able, the exact opposite of read-only.

The precedent is `ResolvedEditorConfig.genre` (`:150`), a top-level field carrying
the comment *"Injected, never persisted — same class of read-only extra as
`model`/`work_dir`"*. `batch_scenes_effective` is the same class of thing and sits
beside it, alongside `model`, `work_dir`, `campaign_dir`, `vtt`.

## 3. `GET /api/editor/extract`

```
GET /api/editor/extract?force={0|1}&batch_scenes={0|1}
```

| Param | Type | Default | Meaning |
|---|---|---|---|
| `force` | int | `0` | Unchanged (#323 / spec 012) |
| `batch_scenes` | int \| absent | absent | Absent → resolve per DM-18. Present → the GM's explicit per-run choice, which wins |

Absent-vs-present is load-bearing: it is how "the GM did not touch the control"
stays distinguishable from "the GM unchecked it", which is what makes the
pre-selection overridable in both directions (FR-007a).

`_build_reextract_cmd` forwards the **resolved** value as an explicit flag
(`--batch-scenes` or `--no-batch-scenes`) plus `--batch-max-tokens
{cfg.extract.batch_tokens}`, so the streamed command line is fully explicit
(DM-19).

**One override, stated in the stream.** `--batch` (Message Batches) reaches the
same command from the stored selection profile via `_selection_args`, and
`scene_extract` refuses the two flags together (cli-surface.md §2). When the
resolved selection carries `--batch`, batched scenes stand down: the command
gets `--no-batch-scenes`, and the stream opens with a `data:` note naming the
reason and the setting to change. Message Batches wins because it already sends
the transcript as a cached prefix, so batched scenes save nothing on that path.
Without this the route built a command that exits 1 before writing anything,
naming a flag the GM never typed.

**Response**: unchanged SSE stream of subprocess output. The run report (see
[cli-surface.md](./cli-surface.md) §3) arrives as ordinary stream content —
nothing new to parse.

**Activity record**: `_record_activity` gains the resolved batching state:

```python
knobs={"batch": …, "force": bool(force), "batch_scenes": effective_batch_scenes}
```

`effective_batch_scenes` is read back off the built command
(`"--batch-scenes" in cmd`), not from the resolution above it — DM-19
guarantees one of the two flags is always present, and a knob record that
disagreed with its own command line would misreport the stood-down case.

## 4. Frontend

### `SessionDocEditor.vue`

A checkbox beside the existing Force toggle, same pattern as `forceReextract`
(`:205`), differing only in that its initial value comes from resolved config
rather than a literal:

```ts
const batchScenes = ref<boolean | null>(null)   // null = untouched by the GM
// initialised from the TOP-LEVEL cfg.batch_scenes_effective on config load
```

The URL carries the param **only when the GM has touched the control**:

```ts
const params = new URLSearchParams({ force: forceReextract.value ? '1' : '0' })
if (batchScenes.value !== null) params.set('batch_scenes', batchScenes.value ? '1' : '0')
connectSSE(`/api/editor/extract?${params}`, { … })
```

Label: **"Batch scenes into one call"**, with help text saying it sends the
transcript once instead of once per scene, and that it is pre-selected on the
subscription backend because that path has no prompt caching.

### `KnobDrawer.vue`, Stage ② section

1. **Add** a "Batched token limit" number field bound to `extract.batch_tokens`,
   help text: *"Output cap for a batched run, forwarded to `scene_extract
   --batch-max-tokens`. Raise it above a long session's projection to keep the
   run to a single call."*
2. **Clarify** the existing "Token limit" help to say **per-scene mode**, so the
   two ceilings are not confusable.
3. **Fix the stale sentence** at `:229` (research D12). It currently reads *"The
   Re-Extract button always forwards `--force` …"*, which stopped being true with
   #323 — Force is an explicit unchecked control now. Leaving a false claim about
   force semantics next to a new force-sensitive control is how the next reader
   gets it wrong.
