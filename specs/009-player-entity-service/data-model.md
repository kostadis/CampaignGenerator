# Phase 1 Data Model — Player Entity & Config Service

**Feature**: `009-player-entity-service` | **Date**: 2026-08-15

Two documents change and one is created. Field-level detail for each, then the
validation rules, then what happens to the fields being retired.

---

## 1. `Player` — new

One human at the table. Lives in `<campaign>/config/players.yaml`, modelled in
`campaignlib/players_config.py`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `str` | **yes** | Short slug authored by the GM (`ben`, `wade`). Unique within the document. The same person uses the same slug in every campaign, by the GM typing it — nothing enforces or reads that across campaigns (FR-005). |
| `name` | `str` | **yes** | The person's name, as you would address them. This is what renders into prompts (FR-019). |
| `display_names` | `list[str]` | no, default `[]` | Exact strings a recording has labelled this person with, ordered as authored. Zero is legitimate — Hillsfar records a placeholder for all four characters. |
| `plays` | `list[str]` | no, default `[]` | Character names in this campaign's roster. Zero, one, or many. |
| `gm` | `bool` | no, default `False` | Runs the game. Independent of `plays` — toee's Calmer is a GM-played PC. |
| `active` | `bool` | no, default `True` | Still at the table. `False` keeps the record for the transcript archive (FR-011a). |
| `dndbeyond_id` | `str \| None` | no | The numeric identifier from a D&D Beyond export filename. **Recorded, read by nothing** in this feature — using it as an attribution key is #312. |

`model_config = ConfigDict(extra="forbid")`.

### `PlayersConfig` — the document root

| Field | Type | Notes |
|---|---|---|
| `players` | `list[Player]` | Default `[]`. Order is meaningful — it is the row order of the page. |

No `selection` field. This service spends no tokens, so it has no model or backend
override to carry.

---

## 2. `PartyCharacter` — changed

`campaignlib/party_config.py`. Two fields added, one removed.

| Field | Change | Notes |
|---|---|---|
| `voice` | **added**, `AuthoredPath`, optional | The character's voice specification file, campaign-root-relative like `sheet`. |
| `examples` | **added**, `AuthoredPath`, optional | The character's style-examples file, same. |
| `player` | **removed** | The player entity owns the binding (FR-011, FR-012). A document still carrying it is refused, naming the field (FR-013). |
| `name`, `sheet`, `backstory`, `dossier`, `arc_score`, `trackless`, plus the root `selection` | unchanged | |

```python
PATH_FIELDS = ("sheet", "backstory", "dossier", "arc_score", "voice", "examples")
```

Adding the two to `PATH_FIELDS` is the whole mechanism: `missing_files` already walks
that tuple, the API already returns its report per character, and the Party page
already renders it. A declared file that is absent becomes a loud failure by reusing
machinery that exists — which is the point of D5.

### `PartyConfig` — one root key added

| Field | Type | Notes |
|---|---|---|
| `shared_examples` | `list[str]`, default `[]` | Campaign-wide example files, authored paths. These reach **every** narrator, by declaration. Sits beside the existing root `selection`. |

`ResolvedCharacter` / `ResolvedPartyConfig` gain the resolved counterparts
(`voice: Path | None`, `examples: Path | None`, `shared_examples: list[Path]`) and
lose `player`.

**Loader/saver warning.** `load_party_config` and `save_party_config` both hand-build
their dict rather than dumping the model — the module docstring records that a field
named in only one of them round-trips to nothing, and that this has already happened
once with `selection`. Every new field must be named in **both**.

---

## 3. `SessionEditorConfig` — a group deleted

`server/session_editor_config_shared.py`.

| Field | Change | Replacement |
|---|---|---|
| `roster.characters` | **removed** | Derived from `party.yaml`'s character names (FR-031). |
| `roster.gm_player` | **removed** | The `gm: true` player in `players.yaml` (FR-015). |
| the `Roster` model | **removed** | Both of its fields are gone. |
| `TYPED_SESSION_DOC_TO_GROUPED` | two entries removed | `"characters"` and `"gm_player"` become *unrecognised* keys — reported, not migrated, matching how `narration_genre` and `roleplay_dir` are already handled there. |

`paths.voice_dir` and `paths.examples_dir` **stay**. They stop being the routing
mechanism and become what the orphan check enumerates, and `pipelines/ensemble/polish.py`
still scans `voice_dir` directly.

---

## 4. Relationships

