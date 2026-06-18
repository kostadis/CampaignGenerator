# refs.yaml reference

`refs.yaml` declares the 5etools MCP server scope for a campaign. It lives at
the campaign root alongside `config.yaml` and is git-tracked. Its per-machine
companion `refs.local.yaml` is git-ignored and holds the root directory paths
that vary between machines.

`resolve_refs.py` reads both files; `launch_5etools_mcp.py` calls it to build
the per-campaign runtime tree.

---

## refs.yaml — full schema

```yaml
# Which WotC/canonical 5etools sources are in scope.
# Required. Use "all" to start; narrow later with canonical_exclude.
canonical: all             # "all" | [list of source codes]

# Drop specific sources when canonical: all.
# Ignored (and an error) when canonical is a whitelist.
canonical_exclude:
  - VRGtR
  - RotFM

# Additional non-canonical content: purchased PDFs and your own JSON files.
# Optional. Each entry must have exactly one of: rpglib, homebrew_private, path.
refs:
  - rpglib: "Wizards of the Coast/Adventures/T14.pdf"
    library: drivethrurpg      # selects roots.rpg_library_drivethrurpg; omit to use roots.rpg_library
    book_id: 7421              # optional but useful for MemPalace ingest
    note: "Tales from the Yawning Portal"

  - homebrew_private: "cross_campaign_canon/setting_bible/"
    note: "shared lore doc"

  - homebrew_private: "1e_modules/desert_of_desolation.json"

  - path: "./converted/icespire-homebrew.json"
    note: "campaign-local file, relative to this refs.yaml"
```

---

## `canonical:` field

| Value | Behaviour |
|---|---|
| `all` (default) | Every source code found in the 5etools data tree is in scope. Use `canonical_exclude:` to drop specific ones. |
| `[MM, PHB, OotA, …]` | Explicit whitelist. Only these source codes are in scope. `canonical_exclude:` is an error in this mode. |

Source codes are uppercase identifiers like `MM`, `PHB`, `OotA`, `XPHB`. Run
`python launch_5etools_mcp.py --campaign-dir . --status` to see all available
source codes from your data tree.

---

## `refs:` entry types

Each entry is a mapping with **exactly one** of the three type keys plus
optional shared fields.

### `rpglib:`

Points at a PDF inside your rpg-library corpus. The resolver looks for a JSON
sidecar at `<pdf-path-without-extension>.json` — produced by `convert_book.py`.

```yaml
- rpglib: "Wizards of the Coast/Adventures/T14.pdf"
  book_id: 7421    # optional; used by fivetools_ingest.py for metadata lookup
  note: "..."      # optional free-text label
```

**Multiple library roots** — if your PDFs are spread across separate directories
(e.g. DriveThruRPG and Kickstarter), add a `library:` key to select a named
root. The root name in `refs.local.yaml` must be `rpg_library_<library>`.

```yaml
# refs.yaml
- rpglib: "Wizards of the Coast/Adventures/T14.pdf"
  library: drivethrurpg

- rpglib: "Some Kickstarter Module.pdf"
  library: kickstarter
```

```yaml
# refs.local.yaml
roots:
  rpg_library_drivethrurpg: /mnt/g/DriveThru/
  rpg_library_kickstarter: /mnt/g/Kickstarter/
```

Entries without `library:` fall back to the plain `roots.rpg_library` root
(existing behaviour — no migration needed).

To find the right path and `book_id`, use:

```bash
python query_rpg_lib.py "tales yawning portal"   # search by title
python query_rpg_lib.py --book-id 7421           # emit a paste-ready refs.yaml block
```

Requires `roots.rpg_library` (or `roots.rpg_library_<name>` when using `library:`) in `refs.local.yaml`.

### `homebrew_private:`

Points at a file or directory inside your private homebrew tree (the root set
by `roots.homebrew_private`).

```yaml
- homebrew_private: "my_campaign/monsters.json"   # single file
- homebrew_private: "cross_campaign_canon/"        # directory — all *.json files recursively
  note: "..."
```

When a directory is given, every `*.json` under it is included (dotfiles and
dot-directories are skipped). Fails loudly if the path doesn't exist or a
directory contains no JSON files.

Requires `roots.homebrew_private` in `refs.local.yaml` (default:
`~/src/homebrew-private`).

### `path:`

Direct path to a JSON file — absolute or relative to the campaign directory.
No root required.

```yaml
- path: "./converted/icespire-homebrew.json"   # relative to campaign dir
- path: "~/src/my-module/statblocks.json"      # tilde-expanded absolute
  note: "..."
```

Use `path:` for files that live inside the campaign workspace itself or at a
fixed absolute location. Use `homebrew_private:` for files in a shared
collection that moves between machines.

---

## refs.local.yaml — full schema

```yaml
# <campaign-dir>/refs.local.yaml — git-ignored, per-machine
roots:
  fivetools_data: ~/src/5etools-kostadis/data/   # canonical 5etools JSON tree
  rpg_library: /mnt/g/                            # rpg-library corpus root (single-root case)
  homebrew_private: ~/src/homebrew-private/       # private homebrew collection

  # Named library roots — used when refs.yaml entries carry a 'library:' key.
  # Any name is valid; the root key must be rpg_library_<name>.
  rpg_library_drivethrurpg: /mnt/g/DriveThru/
  rpg_library_kickstarter: /mnt/g/Kickstarter/
```

All roots are optional in the file — only the roots actually needed by
your `refs:` entries (and `canonical:`) must be set.

### Root resolution precedence

For each root name the resolver checks in order:

1. `refs.local.yaml` — `roots.<name>:` value
2. Environment variable — `FIVETOOLS_DATA_ROOT`, `RPG_LIBRARY_ROOT`, or
   `HOMEBREW_PRIVATE_ROOT`
3. Built-in default — `fivetools_data` defaults to
   `~/src/5etools-kostadis/data`; `homebrew_private` defaults to
   `~/src/homebrew-private`; `rpg_library` has **no default** (path is too
   machine-specific)

If a required root can't be resolved, the launcher exits with a clear error
naming the missing root and telling you which key to set.

To generate a starter `refs.local.yaml` with detected defaults:

```bash
python launch_5etools_mcp.py --campaign-dir . --init-local
```

---

## Collision detection

The resolver raises an error if any `refs:` entry resolves to a 5etools source
code that's already covered by `canonical:`. Fix it by either:

- Adding the source code to `canonical_exclude:`, or
- Renaming your homebrew JSON file so it doesn't look like a canonical source

---

## Minimal refs.yaml (canonical content only)

If you only need the canonical 5etools tree and no purchased PDFs or homebrew,
the file can be as short as:

```yaml
canonical: all
```

No `refs.local.yaml` needed either — `fivetools_data` has a built-in default.
