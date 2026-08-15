# Feature Specification: Roster-Named Sheets & Level Archival

**Feature Branch**: `worktree-feat-dnd-sheet-party-names`

**Created**: 2026-08-13

**Status**: Draft

**Input**: User description: "The D&D character sheet conversion feature (pipelines/content_ingest/dnd_sheet.py) should use party.yaml to assign character names to the players, replacing the downloaded/default name, and rename the output files to <char-name>.md. If a character sheet already exists at that destination, the existing file should be moved into a subdirectory in the same location, old/<level>/ (created if necessary), before the new sheet is written." Followed by: "I want the feature to be useable
from the UI, not just the CLI."

Then: "rather than have 'relaxed', let's just have it fail loudly, and then I will
go and fix the yaml. As for FR-008, let's have the authoritative names live in
party.yaml, because when I download the sheets from D&D Beyond it adds my name
instead of the players name."

**Clarifications resolved (2026-08-13)**: the roster gains a `player:` field and
becomes authoritative for it, because the export stamps the downloader's name into
every sheet (FR-008); attribution keys on the character name read out of the sheet
(FR-002) and is **exact-match-only — no fuzzy fallback, a mismatch is a loud failure
the GM fixes in the roster** (FR-002a, FR-003a); the archive layout is
`old/level/<N>/` (FR-012).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Re-convert a levelled-up character without losing the old sheet (Priority: P1)

The party levels up. The GM re-exports each character's PDF and converts it. Each
conversion finds the sheet that character already has, files it away under an
archive folder keyed by the level it recorded, and writes the new sheet in its
place — at the same path the campaign roster already points at. Nothing is
overwritten, and no roster reference goes stale.

**Why this priority**: This is the whole point. Today the converter writes
`<pdf-stem>.md` into an output directory, so a re-export either lands beside the
old sheet under a different name (roster still points at the stale one) or
overwrites it outright, destroying the only record of what the character looked
like at the previous level. The GM currently does the rename-and-archive by hand
— the evidence is already on disk (`Phandalin/docs/party/old/level/5/` holds four
hand-filed sheets). Automating exactly that hand procedure delivers value on its
own, with no other story built.

**Independent Test**: Convert a PDF for a character who already has a sheet.
Verify the previous sheet is readable at its archive location, the new sheet is
at the original path, and the roster entry for that character still resolves.

**Acceptance Scenarios**:

1. **Given** a roster listing a character whose sheet exists and records level 5,
   **When** a new PDF for that character is converted,
   **Then** the level-5 sheet is present in the archive folder and the new sheet
   is at the path the roster names.
2. **Given** the same conversion,
   **When** the roster is re-read afterwards,
   **Then** every roster file reference still resolves to an existing file.
3. **Given** a character who has no sheet yet,
   **When** their PDF is converted,
   **Then** the sheet is written and no archive folder is created.
4. **Given** an archive folder that does not exist,
   **When** a sheet must be archived into it,
   **Then** the folder is created as part of the operation.

---

### User Story 2 - Sheets are named by the campaign's canonical character name (Priority: P2)

Converted sheets are named after the character as the campaign knows them, not
after whatever the download was called or what the sheet's own title says.

**Why this priority**: Naming today has no authority at all. Live sheets are
lowercase (`soma.md`) while archived ones are capitalised (`Soma.md`), and one is
capitalised in both (`Vukradin.md`). Without a single naming authority, US1's
archival files things under names that drift from the roster. Valuable on its own
— it makes the sheet directory self-consistent — but it is US1 that makes it
load-bearing.

**Independent Test**: Convert a PDF whose filename differs from the roster's name
for that character. Verify the output filename is derived from the roster name
only.

**Acceptance Scenarios**:

1. **Given** a roster entry named `Valphine` and a PDF file named
   `character-sheet-2.pdf`, **When** it is converted, **Then** the output file is
   named from `Valphine`, not from the PDF.
2. **Given** a roster entry whose name differs in case from the existing file on
   disk, **When** it is converted, **Then** the output takes the roster's casing.

---

### User Story 3 - The player behind the character survives a re-export (Priority: P3)

