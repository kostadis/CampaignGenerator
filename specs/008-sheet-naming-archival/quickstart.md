# Quickstart: validating Roster-Named Sheets & Level Archival

Runnable checks that prove the feature works end to end. Scenarios map to the spec's
success criteria; details live in [contracts/](./contracts/) and
[data-model.md](./data-model.md).

---

## 0. Prerequisites — do this first, it is not optional

**Confirm you are testing this worktree, not the main checkout.** The editable install's
`.pth` hardcodes `/home/kroussos/src/CampaignGenerator`, so `import campaignlib` inside a
worktree can silently resolve to main's copy — a green run proves nothing (D12).

```bash
cd /home/kroussos/src/CampaignGenerator/.claude/worktrees/feat-dnd-sheet-party-names
python -c "import campaignlib, sys; print(campaignlib.__file__)"
# MUST print a path under .claude/worktrees/feat-dnd-sheet-party-names/
```

**That check is necessary but not sufficient, and the original workaround here was
wrong.** It passes because an interactive `python` puts the cwd on `sys.path`; the venv's
`pytest` entry point does not, and it does not honour `PYTHONPATH` either — under pytest
only `tests/` is on the path, so the `.pth` wins. `tests/benchmarks/` is collected first,
imports `campaignlib` without a repo-root insert, and every module collected after it then
gets main's copy from `sys.modules`. A whole-suite run reported **3178 green against code
this branch never touched**.

`tests/conftest.py` now inserts the repo root once, before any test module is imported, so
`python -m pytest tests/` is correct from the worktree with no extra environment. To prove
it rather than trust it:

```bash
python -m pytest tests/ -q      # collection must not error on campaignlib.sheet_naming
```

For the UI scenarios only, install into the server's venv (no restart needed):

```bash
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
```

---

## 1. Unit suites (no API key, no campaign, seconds)

```bash
python -m pytest tests/test_sheet_naming.py tests/test_party_config.py \
                 tests/test_sheet_frontmatter.py tests/test_dnd_sheet.py -q
```

Must cover, at minimum:

| Behaviour | Expected |
|---|---|
| exact match, differing case/whitespace | resolves to the roster entry |
| name absent from roster | raises, message lists the available roster names |
| two entries share a name | raises as ambiguous, never first-wins |
| `"Monk 8"` / `"Druid 5"` | level `8` / `5` |
| `"Fighter 9 / Bard 2"` | level `11` — the sum, per D4's revision |
| `"Fighter 9 / Bard"` | `AmbiguousLevelError`, naming the segment that lost it |
| sheet with no frontmatter | level still read from `## Identity` |
| sheet with neither | `AmbiguousLevelError` |
| archive path | `<dir>/old/level/<N>/<char-name>.md` |
| archive slot occupied | refuses, original untouched |
| declared `sheet_name` | the sheet's spelling attributes to the roster entry |
| declared `sheet_name` | `name`, not the declaration, still names the output file |
| blank `sheet_name` in YAML | `load_party_config` refuses, naming the character |
| `sheet_name: ""` over the API | absent, not invalid — the editor sends every field it renders |
| `sheet_name` save → load round-trip | value survives (guards the hand-built saver, D9) |

**Guard suites must stay green:**

```bash
python -m pytest tests/test_layering.py tests/test_retrieve_render_isolation.py -q
```

---

## 2. First run against Phandalin — expect two refusals, in order

This campaign is the live proof. Both refusals are by design; each is a one-line fix.

```bash
cd ~/src/campaigns/Phandalin      # the repo. NOT ~/campaigns, which is a stale copy
dnd_sheet ~/Downloads/Soma.pdf --party-config config/party.yaml
```

**Refusal A — filename mismatch (FR-006, D6).** The roster says
`sheet: docs/party/soma.md`; the conversion would write `Soma.md`. The message prints
the exact replacement line. Apply it to three of the four entries (`soma.md` → `Soma.md`,
`brewbarry.md` → `Brewbarry.md`, `valphine.md` → `Valphine.md`; `Vukradin.md` already
agrees).

**Rename the files too** — `git mv docs/party/soma.md docs/party/Soma.md`, and the same
for the other two. Editing only the roster line leaves the old file on disk where the
archival step will never see it: the first conversion then finds nothing to displace,
archives nothing, and leaves `soma.md` orphaned beside the new `Soma.md`. This is the one
case where the feature's entire purpose is skipped without an error, so verify it:

```bash
ls docs/party/          # exactly four .md files, all roster-shaped, before re-running
```

**Refusal B — name mismatch (FR-003a).** Only for Valphine: her sheet titles itself
`Valphine Sotorra`, the roster says `Valphine`. Settle which is canonical and edit one
side. **Prefer editing the sheet's `# ` heading**: `characters[].name` is also the
campaign's canonical PC name, consumed by `load_pc_names`, `roster_from_config` and the
output filename, so widening the roster widens it everywhere.

Verify after each fix that nothing moved:

```bash
git -C ~/campaigns status --short   # expect no changes under docs/party/ from a refusal
```

---

## 3. The level-up round trip (SC-001, SC-002, SC-003)

