# Contract: UI and Server Selection Parity

## Canonical flow

```text
Vue backend selector
  -> config/service request
  -> resolve_selection (backend + model provenance + batch validation)
  -> selection_cli_args / backend_cli_args
  -> existing router command builder
  -> production CLI
  -> shared API seam
```

No Vue component, route, or command builder invokes Codex directly or guesses a
Codex model.

## Selector behavior

Every backend selector that can reach a scoped capability must:

- obtain or validate `codex-cli` through the canonical config vocabulary;
- show one distinct saved-subscription choice;
- permit an optional Codex-compatible model;
- keep Codex model memory separate from the four existing providers where the UI
  already stores per-backend profiles;
- omit inherited Claude defaults when previewing or launching Codex;
- show an explicit incompatible-model refusal rather than replacing the value;
- disable or refuse provider message batching while leaving application-level
  grouping controls available;
- persist at the same owning configuration boundary as the existing choices.

## Server behavior

- `GET /api/config/models` exposes the canonical backend tuple.
- Runtime, service, editor, grounding, and ensemble request models accept the
  canonical type instead of private repeated literals.
- `resolve_selection()` owns Codex inherited-default omission and explicit-model
  refusal.
- Existing router builders forward only the resolved argument list.
- Progress, results, errors, and artifacts use the existing subprocess/SSE and
  disk-backed workflow paths.

## Reachability rule

Every one of the 30 inventory entries must identify one of:

1. a direct existing UI command builder;
2. an owning workflow face that invokes the command as a visible stage and exposes
   the backend/model choice transitively; or
3. a new invocation face added by this feature.

Internal implementation reuse alone is not reachability. A higher-level mapping is
valid only when the human can choose the relevant inputs, run the capability, and
see its output. There is no CLI-only exemption in this feature because none was
explicitly requested.

### Existing transitive faces

| Command | Owning UI invocation | Required proof |
|---|---|---|
| `ensemble` | Ensemble Extract workflow | `EnsembleExtract` -> ensemble route -> `ensemble_batch` -> `ensemble`. |
| `ensemble_extract` | Ensemble Extract workflow | `ensemble` forwards selection into its extraction dispatcher and children. |
| `extract_facts` | Ensemble Extract workflow | Extraction dispatcher forwards Codex to the leaf operation. |
| `sd_agent` | Session Workflow / Session Document Editor | UI exposes equivalent child stages and the same human boundary; dispatcher forwarding is tested separately. |

The remaining production stage commands already reached through grounding, prep,
setup, projection, scene-editor, and ensemble builders inherit the same selector
and require command-builder regression coverage.

### New invocation faces required by this feature

| Command | UI/server treatment | Boundary |
|---|---|---|
| `check_consistency` | Add direct document-audit control and scene-editor route. | Accept selected document/context and show the canonical audit output; do not substitute `sd_consistency`. |
| `transform` | Add the dossier-to-outline/beat bridge to Session Prep and its router. | Remain an explicit human-gated preparation step. |
| `vtt_voice_compare` | Add a session/voice comparison control and scene-editor route. | Show comparison/update/log outcome without auto-advancing narration. |
| `scabard_sync` | Add an integration view, mounted router, and navigation entry. | Accept the key in the request body, pass it to the child through a child-only `SCABARD_ACCESS_KEY` environment override, and redact that name/value from ordinary subprocess diagnostics; never place the secret in argv. |
| `synthesise_polish` | Add an explicit render option to Ensemble Synthesize. | Reuse the synthesize selection profile and preserve reviewed input/output boundaries. |
| `narrate_chapter` | Add an explicit per-chapter narration/review action in Ensemble. | Reuse extract selection; retain `approved:false` and never auto-cross approval. |
| `polish` | Add an explicit post-assemble route, toggle/run control, output, and changelog face. | Reuse editor selection and preserve the application-brokered operation scope and human checkpoint. |

New faces reuse existing per-run inputs and owning selection profiles; they do not
introduce new persisted stage configuration.

## Persistent editor profile

The session editor's profile set adds a defaulted `codex-cli` entry using YAML
alias `codex-cli`. Loading a pre-feature document must succeed; selecting and saving
a Codex model must round-trip without changing another backend profile.

## Acceptance assertions

- CLI and UI fixtures resolve identical backend/model intent.
- Every existing selector offers Codex exactly once.
- Every capability-inventory row has a tested reachability mapping.
- Router command tests contain `--backend codex-cli` and omit inherited Claude
  models.
- Explicit Codex models are forwarded; explicit Claude models are refused.
- Provider batch is refused before subprocess launch.
- UI-launched artifacts and status events match equivalent manual invocations.