The person who plays a character is recorded from the campaign roster the GM
maintains, not from the value carried in the downloaded sheet.

**Why this priority**: The downloaded sheet's player field is **wrong for every
character, by construction**. The GM downloads all the party's sheets from their own
D&D Beyond account, and the export stamps the downloader's name into the player
field — so every sheet comes back naming the GM, not the person who plays that
character. It is corrected by hand afterwards, and because US1 makes re-conversion
routine, every level-up silently re-imports the GM's name over all four corrections
at once. Lower priority than US1/US2 only because the corrections are recoverable by
hand today; it is the systematic nature of the error that makes the roster the right
home for the value.

**Independent Test**: Convert a PDF whose player value is the GM's name for a
character whose roster entry names a different, real player. Verify the converted
sheet records the roster's player everywhere it states one, and that a second
conversion does not revert it.

**Acceptance Scenarios**:

1. **Given** a roster entry naming a player and a PDF carrying the GM's name in its
   player field, **When** the PDF is converted, **Then** the converted sheet records
   the roster's player value.
2. **Given** the same conversion, **When** both the machine-readable summary and the
   human-readable identity block of the output are read, **Then** they state the
   same player.
3. **Given** a roster entry that names no player, **When** the PDF is converted,
   **Then** the output records no player rather than the downloaded value, and the
   run reports that the character has none.

---

### User Story 4 - Run the whole thing from the web UI (Priority: P2)

The GM does the level-up re-conversion from the D&D Sheet page — picks the PDFs,
runs it, and reads back which character each was attributed to, what was archived
where, and what was skipped — without opening a terminal.

**Why this priority**: The capability is not considered delivered CLI-only. The
surface already exists (`/setup/dnd-sheet`, backed by `/api/setup/run/dnd-sheet`,
which already shells out to the converter and streams its output), so this is reach
rather than new capability — but the existing page always sends an explicit output
location when its field is filled, which under FR-017 would disable roster naming
and archival on every UI run. Without this story the feature is silently
unreachable from the UI it appears to already have. It also needs the party roster
editor to expose the new player field, or the GM cannot set the value that FR-008
makes authoritative.

**Independent Test**: From the UI alone, re-convert a character who already has a
sheet. Verify the archive move happened, the new sheet is at the roster's path, and
the run output names the matched roster entry — with no terminal commands.

**Acceptance Scenarios**:

1. **Given** the D&D Sheet page with roster-driven naming chosen,
   **When** a PDF for an already-sheeted character is run,
   **Then** the streamed output names the matched roster entry, the archive
   destination, and the final sheet path.
2. **Given** a PDF that matches no roster entry,
   **When** it is run from the UI,
   **Then** the page shows the refusal and its reason, not a generic failure.
3. **Given** the party roster editor,
   **When** the GM sets a player for a character and saves,
   **Then** the value persists and a later conversion uses it.
4. **Given** any action performed in the UI,
   **When** the equivalent command is run at the CLI,
   **Then** it produces the same files.

---

### Edge Cases

- **No matching roster entry.** A PDF that cannot be attributed to exactly one
  roster entry is reported and skipped — never written under a guessed name, and
  never allowed to trigger an archival move.
- **The sheet's own name is longer than the roster's.** Live today: the sheet reads
  "Valphine Sotorra", the roster reads "Valphine". This is a loud failure, not a
  near-match to resolve. The GM then settles which spelling is canonical and edits
  the roster. Worth knowing which way to fix it: the roster's character name is also
  the campaign's canonical PC name, consumed well beyond this feature — it is the
  output filename, the PC-name exclusion list, and the roster rendered into prompts
  — so widening it to `Valphine Sotorra` widens it everywhere. Correcting the sheet
  instead is the narrower change. The conversion states the disagreement and takes
  no side.
- **Two roster entries carry the same name.** Ambiguity is a refusal, not a
  first-wins pick.
- **The extracted name is garbled or absent**, so nothing matches — the PDF is
  reported and skipped rather than filed under whatever was read.
