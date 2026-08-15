# Phase 0 Research: Roster-Named Sheets & Level Archival

Codebase survey behind [plan.md](./plan.md). Every decision below is grounded in a file
that exists today. Extend this rather than re-deriving it.

---

## D1 — Where the roster comes from: an explicit `--party-config`, no auto-discovery

**Decision**: `dnd_sheet` gains `--party-config PATH` and loads it with the existing
`campaignlib.party_config.load_party_config_arg(path_str, base)`. Roster mode is ON when
that flag is given, OFF when it is not. No probing of `config/party.yaml` from the cwd.

**Rationale**: `load_party_config_arg` is the established shape for exactly this flag —
`sd_narrate`, `polish`, `scene_extract` and `enhance_summary` all take `--party-config`
and call it. Its docstring records that `base` defaults to the cwd and that #291 rewrote
all three divergent campaigns' rosters campaign-root-relative so that default is now
correct everywhere. Auto-discovery would also collide with Constitution X: turning roster
mode on implicitly is the system manufacturing an explicit act on the GM's behalf.

**Alternatives considered**: auto-discover via `campaignlib.constants.config_path(cwd,
"party.yaml")` — rejected on Principle X, and because obelisk's `config/party.yaml` is a
PC-name *exclusion list*, not a roster (recorded in `PartyRosterCanonicalFormat.md`), so
discovery would silently arm the feature against a file that means something else.

---

## D2 — Attribution is an exact, case-insensitive, whitespace-trimmed match. Nothing else.

**Decision**: `attribute(name, roster)` lowercases and strips both sides and requires
exactly one hit. Zero hits or more than one hit both raise, carrying the extracted name
and the full list of roster names. No prefix, token, edit-distance or embedding fallback
exists in the module at all.

**Rationale**: GM ruling, 2026-08-13 — "let's just have it fail loudly, and then I will
go and fix the yaml." It also keeps the feature clear of the project's own recorded
finding that a similarity band tells you an edit happened and never that the result is
safe. Case-insensitivity is not fuzziness: `sheet_frontmatter.propose` already keys its
party cross-check on `name.lower()`, and stripping is required because `zalthir.md:5` has
a documented trailing space.

**Live consequence to expect**: Phandalin refuses on first run. Its roster says
`Valphine`; `docs/party/valphine.md` titles itself `Valphine Sotorra`. This is by design
— the GM settles which is canonical and edits the roster (or the sheet), and the run then
succeeds. Note which way to fix it: `characters[].name` is also the campaign's canonical
PC name, consumed by `load_pc_names` (PC exclusion), `roster_from_config` (prompt text)
and the output filename, so widening it to `Valphine Sotorra` widens it everywhere.

---

## D3 — The Identity parser moves to `campaignlib/sheet_identity.py`

**Decision**: `SheetParseError`, `_find_identity_block`, `parse_identity_fields` and
`sheet_name` move from `pipelines/content_ingest/sheet_frontmatter.py` into a new
`campaignlib/sheet_identity.py`. `sheet_frontmatter.py` imports them from there and keeps
its public behaviour byte-identical.

**Rationale**: the archival step must read the level off the sheet it is displacing, and
those sheets frequently have **no frontmatter** — verified: all four Phandalin sheets
(`brewbarry.md`, `valphine.md`, `Vukradin.md`, `soma.md`) start at `# Name` with no `---`
block, as do the archived `old/level/5/*.md`. So the `## Identity` block is the only
universally available source and its parser must be reachable from the new code.
`campaignlib` cannot import `pipelines` (`tests/test_layering.py` enforces the arrow),
so the parser moves down rather than being duplicated — Principle V, and the same move
`server/party_config_shared.py` → `campaignlib/party_config.py` already made.