```
PlayersConfig 1 ──── * Player
                        │ id            (unique in document)
                        │ display_names (unique across ALL players in document)
                        │ plays ────────────────┐
                        │                        │  by character name, exact
PartyConfig 1 ──── * PartyCharacter  ◄───────────┘
                        │ name
                        │ sheet / backstory / dossier / arc_score  (paths)
                        │ voice / examples                          (paths, new)
              └── shared_examples : list[path]      (reaches every narrator)
```

The binding is **many-to-many** and lives on the player side only:

- one player, two characters → two entries in `plays`;
- one character, two players → that character name appears in two players' `plays`.

Nothing on the character side points back. That is deliberate: one direction, one
authority (FR-011).

---

## 5. Validation rules

Grouped by when they fire, because the spec is explicit that a save is lenient about
files and strict about shape.

### Refused at load and at save (shape and identity)

| Rule | Message names | Requirement |
|---|---|---|
| Unknown field anywhere | the field and the entry | FR-008 |
| `id` missing or blank | the entry's position | FR-004 |
| `name` missing or blank | the `id` | FR-001 |
| Duplicate `id` | both entries | FR-005a |
| A `display_name` appearing under two players | both players and the shared value | FR-005b |
| `party.yaml` still carrying `player:` | the character and the retired field | FR-013 |
| Malformed YAML | the file and the parser error | FR-008 |

### Reported, never refused (references)

| Rule | Where it surfaces | Requirement |
|---|---|---|
| `plays` names a character absent from `party.yaml` | response body; the page | FR-016, FR-017 |
| A declared `voice` / `examples` file does not exist | `missing_files`, response body, the page | FR-017 |
| A campaign roster character no active player plays | `players check` | FR-038 |
| A player with no `display_names` | `players check` | FR-038 |
| A file in `voice_dir`/`examples_dir` nothing declares | `players check` | FR-030b |
| An expected display name absent from a given transcript | `players check --vtt` | FR-039 |

### Refused at run time (a consumer cannot proceed)

| Rule | Behaviour | Requirement |
|---|---|---|
| A narrating character has no declared voice/examples file, and the declared path is absent | stderr naming character and path; exit 1, before the first API call | FR-028 |
| A character in this render has no player bound | stderr naming the character; exit 1 | FR-024 |
| `players.yaml` absent on a campaign whose consumers need it | stderr naming the file and the adoption command; exit 1 | SC-008 |

### Empty and absent are not errors

An absent or empty `players.yaml` loads as `PlayersConfig(players=[])` (FR-009) —
the "an emptied file reads back as 400" bug that `docs/config/planning-isolation.md`
had to fix twice.

---

## 6. State transitions

A player has exactly one lifecycle axis, `active`.

```
        (created)
            │
            ▼
      ┌──────────┐   GM marks departed    ┌────────────┐
      │  active  │ ─────────────────────► │  inactive  │
      │  = true  │ ◄───────────────────── │  = false   │
      └──────────┘    GM marks returned   └────────────┘
            │                                    │
            │ delete (GM, explicit)              │ delete (GM, explicit)
            ▼                                    ▼
        (removed — the transcript archive stops resolving this speaker)
```

| State | Display names resolve | In the prompt roster | Their character reported as unbound |
|---|---|---|---|
| `active: true` | yes | yes | no |
| `active: false` | **yes** — the archive still carries the label | no | **no** |
| removed | no | no | yes |

Deletion stays available and is never automatic. `active: false` is what the page
offers; the file is where a GM removes someone for good.

No other entity has a lifecycle. A character's states are `party.yaml`'s business and
are unchanged by this feature.

---

## 7. Derived values — computed, never stored

| Value | Computed from | Consumer |
|---|---|---|
| speaker map (display name → label) | `players.yaml` + `party.yaml`; GM entries written **last** so they overwrite (FR-021a) | `normalize_vtt_speakers` in `scene_extract`, `enhance_summary` |
| the prompt roster block | active players' `name` + each character's sheet frontmatter (`species`, `class_level`, `subclass`) | `roster_from_config` → `sd_narrate`, `polish` |
| the narrating-character list | `party.yaml` character names | `sd_plan --characters`, built by `scene_editor.py` |
| per-character voice text | the character's declared `voice` path | `sd_narrate` |
| per-character examples text | the character's declared `examples` path | `sd_narrate` |
| the global examples block | `party.yaml`'s `shared_examples` | `sd_narrate` |
| the sheet's stamped `player` value | the bound player's `name` | `dnd_sheet` → `apply_roster_player` |

Each of these is recomputed per run. None is written back into a config document —
that is the `narrate.genre` failure the whole design avoids. The one value written to
disk, the sheet's `player:` line, is explicitly a **rendered copy and not an
authority** (FR-023), and no consumer reads it back.
