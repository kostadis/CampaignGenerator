# Contract: `dnd_sheet` CLI

The engine surface. Every behaviour in this feature is reachable here; the HTTP surface
([http-api.md](./http-api.md)) only forwards flags to it (Constitution VI).

## Invocation

```
dnd_sheet PDF [PDF ...] [--party-config PATH] [--output FILE] [--output-dir DIR]
               [--model MODEL] [backend args]
```

### Flags

| Flag | Default | Change | Meaning |
|---|---|---|---|
| `PDF...` | — | — | One or more PDFs. Always explicit; never a glob expanded by the tool. |
| `--party-config PATH` | unset | **NEW** | Path to the campaign's `config/party.yaml`. **Presence turns roster mode on.** Relative sheet paths inside it resolve against the cwd (the campaign root). |
| `--output FILE` | unset | — | Single PDF only. Suppresses roster naming and archival (FR-017). |
| `--output-dir DIR` | **`None`** (was `"doc"`) | **CHANGED** | Only meaningful outside roster mode, where it falls back to `doc`. The default flips to `None` so the tool can tell "unset" from "explicitly `doc`" — without this the UI cannot reach roster mode (D11). |
| `--model`, backend args | unchanged | — | Via `add_backend_args` / `client_from_args`. |

### Mode selection

| `--party-config` | `--output` / `--output-dir` | Mode |
|---|---|---|
| absent | either | **Legacy** — `<pdf-stem>.md`, exactly as today, plus a one-line notice (FR-018) |
| present | absent | **Roster** — attribute, name, archive |
| present | present | **Legacy**, plus a notice that roster naming and archival were skipped (FR-017) |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Every PDF converted and written. |
| `1` | At least one PDF was refused, or an argument/file error. Others in the same run still converted (FR-004). |

## Output contract

Reports go to **stderr** (matching today's `Converting …` / `Saved to: …`); the converted
markdown is the only thing that reaches a file. Every message below is deterministic — no
timestamps, no dict-order dependence — so two identical runs produce identical text.

### Success, per PDF

```
Converting Soma-4271883.pdf...
Matched roster entry: Soma
Archived: docs/party/Soma.md -> docs/party/old/level/6/Soma.md  (level 6)
Player: Kostadis -> Wade  (from party.yaml)
Saved to: docs/party/Soma.md
```

- The `Matched roster entry` line is FR-002b and is printed for **every** written file.
- The `Archived` line is FR-016; omitted when nothing was displaced.
- The `Player` line is FR-008. When the roster names no player:
  `Player: none recorded in party.yaml — left empty (the downloaded value names the
  downloader, not the player)` (FR-009).

### Refusals

Each names the file, the reason, and the fix. Nothing on disk is touched.

**No roster match (FR-003, FR-003a)**

```
REFUSED Valphine-1120044.pdf: the name on this sheet is not in the roster.
  Sheet says:      "Valphine Sotorra"
  Roster has:      Brewbarry, Soma, Valphine, Vukradin
  The roster and the sheet disagree, and there is no fuzzy matching
  here on purpose. Three ways out, in order of preference:
    1. Fix the name at source in D&D Beyond and re-download.
    2. Rename the character in config/party.yaml to match the sheet.
    3. If the sheet's spelling is wrong and cannot be corrected, add
       sheet_name: "Valphine Sotorra" to that character's roster
       entry — the sheet is then matched on it while the roster's own
       name still names the file.
  Nothing was written or moved.
```

The three fixes are ordered deliberately. Correcting the download is always better
than teaching the roster to live with it, and renaming the character is better than
carrying two spellings — `sheet_name` (FR-002c) is the last resort, for a download
that is wrong and cannot be corrected. An entry that declares one is listed as
`Akritas (sheet: Akrita)` on the `Roster has:` line, because printing the name alone
would tell the GM the roster lacks a string the declaration just made present.

**Ambiguous match (FR-003)**

```
REFUSED Soma.pdf: "Soma" matches 2 roster entries. Names must be unique.
```

**Roster filename mismatch (FR-006, D6)**

```
REFUSED Soma.pdf: the roster points at a filename this conversion would not write.
  party.yaml says: sheet: docs/party/soma.md
  would write:     docs/party/Soma.md
  Fix the roster entry for Soma to:
      sheet: docs/party/Soma.md
  If a sheet already exists at the old name, RENAME IT TOO —
      git mv docs/party/soma.md docs/party/Soma.md
  — or the next run will see no sheet to displace, archive nothing,
  and leave the old file orphaned beside the new one.
  Nothing was written or moved.
```

The rename half is not decoration. Fixing only the roster line is the one path on which
archival is skipped without an error: the destination no longer exists, so `plan_archive`
returns "nothing to displace" and the level-N sheet is left orphaned instead of filed.

**Unreadable level (FR-013)**

A complete multiclass phrase is not a refusal — `Fighter 9 / Bard 2` archives at
level 11. This fires when one of the classes has no level of its own.

```
REFUSED Soma.pdf: cannot read a level from the sheet being replaced.
  docs/party/Soma.md says: "Fighter 9 / Bard"
  The archive is keyed by the character's total level, so every class listed
  needs its own — fix the "Class & Level" line, or move the sheet by hand.
  Nothing was written or moved.
```

```
REFUSED Vukradin.pdf: cannot read a level from the sheet being replaced.
  docs/party/Vukradin.md has no "Class & Level" in its ## Identity block and no
  class_level frontmatter. Nothing was written or moved.
```

**Occupied archive slot (FR-014)**

```
REFUSED Soma.pdf: docs/party/old/level/6/Soma.md already exists.
  A level-6 sheet is already archived; overwriting it is the one thing this
  archive exists to prevent. Nothing was written or moved.
```

**Unusable roster**

```
Error: --party-config not found: config/party.yaml
```
(from the existing `load_party_config_arg`; the run then proceeds in legacy mode with the
FR-018 notice, per that function's established soft-fail contract)

## Ordering guarantee (FR-015, D7)

The API call completes before any filesystem mutation. Consequences the contract commits
to:

1. A refused PDF never leaves a character without a sheet.
2. A crashed or aborted run never leaves an empty destination — the displaced sheet is
   moved only once the replacement content exists in memory.
3. An attribution failure costs one API call and changes nothing on disk.

## Module boundaries this CLI must respect

- `pdf_to_markdown` keeps its `call_api` / `run_single_batch` body and gains **no**
  retrieval call (`tests/test_retrieve_render_isolation.py`).
- All new logic lives in `campaignlib/sheet_naming.py` and `campaignlib/sheet_identity.py`,
  which import nothing from `server` or `pipelines` (`tests/test_layering.py`).
- `SYSTEM_PROMPT` is unchanged — the model is still asked for all five frontmatter keys,
  and the player substitution happens afterwards (D8).

## Sibling CLI: `sheet_frontmatter`

Behaviour unchanged. Its parsers now live in `campaignlib/sheet_identity.py` and are
imported; `parse_identity_fields`, `sheet_name` and `SheetParseError` keep their names and
semantics so `tests/test_sheet_frontmatter.py` passes untouched.
