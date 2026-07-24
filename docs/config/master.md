# CampaignGenerator Configuration — Master Map

Every configuration layer for CampaignGenerator, from mneme's host authority down to the
generated grounding docs. Stitches together the schema, value-level map, the Session Doc Editor's
own `session_doc.yaml`, and the ensemble + grounding subsystems.

## Authority & flow chain

```mermaid
flowchart TB
  HY["mneme hypostasis.yaml<br/>single authority"] -->|renders| WI["config/wiring.yaml<br/>external"]
  WI --> SVC
  CY["config.yaml<br/>internal, human"] --> SVC[CampaignConfigService]
  US[ui_state.yaml] --> SVC
  BO[boot_overrides] --> RES[resolved]
  SVC --> RES
  BO --> RESE[resolved_editor_config]
  RES -->|runtime.session_dir, default_model,<br/>campaign_dir| RESE
  SD["session_doc.yaml<br/>SessionEditorConfigService"] --> RESE
  UIE["ui.ensemble + party.yaml + planning.yaml"] --> GD["docs/*.md grounding"]
  GD -->|documents list| SVC
```

`scene_editor.CONFIG` — the old in-memory session-doc mirror — no longer exists; the Session Doc
Editor's own `SessionEditorConfigService` composes `CampaignConfigService` (platform reads only,
via `resolved()`) rather than being mirrored into it. See
[session-editor-isolation.md](./session-editor-isolation.md).

| Layer | Surface(s) | Owner | Format / persistence | Holds |
|---|---|---|---|---|
| 1. External wiring | `config/wiring.yaml` | mneme (rendered) | YAML, do-not-edit, hash-stamped | endpoints + roots |
| 2. Internal tracked | `config.yaml` | human | YAML, read-only to app | system_prompt, log_dir, agents, documents[], mempalace.* |
| 3. Server-owned UI state | `ui_state.yaml` | server (config service) | YAML, UIState v2, atomic writes | ui.<13 sections> + runtime + legacy — `session_doc`/`profiles` no longer live here (see layer 3b) |
| 3b. Session Doc Editor | `<config>/session_doc.yaml` | server (`SessionEditorConfigService`) | YAML, `SessionEditorConfig`, strict (`extra="forbid"`), atomic writes | `paths`/`narrate`/`scrub`/`roster`/`backends`/`session_name`/`profiles`/`active_profile` — its own document, not a `ui_state.yaml` section or an in-memory mirror |
| 4. Machine-local | `.campaigngenerator.local.yaml` | server | YAML, gitignored | server.{host,port}, nav.last_page |
| 5. Boot overrides | CLI flags to `server.main` | operator | in-memory only | session/campaign dirs; reach both `resolved()` and `resolved_editor_config()` from the same `boot_overrides` derivation |
| 6. Content / refs | `refs.yaml`, `refs.local.yaml`, `ingest_manifest.yaml`, `~/.5etools-mcp-runtime/` | human (+ `launch --init-local`) | YAML + generated symlink farm | 5e content scope, roots, ingest list, built MCP tree |
| 7. Ensemble subsystem | `ui.ensemble`, `manifest.json`, `merge.yaml`, `docs/*_draft.md` | server + ensemble CLI | persisted section + per-run artifacts | chapters/known_names/aliases/backends |
| 8. Planning subsystem | `planning.yaml` | human + planning service | YAML, planning service owned | npcs[], factions[] |
| 9. Grounding docs | `party.yaml`, `tracking.txt`, `docs/*.md` | human + generators | YAML config + generated md | rosters/dossiers → world/campaign/party docs |

## Who writes what

| Surface | Writer path | Notes |
|---|---|---|
| `config.yaml` | none (human-only) | `pipelines/workspace/new_workspace.py` creates; hand-edit |
| `ui_state.yaml` | `PUT /section/{name}`, `PUT /runtime`, boot `_normalize_stored_paths` | lazy on first write; atomic + write-lock; `PUT /section/session_doc` 404s (unknown section) |
| `session_doc.yaml` | `PUT /api/editor/config`, `/api/editor/profiles` CRUD + `/activate` | lazy on first editor write; atomic write, own file — cannot corrupt `ui_state.yaml` |
| `.campaigngenerator.local.yaml` | `PUT /local` | lazy on first write |
| `config/wiring.yaml` | mneme render only | not written by CampaignGenerator |
| `refs.yaml` / `ingest_manifest.yaml` | hand-authored | refs.local.yaml seedable via `launch --init-local` |
| ensemble artifacts | ensemble_extract (manifest+facts), synthesize (drafts), promote (live) | per-run workdir; disk is truth |
| `party.yaml` | `PUT /party-yaml` | UI editor or hand |
| `planning.yaml` | `/api/planning/*` CRUD (`PlanningConfigService`) | UI editor or hand |
| `docs/*.md` grounding | `pipelines/grounding/party.py` / `pipelines/grounding/campaign_state.py` / `pipelines/grounding/planning.py` (+ ensemble) | non-clobbering `.candidate` on conflict |

An existing campaign migrates its pre-isolation `ui.session_doc`/`ui.profiles` data into
`session_doc.yaml` via `python -m server.migrate_session_doc --campaign-dir DIR` — see
[session-editor-isolation.md § Migrating an existing
campaign](./session-editor-isolation.md#migrating-an-existing-campaign).

## Mental model

Two owners, three persistence classes.

- **Owners:** the human (`config.yaml`, refs, `party`/`planning.yaml`, grounding docs) and the
  server (`ui_state.yaml`, `session_doc.yaml`, `local.yaml`) — with mneme owning the external
  `wiring.yaml` above them.
- **Persistence classes:** tracked+portable (`config.yaml`, `refs.yaml`, `ui_state.yaml`,
  `session_doc.yaml`, `planning.yaml`), machine-local (`refs.local.yaml`, `.local.yaml`), and
  generated/derived (`wiring.yaml`, 5etools runtime, ensemble manifests+drafts, `resolved()`,
  `resolved_editor_config()`).
- **Invariant:** `config.yaml` is never machine-written, boot flags never persist, external
  endpoints live only in mneme-rendered wiring, and disk is the source of truth for the content
  pipelines.

See also [service-cut.md](./service-cut.md) for the multi-service reading of this same map.
