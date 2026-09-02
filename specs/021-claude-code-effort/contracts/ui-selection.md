# Contract: UI Selection, Persistence, and Parity

**Feature**: `021-claude-code-effort`

Constitution Principle XI: every CLI capability is reachable from the UI, shipped in the same feature. No CLI-only ruling is claimed for this feature, so every surface below is in scope.

---

## The control

**Label**: Effort · **Options**: `Claude Code default` + `low` `medium` `high` `xhigh` `max` — six choices, a select, never free text.

`Claude Code default` is the empty value and persists as **omission**, not as a guessed level. The distinction is load-bearing: a stored `"high"` outranks the platform tier, while omission defers to it.

**Visibility**: shown only when the resolved or draft backend is `claude-code`, mirroring `SelectionPanel.vue`'s existing `resolved.backend === 'codex-cli'` gate.

**Helper text**: higher levels increase run time; `xhigh` and `max` require thinking (`CG_CLAUDE_CODE_THINKING=1`) and are refused without it, except on always-thinking models.

**Values come from the server.** `/models` gains `claude_code_efforts` beside the existing `codex_reasoning_efforts`, sourced from `CLAUDE_CODE_EFFORTS`. The frontend must not hardcode the list — a literal in `config.ts` is a second declaration of a vocabulary that already has an owner (Principle XII), and it silently drifts the day a value is added.

---

## Surfaces

| Surface | Obligation |
|---|---|
| `AppSidebar.vue` | Global/platform-tier selector |
| `SelectionPanel.vue` | Per-service selector **and** resolved-state display, including origin |
| `KnobDrawer.vue` | Scene-editor tier |
| `EnsembleSetup.vue` + `useEnsembleRun.ts` | Per-stage selection, carried into the run |
| `SessionDocEditor.vue`, `ReviewAssemble.vue` | Selection reaches the launched run |
| `ConnectionGraph.vue` | Reports effective model and effort in results |
| `StreamOutput.vue` | Surfaces the identity banner |
| `stores/config.ts` | `claudeCodeEfforts` (list), `claudeCodeEffort` (platform default) |
| `api/client.ts` | Types and payload field |

The rule that decides membership: **any surface exposing `claude-code`, a Claude model for it, or a Claude Code-backed launch also exposes the control** — or, if it only displays, reports it.

---

## Precedence

Identical to the CLI, resolved server-side in `platform_config_service.resolve_selection`:

```
request → service → platform → CG_CLAUDE_CODE_EFFORT → omission
```

The UI **must not** implement its own precedence. It sends what the operator chose and renders what the server resolved. A second precedence rule in TypeScript is Split-Brain (Principle VI), and it diverges the first time either side changes.

The route edge takes a sentinel (`""` / `None`) and resolves from the config service — **never a defaulted literal in a router**. `tests/test_ensemble_config_defaults.py` enforces this shape for ensemble; the same discipline applies here.

---

## Persistence and isolation

1. **Survives reload.** A chosen level is restored from the stored profile.
2. **Survives backend switching.** Switch to `codex-cli` and back: the Claude Code level is still there. Switching must not clear it, and must not write it into the other backend's profile.
3. **Coexists with the Codex selection.** A profile may hold `claude_code_effort` *and* `codex_reasoning_effort` at once; each stays dormant while the other backend is active. Setting one must not read, write, or clear the other.
4. **Represents default as omission.** Selecting `Claude Code default` clears the field; it does not store the level the platform tier happens to hold today.
5. **Never rewrites unrelated config.** Loading a profile without the field leaves the file untouched.

Isolation comes from `session_editor_config_shared.py`'s existing per-backend `BackendProfile` keying (`claude-code`, `codex-cli`). The work is to avoid breaking it — and to assert it, because nothing currently would catch a regression here.

---

## The `is_empty()` trap

`ModelSelection`, `BackendProfile`, and `EnsembleBackend` each implement `is_empty()`, and each **must** account for `claude_code_effort`.

A profile carrying *only* an effort selection has something to say. If `is_empty()` does not know the field, that profile reads as "no override at all" and the save paths that gate on emptiness drop it — the operator's choice vanishes on reload with no error. This is the same failure the `batch` field's existing docstring note describes, and it is the most likely way this feature fails silently.

---

## Launch path

A UI-launched run must reach the identical CLI invocation a manual run would (Principle VI). The router adds `--claude-code-effort <value>` in `_build_*_cmd()`; the UI never constructs a command line, never calls a model itself, and never invents a second vocabulary.

The copyable command a run displays must be fully explicit — resolution happens **before** argv is built, so what the operator sees is what ran.

---

## Testing

No frontend component-test harness exists (issue #345). UI parity is asserted by **static source checks** over `frontend/src/**`, mirroring `tests/test_codex_reasoning_ui.py`: the control is present on each named surface, the vocabulary is not hardcoded, and no surface offering `claude-code` omits it.

**Stated limitation**: this proves presence in source, not that the control renders, persists, or round-trips. The quickstart's manual steps cover that, and the gap is recorded rather than counted as coverage.
