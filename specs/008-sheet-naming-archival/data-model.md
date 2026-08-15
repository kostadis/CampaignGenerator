# Phase 1 Data Model: Roster-Named Sheets & Level Archival

Entities from [spec.md](./spec.md), grounded in the modules that own them. Decisions
referenced as D1–D12 live in [research.md](./research.md).

---

## 1. `PartyCharacter` — one roster entry

**Owner**: `campaignlib/party_config.py` · **Persisted**: `<campaign>/config/party.yaml`
· **Model config**: `extra="forbid"`

| Field | Type | Required | Change | Meaning |
|---|---|---|---|---|
| `name` | `str` | yes | — | Canonical character name. **New role**: the attribution key and the output filename stem. |
| `sheet` | `str` (authored path) | yes | — | Where the character's sheet lives. **New role**: its parent directory is the conversion destination. |
| `player` | `str \| None` | no | **NEW** | Who plays the character. Authoritative over the downloaded sheet (FR-008). |
| `backstory` | `str \| None` | no | — | |
| `dossier` | `str \| None` | no | — | |
| `arc_score` | `str \| None` | no | — | |
| `trackless` | `bool` | no | — | Three-state encoding with `arc_score`; unchanged. |

**Validation**

- `player` is optional and additive: a roster with no `player` anywhere stays valid and
  loads unchanged (FR-008a). Because the model is `extra="forbid"`, the field must exist
  on the model *before* any campaign writes it into YAML.
- `player` is stored and compared as authored, but **trimmed** before it is written into
  a sheet — `zalthir.md:5`'s documented trailing space is the precedent.
- `player` MUST be the **Zoom display name**, not a legal name (D8).
  `normalize_vtt_speakers` matches speaker prefixes exactly, and a near-miss silently
  drops that PC's lines. This is help text, not a validator — the system cannot know what
  Zoom shows.
- Two entries sharing a `name` (case-insensitively) make attribution ambiguous. Not
  rejected at load time — the roster may legitimately be mid-edit — but every conversion
  that resolves to them refuses (FR-003).

**Persistence trap (D9)**: `load_party_config`, `save_party_config` and
`resolve_party_config` all **hand-build** their output rather than dumping the model.
`player` must be named in all three or a save appears to succeed and persists nothing —
the exact defect feature 003 shipped when it added `selection`.

---

## 2. `ResolvedCharacter` — a roster entry with paths resolved

**Owner**: `campaignlib/party_config.py` · **Never persisted**

Gains `player: str | None`, carried through verbatim from `PartyCharacter`. It is not a
path, so `resolve_party_config`'s `_resolve` does not touch it; it is copied like
`trackless`. `require_files=False` remains the loading mode for this feature — the
destination sheet may legitimately not exist yet (first conversion for a character).

---

## 3. Character sheet document — the converted markdown

**Owner**: produced by `pipelines/content_ingest/dnd_sheet.py` · **Persisted**:
`<sheet-dir>/<char-name>.md`

Two channels state the same identity, and this feature must keep them agreeing (FR-010a):

| Channel | Location | Player field | Class & level field |
|---|---|---|---|
| Machine | YAML frontmatter | `player:` | `class_level:` |
| Human | `## Identity` block | `- **Player:**` | `- **Class & Level:**` |

**Authority**: the sheet is authoritative for everything about the character **except**
`player`, which the roster overrides on every conversion.

**Reality check**: frontmatter is *not* guaranteed. All four live Phandalin sheets and all
four archived ones begin at `# Name` with no `---` block. Any read of an existing sheet
must therefore fall back to the `## Identity` block (D3, D4).

---

## 4. Character level — the archive partition key

**Derived**, never stored as its own field. Read from the sheet **being displaced**, not
the incoming one.

```
class_level phrase  →  parse_level()  →  archive partition
"Monk 8"                    8              old/level/8/
"Druid 5"                   5              old/level/5/
"Fighter 9 / Bard 2"     AmbiguousLevelError   (refuse — D4)
""  /  absent            AmbiguousLevelError   (refuse)
```

Source precedence: frontmatter `class_level` → `## Identity` `**Class & Level:**` → none.

---

## 5. Archive location — a directory, not a record

`<sheet-dir>/old/level/<N>/<char-name>.md`, created with parents (FR-011).

- Not a live sheet location. Nothing reaches sheets by scanning the directory; readers
  follow the roster's `sheet:` reference.
- **Immutable once written**: an occupied slot is a refusal, never an overwrite or a
  suffix (FR-014, D5).
- Filenames are roster-shaped even when the file they displaced was not — matching the
  existing hand-built archive, where `old/level/5/Soma.md` sits above a live `soma.md`.

---

## State transitions — one PDF through one conversion

```
                         ┌─ no --party-config ──→ legacy: <pdf-stem>.md, notice (FR-018)
  PDF ─→ extract text ──┤
                         └─ roster mode
                               │
                        call the API  ← the only fallible step, and it runs
                               │        BEFORE any filesystem mutation (D7)
                        read name from output
                               │
                    ┌──────────┴──────────┐
              exactly one              zero or >1
              exact match             exact match
                    │                       │
                    │                  REFUSE (FR-003/003a): print the name read,
                    │                  the roster names available, and that the
                    │                  roster is the file to fix. Nothing touched.
                    │
          destination = <declared sheet dir>/<char-name>.md
                    │
        ┌───────────┴───────────┐
   basename agrees          basename differs
        │                        │
        │                   REFUSE (FR-006, D6): print the exact replacement
        │                   `sheet:` line for party.yaml. Nothing touched.
        │
   destination exists? ──no──→ write ─→ report path + player source
        │ yes
   read displaced level
        │
   ┌────┴────┐
 parsed   ambiguous/absent ──→ REFUSE (FR-013). Nothing touched.
   │
 archive slot occupied? ──yes──→ REFUSE (FR-014). Nothing touched.
   │ no
 move displaced → old/level/<N>/<char-name>.md
   │
 substitute player in BOTH channels (FR-010a); empty when the roster
 states none, plus a report line (FR-009) — never the downloaded value
   │
 write new sheet ─→ report: matched entry, archive move, final path (FR-002b, FR-016)
```

**Multi-PDF runs**: each PDF walks this independently. One refusal does not stop the
others; the process exits non-zero if any were skipped (FR-004).

---

## Field-level provenance summary

| Value on the converted sheet | Comes from | Overridden by the roster? |
|---|---|---|
| `name` / `# H1` | the model, reading the PDF | no — but it must *match* the roster or the run refuses |
| `player` | **the roster** | **yes, always** — the download stamps the downloader's name |
| `species`, `class_level`, `subclass`, body | the model, reading the PDF | no |
| output **filename** | **the roster** (`name`) | n/a |
| output **directory** | **the roster** (`sheet` parent) | n/a |
| archive partition | the **displaced** sheet's level | n/a |