With the roster corrected and a `player` recorded for each character:

```bash
cd ~/campaigns/Phandalin
dnd_sheet ~/Downloads/Soma.pdf --party-config config/party.yaml
```

Expect on stderr: `Matched roster entry: Soma`, an `Archived: … (level 6)` line, a
`Player: … (from party.yaml)` line, and `Saved to: docs/party/Soma.md`.

```bash
# SC-002 — the displaced sheet is retrievable, alongside the GM's hand-filed level 5
ls docs/party/old/level/*/Soma.md

# SC-001 — every roster reference still resolves
python -c "
from pathlib import Path
from campaignlib.party_config import load_party_config, missing_files
cfg = load_party_config(Path('config/party.yaml'))
print(missing_files(cfg, Path('.')) or 'all roster references resolve')"

# SC-004 — the downloader's name appears nowhere
grep -n 'Player' docs/party/Soma.md   # both lines show the roster's value
```

**Re-run the same PDF immediately.** It must refuse on the occupied archive slot
(FR-014) rather than overwrite the sheet you just archived.

---

## 3b. A sheet whose printed name is wrong (FR-002c)

The live case: a player typed `Akrita` into D&D Beyond for a character the campaign
has always called Akritas, and the download cannot be corrected.

```bash
# 1. The first run refuses, and the refusal itself names the three fixes.
dnd_sheet ~/Downloads/Akrita-1120044.pdf --party-config config/party.yaml
#    -> REFUSED …: the name on this sheet is not in the roster.
#       Sheet says:      "Akrita"

# 2. Only because fixes 1 and 2 are unavailable, declare the spelling:
#       - name: Akritas
#         sheet: docs/party/Akritas.md
#         sheet_name: Akrita

# 3. Re-run. It resolves, and the roster's own name is what lands on disk.
dnd_sheet ~/Downloads/Akrita-1120044.pdf --party-config config/party.yaml
```

Confirm all three, because the containment is the point of the feature:

- the run reports the matched entry as **Akritas**, not Akrita
- the file written is `docs/party/Akritas.md` — the declaration reaches attribution
  and nothing else
- any sheet it displaces archives under `Akritas.md` too
- a later refusal listing the roster shows `Akritas (sheet: Akrita)`, so the GM is
  never told the roster lacks a name the declaration made present

---

## 4. Refusal matrix (SC-005)

Each leaves the tree untouched and exits `1`. Confirm with `git status` after every one.

| Scenario | How to induce it |
|---|---|
| name not in roster | convert a PDF for a character with no roster entry |
| ambiguous name | temporarily duplicate a `name` in `party.yaml` |
| filename mismatch | revert one `sheet:` to its lowercase form |
| a class with no level | point the destination at a sheet reading `Fighter 9 / Bard` (a complete `Fighter 9 / Bard 2` archives at level 11 instead) |
| no level at all | strip the `**Class & Level:**` line from the destination sheet |
| occupied archive slot | run the same conversion twice |

---

## 5. Legacy modes are untouched (FR-017, FR-018)

```bash
dnd_sheet ~/Downloads/Soma.pdf --output /tmp/soma.md \
          --party-config config/party.yaml   # notice: roster naming/archival skipped

dnd_sheet ~/Downloads/Soma.pdf --output-dir /tmp/out   # legacy: <pdf-stem>.md + notice

dnd_sheet ~/Downloads/Soma.pdf                          # legacy, defaults to doc/
```

The third case guards the `--output-dir` default flip (D11): with no flags at all the tool
must still write into `doc/` exactly as before.

---

## 6. UI parity (SC-007, SC-008)

Start the app (`./startup`), then:

1. **Party page** — set a `player` for each character. Reload the page: the values persist.
   Then confirm on disk that `config/party.yaml` actually gained them — a `200` from the
   API is not proof (D9).
2. **Setup → D&D Sheet** — leave both output fields blank, fill the party-config path,
   run a conversion. The page's mode notice should say roster mode is active.
3. Confirm the streamed output contains the same `Matched roster entry` / `Archived` /
   `Player` / `Saved to` lines the CLI printed — no summarisation (SC-008).
4. Induce a refusal (point at a PDF with no roster entry). The page must show the CLI's
   refusal text and its reason, not a generic failure (FR-025).
5. **Parity** — run the equivalent CLI command for step 2 and confirm it produces the same
   files (FR-024).

If step 2 fails with `Stream error — check terminal.`, the console scripts are missing
from the server's venv — see Prerequisites.

---

## Definition of done

- [ ] Unit suites above pass, **verified importing from the worktree**
- [ ] `test_layering.py` and `test_retrieve_render_isolation.py` green
- [ ] Phandalin's two first-run refusals reproduce, then clear after the documented edits
- [ ] A level-up round trip archives, writes, and leaves every roster reference resolving
- [ ] Re-running the same conversion refuses instead of overwriting the archive
- [ ] All six refusals leave `git status` clean under `docs/party/`
- [ ] All three legacy invocations behave exactly as before
- [ ] The full flow completes from the UI with no terminal commands
- [ ] `docs/design/PartyRosterCanonicalFormat.md` amended for the FR-008 reversal
