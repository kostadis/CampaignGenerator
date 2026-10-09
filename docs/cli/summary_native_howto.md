# Summary-native grounding docs — how to actually use it

> Task-oriented walkthrough for the GM. **Start here for summary-native
> grounding docs.** What to run, in what order, what every finding means, and
> what every refusal says. The *design* lives in
> [`specs/031-summary-native-grounding/`](../../specs/031-summary-native-grounding/)
> (`spec.md`, `research.md` R2 and R7, `contracts/cli.md`, `contracts/http.md`);
> this page is the operator's manual and documents what the code does.

## The things that confuse everyone first

**1. This is a fourth rendering path, not a replacement for the other three.**
All four produce a draft of `world_state`, `campaign_state`, `party` or
`planning`. They differ in what the model is asked to read:

| Path | The model reads | Where it lives |
|---|---|---|
| per-tool (`distill`, `campaign_state`, `party`, `planning`) | chunks of summaries, extracting then synthesising | [Grounding documents](grounding_docs.md) |
| dossier synthesis (ensemble) | atomic facts a local-LLM ensemble extracted from chapter prose | [Ensemble workflow](ensemble_workflow.md) |
| state projection | stores built by `event_spine` / `thread_registry`, rendered section by section | [State Projection how-to](state_projection_howto.md) |
| **summary-native** | **your reviewed structured summaries, parsed with no model** | this page |

The summary-native path reads structure your summaries already declare (scenes,
entity sections, memorable moments). A deterministic parser writes an ordered
evidence corpus; `extract` then has a model read it a chunk at a time, **code**
keeps only the notes whose citations resolve and whose quotations are verbatim,
and `synth` writes each section of each document from only the checked notes
that code routed to it. Scope, order and attribution are code's decisions
(Steps 5b and 6).

**2. It never creates or edits a summary.** How summaries get written is out
of scope; the pipeline starts from a directory of summaries that already exist
and tells you what is wrong with them. Every fix is yours, in the summary
files.

**3. Everything up to `synth` calls no model and costs nothing.** `validate`,
`build` and `compare` are deterministic. `synth --dump-only` also makes no
model call. Only a plain `synth <doc>` spends tokens.