**Alternatives considered**: duplicate the regexes in the new module (two parsers that
drift — the exact defect the layering test was written for); or require frontmatter and
refuse without it (would refuse on every campaign's current sheets).

---

## D4 — Level: frontmatter first, Identity block second, refuse on multiclass

**Decision**: `read_class_level(text)` returns the `class_level` frontmatter value when
present, else the `## Identity` `**Class & Level:**` value, else `None`.
`parse_level(phrase)` accepts a single trailing integer (`"Monk 8"` → `8`) and raises
`AmbiguousLevelError` on anything else — no value, no integer, or more than one
class-and-level segment.

**Rationale**: verified against real data — `old/level/5/Soma.md` records
`- **Class & Level:** Druid 5` and the live `soma.md` records `Druid 6`, which is exactly
the archive key the GM chose by hand. Frontmatter is preferred when present because #293
landed it on 19 sheets and it is the machine channel. Multiclass is a refusal, not a sum
or a first-wins: `Human Fighter 9 / Bard 2` is a real Hillsfar value recorded in
`PartyRosterCanonicalFormat.md`, and picking 11, 9 or 2 from it is inventing precision the
source lacks — the same reason `class_level` was deliberately kept as one undecomposed
string.

**Alternatives considered**: `old/level/unknown/` for unparseable levels — rejected, it
turns a refusal into a bucket that silently accumulates and collides.

---

## D5 — Archive layout `old/level/<N>/<char-name>.md`, refuse when occupied

**Decision**: the archive directory is `<sheet-dir>/old/level/<N>/`, created with parents.
The archived filename is the roster-derived `<char-name>.md`, not the displaced file's own
name. If that path already exists, refuse — never overwrite, never suffix.

**Rationale**: matches the GM's existing hand-built archive exactly
(`Phandalin/docs/party/old/level/5/{Soma,Brewbarry,Valphine,Vukradin}.md` — note the
capitalised, roster-shaped filenames against the lowercase live ones), so nothing has to
be migrated and the two conventions never coexist. Overwriting an archived sheet is the
single thing this feature exists to prevent, so it cannot be the failure mode of a
re-run.

**Alternatives considered**: `old/<N>/` (the literal request) — rejected by GM ruling in
favour of the on-disk precedent. Timestamp or run-counter partitions — rejected, the level
is what makes the archive meaningful to a reader.

---

## D6 — Destination is the roster's declared sheet directory; a basename mismatch refuses

**Decision**: the output path is `<declared sheet path>.parent / f"{char-name}.md"`. When
that differs from the declared `sheet:` basename, the conversion **refuses** and prints
the exact one-line roster edit needed. `dnd_sheet` never writes to `party.yaml`.

**Rationale**: FR-006 requires the roster's pointer to stay valid, and there are only two
ways to guarantee it — edit the roster automatically, or refuse until it agrees. The
roster is a hand-authored file (`docs/config/grounding-isolation.md` built the whole
authored-vs-resolved split to stop a load/save round-trip rewriting what the GM typed),
and the GM's stated preference on the sibling question was explicitly "fail loudly, and
then I will go and fix the yaml". Refusing is also the cheaper failure: a wrong automatic
edit is silent, a refusal is a one-line fix.

**Live consequence**: a one-time roster edit per campaign — Phandalin's
`sheet: docs/party/soma.md` becomes `docs/party/Soma.md`, and so on for three of its
four entries. The refusal message prints the replacement line verbatim.

**And the file must be renamed alongside it.** Fixing only the roster line leaves
`docs/party/soma.md` on disk while the conversion writes `Soma.md`: the archival step
sees nothing at the destination, archives nothing, and the level-N sheet is orphaned
beside the new one rather than filed. The refusal message therefore prints the `git mv`
too. This is the one migration case where the feature's whole purpose can be skipped
silently, so it is stated at the point of failure, not just here.

**Path convention, verified 2026-08-14**: all five rosters under `~/src/campaigns` are
campaign-root-relative (`docs/party/…`), as D1 says. A stale second copy of the campaigns
tree exists at `~/campaigns` whose Phandalin roster is still config-relative
(`../docs/party/…`) — it is not the repo (`/home/kroussos/src/CLAUDE.md` and
`tests/conftest.py` both point at `~/src/campaigns`) and must not be used to check this.

**Alternatives considered**: auto-update `party.yaml` via the existing atomic
`save_party_config` — viable and rejected for the reason above; worth revisiting only if
the one-time edit proves annoying across campaigns. A `--fix-roster` opt-in flag — rejected
as scope creep for a once-per-campaign action.

---

## D7 — Order of operations makes crash-safety free

**Decision**: load roster → extract text → **call the API** → attribute → resolve
destination → read displaced level → check archive slot → move → substitute player →
write.

**Rationale**: FR-015 wants "never leave the character sheet-less". Putting the single
fallible, slow, non-idempotent step (the API call) *before* the first filesystem mutation
satisfies it without a rollback path, a temp file, or a lock. Every refusal after the call
still leaves the tree untouched. The cost is a spent API call on an attribution failure —
tokens, not damage, and the run says so.

**Alternatives considered**: archive first then convert (a failed call leaves an empty
slot); write new then archive old (they collide on the same path).

---

## D8 — The player is substituted deterministically, in both places, after generation

**Decision**: `apply_roster_player(markdown, player)` rewrites the frontmatter `player:`
value **and** the `- **Player:**` line of the `## Identity` block. `SYSTEM_PROMPT` is not
changed and the model is still asked for both fields.

**Rationale**: FR-010a — the sheet states the player twice, and replacing one leaves the
downloader's name legible in the document while tooling reports someone else. The prompt
is left alone deliberately: the model's output is the *shape* the substitution keys on
(`FRONTMATTER_KEYS` order, the `- **Player:**` line the Identity template specifies), and
`PartyRosterCanonicalFormat.md` records that dropping a frontmatter key breaks the
downstream parser, which expects all five every time.

**Constraint worth carrying into the roster's content**: `player` must hold the **Zoom
display name**, not a legal name. `campaignlib/npc.py::normalize_vtt_speakers` matches
speaker prefixes exactly, and `PartyRosterCanonicalFormat.md` (#293) records the GM ruling
that the sheet's `player` carries the Zoom display name precisely because "a near-miss
silently drops that PC's lines". Putting `Wade Brown` in the roster where Zoom shows
`Wade` would break speaker attribution downstream. This belongs in the field's help text
in both the CLI docs and `PartyConfigEditor.vue`.

---

## D9 — `PartyCharacter.player` must be named in the loader AND the saver

**Decision**: add `player: AuthoredPath`-style optional string to `PartyCharacter` and
`ResolvedCharacter`, then explicitly add it to `load_party_config`'s hand-built
`PartyCharacter(...)` construction, `save_party_config`'s hand-built `entry` dict, and
`resolve_party_config`'s `ResolvedCharacter(...)` construction.

**Rationale**: `campaignlib/party_config.py` documents this trap in its own source —
"these savers hand-build the YAML dict rather than dumping the model, so a new field is
silently dropped unless added here — which is exactly what happened when feature 003 first
added it, and the write appeared to succeed while persisting nothing." Three construction
sites, all hand-built, all must name it. A round-trip test is the guard.

`model_config = ConfigDict(extra="forbid")` means the field must exist on the model before
any campaign puts it in YAML, so this lands before the roster edits do. The field is
additive and optional, so every existing roster keeps loading unchanged (FR-008a).

---

## D10 — `player_map_from_config` is deliberately NOT changed

**Decision**: out of scope. `campaignlib/npc.py::player_map_from_config` keeps reading
`player` from each character's **sheet frontmatter**.

**Rationale**: after a conversion the sheet carries the roster's value, so the two agree
and one source propagates. Repointing it at the roster would change speaker attribution
for five campaigns in the same change that introduces the field, and its all-or-nothing
contract plus the placeholder rule (`is_player_placeholder`) are load-bearing.

**Known residual divergence, recorded not fixed**: a GM who sets `player` in the roster and
does *not* re-convert leaves the sheet stating the old value, and downstream speaker
attribution keeps using the sheet. There is no detector for that today. If it bites,
the cheap fix is a report — extend `sheet_frontmatter --party`-style conflict output to
cross-check the roster — not a silent precedence rule.

---

## D11 — The UI needs a mode notice, not new logic

**Decision**: `server/routers/setup.py::run_dnd_sheet` gains a `party_config: str = ""`
query parameter forwarded as `--party-config`. `--output-dir` is forwarded only when the
caller actually set it, so `dnd_sheet` can distinguish "unset" from "explicitly `doc`" —
which requires flipping the CLI's `--output-dir` default from `"doc"` to `None` and
falling back to `doc` only outside roster mode. `DndSheet.vue` gains a party-config
`PathField` and a notice stating which mode the current inputs select.

**Rationale**: Constitution VI — the router forwards flags and never reimplements. The
CLI's current `--output-dir` default of `"doc"` is the specific thing that would make the
feature unreachable from the UI: under FR-017 an explicit output location suppresses
roster naming, and today the router always effectively supplies one. `RunPanel` already
streams the CLI's stderr verbatim, so FR-022 and FR-025 need no new plumbing — the CLI's
messages are what the page shows.

**Verified surface**: `frontend/src/views/setup/DndSheet.vue` already posts to
`/api/setup/run/dnd-sheet` via `RunPanel`; `frontend/src/components/shared/PartyConfigEditor.vue`
holds the roster table with a `PartyChar` interface (`name`, `sheet`, `backstory`,
`dossier`, `arc_score`) that needs `player` added in four places: the interface, the
blank-row factory, the load mapping, and a column in the template.

---

## D12 — Testing in this worktree can lie to you

**Decision**: every validation run must first assert that `campaignlib` resolves inside
the worktree.

**Rationale**: the editable install's `.pth` hardcodes `/home/kroussos/src/CampaignGenerator`,
so `import campaignlib` inside a worktree can resolve to the **main checkout's** copy. A
green test run in the worktree is not proof the branch was tested. `quickstart.md` opens
with the one-line check. Related: the web UI resolves pipelines through
`console_script(name)` against the server's venv, so a CLI signature change is not visible
to the UI until `uv pip install -e .` is run into that venv — no server restart needed,
since `console_script()` resolves per request.

---

## Resolved unknowns

No `NEEDS CLARIFICATION` markers remain in the Technical Context. The three spec-level
questions were settled by GM ruling on 2026-08-13 and are recorded in `spec.md`; the
design-level questions they left open (D3 parser location, D6 mismatch handling, D7
ordering, D10 scope boundary) are decided above.
