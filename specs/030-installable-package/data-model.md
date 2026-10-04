# Data Model: installed resources and external wiring

There is no new database or campaign schema. The feature changes ownership and resolution of existing files. These entities describe the on-disk contract and the state transitions the implementation must preserve.

## ShippedResource

| Field | Meaning | Validation |
|---|---|---|
| `logical_name` | Existing caller-facing name such as `config/agents/citation_rules_extract.md` | Relative, normalized, within the approved shipped-resource tree; no path traversal |
| `package_anchor` | Importable package owning the bytes | Must exist in the wheel |
| `resource_name` | Path beneath that package anchor | Must resolve to a readable file in the built wheel |
| `kind` | Prompt, template, reference file, or reviewer page | Read-only after installation |
| `contents` | Exact bytes shipped by the project | Prompt bytes match approved source; never generated at import |

**Relationships**: A shipped resource is the fallback for a named campaign prompt override. `session_doc/review/reviewer.html` is a shipped resource owned by `session_doc.review`. `config/config.yaml` is campaign configuration, not an implicit shipped configuration fallback.

## CampaignOverride

| Field | Meaning | Validation |
|---|---|---|
| `campaign_root` / `base_dir` | Operator-selected campaign location | Explicit or derived by existing campaign config rules |
| `logical_name` | Shipped prompt name being overridden | Same normalized name as its fallback |
| `path` | `<campaign>/config/agents/<name>.md` or existing base-dir equivalent | Must be a real file; no directory traversal |
| `contents` | GM-authored prompt text | Strict placeholder contract still applies |

**Resolution state**: `override present → override selected`; `override absent and shipped default present → shipped selected`; `both absent → named error`. An explicitly named absolute path that is missing is an error rather than a switch to another resource by basename. The selected origin participates in prompt cache identity so an override cannot be confused with a packaged default.

## ExternalWiring

| Field | Meaning | Validation |
|---|---|---|
| `source` | Explicit argument, `MNEME_WIRING`, or chosen default | Precedence in that order; only one selected source |
| `path` | Actual host file, default `~/.config/campaigngenerator/wiring.yaml` | Expanded for current user; not inside installed code |
| `settings` | Mneme-rendered endpoint and data-root mapping | YAML mapping; unknown keys retained during migration and reported |
| `producer` | Mneme hypostasis render target | Must match the consumer's default or use a deliberate explicit path |

**Resolution state**: `explicit/env path missing or malformed → clear error`; `default missing → {}` for optional wiring; `selected file valid → mapping returned`. No checkout/CWD fallback. Current known keys: `dgx_endpoint`, `dgx_model`, `rpg_library_url`, `fivetools_data_root`, `fivetools_mcp_index`, `rpg_library_db`, `pdf_translators`, `homebrew_private`.

## WiringMigration

| Field | Meaning | Validation |
|---|---|---|
| `source_checkout` | Operator-selected checkout holding retired `config/wiring.yaml` | Explicit path, must exist and contain the old file |
| `target` | Default user-config path or explicit target | Existing target refuses without `--force`; parent can be created |
| `raw_settings` | Original YAML mapping | Read raw, preserve known and unknown keys; report unrecognised names |
| `result` | Moved, no source, refused, or failed | Never report success before safe target write and old-file cleanup |

**State transitions**:

```text
legacy source only ──explicit migrate──> target valid, legacy source removed
legacy source + target present ──without --force──> refused, both unchanged
legacy source malformed ──migrate──> refused, source unchanged
target only ──normal use──> target read, no migration
neither present ──normal use──> optional empty wiring
```

Normal application startup does not enter a migration transition. A known retired checkout location produces an actionable migration error rather than a fallback read. An installed process that has no checkout path cannot discover arbitrary old checkouts; the operator supplies that path to the migration command.

## InstalledDistribution

| Field | Meaning | Validation |
|---|---|---|
| `wheel` | Non-editable install artifact | Built from this feature's source revision |
| `packages` | Seven currently declared package trees | Five required top-level areas import from unrelated CWD |
| `resources` | Shipped read-only resource inventory | Required prompt tree and reviewer page present |
| `commands` | Declared console entry points | Three representative help commands plus migration command run outside checkout |

**Relationship**: The wheel contains ShippedResource bytes and code. It never owns CampaignOverride, ExternalWiring, or runtime output. Installed mode does not contain or serve `frontend/dist`.