**4. It never writes a live document.** Drafts land under
`docs/summary_native/ch<since>-<until>/drafts/`. You review one and copy it
over `docs/<doc>.md` yourself. See [Review and promote](#step-8--review-and-promote-by-hand).

**5. Duplicates are fixed in the summaries, not mapped.** If the tool lists
`Hand Crossbow` and `Hand Crossbows` as a possible duplicate, you correct the
summary file. There is no alias file, and nothing merges two headings on a
similarity score. See [Possible duplicates](#step-4--possible-duplicates-fix-the-summaries).

---

## Step 0 — one-time setup

`summary_native` is a `[project.scripts]` console script. The web UI resolves
it through `console_script()` against the **server's venv**, not `$PATH`, so
it must be installed there:

```bash
uv pip install -e . --python ~/.venvs/main/bin/python
ls ~/.venvs/main/bin/summary_native
```

Symptom when skipped: the page's Validate/Build/Synthesize buttons fail with
`Stream error — check terminal.` No server restart is needed after installing.

Run every command **from the campaign root** (the directory containing
`config/config.yaml`). There is no fallback config: a missing
`<cwd>/config/config.yaml` is an error.

Point it at your summaries either per run (`--summaries-dir docs/summaries`)
or once in `config/grounding.yaml`:

```yaml
summary_native:
  summaries_dir: docs/summaries
  out_root: docs/summary_native      # default
  canon_file: null                   # default: <out_root>/canon.yaml
  registry: null                     # default: auto-discover docs/entity_registry.yaml; a file or a campaign dir
  range_since: null                  # the UI reads these; the CLI does not
  range_until: null
  recent_chapters: 4                 # default
  recurring_min: 10                  # default
  dup_threshold: 0.88                # default
```

The CLI reads `summaries_dir`, `out_root`, `canon_file`, `registry`, `dup_threshold`,
`recent_chapters` and `recurring_min` from that group; a flag always wins
(flag > `grounding.yaml` > default). A relative `canon_file`/`registry` resolves
against the campaign root, and `~` is expanded. With no
summaries directory from either place it refuses (see
[the refusal table](#every-refusal-and-exit-code-decoded)).

A `parts:` key left over in this group is refused when the file loads (the option is retired; delete the line).

A `canon_file` or `registry` you set explicitly (flag or `grounding.yaml`) must exist; a missing one is refused with exit 2 rather than silently read as "no rulings" or "no registry". Only the defaults may be absent. A non-string value in `grounding.yaml` (for example `registry: 5`) is refused the same way.

---

## What a valid summary looks like

One file per chapter, in one directory, named with a **numeric prefix**:
`NNN-anything.md` (the prefix pattern is `^(\d+)[-_.]`, so `015-session-04-14.md`,
`15_foo.md` and `15.foo.md` all place a file in chapter 15). Only top-level
`*.md` files are read.

Minimal valid file, `docs/summaries/001-the-gate.md`:

```markdown
# Chapter 1

Date: 2025-01-04

## Scenes

### 001.01 The Gate

#### The party reaches Gauntlgrym.

### 001.02 The Vault

#### They open the vault.

## NPCs

### Bruenor

Dwarf king.

## Items

### Short Sword

A plain blade.

## Memorable Moments

- A joke.
```

The rules, exactly as the parser applies them:

| Part | Rule |
|---|---|
| Title | A line `# Chapter N` (case-insensitive) outside a fenced code block. **N must equal the filename prefix.** |
| `Date:` | Optional. Read only from lines *before the first `##`*. Shown in the chronology; a file without one says `date not stated`. |
| `## Scenes` | Required, and must contain at least one `###`. |
| Scene heading | `### NNN.SS Title` — three digits, a dot, two digits, a space, a title. `NNN` must equal the filename prefix and be unique in the file. The id is kept verbatim. |
| Synopsis | The scene's `####` lines joined with ` / `; if there are none, its first paragraph. |
| Entity sections | Optional. `## NPCs`, `## Locations`, `## Items`, `## Spells`, `## Abilities`. Each `###` is one observation of that entity, with everything under it kept verbatim. They are an appendix: an observation is **never** attached to a scene. |
| `## Memorable Moments`, `## Session-End State` | Optional. Carried into `memorable_moments.md` / the chronology verbatim. |
| Any other `##` | Not an error (`unknown-section`, non-blocking). Preserved in `other_sections.md`. |

Headings inside fenced code blocks are ignored. A BOM is tolerated.

---

## Step 1 — validate (one pass reports everything)

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
summary_native validate --summaries-dir docs/summaries
```

`validate` is a **collector, not a raiser**: it parses every file, runs every
check on every file, and prints one report. You fix the whole directory in one
pass, not one error per re-run. It also writes
`docs/summary_native/ch<since>-<until>/validation_report.md` and `.json`, and
nothing else. Exit `0` = no blocking problem, `1` = at least one.

A real report from Out of the Abyss before its titles were fixed (67 files;
two lines elided):

```text
# Validation report

- Summaries directory: docs/summaries
- Range: 2–70
- Files scanned: 67
- Files in range: 67
- Gaps: 33, 66

## In range

### docs/summaries/015-session-04-14.md

missing-title  expected "# Chapter 15"  found "# Session 2025-04-14"  — no `# Chapter N` title line

...

### docs/summaries/070-session-untitled.md

L1  title-chapter-mismatch  expected "# Chapter 70"  found "# Chapter 66"  — title chapter disagrees with the filename prefix; fix the summary

### docs/summaries

range-gap  found "33"  — chapter 33 has no file inside the range

range-gap  found "66"  — chapter 66 has no file inside the range

## Outside range — not blocking

(none)

## Summary

- Blocking problems: 8
- Files failing: 8
- Non-blocking findings: 2
```

Seven files were titled `# Session <date>` (015, 016, 019, 054, 065, 067,
068) and 070 was titled `# Chapter 66`. A finding with no line number omits
the `L<n>` token. `expected` and `found` are on the line so you can fix it
without opening the file to look.

### The header lines

| Line | Meaning |
|---|---|
| `Range` | The resolved inclusive range. Unset bounds become the first/last chapter present. |
| `Files scanned` / `Files in range` | Every readable `*.md` / those inside the range. |
| `Gaps` | Chapter numbers inside the range with no file. Informational; `none` when complete. |
| `Duplicate threshold` | The `--dup-threshold` actually used. |
| `Existing corpus` | Only when `docs/summary_native/ch<since>-<until>/` already holds a build. See [below](#the-existing-corpus-line). |

### Every finding code

| Code | Blocking? | What it means | How to fix it |
|---|---|---|---|
| `no-numeric-prefix` | yes | The filename has no leading number followed by `-`, `_` or `.`, so it cannot be placed in a chapter. | Rename the file `NNN-<name>.md`. (Such a file counts as in range, because it breaks the corpus wherever it is.) |
| `duplicate-chapter` | yes, **even out of range** | Two files claim the same chapter number; ordering would be ambiguous. `found` lists the other file(s). | Renumber or remove one. Blocks everywhere because it makes the range itself ambiguous. |
| `missing-title` | yes | No `# Chapter N` line. `found` shows the first `# ` line the file does have. | Retitle it `# Chapter N` with N = the filename prefix. |
| `title-chapter-mismatch` | yes | The title's N differs from the filename prefix. The tool does not guess which is right. | Fix whichever is wrong, in the summary. |
| `missing-scenes` | yes | No `## Scenes` section. | Add one. |
| `empty-scenes` | yes | `## Scenes` has no `###` headings. | Add the scenes. |
| `bad-scene-id` | yes | A `###` under Scenes does not start with `NNN.SS `. | Rename it `### NNN.SS Title`. |
| `scene-chapter-mismatch` | yes | The scene id's `NNN` differs from the filename prefix. | Correct the id (a scene pasted from another chapter is the usual cause). |
| `duplicate-scene-id` | yes | The same `NNN.SS` appears twice in one file; the message gives the first line. | Renumber one. |
| `unreadable-file` | yes | The file cannot be read or is not UTF-8. The scan carries on with the other files. | Fix the encoding or permissions. |
| `unknown-section` | no | A `##` that is not one of Scenes, NPCs, Locations, Items, Spells, Abilities, Memorable Moments, Session-End State. | Nothing required; it is preserved in `other_sections.md`. Rename it if it was a typo for a recognised section — otherwise its entities are *not* in any dossier. |
| `possible-duplicate` | no | Two same-category headings that look alike. | See [Step 4](#step-4--possible-duplicates-fix-the-summaries). |
| `stale-ruling` | no | A `canon.yaml` ruling names a heading that no summary contains any more. | Delete or correct the ruling. See Step 4. |
| `range-gap` | no | A chapter number inside the range has no file. | Informational. A deliberate gap (a missed session) needs nothing. |

### "Outside range — not blocking"

Files outside `--since`/`--until` are scanned with the same checks, so you
can see their problems, but their findings are listed under **Outside range —
not blocking** and never stop a run. (The one exception is
`duplicate-chapter`, above.) That is how you build chapters 2–40 while 070 is
still broken: with `--since 2 --until 40`, the 070 `title-chapter-mismatch`
above lands in that section.

### The existing-corpus line

When a corpus already exists for the range, `validate` adds one of:

```text
- Existing corpus: matches current input
- Existing corpus: built from 67 files; 3 differ from current input; rebuild with build --force
  - changed: docs/summaries/015-session-04-14.md, ...
- Existing corpus: incomplete (the previous build did not finish); rebuild with build --force
```

`added` / `removed` / `changed` list up to 20 files each. This is the same
comparison `synth` makes before it will run
([stale-corpus refusal](#the-stale-corpus-refusal)).

---

## Step 2 — choose a range

```bash
summary_native validate --summaries-dir docs/summaries --since 2 --until 40
```

`--since` and `--until` are inclusive chapter numbers (filename prefixes). An
unset bound becomes the first/last chapter present, so no flags means the whole
directory. The range directory is
`docs/summary_native/ch<since:03d>-<until:03d>/` — `ch002-040` — so different
ranges never overwrite each other.

Refusals (exit 2, nothing written) — each names the chapters present:

```text
Error: --since 1 matches no file; chapters present: 2, 3, 4, ...
Error: --since 40 is after --until 2; chapters present: ...
Error: range 5-6 contains no file; chapters present: ...
```

A bound must *be* a chapter that has a file; `--until 33` is refused when
chapter 33 is a gap. Choose 32 or 34.

**The web UI never assumes "all".** It will not run without an explicit range
(HTTP 400, `choose a chapter range`). The **All chapters** button fills in the
first and last chapter present so the run still names them.

A draft made for chapters 2–40 describes the campaign **as of chapter 40**:
chapters 41+ are not in the corpus, any prompt or any draft.

---

## Step 3 — build the evidence corpus

```bash
summary_native build --summaries-dir docs/summaries --since 2 --until 40
```

`build` runs `validate` first and prints the same report. If anything blocks it
exits `1` and writes only the report. Otherwise it writes, with no model call:

```text
docs/summary_native/ch002-040/
  validation_report.md / .json   ← from validate
  chronology.md                  ← every scene, chapter then scene order, with provenance
  memorable_moments.md           ← each chapter's ## Memorable Moments, verbatim
  other_sections.md              ← only if some ## section was unrecognised
  dossiers/<category>_<slug>.md  ← one per entity: every observation, with file:line
  manifest.json                  ← range, gaps, every input file's sha256, counts
  drafts/                        ← created by synth
  runs/<doc>/<run_id>/           ← created by synth
```

Dossier names are `<category>_<slug>.md`, the slug being the subject
casefolded with runs of non-word characters collapsed to `_`: `Short Sword +1`
is `item_short_sword_1.md`. If two subjects produce the same name, each gets
`_` plus eight hash characters.

Output is **byte-stable**: building twice from the same input gives
identical files (sorted, no timestamps, no absolute paths).

### `manifest.json` and `complete`

`build` writes `{"kind": "summary_native", "complete": false}` *first*, then
the corpus, then the full manifest with `"complete": true` last. A crashed
build therefore leaves a directory the tool recognises as its own and as
unfinished. `synth` refuses an incomplete corpus.

### `--force`

| Situation | Without `--force` | With `--force` |
|---|---|---|
| Nothing there yet | builds | builds |
| A complete corpus exists | exit 2, `a summary-native corpus already exists; pass --force to rewrite it` | rewrites it |
| An incomplete corpus exists | exit 2, `the previous build did not finish; rerun with --force` | rewrites it |

`--force` deletes only the files `build` generates (`chronology.md`,
`memorable_moments.md`, `other_sections.md`, `manifest.json`, `dossiers/`).
**It does not touch `drafts/` or `runs/`**, and a stray file you dropped in
the directory (`notes.md`) is tolerated and left alone. The guard runs before
any deletion.

### A directory that is not ours is refused

Every subcommand refuses a range directory that:

- holds ensemble artifacts (`merged.json`, `state_dossiers/`,
  `merged_dossiers/`, `facts_*.json`, `extract_*.md`);
- has a `manifest.json` whose `kind` is not `summary_native`;
- or is non-empty but has no manifest (only the two `validation_report.*`
  files are allowed in such a directory).

`--summaries-dir` under `docs/ensemble` is refused too. Summary-native and
ensemble corpora must never be mixed, so `--out-root docs/ensemble` gets you a
refusal, not a corpus.

---

## Step 4 — possible duplicates: fix the summaries

Whether `Hand Crossbow` and `Hand Crossbows` are the same item is an identity
decision, and it is yours. `validate` lists likely duplicates; it never merges
them, and `build` groups only two things (below).

A real listing from Out of the Abyss (file paths shortened):

```text
## Possible duplicates — fix in the summaries

- possible-duplicate  — item: 'Hand Crossbow' ~ 'Hand Crossbows' (similarity 0.96); fix the summaries or rule it in canon.yaml
  - 'Hand Crossbow': 003-session-untitled.md:273, 004-session-untitled.md:272, 051-session-a-spore-filled-finale.md:292
  - 'Hand Crossbows': 005-session-untitled.md:211
- possible-duplicate  — spell: 'Tasha's Caustic Brew' ~ 'Tasha’s Caustic Brew' (similarity 0.95); fix the summaries or rule it in canon.yaml
  - 'Tasha's Caustic Brew': 007-session-untitled.md:243, 009-session-untitled.md:212, ...
  - 'Tasha’s Caustic Brew': 065-session-08-03.md:325
- possible-duplicate  — spell: 'Shape Water' ~ 'Shape Water (Ice Bridge)' (qualifier; ratio 0.63); fix the summaries or rule it in canon.yaml
```

The second one is a straight versus a curly apostrophe — invisible on screen,
different strings. Every `file:line` of each spelling is given so you can fix
them all.

**How the tool decides.** Within one category (`npc`, `location`, `item`,
`spell`, `ability` — never across categories), two distinct subjects are
listed when either:

- they are equal after stripping a trailing parenthetical qualifier
  (`Shape Water` / `Shape Water (Ice Bridge)`), reported as `qualifier`; or
- their casefolded `difflib.SequenceMatcher` ratio is at or above
  `--dup-threshold` (default **0.88**; `grounding.yaml
  summary_native.dup_threshold`), reported as `similarity`.

Raise the threshold for fewer, surer hits; lower it to catch more typos at the
price of noise. It changes only what is *listed* — never what is grouped.

**What `build` groups.** Only (a) headings with identical text after stripping
whitespace, within a category (case-sensitive: `Short Sword` and `short sword`
are two subjects), and (b) an exact, case-insensitive match on an entity
registry `name`/`aliases` entry whose registry *type equals the category*
(`npc`, `location`, `item`). Registry aliases are approved alternate names,
never misspellings. Spells and abilities **never** touch the registry — it does
not carry them — so those group by identical text only. A dossier made by
registry grouping says `grouped_by: [registry]` in its frontmatter. The
registry's first-token inference (turning `Kazryn` into `Kazryn Nyantani`) is
deliberately not used.

The registry is found automatically (`docs/entity_registry.yaml` under the
campaign root); `summary_native.registry` in `grounding.yaml` overrides that, and
`--registry` overrides both. A pair the registry holds apart
(`distinct` or `rejected_aliases`) is not listed.

### Two ways to clear a listing

**1. Fix the summary files (the usual answer).** Correct the spelling at the
`file:line` shown, re-run `validate`, and the pair disappears. If you had
already built, `build --force`.

**2. Rule that the two are genuinely different**, in `canon.yaml`
(`<out-root>/canon.yaml`, default `docs/summary_native/canon.yaml`; `summary_native.canon_file` in
`grounding.yaml` overrides that and `--canon` overrides both). It is hand-authored, shared by every range, and read-only to the
tool. Its one and only key is `not_duplicates`:

```yaml
not_duplicates:
  - category: item        # npc | location | item | spell | ability
    a: Short Sword
    b: Short Sword +1
  - category: spell
    a: Shape Water
    b: Shape Water (Ice Bridge)
```

Each entry is exactly `{category, a, b}` — no more keys, no fewer. Matching is
case-insensitive on either heading as written, in either order. An absent file
is an empty record.

### Why `canon.yaml` cannot merge

`canon.yaml` records *not-a-duplicate* rulings only, because merging is exactly
the identity decision the tool refuses to take. Any other key — `accepted:`,
`merge:`, `aliases:` — is refused with `canon.yaml records not-a-duplicate
rulings only; fix duplicates in the summary files`. The fix for a real
duplicate is always an edit to the summary. There is no file in which a typo
can be recorded as an alias.

### Stale rulings

A ruling whose heading occurs in **no readable summary at all** (any range, in
or out) is reported as `stale-ruling`, non-blocking, under the same section:

```text
- stale-ruling  — item: ruling 'Short Sword' / 'Short Sword +1' is stale; 'Short Sword +1' no longer occurs in any summary
```

You corrected the summary, so the ruling has nothing left to rule on. Delete
it. Staleness is judged against every summary, not just the range, because
`canon.yaml` is shared across ranges.

---

## Step 5 — synthesise a draft

`synth <doc>` renders one document. `<doc>` is one of `world_state`,
`campaign_state`, `party`, `planning`, and **every one of them is built the same
way since spec 034: one model call per section, from the checked notes
`extract` wrote, with code checking each section.** Read
[Step 5b](#step-5b--world_state-and-campaign_state-are-a-four-step-chunked-build)
for the build and its files.

> **What is gone.** The one-shot path (the corpus's chronology and dossiers in
> one prompt per document, `--parts`, `drafts/` and `runs/<doc>/`) was retired
> by spec 034. These are refused with the replacement named (exit 2 from the
> CLI, HTTP 400 from the routes):
>
> | Retired | Message |
> |---|---|
> | `--parts N` | `--parts is retired: every document is built one call per section from the checked notes` |
> | `--world-state FILE`, `--campaign-state FILE` | `--world-state is retired: upstream drafts are no longer prompt context: party and planning build from the checked notes; review those documents on their own` (likewise `--campaign-state`) |
> | `parts:` under `summary_native` in `grounding.yaml` | "summary_native.parts is retired (every document is built one call per section from the checked notes): delete the `parts:` line from grounding.yaml" (refused when the config loads, not only at `synth`) |
>
> The retired flags are checked first, before any config or corpus is read.

**Order no longer matters between documents.** No document reads another's
draft, so there is no upstream draft to name: build them in any order, and review
each on its own.

```bash
summary_native extract --summaries-dir docs/summaries --since 2 --until 70
summary_native synth world_state    --summaries-dir docs/summaries --since 2 --until 70
summary_native synth campaign_state --summaries-dir docs/summaries --since 2 --until 70
summary_native synth party          --summaries-dir docs/summaries --since 2 --until 70
summary_native synth planning       --summaries-dir docs/summaries --since 2 --until 70
```

### What goes into the prompt

One call per section, and each call sees only the checked notes code routed to
it (plus, for a few sections, the last chunk's summaries or a configured sheet).
Nothing reads the corpus's chronology or dossiers wholesale, and no document
reads another's draft. What each document's calls see is described in
[Step 5b](#step-5b--world_state-and-campaign_state-are-a-four-step-chunked-build)
(world_state, campaign_state) and [Step 6](#step-6--party-and-planning-the-chunked-builds)
(party, planning).

These `synth` flags select or configure; each is refused (exit 2) for a document
it does not apply to:

| Flag | Applies to | What it does |
|---|---|---|
| `--party-config FILE` | `party` | The roster. Default `<config dir>/party.yaml`. A missing file, an unreadable one, one with no characters, or a missing sheet/backstory/arc-score file is a refusal. |
| `--planning-config FILE` | `planning` | Tracked NPCs/factions and arc scores. Default `<config dir>/planning.yaml`; an *absent default* means "no arc scores configured", an *absent explicit* path is a refusal. |
| `--name SUBJECT …`, `--recent-chapters N`, `--recurring-min N` | `planning`, `world_state` | Choose the NPCs that get a published-dossier line (defaults 4 and 10; `0` recent chapters = all). Refused for `party` and `campaign_state`. |
| `--fallback-npc-lines` | `planning`, `world_state` | Per run only: write a marked code-built line for an NPC without a published dossier instead of refusing. Refused for `party` and `campaign_state`. |
| `--npc-root DIR` | `planning`, `world_state` | Where draft verifications and the publish log are read, to explain a missing dossier. |

`--audit` is accepted by the parser only to be refused for every document: the
audit is its own step (`summary_native audit`, Step 5b).

### Outline check, `--max-tokens`

Each document has a fixed ordered outline (the H2 headings in
`pipelines/summary_native/prompts/<doc>.outline.yaml`):

| Doc | Headings, in order |
|---|---|
| `world_state` | Party · Factions and Powers · Key NPCs · Locations · Items and Artifacts · Active Threats and Open Pressures · Canon Events Timeline |
| `campaign_state` | Completed Encounters & Quests · Resolved Plot Threads · NPC Current States · Active Quests & Open Threads · Party Current Situation · Audit: Tracking Claims |
| `party` | Party Overview · Characters · Party Dynamics |
| `planning` | Threat Tracker · NPC Dossiers · Faction States · Active Plots · DM Notes |

After the build the assembled document is checked **deterministically** against
the outline: no text before the first heading, every heading present exactly once
and in order, no extra `## ` heading, and a non-empty body under each. A document
that fails is never written as a draft (it becomes `<doc>.incomplete.md`, exit 3).

- `--max-tokens N` is per call; default **16000**.
- Word budgets are per section, reported (`Party Overview: 241/300 words`) and
  **never trimmed**: an overrun is flagged `OVER` and kept whole. Defaults are
  declared once in `schema.py` (`DEFAULT_PARTY_BUDGETS`, `DEFAULT_PLANNING_BUDGETS`);
  override them under `summary_native.prose.party_budgets` /
  `planning_budgets` in `grounding.yaml`. A section name outside the defaults, or
  a value below 1, is refused when the config loads. `Characters` is words **per
  character**.

### The Threat Tracker sentinel

For `planning`, code writes the Threat Tracker; the model never does. When the
planning config configures **no** arc score (or there is no config), the body is
**exactly** the single line

```text
_No arc scores configured._
```

With arc scores configured it is a table, one row per tracked NPC or faction
that has a mechanic file; see [Arc-score candidates](#arc-score-candidates) in
Step 6 for what goes in the cells.

### Backend and model

Same flags as the other synthesis tools: `--backend
{anthropic,dgx,openrouter,claude-code,codex-cli}`, `--model`, `--endpoint`
(with `--backend dgx`), and the `--codex-reasoning-effort` /
`--claude-code-effort` / `--[no-]claude-code-thinking` knobs. The prose backend
is `summary_native.prose.*` in `grounding.yaml` (flag > config > default), and
the default is `claude-code` / `claude-sonnet-5-5` / effort `medium`, the same
for all four documents. A backend/model pair that cannot work together is a
refusal; each backend refuses for itself at the call.

### `--dump-only`

```bash
summary_native synth world_state --summaries-dir docs/summaries --dump-only
```

Writes the run directory (below) with the exact prompts and `record.json`,
makes no model call, writes no draft, and exits 0. It still requires a fresh
built corpus. Use it to read what the model would be given. It also skips the
existing-draft `--force` check, because nothing is overwritten.

### Where everything goes

Nothing is written outside `state/` any more: the one-shot `drafts/`, `runs/<doc>/` and `selection.json` are
gone. The layout of the runs, drafts and reports is under
[Step 5b](#step-5b--world_state-and-campaign_state-are-a-four-step-chunked-build). A new
`state/runs/<run_id>/` is created on every invocation and earlier runs are never touched. `run_id` is a UTC
timestamp (`20261005T154310Z`), with `-1`, `-2`… appended if two runs start in the same second. `record.json`
holds `step`, `doc`, `run_id`, `range`, `backend`, `model`, `effort`, `max_tokens`, the sha256 of every input
(`inputs`), one entry per model call (`calls`), the `check` result (`{complete, problems}`, or `"not run"` for
`--dump-only`, or `{complete: false, error}` when the run died before or during a model call), and
`started` / `finished`.

A complete draft begins with a one-line HTML comment naming the doc, the range, the run's `record.json` and the
notes manifest sha256.

### An incomplete draft: `.incomplete.md` and exit 3

```text
Incomplete: docs/summary_native/ch002-070/drafts/world_state.incomplete.md
  - missing heading: ## Canon Events Timeline
```

The output is kept for inspection as `<doc>.incomplete.md` and the command
exits **3**. An incomplete draft is not promotable. An existing
`<doc>.draft.md` is **kept** (stderr says `previous draft kept:
state/drafts/<doc>.draft.md (from run <id>)`); an existing `.incomplete.md` never
blocks a run and is replaced. A later complete run deletes the stale
`.incomplete.md`.

### Replacing a reviewed draft

An existing `<doc>.draft.md` is treated as GM-reviewed material: `synth`
refuses to overwrite it without `--force` (exit 2,
`…world_state.draft.md exists; pass --force to overwrite it`).

### The stale-corpus refusal

Before it does anything, `synth` re-validates and compares the sha256 of every
in-range summary file with `manifest.json`. If a summary changed, was added or
was removed since `build`, it refuses:

```text
Error: summaries changed since build — run `summary_native build --force`
```

A draft must never be rendered from a corpus that no longer matches the files
you think it came from. If the directory now has blocking problems it prints
the validation report followed by `validation has blocking problems; fix the
summaries, then build --force`, and exits **1** (the same as `validate` and
`build`). The stale-corpus refusal itself exits 2.

The entity registry counts too. `synth` hashes the registry `build` would use
now (the `summary_native.registry` configured in `grounding.yaml`, the `--registry` you pass, or the
auto-discovered `docs/entity_registry.yaml`; none if absent) and compares it with the one recorded in `manifest.json`. If it
changed, it refuses:

```text
Error: entity registry changed since build — run `summary_native build --force`
```

`canon.yaml` does **not** make a corpus stale: it holds not-a-duplicate rulings
that change validation findings only, never the corpus. A registry set in `grounding.yaml` is resolved the same way at `build` and `synth`. If you gave `build` a `--registry` flag, pass `synth` the same one, or the configured/auto-discovered registry will be compared instead.

---

## Step 5b — `world_state` and `campaign_state` are a four-step chunked build

> Every document takes this path (spec 034 retired the one-shot one for `party`
> and `planning`). `--parts`, `--world-state` and `--campaign-state` are refused
> for all four (exit 2, with the replacement named), `--audit` is refused as
> below, and every draft lives under `state/drafts/`. Design:
> `specs/033-chunked-grounding-docs/` and `specs/034-chunked-party-planning/`
> (`contracts/cli.md` and `contracts/http.md`). This step walks world_state and
> campaign_state; [Step 6](#step-6--party-and-planning-the-chunked-builds) covers
> what is different for party and planning.

The long chapter range is cut into chapter groups, each group is read by its own
model call, **code** checks what came back, and only the checked notes reach the
prose step. The model never decides scope, order or attribution: code does.

```text
extract  →  synth world_state  →  synth campaign_state  →  (annotate)  →  audit
 map         (build + annotate)    (build + annotate)       re-run only      its own
 step                                                       when needed      step
```

Run them from the campaign root, with the same `--since/--until` as `build`:

```bash
summary_native extract --since 2 --until 70 --endpoints http://spark:8001/v1 http://spark2:8001/v1
summary_native synth world_state    --since 2 --until 70      # Key NPCs need published dossiers (below)
summary_native audit --since 2 --until 70                     # needs --track-file, or campaign_state.track_files
summary_native synth campaign_state --since 2 --until 70      # renders the audit it finds
summary_native annotate world_state --since 2 --until 70 --dry-run
```

### `extract` — the map step

One call per chapter group, a code check, then `state/notes/`. A note survives
only if its citation `[ch NNN / target]` resolves inside its own chunk and any
quotation is verbatim; everything else is a **drop**, listed with its reason in
`state/notes/drops.md`. Read it before you synthesise. Each line of output is
one chunk (`chunk 07/60 ch 009-010 @spark2:8001 214s kept 61 dropped 2`;
`cached` for a reused chunk), then totals and any **outlier chunks** (a runaway
call).

| Flag | Meaning |
|---|---|
| `--backend --model --endpoint` | As elsewhere. Default: `summary_native.extract.*` in `grounding.yaml`, else `dgx` / `qwen3.8-flash-next`. |
| `--endpoints URL…` | Several dgx endpoints sharing **one** chunk queue; a slower box simply takes fewer chunks. Refused with `--endpoint`, and for a non-dgx backend. Wiring, never stored in config. |
| `--parallel N` | In-flight calls **per endpoint**; default **6** (`--endpoints A B --parallel 4` is 8 calls). |
| `--chunk-chars N` | Chunk size; a chapter is never split. |
| `--max-tokens N` | Per call. |
| `--dump-only` | Write prompts, chunks and the manifest; no model call. |
| `--force` | Re-extract every chunk, ignoring cache keys. |

Chunks are cached by a key over the chapter texts, prompts, backend, model and
limits, so a second run extracts only what changed or failed. The cache also searches
sibling `chNNN-NNN/state/notes/` folders under the configured output root. Extending
ch002-070 to ch002-071 reuses unchanged chunks from the earlier build; only a new
or changed final chunk makes a model call. A hit reports `cached`, copies the raw
response into the new range, and runs the current checker again. `--force` ignores
both local and sibling caches. Older builds require no cache migration.

**A bad endpoint stops the run.** Before the first chunk is sent, every endpoint
is asked for `/models`; one that does not answer, or does not serve `--model`,
refuses the whole run (exit 2) naming the endpoint and what it serves. No chunk
is sent, and the run record keeps the refusal. Fix the endpoint or drop it from
`--endpoints`; there is no silent fall-back to the others.

### `synth world_state | campaign_state` — build from the checked notes

Code builds the timeline (its own file), the completed list, the NPC status
table, the six `reference/` files, the Audit section and `world_state`'s reading
contract. Reference headings group exact registry names and aliases under the
canonical name. Unknown or ambiguous subjects keep their own headings; every note
retains its original subject spelling and verbatim text. The model writes each remaining section (one call per section) from
only the notes code routed to it, inside word budgets that are reported
(`Locations: 279/450 words`) and never trimmed. Code checks the output
(each heading present; Key NPCs lines pass their checks), runs `annotate`
automatically, and writes the drafts. The prose backend is separate from the
extraction one: `summary_native.prose.*`, default `claude-code` /
`claude-sonnet-5-5` / effort `medium`.

**Key NPCs come from published dossiers, and a missing one refuses the build.**
`world_state`'s Key NPCs are rendered from the NPC dossiers `npc-publish`
wrote (never from `## Secrets`). If any selected NPC has no published, verified
dossier **eligible for this build's range**, `synth world_state` refuses (exit 2)
and lists each one:

```text
world_state's Key NPCs need a published, verified dossier for each selected NPC; 2 of 30 have none:
  Ilvara Mizzrym: not drafted
  Kalan: failed verification (not-found 2)
Draft, verify and publish them, then build again:
  summary_native npc-draft --since 2 --until 70 --name "Ilvara Mizzrym" "Kalan"
  ...
or pass --fallback-npc-lines to write a code-built line (no published dossier — from checked notes) for each of them.
```

The state of each NPC is `not drafted`, `drafted, not verified`, `failed
verification (<checks>)`, `drafted, not published` or `published for <range>,
not <range>`. A dossier for the same range is eligible. One with the same start
and an earlier end is also eligible when no checked note in the added chapters
names that NPC by an exact registry name or alias. This includes mentions in event
and thread notes, and every citation on a note is considered. The report records
`carried over from ch002-070`; the line keeps its published-dossier pointer.
A touched NPC must be republished for the new range. The refusal names both ranges
and supplies the four `npc-* --name` commands for the affected NPCs. Future-ending
and different-start dossiers are refused. Unknown spellings must be fixed in the
summaries or registry; the carry-over check never guesses by similarity.
Two ways out: do the `npc-*` steps
([NPC dossiers how-to](npc_dossiers_howto.md)), or pass
**`--fallback-npc-lines` for this run only**. It is never read from config and the
web page's checkbox is unchecked on every load, so the choice is yours each time.
A fallback line is the NPC's latest checked status and ends in
`(no published dossier — from checked notes)`; it has no dossier to open.

`--recent-chapters`, `--recurring-min` and `--name` choose Key NPCs and are
refused for `campaign_state`, which has no such section, as are
`--fallback-npc-lines` and `--npc-root`.

### `annotate` — evidence under a line, never a changed line

Deterministic, no model. It re-runs the detectors over an existing draft and
rewrites only the annotation sub-bullets under lines: `⚠ later:` (newer
information about the same subject), `ℹ since:` (the later status of someone the
line mentions) and `⚠ unverified:` (a quotation not verbatim in the chapter it
cites, or a citation that does not resolve). A player character listed as a
companion, and a Faction States block named for a player character, are the only
things it removes. It works on all four documents (for party and planning's scope
see [Step 6](#annotation-for-party-and-planning)). Use it after publishing a dossier or
editing a summary when you do not want a full rebuild; `--dry-run` prints the hits
and writes nothing. It prints `annotations: 8 later, 7 since, 2 unverified; 0
removed` and writes `annotations.md`.

### `audit` — the tracking files, checked item by item

Its own step, and it needs the built corpus but **not** the extracted notes. Code
numbers each `- ` line of the track files (`A1`…) and picks, for each, the few
chapters that could show it; the model judges that one item against only those
chapters; code accepts **SUPPORTED** only for a citation inside the candidates
and a verbatim span of at least 8 characters. An item with no candidate chapter is
`NOT FOUND (no-candidates)` and costs no call; a `SHOWN` answer that fails a check
becomes `NOT FOUND (unverified)`, with the failed check named in `audit.md`.
Track files come from `--track-file` (repeatable, same spelling as
`campaign_state --track-file`) or `grounding.yaml campaign_state.track_files`.
`--candidates N` (default 3), `--backend --model --endpoint --endpoints
--parallel --max-tokens --dump-only --force` are as for `extract`. Output:
`audit: 443 items — 171 SUPPORTED, 249 NOT FOUND (31 no candidates, 18 unverified)`.

`synth campaign_state` renders its Audit section from `audit.json`. With no audit
run it says "Audit not run for this range."; with a stale one (a track file
added, removed or changed, or the notes re-extracted) it **refuses**, naming
`summary_native audit`. Rerun the audit, then rebuild.

### Where everything goes

```text
docs/summary_native/ch002-070/
  manifest.json, chronology.md, dossiers/ …     ← the 031 corpus, read-only here
  state/
    notes/    manifest.json, chunkNN.*.{user,out}.md, chunkNN.*.checked.json, drops.md
    runs/<stamp>/record.json                     ← one per extract / synth / audit run, with the prompts
    audit/    items.json, audit.json, audit.md
    threads/  attach.json (planning), propose.NN.{user,out}.md, propose_report.md (thread-propose)
    drafts/
      world_state.draft.md  campaign_state.draft.md   (*.incomplete.md if a section is missing)
      party.draft.md  planning.draft.md
      canon_events_timeline.md
      reference/{factions,npcs,locations,items,threads,threats}.md   (party: reference/party.md)
      annotations.md, npc_status_report.md, key_npcs_report.md, budget_report.json
      party_report.md, planning_npcs_report.md, threads_report.md, arc_report.md
      budget_report.party.json, budget_report.planning.json
```

Everything this build writes is under `state/`. `docs/`, `docs/npcs/` and the 031
corpus are never written (`tests/test_state_docs_no_live_writes.py`).

### Drafts are regenerated: fix at the source

A draft is output, not a document you maintain. The next `synth --force`
replaces it. So an error found in a draft is fixed where it comes from:

| The draft is wrong because… | Fix |
|---|---|
| a summary says the wrong thing | the summary, then `build --force`, `extract`, `synth --force` |
| a name is split or merged wrongly | the entity registry, then the same |
| a Key NPC line is wrong | the NPC's authored file / dossier, `npc-*` again, `synth world_state --force` |
| a note was dropped that should not have been | `drops.md` says why; usually the summary's wording |

**Prose edits are made only after promotion**, in `docs/`, where the next build
cannot overwrite them. Editing a draft first only to have it regenerated is the
mistake this rule exists to prevent.

### Refusals and exit codes of the new steps

Exit codes are the same as everywhere: `0` ok, `1` blocking validation problems,
`2` refusal, `3` incomplete, `4` model call failed.

| Message (abridged) | Command | What to do |
|---|---|---|
| `no checked notes for this range; run summary_native extract --since A --until B` | synth, annotate | Run `extract`. |
| `checked notes are stale (corpus manifest / entity registry / players changed); run …` | synth, annotate | Rerun `extract`. |
| `state/notes/manifest.json is unreadable` / `is not a state-notes manifest; run … --force` | synth, annotate | `extract --force`. |
| `<notes error>; run summary_native extract …` | synth, annotate | Some chunk has no checked notes; rerun `extract` (it does only the missing ones). |
| `world_state's Key NPCs need a published, verified dossier …` | synth world_state | See above: publish dossiers, or `--fallback-npc-lines` for this run. |
| `--parts is retired: every document is built one call per section from the checked notes` | synth | Drop it. |
| `--world-state is retired: upstream drafts are no longer prompt context …` (likewise `--campaign-state`) | synth | Drop it; no document reads another's draft. |
| `--audit does not apply to campaign_state: the audit is its own step: summary_native audit` (world_state: `--audit applies to campaign_state only`) | synth | Run `audit`; `synth campaign_state` picks it up. |
| `--fallback-npc-lines applies to world_state and planning only, not <doc>` / `--npc-root applies to world_state and planning only, not <doc>` | synth | Drop it. |
| `--name / --recent-chapters / --recurring-min does not apply to campaign_state: it has no Key NPCs section` | synth | Drop it. |
| `--name / --recent-chapters / --recurring-min does not apply to party: party selects no NPCs; these apply to planning and world_state` | synth party | Drop it. |
| `the party notes predate the subject grammar; run summary_native extract --since A --until B (it re-extracts every chunk)` | synth party, synth planning | Run the `extract` it names, once. See Step 6. |
| `planning's NPC Dossiers need a published, verified dossier for each selected NPC; N of M have none: …` | synth planning | As world_state's Key NPCs above: run the four `npc-*` commands it lists, or `--fallback-npc-lines` for this run. A selected NPC can be one the notes never mention but `planning.yaml` tracks. |
| `no dossier has subject: X (NPC Dossiers select the global NPCs only)` | synth planning (also world_state: Key NPCs) | A `--name` matched no global NPC, or named a player character. Check the spelling against the registry. |
| `the thread registry docs/thread_registry.yaml fails thread_registry check; fix it first:` + the findings | synth planning, thread-propose | Run `thread_registry check`, fix what it lists. An *absent* registry is not an error. |
| `cannot read the thread registry: …` / `cannot read the thread registry or the proposals file: …` | synth planning, thread-propose | The YAML will not load; fix the file. |
| `cannot read the entity registry or players.yaml: …` | synth, thread-propose | Fix the file named. |
| `thread-propose needs --since and --until: the thread notes of a chapter range, never all chapters` | thread-propose | Give both. |
| exit 3: `<label>: the model wrote no body` / `…wrote a heading (…)` / `…wrote a level line (…)` / `…wrote '#### Candidate Arc Score Events'; code places the checked candidates there` | synth party | Rerun with `--force`; the label names the section or `Characters: <name>`. The draft is `party.incomplete.md`. |
| exit 3: `<section>: the model wrote no body` | synth planning | As above (`planning.incomplete.md`). |
| exit 4: `batch i/N failed after one retry: …; no proposal was written` | thread-propose | The backend failed; nothing was merged. Rerun. A batch that *answers* with unusable JSON is not exit 4: its notes become single-note proposals. |
| exit 4: `model call failed in Arc score: <subject> …` | synth party, planning | The arc call failed; no draft was written. Rerun. |
| `the audit is stale (track file(s) changed: …); run summary_native audit` / `(the checked notes changed)` | synth campaign_state | Rerun `audit`. |
| `state/audit/items.json is unreadable; run summary_native audit --force` | synth campaign_state | As said. |
| `…/state/drafts/<doc>.draft.md exists; pass --force to overwrite it` | synth | `--force` only if you do not mind losing that draft (it is output; see above). |
| `no draft for <doc> at …; run summary_native synth <doc>` (also: `only <doc>.incomplete.md exists`) | annotate | Build the draft first. A draft is annotated only once complete. |
| `endpoint X is not answering (…); no chunk was sent` / `endpoint X serves […], not <model>; every endpoint must serve the same model; no chunk was sent` | extract, audit | Fix or drop the endpoint. (`audit` says `no item was sent`.) |
| `--endpoints applies to --backend dgx only, not <backend>` | extract, audit | Use dgx, or `--endpoint`. |
| `give --endpoint or --endpoints, not both` | extract, audit | Pick one. |
| `--parallel must be at least 1` / `--candidates must be at least 1` / `--chunk-chars must be a whole number of at least 1` | extract, audit | Fix the value. |
| `no track files: pass --track-file FILE, or set grounding.yaml campaign_state.track_files` | audit | Name one. |
| `track file X: no such file` | audit | Check the path (relative paths resolve against the campaign root). |
| `the track files hold no items (lines starting with `- `)` | audit | Items are `- ` lines. |
| `no summaries for chapters A-B in <dir>` / corpus missing or stale (`run summary_native build`) | extract, audit | Build the corpus for this range. |
| exit 3: `N chunk(s) failed after one retry: …` | extract | Rerun; only those chunks are redone. |
| exit 3: `N item(s) failed after one retry: …` | audit | Rerun; they are recorded `NOT JUDGED` until then. |
| exit 3: `Incomplete: …/state/drafts/<doc>.incomplete.md` | synth | A section is missing; the file is never promotable. An earlier complete draft is kept. |
| exit 4: `no chunk could be extracted: the backend could not be reached …` / `no item could be judged …` | extract, audit | The backend is unreachable; see `state/runs/<stamp>/record.json`. |
| exit 4: `model call failed in section <heading> …` | synth | See `record.json`; no draft written. |

### Promotion

The tool never writes `docs/`. To promote a chunked build, copy by hand, and
note the **timeline and `reference/` files are part of the promotion**, because
the reading contract at the top of `world_state` points at them:

| From `state/drafts/` | To |
|---|---|
| `world_state.draft.md` | `docs/world_state.md` |
| `campaign_state.draft.md` | `docs/campaign_state.md` |
| `canon_events_timeline.md` | `docs/canon_events_timeline.md` |
| `party.draft.md` | `docs/party.md` |
| `planning.draft.md` | `docs/planning.md` |
| `reference/` (incl. `party.md`) | `docs/reference/` |

The timeline and `reference/` paths are relative to `world_state`, so the whole
bundle can instead be copied to another directory. Summaries and NPC dossiers
remain relative to the campaign root; a summaries directory outside that root
keeps its absolute path. After copying, verify the actual destination:

```bash
summary_native check-pointers docs/world_state.md
# Or: summary_native check-pointers reviewed/grounding/world_state.md
```

The check makes no model call and writes nothing. It exits 2 and names each missing
file, summaries directory or cited chapter. Copying just `world_state` therefore
reports the missing companions. It requires only the files the document's own
reading contract names: `world_state` lists six reference files and the timeline,
`planning` lists `factions`, `npcs` and `threads` (no timeline), `party` lists
`party` (no timeline), so a promoted party or planning bundle is complete without
the files it never pointed to. Keep the hidden path record in the reading
contract so the checker can resolve it; regenerate older drafts without one.
The first-line HTML provenance comment is optional for this check.
Prose edits, if any, happen now,
in `docs/`. `annotations.md`, `npc_status_report.md` and the two Key NPCs reports
are for your review and are not promoted. `summary_native compare` works on these
documents too (it reads `state/drafts/`).

---

## Step 6 — party and planning, the chunked builds

`party` and `planning` are built exactly like `world_state`: `extract` writes the
checked notes, `synth` builds one document from them (code first, then one model
call per section, then a code check), and `annotate` runs at the end. Neither
reads another document's draft, and nothing is written to `docs/`.

```bash
# party needs config/party.yaml (or --party-config)
summary_native synth party    --since 2 --until 70

# planning reads config/planning.yaml; without one, the Threat Tracker sentinel applies
summary_native synth planning --since 2 --until 70
```

**Run `extract` again once, after upgrading.** The `## Party` grammar changed
(below), and the extraction prompt is part of the chunk cache key, so the first
`extract` reports `0 cached` and re-reads every chunk. Until you do, both
documents refuse:

```text
Error: the party notes predate the subject grammar; run `summary_native extract --since 2 --until 70` (it re-extracts every chunk)
```

Both documents also accept `--force`, `--dump-only`, `--max-tokens` and the
backend flags, as in Step 5. `--dump-only` writes every prompt to
`state/runs/<stamp>/` and makes no call.

### party

Sections, in order: **Party Overview**, **Characters**, **Party Dynamics**.
Budgets (words): 300, 500 *per character*, 300.

**The party grammar, and the re-extract.** Every `## Party` bullet the extraction
step writes begins with a bold subject:

```text
- **Daz** — carries the Ring of Winter now [ch 031 / 031.04]
- **Party** — camped at the Darklake shore [ch 031 / end]
- [LEVEL] **Party** — 9 [ch 034 / moment]
```

The subject is one player character, several joined by `,` / `and` / `&`, or
exactly `Party`. A level gets its own `[LEVEL]` bullet with the number alone.
`extract` drops (listed in `state/notes/drops.md`):

| Drop reason | Meaning | What to do |
|---|---|---|
| `missing-party-subject` | A party bullet with no leading `**Subject**`. | Nothing; rerun `extract` if many. The note is not guessable. |
| `level-not-in-cited-text` | A `[LEVEL]` row whose number is not stated as a character level ("level 9", "9th level", "reaches ninth level") in a section it cites. A spell level or slot does not count. | Nothing: this is the check working. If the summary never states the level, there is no level row. |
| `malformed-level-row` | A `[LEVEL]` row without the `**Subject** — N` shape. | Rerun `extract`. |

**Attribution is code's decision.** Each party note is attributed from its
subject by exact, casefolded equality through the entity registry and
`players.yaml`, never by similarity (`Dazz` is not `Daz`). The whole subject is
tried first; it is split on `,` / `&` / `and` only when the whole resolves to
nothing, and then *every* piece must resolve (so a registry entity called
"Topsy and Turvy" stays one companion). The result is one of:

| Scope | Where the note goes |
|---|---|
| `character` | The section of each player character it names (a joint note counts for each). |
| `party` | Party-wide: seen by Party Overview and Party Dynamics, and by every character's call from the last chunk. |
| `companion` | A non-player entity the registry names (Glabbagool, Jimjar, Ront in Out of the Abyss). No character section. |
| `unattributed` | Resolves to nothing, or to more than one entity. Listed in `party_report.md` with the reason. |

An unattributed note is a fix-at-source item: declare the name in `players.yaml`
or the registry, or correct the summary, then `extract` and `synth --force`.

**Companions are in the overview and the dynamics.** *(GM ruling, 2026-10-08.)*
Party Overview and Party Dynamics are written from every party-wide note, the
latest two notes of each character, **and the latest two notes of each
companion**, so the group is described with the people travelling with it. A
companion never gets a `### name` section.

**Level is code's decision too.** Each `### name` carries a line the model cannot
write:

- `Level: 9 [ch 034 / moment]`: the latest `[LEVEL]` row for that character or for
  `Party`, by first chapter (a character's own row beats a party row of the same
  chapter);
- else `Level: not recorded in the summaries (sheet says 8)`: the figure from an
  explicit `Level:` / `Class & Level:` / `## Level N` line of the character's
  sheet, shown as the sheet's, never as fact; or `(sheet gives none)` when the
  sheet has none or two different ones.

A model that writes a level line, any `#` heading, or the arc-score heading in
its body makes the draft incomplete (exit 3, below).

**Characters.** One `### name` per character in `party.yaml`, in that order and
spelled as configured: the level line, the model's body (written from *that
character's* notes, the last chunk's party-wide notes, and their sheet and
backstory, nothing else), an `Unsupported by the summaries:` line where the sheet
says more than the notes, optionally the candidate arc-score subsection, and
`_Full notes: reference/party.md_`. A character with no notes gets the code line
`The summaries in this range record nothing for <name>.` and no call. A player
character with notes but no `party.yaml` entry gets no section, and is named in
`party_report.md`.

**Files.**

| File (under `state/drafts/`) | Holds |
|---|---|
| `party.draft.md` | The document, annotated. |
| `reference/party.md` | Every checked party note, verbatim: one group per character, then `Party`, `Companions`, `Unattributed`. Promote it beside `party.md`. |
| `party_report.md` | Counts by scope, the level source per character, the companions, the unattributed notes with reasons, and the word counts against budget. **Read this first.** |
| `arc_report.md`, `budget_report.party.json`, `annotations.md` | As below. |

### planning

Sections, in order: **Threat Tracker** (code only), **NPC Dossiers**, **Faction
States**, **Active Plots**, **DM Notes**. Budgets: 1500, 600, 1200, 400.

**NPC Dossiers** come from *published* dossiers, as world_state's Key NPCs do.
Code selects the NPCs: those in `planning.yaml`, then `--name`, then the recent
and recurring ones (`--recent-chapters`, `--recurring-min`), never a player
character. For each, one block `### <name>` with `Status and location:`,
`Goals:` and `Relationships:` lines, written from that NPC's dossier (Identity,
Personality and Motivations, Last Observed State and Relationships only) and
ending in `→ docs/npcs/<slug>.md`. Code checks the heading set and order, that
every citation is one of that dossier's, and that quotes are verbatim; a block
that fails is replaced by the dossier's own first Last Observed State sentence
and listed in `planning_npcs_report.md`.

A selected NPC without a published, verification-passing dossier **refuses the
build** (exit 2) with the same message and `npc-draft` / `npc-verify` /
`npc-compose` / `npc-publish` commands as world_state (Step 5b), starting
`planning's NPC Dossiers need a published, verified dossier for each selected
NPC; N of M have none:`. `--fallback-npc-lines` is the per-run way out: a code
line ending `(no published dossier — from checked notes)`. It is never read from
config.

**Faction States.** Code selects the factions: those in `planning.yaml` plus every
`[FACTION]` subject in the notes (canonical by registry name or alias), newest
activity first, at most 20 written; the rest are named in one closing line with a
pointer to `reference/factions.md`. One call writes a `### <faction>` block per
faction that has notes; a faction with none gets the code line
`The summaries in this range record nothing for <name>.`; a block that is
missing, out of order or empty is replaced by that faction's latest note,
verbatim. A block named for a *player character* is removed by `annotate`.

**Active Plots has three layers**, and the thread registry is why. Out of the
Abyss's checked notes carry 554 distinct thread names, and 550 of them appear
once; the extractor names a thread freshly each time, so no count or grouping of
those names is a plot list. Thread identity is the GM's
`docs/thread_registry.yaml`, nothing else:

1. **Open ratified threads** (`### <title>`), newest activity first. A thread's
   notes attach to it when the note's bold name equals the thread's title or one
   of its aliases after `norm_title`; equality is the whole rule. A name two
   threads claim is *ambiguous*: reported, and the note stays unattached. Whether
   a thread is open is code's decision: a registry status of `dormant`,
   `resolved` or `abandoned` that you set wins; a status of `open` defers to the
   latest attached note (open if its tag is `OPENED` or `ADVANCED`). One call
   writes the entries; a missing or bad one is replaced by the thread's latest
   attached note, verbatim.
2. **`### Dormant threads`**: threads you marked `dormant` that have notes in the
   range, as `- **title** — latest note, verbatim`. A code-built block of its own;
   no model call. *(GM ruling.)*
3. **`### Unratified thread notes (not yet ruled on)`**: one italic line, built
   by code: the count of checked thread notes no ratified thread owns, a pointer
   to `reference/threads_unratified.md`, and a pointer to the proposals queue.
   The notes themselves (verbatim, chapter order) are in that reference file,
   not in planning *(GM ruling 2026-10-09: listed in full they made planning 73K
   characters against the one-shot's 12.5K)*. Evidence, not plots.

With no ratified thread that has notes in the range the first layer is the line
`_No ratified thread has notes in this range._`; with some but none open it is
`_No ratified thread is open in this range._`. An **absent or empty registry is
not a refusal**: every thread note is then unratified. A registry that fails
`thread_registry check` **is** refused (exit 2) with the check's findings, and
nothing is read from it.

**DM Notes** opens with the code label `_Suggestions for the GM, not events._`,
then bullets written from the open threads' latest notes, the NPC status table
and the last chunk.

**Files.**

| File (under `state/`) | Holds |
|---|---|
| `drafts/planning.draft.md`, `drafts/reference/{factions,npcs,threads,threads_unratified}.md` | The document and the four reference files its reading contract names. `threads_unratified.md` holds the unattached thread notes verbatim (it exists, saying none, when there are none). |
| `drafts/planning_npcs_report.md` | Per NPC: model line / substituted by the dossier's sentence / fallback; and the Faction States selection and replacements. |
| `drafts/threads_report.md` | Ratified threads with notes in range (open, dormant or closed, and why), ambiguous names, ratified proposal members that no longer attach (alias removed?), the unattached count, and each Active Plots entry code replaced. |
| `threads/attach.json` | Code's map: note id → thread id, `"ambiguous"` or `null`. |
| `drafts/arc_report.md`, `budget_report.planning.json`, `annotations.md`, `missing_dossiers.planning.json` | As described here and in Step 5b. |

### Thread proposals — grouping the notes nobody owns

The unratified notes (`reference/threads_unratified.md`) are the queue of notes that need a decision. Three commands
move them into the registry, and the model is only in the first:

```bash
summary_native thread-propose --since 2 --until 70      # a model groups; code checks; the GM rules
# then /grounding/threads: Ratify (edit, split), Reject or Defer, one group at a time
summary_native synth planning --since 2 --until 70 --force
```

`thread-propose` needs `--since` and `--until` (`thread-propose needs --since
and --until: the thread notes of a chapter range, never all chapters`) and a
current corpus and checked notes. It also accepts `--max-input-chars N` (default
150000: the notes are sent in chapter-ordered batches no larger than this),
`--max-tokens`, `--dump-only` and the backend flags.

What it does, in order:

1. **Code attaches first.** Notes whose name equals a ratified title or alias are
   attached and never sent. Notes in a group you rejected or deferred are not sent
   either.
2. The rest are sent in batches with the ratified-thread list. **Each batch sees
   only the checked notes and the ratified threads**, never another batch's
   output. The model returns groupings as JSON: a suggestion.
3. **Code checks every group** and removes what the notes and the registry do not
   support: an unknown kind, a `continues` group naming a thread that is not in the
   registry, a member that is not an unattached checked note of this run, a member
   claimed by two groups (removed from *both*), an empty group. Every note left
   out is offered as a one-note `single` proposal, so none is lost. A batch whose
   output is not the JSON asked for becomes single-note proposals.
4. The groups are merged into the proposals file (`projections.yaml`
   `thread_proposals`, default `docs/ensemble/thread_proposals.yaml`), keeping
   every ruling by `key` (`g-` plus a hash of the member ids). A pending group the
   run replaces keeps its out-of-range members: a member outside `--since`..`--until`
   that no other proposal holds stays as a pending `single`, and the report and the
   terminal name the replaced group and those singles. A kept single may name a note a
   ratified thread now attaches (an alias added since the wide run); the next run whose
   range covers it resolves that. A member whose id is in no range's checked notes on
   disk is dropped from a replaced group and written out in full in the report; a
   pending proposal none of whose notes is on disk is kept untouched and named in the
   report and output every run (re-extract that range or reject it on the Threads
   page); rulings are never touched. If a checked-notes file is unreadable the run
   warns and judges nothing missing. It never writes the registry.

It prints `threads: 120 notes — 40 attached to 12 ratified threads, 80 unattached
→ 21 group proposals (9 single), 3 dropped (see propose_report.md)` and writes
`state/threads/propose.NN.{user,out}.md`, `propose_report.md` (what was dropped and
why, replaced groups with notes outside the range, pending proposals with no note on
disk, ratified
members that no longer attach, stale rulings, ambiguous names) and a run record.

**A proposal is a candidate the GM ratifies.** Grouping notes under one thread name
is an identity assertion, and it is yours. On the [Threads page](state_projection_howto.md#grouping-proposals-from-summary-native)
you edit the title, status, members and aliases before anything is written;
there is no one-click accept. Ratifying adds the thread (or log rows on an existing
one), and **every member's name becomes an alias**, so the next build attaches those
notes by exact match. Reject, Defer and splitting are covered there. If you later
remove one of those aliases, the notes it attached are unattached again: the next
`thread-propose` offers them again as pending single-note proposals and lists them
under "Ratified but no longer attached (alias removed?)" in `propose_report.md`
(and `threads_report.md`).

### Arc-score candidates

Arc scores are yours. The documents may surface *candidate events* that might
count toward a score, never a value, a total or a threshold.

- **party:** a `#### Candidate Arc Score Events` subsection under a character
  whose `party.yaml` entry has an `arc_score` mechanic file.
- **planning:** the Threat Tracker table has one row per NPC or faction with a
  mechanic file, columns `Score | Subject | Candidate events | Trigger text`. The
  candidates are in the third cell; the fourth is the mechanic file's path. A
  subject with none shows `—`.

One call per scored subject that has checked notes, from that subject's notes and
the mechanic file, nothing else. A trackless subject (no file) gets no call. Code
keeps a line `- <event> [cite] — trigger: "<text>"` only if it passes all three
checks; every dropped line is listed in `arc_report.md` with its reason:

| Drop reason | Meaning |
|---|---|
| `cite-not-in-notes` | A citation is missing, malformed, or not one of that subject's own checked notes' citations. |
| `trigger not verbatim` | The quoted trigger (at least 4 characters) is not verbatim in the mechanic file, or the line names no trigger. |
| `states a value` | The event text states a value, running total or threshold crossed: a score word with a number (`score of 5`, `a score of seven`), `now at N` / `is at N`, `pushes it to 5`, a signed delta (`Wrath +2`), a fraction (`(2/3)`), a count of strikes or ticks (`has 3 strikes`, `his third strike`), a meter filling, a threshold reached, or one of the mechanic file's own score names with a number (`gains 1 Obsession`). Ordinals (`3rd gate`), amounts with a unit (`500 gp`, `2 bells`) and street addresses (`3 Waterdeep Lane`) are not values. |

A false drop costs only a candidate you can read in `arc_report.md`, so the value
check errs towards dropping: it will drop some ordinary lines (a `+1 longsword`, "a
total of 12 guards", `2/3 of the guards`, `3 strikes on the ogre`). It was tightened in #526 from a table of
verdicts (`specs/034-chunked-party-planning/arc_value_check.md`) but has **not yet been
measured on real campaign output**; read the kept candidates as candidates. Phrasings
with no number or score word ("two more and he breaks", "doubles his Wrath") and Roman
numerals can still pass; the spec lists the known gaps.

### Annotation for party and planning

`annotate` runs at the end of `synth`, as for the other two documents, and adds
`⚠ later:`, `ℹ since:` and `⚠ unverified:` under lines; no line's text changes.
For these documents it scans the model-written sections line by line, **prose
paragraphs as well as bullets**. It skips what code built or what is not a claim:

- the Threat Tracker and the NPC Dossiers;
- Active Plots' `### Dormant threads` and `### Unratified thread notes` blocks;
- the `#### Candidate Arc Score Events` subsection (triggers are quoted from the
  mechanic file, not a chapter);
- the level line, the `_Full notes_` pointers and the labels.

Two things are **removed** (a rule, not a judgment, listed in `annotations.md`): a
player character listed as a companion, and a Faction States block named for a
player character. A line inside a real faction's block that merely mentions a
player character is a claim and stays.

**Subjects.** `⚠ later:` compares a line with the later notes about its subject: its
first bold name, else the `###` group it sits under. Party Overview and Party
Dynamics are free prose with neither, so a line there with no subject of its own is
about the whole party and gets the subject `Party`, the same token a whole-party
note carries (`- **Party** — fact [cite]`). It is compared with the later
whole-party notes only: the newest one, when it is cited after the line, appears
under it as `⚠ later: **Party** — … [ch NNN / …]`. A line with its own subject (a
bold character, or a group) keeps it and is compared with that character's notes.
An unbolded mention is never a subject (`The party holds **Brindol**.` still takes
Brindol, the first bold name, and a standalone bold label line such as
`**Where they are**` becomes a group), and a one-character note or a level row is
not whole-party evidence. `Party` is resolved before the registry, so an entity
aliased "Party" does not capture it. The implicit `Party` subject takes part in the stale check
only: two subject-less lines in different sections are not paired by the
cross-section check. The citation, quotation and mentioned-NPC checks run on every
line as before.

### Incomplete drafts for these two documents

Exit 3 and `<doc>.incomplete.md` also cover: `<label>: the model wrote no body`,
`<label>: the model wrote a heading (...)`, `<label>: the model wrote a level line
(...)`, and `<label>: the model wrote '#### Candidate Arc Score Events'`. A chunk
that is missing one of its sections still passes the extraction check (#515), so a
quiet section in `drops.md` is worth a look. Incremental rebuilds after a new
session are tracked in #512.

---

## Step 7 — compare with the live document

```bash
summary_native compare world_state --summaries-dir docs/summaries --since 2 --until 70 \
    --live docs/world_state.md
```

Read-only on both inputs. It prints a small table (numbers here are
illustrative)

```text
              bytes   lines  highest chapter (heuristic)
draft         52311     640  70
live          47902     588  66
diff: docs/summary_native/ch002-070/drafts/world_state.vs-live.diff
```

and writes the unified diff (`a/` = live, `b/` = draft). "Highest chapter" is
only the largest `ch N` / `Chapter N` mention in the text — a heuristic, handy
for spotting a live doc that stops at chapter 66. `compare` has no model call
and no staleness check; it needs `drafts/<doc>.draft.md` and the live file to
exist.

---

## Step 8 — review and promote by hand

The tool never writes `docs/<doc>.md`. (For `world_state` and `campaign_state`,
promotion also carries the timeline and `reference/`; `party` carries
`reference/party.md`; see [Promotion](#promotion) in Step 5b.) To promote:

1. Read `drafts/<doc>.draft.md` against the diff and its reports.
2. Fix what is wrong at its source (a summary, the registry, a dossier, a thread
   ruling), then `synth --force`. Prose edits happen only after promotion, in
   `docs/`, where the next build cannot overwrite them.
3. Copy it over the live file yourself, deleting the first-line HTML provenance
   comment if you do not want it in the live document. `git diff` and the commit
   are your record.

---

## What session prep may rely on — the documents are an index

All four chunked documents (`campaign_state.md`, `world_state.md`, `party.md` and
`planning.md`, built by `extract` → `synth` → `annotate`, plus `audit` for
campaign_state) are designed to be read by session prep as an **index**, not as
proof. The summaries stay the authority, and that holds for party and planning
exactly as for the first two: a level line, a Threat Tracker candidate, an
Active Plots entry and a dossier line are all things to navigate by and then
check. The
agreement is written down in
[`specs/033-chunked-grounding-docs/contracts/session-prep.md`](../../specs/033-chunked-grounding-docs/contracts/session-prep.md);
this section is what it means for you at the keyboard. The consumer is the
gm-assistant `gm-session-prep` skill, which lives in another repository and
has not adopted the contract yet. The draft skill text is
[`experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md`](../../experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md);
nothing in this repo installs it.

### What the documents promise

Four things. The first three are checked for world_state by
`tests/test_summary_native_state_sections.py` (`TestSessionPrepContract`) on the
fixture campaign, and party and planning are exercised by
`tests/test_summary_native_party.py` and `tests/test_summary_native_planning.py`.
What differs per document is noted in each item:

1. **Every content line carries a citation** `[ch NNN / target]` that resolves
   to a scene id (`NNN.SS`) or a named section (`npcs`, `locations`, `items`,
   `spells`, `moment`, `end`) of `docs/summaries/NNN-*.md`. A table row cites in
   its last column. Not counted: headings, the reading-contract blockquote, the
   italic pointer lines (`_Full notes: ..._`, `_Source: ..._`), annotation
   sub-bullets, the Timeline section (a pointer to the timeline file), an
   "Audit not run" notice, party's code-written `Level:` line, and planning's
   Threat Tracker table, whose rows name the GM's mechanic file rather than a
   chapter (the candidate events in its cells do cite).
2. **Each document opens with a reading contract.** A blockquote that names
   the three markers (`⚠ later:`, `ℹ since:`, `⚠ unverified:`), the citation
   grammar, the `reference/*.md` files that document points to
   (`world_state`: six and `canon_events_timeline.md`; `party`: `party.md`;
   `planning`: `factions`, `npcs`, `threads`) and says that anything the document
   does not settle is a decision for the GM. Planning's also says what the three
   Active Plots layers are and that the thread registry is the GM's.
3. **Every dossier-sourced line ends in `→ docs/npcs/<slug>.md`**, or in
   `(no published dossier — from checked notes)`: world_state's Key NPCs and
   planning's NPC Dossiers. The second form means there is no dossier to open: the
   line is the NPC's latest status and checked notes.
4. **No model rewrote a line after the code check.** After drafting, a line
   changes only by an annotation under it, or by removal of a player character
   listed as a companion or a Faction States block named for one.
   `annotations.md` in the drafts folder lists each one.

Two promises are specific to party and planning:

- **A level is a citation or a disclaimer.** Party's `Level: N [cite]` comes from
  a `[LEVEL]` row whose number the cited text states; otherwise the line says the
  summaries record none and shows the sheet's figure as the sheet's.
- **Arc scores are never stated.** The documents list candidate events with a
  quoted trigger; the score, its total and its threshold are the GM's.
  Planning's Active Plots lists only threads the GM has ratified; the rest sit in
  the unratified notes in `reference/threads_unratified.md` (planning carries only their count), and dormant threads in their own block.

The markers mean: `⚠ later:` is newer information about the same subject (where
they conflict, the later one wins); `ℹ since:` is the later status of someone the
line mentions (context, not a correction); `⚠ unverified:` is a quotation that is
not verbatim in the chapter it cites, or a citation that does not resolve (read
it as a paraphrase).

### What the contract asks of session prep

The skill, not this tool, does these. They are listed so you know what a prep
run should have done, and what to check if it did not:

1. **Index pass.** Read the state documents, following each one's reading
   contract, to decide what the session puts on stage.
2. **Read the last two summaries in full.**
3. **Verify pass.** For each NPC, item, faction or thread the prep *uses*,
   follow its citation (or its dossier pointer, or a search of the summaries) to
   the latest mention and confirm the state there. Background mentions are not
   verified.
4. **The summary wins** when it disagrees with a document.
5. **Tag provenance.** `[TABLE chNN NNN.SS]` for a verified state claim,
   `[DOC unverified: <doc>]` for one taken from a generated document unchecked.
6. **End with "Doc errors found".** One entry per disagreement: the document and
   line, what it says, what the summary says (with its citation), which the prep
   used. "none" when everything agreed.

### What to do with "Doc errors found"

That list is your fix-at-source queue. It is never patched in the generated
document. Fix the **summary** (then `build --force` and `synth --force` again),
the **entity registry**, a dossier's **authored file**, or rebuild, whichever the
entry points at. A citation that does not lead to the claim is itself a document
error: guarantee 1 says a citation *resolves*, not that it *supports* the line.
`audit` and `annotate` narrow that gap; they do not close it.

### What is not promised

- That a line is **true**. Only that it is cited, so it can be checked. The
  experiment that motivated this (round 5 in `experiments/20261007-chunked-state-docs/`)
  found a stale fact marked "verified" when the documents were the old,
  uncited ones; verification is only as good as the citation it follows.
- That the documents are current. The reading contract states the range they
  cover and that the last two summaries outrank them.
- That the skill has adopted any of this. Until the gm-assistant follow-up
  lands, prep behaves as it did before; the documents are still safe to read.

---

## The web page

Sidebar **Grounding Docs → Summary-native** (`/grounding/summary-native`). The
page invokes the CLI and reimplements none of it. Numbered steps —
Validate, Build corpus, Extract, Synthesize a draft, Audit, Compare with the live
document — an Annotate action per draft (with a dry-run preview), links to the
timeline, reference files and reports, then the validation report (possible duplicates listed separately) and a draft
list marking each `draft` or `incomplete`.

What it exposes per run: the summaries directory, the range (with **All
chapters**), the duplicate threshold, build `--force`, and for synthesis the
document, the party or planning config path, audit files, named subjects,
recent chapters, recurring minimum, max tokens, dump-only, force, the
model/backend selection and, for world_state and planning only, a
**"Write fallback lines for NPCs without a published dossier"** checkbox that is
unchecked on every load and never saved. `recent_chapters`, `recurring_min` and
`dup_threshold` fall back to `grounding.yaml`. The Parts control and the
upstream-draft pickers are gone. A request that carries `parts`, `world_state` or
`campaign_state` gets HTTP 400 with the CLI's refusal text; `fallback_npc_lines`
for party or campaign_state, and `name` / `recent_chapters` / `recurring_min`
for party, are 400 too.

The planning step also shows the **ratified-thread counts** of the last planning
build (ratified in range, open, dormant, unattached, ambiguous, and pending group
proposals), read from `state/threads/attach.json` and the proposals file, with a
link to the [Threads page](state_projection_howto.md#grouping-proposals-from-summary-native).
The Drafts list includes `reference/party.md`, `party_report.md`,
`planning_npcs_report.md`, `threads_report.md` and `arc_report.md`.
Annotate (with its dry-run preview) and the **word-budget panel** follow the
document picker for world_state, party and planning: the panel reads that
document's last `budget_report*.json` (words against each section's budget,
overruns flagged, nothing trimmed) and is absent until the document has been
built. `thread-propose` is run from the Threads page, not this one.

What it deliberately does **not** do: promote a draft, or edit `canon.yaml`.
Those are judgment steps and stay by hand.

**`--registry`, `--canon` and `--out-root` have no per-run control on the page.** They are
campaign-layout paths set once, so the routes never pass them; the CLI reads
`grounding.yaml summary_native.registry`, `canon_file` and `out_root` itself
(flag > config > default: `docs/entity_registry.yaml` auto-discovery,
`<out-root>/canon.yaml`, `docs/summary_native`). A per-run control for them would
invite two runs of the same range using different canons, and the page would not
show it. Change them in `grounding.yaml`, or use the CLI flag.

The page's Compare always diffs against `docs/<doc>.md`.

---

## Every refusal and exit code, decoded

| Exit | Meaning |
|---|---|
| `0` | Success (`validate`/`build`: no blocking problem; `synth`: draft written or `--dump-only`; `compare`: done). |
| `1` | `validate`, `build` or `synth` found **blocking** validation problems. The report was printed (`validate`/`build` also write it). |
| `2` | A refusal (bad range, bad input, mixed corpus, existing output, stale corpus, bad flag/config) or an argparse usage error. Message on stderr, prefixed `Error:`. |
| `3` | `synth` produced an incomplete document. `<doc>.incomplete.md` was written. |
| `4` | `synth` or `thread-propose`: the model call failed. See below. |

| Message (abridged) | What to do |
|---|---|
| `no summaries directory: pass --summaries-dir or set grounding.yaml summary_native.summaries_dir` | Give it a directory. |
| `…: lives under docs/ensemble; summary-native and ensemble corpora must never be mixed` | Point `--summaries-dir` at the real summaries, not at ensemble output. |
| `…: not a directory` / `…: no *.md summaries found` | Wrong path, or the directory holds no top-level `*.md`. |
| `no summary has a numeric chapter prefix; chapters present: none` | Every filename lacks a `NNN-` prefix. Rename them. |
| `--since N matches no file; chapters present: …` (also `--until`) | Pick a chapter in the list. |
| `--since A is after --until B; chapters present: …` | Swap or fix them. |
| `range A-B contains no file; chapters present: …` | Widen the range. |
| `registry D: no entity_registry.yaml found under D/docs/` | The `--registry` flag or `summary_native.registry` names a directory without one. Name the registry file, or a campaign root that has `docs/entity_registry.yaml`. |
| `invalid entity registry …` | The registry will not load; fix it (`registry check`). |
| `canon.yaml records not-a-duplicate rulings and link rulings for generic forms only; fix duplicates in the summary files` | `canon.yaml` has a key other than `not_duplicates` or `link_rulings`. Remove it; fix the summary instead. |
| `…: cannot read canon.yaml (…)` | Not valid YAML. |
| `…: not_duplicates must be a list of {category, a, b}` | Make it a list. |
| `…: not_duplicates entry N must be exactly {category, a, b}` | Wrong or extra keys in entry N. |
| `…: not_duplicates entry N: category 'x' is not one of npc, location, item, spell, ability` | Fix the category. |
| `…: not_duplicates entry N: a and b must be non-empty strings` | Fill both. |
| `…: holds ensemble artifacts (…); summary-native and ensemble corpora must never be mixed` | You pointed `--out-root` at an ensemble directory. Use another. |
| `…: manifest.json has kind 'x', not 'summary_native'` | Some other tool owns that directory. |
| `…: is not empty and has no summary-native manifest (found: …)` | Move your files out, or choose another `--out-root`. |
| `…: manifest.json is unreadable (…)` | Delete it and rebuild, or restore it. |
| `…: a summary-native corpus already exists; pass --force to rewrite it` | `build --force` if you mean it. |
| `…: the previous build did not finish; rerun with --force` | `build --force`. |
| `…: no manifest.json; run build first` (synth) | Run `build` for this range. |
| `…: the previous build did not finish; rerun build --force` (synth) | `build --force`. |
| `summaries changed since build — run summary_native build --force` | A summary changed after `build`. Rebuild, then synthesise. |
| `validation has blocking problems; fix the summaries, then build --force` | Printed after the report (exit 1). Fix the files. |
| `entity registry changed since build — run summary_native build --force` | The registry differs from the one `build` used. Rebuild, then synthesise. |
| `--audit applies to campaign_state only, not <doc>` | Drop it, or synthesise `campaign_state`. |
| `--party-config applies to party only, not <doc>` / `--planning-config applies to planning only, not <doc>` | Same. |
| `--parts is retired: …` / `--world-state is retired: …` / `--campaign-state is retired: …` | Drop it: every document is built one call per section, and none reads another's draft. |
| `audit file X: no such file` | A `track_files` entry or `--audit` path is wrong. |
| `…/<doc>.draft.md exists; pass --force to overwrite it` | You reviewed that draft. `--force` only if you mean to replace it. |
| `--party-config …: not found` / `…: unreadable (…)` / `…: no characters declared` / `party config: <name> sheet file missing: …` | Fix `config/party.yaml` or its sheet/backstory/arc-score paths. |
| `--planning-config X: no such file` | An explicit path that does not exist. (A missing *default* is not an error.) |
| `planning config: <name> arc score file missing: …` | Fix the arc-score path. |
| `no dossier has subject: X` (planning adds `(planning selects NPC dossiers only)`) | A `--name` matched no dossier subject. Check spelling against `dossiers/`. |
| a backend setup or model message | Missing key/endpoint, or an unsupported backend/model pair. |
| `no draft file at …` / `no live file at …` (compare) | Run `synth` first / check `--live`. |
| `Incomplete: …` + problem list (exit 3) | See [incomplete draft](#an-incomplete-draft-incompletemd-and-exit-3). Problems are `missing heading`, `headings out of order`, `unexpected heading`, `empty body`, `text before the first heading (no preamble allowed)`, `threat tracker must be empty: no arc scores configured`. |

`thread-propose` is a model step too: a batch that fails after one retry exits **4**, writes no proposal, and prints `batch i/N failed after one retry: …`. A model-call failure mid-run (a rate limit that exhausts retries, a dropped
connection) is not an exit-3 case. It exits **4**, no draft is written, and
stderr says where to look:

```text
Error: model call failed in part 1: RuntimeError: upstream 529 (see runs/world_state/<run_id>/record.json)
```

The run directory's `record.json` is saved first with
`check: {complete: false, error: …}`.

---

## A first run, end to end — Out of the Abyss

67 files, chapters 2–70, gaps at 33 and 66. All from
`~/out-of-the-abyss/out-of-the-abyss`.

**1. Validate and see everything wrong.**

```bash
summary_native validate --summaries-dir docs/summaries
# exit 1: 8 blocking — seven "# Session <date>" titles + 070 "# Chapter 66"
```

**2. Fix the titles in the summary files** (by hand, in your editor):
`015`, `016`, `019`, `054`, `065`, `067`, `068` become `# Chapter 15`,
`# Chapter 16`, … and `070` becomes `# Chapter 70`. The expected title is on
each finding line, so this is a single pass.

**3. Validate again; settle the duplicates.**

```bash
summary_native validate --summaries-dir docs/summaries
# exit 0. Read "Possible duplicates": correct the typos at file:line; for
# Short Sword / Short Sword +1 (genuinely different items) add a not_duplicates
# ruling to docs/summary_native/canon.yaml.
```

**4. Build.**

```bash
summary_native build --summaries-dir docs/summaries
# docs/summary_native/ch002-070/ — manifest.json says "complete": true
```

**5. world_state, then review it.**

```bash
summary_native synth world_state --summaries-dir docs/summaries
# → state/drafts/world_state.draft.md   (exit 3 instead? see the problems it printed; state/drafts/world_state.incomplete.md has the output)
```

Read and correct `docs/summary_native/ch002-070/state/drafts/world_state.draft.md`.

**6. campaign_state, audited against your tracking files.**

```bash
summary_native audit --summaries-dir docs/summaries --track-file <your tracking file>
summary_native synth campaign_state --summaries-dir docs/summaries
```

(Omit `--track-file` to use `campaign_state.track_files` from `grounding.yaml`.)
Anything in the tracking files that no summary supports comes back labelled
`NOT FOUND IN SUMMARIES`.

**6b. party and planning (extract first).**

```bash
summary_native extract --since 2 --until 70            # first run after upgrading: 0 cached
summary_native synth party --since 2 --until 70
# read state/drafts/party_report.md: Daz, Gyrgum, Thorin Giantfriend and Zalthir get a
# section each; Glabbagool, Jimjar and Ront are companions (reference/party.md), not sections.
summary_native thread-propose --since 2 --until 70     # 554 thread names, 550 of them seen once
# /grounding/threads: ratify, split, reject or defer each group; then
summary_native synth planning --since 2 --until 70     # needs published dossiers, or --fallback-npc-lines
```

Before ratifying anything there, `synth planning` still works: with an empty
registry every thread note lands in `reference/threads_unratified.md`, counted under "Unratified thread notes".

**7. Compare each draft against what is live.**

```bash
summary_native compare world_state --summaries-dir docs/summaries --live docs/world_state.md
summary_native compare campaign_state --summaries-dir docs/summaries --live docs/campaign_state.md
```

**8. Promote by hand.** Open the diffs, then copy the draft you are satisfied
with over `docs/world_state.md` (and so on). The tool does not do this step.

Later, if you edit a summary, `synth` refuses until you `build --force` — that
refusal is the tool telling you the drafts it would write no longer match the
files.

---

## What it does not do

It does not write or repair a summary, merge two headings, record a
misspelling as an alias, read a draft you did not name, write a live grounding
document, or call a model outside `synth`, `extract` and `audit`. Each absence is a requirement with a
test behind it (`tests/test_summary_native_no_llm.py`, the retrieve/render
isolation test), not a missing feature.
