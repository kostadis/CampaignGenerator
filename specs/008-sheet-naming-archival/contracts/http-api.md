# Contract: HTTP surface

Two existing routers change. Neither gains logic — the setup router forwards flags to the
CLI, and the party router carries one more model field (Constitution VI).

---

## 1. `GET /api/setup/run/dnd-sheet` — run a conversion

**Owner**: `server/routers/setup.py::run_dnd_sheet` · **Response**: unchanged —
`text/event-stream`, the subprocess's stdout/stderr streamed via `stream_subprocess`.

### Query parameters

| Parameter | Type | Change | Forwarded as |
|---|---|---|---|
| `pdfs` | `list[str]` | — | positional arguments |
| `party_config` | `str` | **NEW** | `--party-config <value>` when non-empty |
| `output` | `str` | — | `--output <value>` when a single PDF and non-empty |
| `output_dir` | `str` | **CHANGED** | `--output-dir <value>` **only when non-empty** — never synthesised |
| `model` | `str \| None` | — | via `resolve_selection` + `selection_cli_args`, unchanged |

### Required behaviour

- **The router must not send an output location the operator did not set.** Under FR-017
  an explicit output path suppresses roster naming and archival, so a synthesised default
  makes the feature unreachable from the UI. This is the single highest-risk line in the
  change (D11).
- The router performs **no** attribution, name derivation, level parsing or archival, and
  contains no default sheet path or directory literal.
- Refusals reach the browser as the CLI's own stderr text, unmodified (FR-022, FR-025).
  `RunPanel` already renders the stream verbatim, so no new plumbing is required.
- `GET /api/setup/selection/resolved` is unchanged. Setup remains an *inheriting* service
  with no config document of its own — this feature adds no `setup.yaml`.

---

## 2. `/api/party/characters` — the roster

**Owner**: `server/routers/party_routes.py` over `campaignlib.party_config.PartyCharacter`

No route signature changes. Every endpoint below now carries `player` because it is a
field on the model the routes already pass through:

| Endpoint | Change |
|---|---|
| `GET /characters` | response objects include `player` |
| `PUT /characters` | accepts and persists `player` for every entry (atomic whole-roster write) |
| `POST /characters` | accepts `player` |
| `GET /characters/{name}` | includes `player` |
| `PUT /characters/{name}` | accepts and persists `player` |
| `DELETE /characters/{name}` | unchanged |

### Required behaviour

- **`player` must survive a round-trip.** `PUT` then `GET` must return what was sent.
  `save_party_config` hand-builds its YAML dict, so the field is dropped unless named
  there explicitly — the failure mode is a save that returns `200` and persists nothing
  (D9). A route-level round-trip test is the guard.
- `player` is optional. Omitting it, or sending `null`/`""`, is valid and means "no player
  recorded" — which the converter reports rather than filling in (FR-009).
- `extra="forbid"` still applies: the model must carry the field before any campaign's
  YAML does.
- `missing_files` reporting is unaffected — `player` is not a path and is not added to
  `PATH_FIELDS`.

---

## 3. Frontend contract

| Component | Change |
|---|---|
| `frontend/src/views/setup/DndSheet.vue` | Add a party-config `PathField` (`resolve-base="campaign"`). Add a notice stating which mode the current inputs select — roster mode requires a party config and **no** output path. Send `party_config` in `runParams`. |
| `frontend/src/components/shared/PartyConfigEditor.vue` | Add `player` to the `PartyChar` interface, the blank-row factory (`{ name: '', sheet: '', player: '', … }`), the load mapping (`player: c.player ?? ''`), and a column in the table. |

**Help text for the `player` field** (both surfaces) must carry D8's constraint: this is
the **Zoom display name**, not a legal name — `normalize_vtt_speakers` matches speaker
prefixes exactly, and a near-miss silently drops that character's lines from every
downstream extraction.

**No browser-held state**: the roster is read and written through the API to
`party.yaml`; the run is a subprocess whose output is a file. Files remain the only
interchange between the UI, the CLI and a Claude conversation (FR-024, Constitution IX).

---

## Deployment note

The UI resolves pipelines through `console_script(name)` against the **server's** venv, not
`$PATH`. A CLI signature change is invisible to the UI until the package is reinstalled
into that venv:

```bash
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
```

No server restart is needed — `console_script()` resolves per request. Skipping this shows
up as `Stream error — check terminal.` on the page.