- **No level recoverable.** The sheet being displaced records no level (some
  existing sheets carry no machine-readable summary at all). Archival cannot pick
  a folder; the conversion refuses rather than filing under a placeholder.
- **Multiclass level.** A displaced sheet recording `Fighter 9 / Bard 2` has no
  single level number. The archive folder cannot be chosen without a rule.
- **Archive slot already occupied.** A second conversion at the same level would
  overwrite an already-archived sheet — the one thing this feature exists to
  prevent.
- **Case-only rename.** The live file is `soma.md` and the roster name yields
  `Soma.md`. On a case-insensitive filesystem these are the same file.
- **Roster reference goes stale.** The roster points at `docs/party/soma.md`; the
  new name is `Soma.md`. Renaming without updating the reference breaks the roster
  for every downstream reader.
- **Conversion fails after the archive move.** The old sheet has already been
  moved and the new one was never written, leaving the roster's path empty.
- **No roster at all**, or a roster file that is a name-exclusion list rather than
  a character roster (one campaign's is exactly that).
- **Explicit output path given.** The GM names an output file or directory
  directly, which contradicts roster-derived naming.
- **Archived sheets picked up by readers.** Files under the archive folder sit
  inside the same directory tree as live sheets and could be read as current by
  anything that scans the directory rather than following roster references.
- **The UI's output-location field is filled.** Under FR-017 that suppresses roster
  naming and archival — so the page must not send one by default, or the feature is
  unreachable from the surface that appears to offer it.
- **A roster saved through the UI round-trips.** The roster's savers hand-build
  their output, so a newly added field is dropped unless it is named on the write
  path as well as the read path — a save that appears to succeed while persisting
  nothing.

## Requirements *(mandatory)*

### Functional Requirements

**Attribution**

- **FR-001**: The conversion MUST attribute each source PDF to exactly one entry
  in the campaign roster before writing anything.
- **FR-002**: Attribution MUST be by the character name read out of the converted
  sheet, matched against the roster's character names, case-insensitively and
  ignoring surrounding whitespace.
- **FR-002a**: The match MUST be exact. The conversion MUST NOT attempt any
  relaxed, fuzzy, prefix, token, or similarity-based fallback, and MUST NOT rank
  candidates. A name that does not match a roster entry exactly is a failure, not a
  weaker match — the roster is a hand-authored file the GM can fix in seconds, and a
  near-miss that silently resolves is how the wrong file gets moved.
- **FR-002b**: For every PDF it writes, the conversion MUST report which roster
  entry it was attributed to, so a wrong attribution is visible in the run output
  before the GM relies on the file.
- **FR-003**: When attribution is ambiguous or finds no entry, the conversion MUST
  fail loudly for that PDF: report the file, the name read out of it, and the roster
  names that were available to match against, then skip it leaving every existing
  file untouched. It MUST NOT fall back to a name taken from the PDF.
- **FR-003a**: The failure MUST say what to do about it — that the roster and the
  sheet disagree and the roster is the file to correct — because fixing the roster
  by hand IS the intended resolution path, not a workaround. This is the live
  Phandalin case: the roster says `Valphine`, her sheet titles itself
  `Valphine Sotorra`, and the conversion refuses until the GM settles which is
  canonical.
- **FR-004**: When several PDFs are converted in one invocation, a failure to
  attribute one MUST NOT prevent the others from being converted, and the exit
  status MUST indicate that at least one was skipped.

**Naming**

- **FR-005**: The output sheet's filename MUST be derived from the roster's name
  for the attributed character, and from no other source.
- **FR-006**: When the roster already declares a file location for that character,
  the conversion MUST NOT leave that declaration pointing at a file that no longer
  exists.
- **FR-007**: Renaming MUST be safe when the old and new names differ only by
  letter case.

**Player identity**

- **FR-008**: The roster MUST be able to record a player name per character, and
  the converted sheet MUST record that value, replacing whatever the downloaded
  sheet carried. This makes the roster — not the download — the authority for who
  plays a character, reversing the prior ruling in
  `docs/design/PartyRosterCanonicalFormat.md` ("the D&D Beyond sheet is canonical,
  `party.yaml` just points at it") for this one field. The reversal is not a
  preference: the export stamps the *downloader's* name into every sheet's player
  field, so the downloaded value is wrong for every character in the party, every
  time. The download is not a degraded source for this field; it is not a source for
  it at all. That design document MUST be amended to record the change rather than
  left contradicting the shipped behaviour.
- **FR-008a**: A roster that records no player for any character MUST remain valid
  — the field is additive, and every existing roster MUST keep loading unchanged.
- **FR-009**: When the roster records no player for a character, the converted sheet
  MUST record no player, and the run MUST report which characters lack one. The
  downloaded value MUST NOT be carried forward as a fallback — under FR-008 it is
  known to name the downloader, so propagating it would assert something false
  rather than leave a gap the GM can see and fill.
- **FR-010**: Values the roster supplies MUST be written by the conversion itself,
  not requested from the model that reads the PDF.
- **FR-010a**: The converted sheet states the player in two places — a
  machine-readable summary and a human-readable identity block. Both MUST carry the
  roster's value. Replacing only one leaves the document self-contradictory, with
  the downloader's name still legible to any reader while tooling reports the real
  player.

**Archival**

- **FR-011**: When a sheet already exists at the destination, the conversion MUST
  move it into an archive folder beneath the destination's own directory before
  writing the new sheet, creating any missing folders.
- **FR-012**: The archive folder MUST be keyed by the level recorded in the sheet
  being displaced — not the level of the incoming sheet — so the archive reads as
  "the sheet as it was at level N". The layout MUST be `old/level/<N>/` relative to
  the sheet's own directory, matching the archive the GM has already built by hand
  (`Phandalin/docs/party/old/level/5/`), so existing archives stay continuous and
  no campaign ends up with two archive layouts side by side.
- **FR-013**: The level MUST be read from the displaced sheet's own recorded class
  and level. When no level can be read, or the sheet records more than one class
  and level, the conversion MUST refuse that PDF with a message naming the file
  and the value it could not interpret, and MUST NOT move or overwrite anything.
- **FR-014**: The conversion MUST refuse rather than overwrite when the archive
  destination is already occupied.
- **FR-015**: A conversion that fails after the archive move MUST leave the
  character with a readable sheet at the roster's path — either by restoring the
  displaced sheet or by not moving it until the new content is in hand.
- **FR-016**: Archival MUST be reported: which file moved, where to, and what the
  new sheet's path is.

**Scope guards**

- **FR-017**: An explicitly supplied output path MUST take precedence over
  roster-derived naming, and when it does, the conversion MUST say that
  roster-derived naming and archival were skipped.
- **FR-018**: When no roster is available, the conversion MUST behave as it does
  today — write a sheet named from the source PDF — and say that roster naming and
  archival were not applied.

**UI surface**

- **FR-019**: The capability MUST be operable end to end from the existing D&D
  Sheet page — attribute, name, archive, and report — with no terminal step.
- **FR-020**: The UI MUST NOT reimplement attribution, name derivation, level
  reading, or archival. It MUST invoke the same command-line engine and forward
  options only, so a fix to the engine is a fix in both places.
- **FR-021**: The operator MUST be able to choose roster-driven naming explicitly
  on the page, and the page MUST NOT send an output location that silently
  suppresses it under FR-017.
- **FR-022**: The run output shown in the UI MUST carry, per PDF, the same facts
  the CLI reports — matched roster entry and match kind, archive move, final sheet
  path, and any skip with its reason — not a summarised version.
- **FR-023**: The party roster editor in the UI MUST read and write the player
  field, and a roster saved through the UI MUST NOT drop it.
- **FR-024**: Every UI action in this feature MUST have an equivalent command-line
  invocation producing the same files, and files MUST be the only interchange
  between the two surfaces — no pipeline state that exists solely in the browser.
- **FR-025**: A refusal (no roster, unattributable PDF, unreadable or multiclass
  level, occupied archive slot) MUST surface in the UI with its reason, not as a
  generic failure.

### Key Entities

- **Party roster**: the GM-maintained, hand-authored list of the campaign's
  characters. Names each character, where their sheet lives, and — new in this
  feature — who plays them. The authority for both the character name and the
  player name.
- **Character sheet document**: the converted markdown sheet. Carries the character
  name, the player, and the class-and-level phrase the archive is keyed by, each
  stated twice — once machine-readable, once human-readable. Some existing sheets
  carry only the human-readable form. Authoritative for everything about the
  character *except* the player, which comes from the roster.
- **Archive location**: a folder beneath the sheet directory holding superseded
  sheets, partitioned by the level each recorded. Not a live sheet location.
- **Character level**: the numeric level recorded on a sheet, used solely to name
  the archive partition. Multiclass sheets do not have one.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After any conversion run, 100% of the campaign roster's file
  references resolve to an existing file.
- **SC-002**: No previously converted sheet is ever lost — after re-converting a
  character at N levels, all N previous versions are retrievable, 100% of the time.
- **SC-003**: A GM re-converts a levelled-up party in one command with zero manual
  renames, folder creations, or file moves, down from three manual steps per
  character today.
- **SC-004**: A re-conversion never silently changes who a character's player is:
  the recorded player matches the roster in 100% of conversions where the roster
  states one, and the downloader's name appears on zero converted sheets.
- **SC-004a**: The GM stops re-applying player corrections by hand — currently once
  per character per level-up, target zero.
- **SC-005**: Zero sheets are filed under a guessed name — every PDF that cannot be
  attributed to exactly one roster entry is reported and skipped.
- **SC-006**: Every archival move is reported in the run's output, so a GM
  reviewing the run afterwards can account for every file that moved without
  inspecting the filesystem.
- **SC-007**: A GM completes a full level-up re-conversion for an entire party from
  the web UI alone, with zero terminal commands.
- **SC-008**: Zero information is lost between surfaces — every fact the
  command-line run reports about a conversion is visible in the UI's run output.

## Assumptions

- **Archived filenames follow the same naming rule as live ones** — a displaced
  sheet is archived under the roster-derived character name, matching the GM's
  existing hand-built archive, so the archive is uniform even when the live file
  it displaced was named differently.
- **The archive is keyed by the displaced sheet's level, not by a run counter or
  date.** This matches the request and the existing on-disk archive.
- **Attribution keys on a model-extracted value, by GM ruling.** The character name
  used to pick a roster entry is read out of the converted sheet, so an extraction
  error can mis-attribute a file move. Three things bound that risk and none of them
  is a threshold: the roster is a closed, hand-authored set of candidates, so a wrong
  name matches nothing rather than matching the wrong character; anything short of
  exactly one exact match refuses (FR-002a, FR-003); and every match is named in the
  run output (FR-002b). The alternative — an explicit `--character` per PDF — was
  considered and not chosen.
- **There is no fuzzy matching anywhere in this feature.** A disagreement between
  the sheet and the roster is surfaced for the GM to fix in the roster, by hand,
  before the run succeeds. This is a deliberate trade of convenience for
  correctness: the roster is a small hand-authored file, an edit costs seconds, and
  a silently-resolved near-miss moves a file the GM never approved moving. It also
  keeps this feature clear of the project's recorded finding that a similarity band
  tells you an edit happened and never that the result is safe.
- **The archive folder is not a sheet location.** Nothing that reads current
  character state is expected to read from it; readers reach sheets through roster
  references, not by scanning the directory.
- **Conversion of a character absent from the roster remains possible** via the
  explicit-output-path route, so this feature does not make the roster a
  precondition for using the converter at all.
- **Only the party roster is written to, if anything is** — this feature does not
  touch the entity registry, dossiers, or any generated grounding document.
- **A single GM runs this on one campaign at a time**; concurrent conversions of
  the same character are not a case that needs handling.
- **The UI surface is an extension of the page that already exists**, not a new
  one. No second implementation of the conversion is introduced anywhere.
- **Source PDFs stay addressed by a path the server can read.** Uploading a PDF
  through the browser is out of scope — the server and the GM's downloads share a
  filesystem in this single-user deployment. Worth revisiting only if that stops
  being true, in which case the UI is reachable but not self-sufficient.
