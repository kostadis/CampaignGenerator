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

The summary-native path does not re-extract. A deterministic parser reads the
structure your summaries already declare (scenes, entity sections, memorable
moments), writes an ordered evidence corpus, and only then calls a model — once
per document — to render a draft from that corpus. Nothing in it is chunked or
re-read for facts.

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
  range_since: null                  # the UI reads these; the CLI does not
  range_until: null
  recent_chapters: 4                 # default
  recurring_min: 10                  # default
  dup_threshold: 0.88                # default
  parts: 0                           # default (0 = one call)
```

The CLI reads `summaries_dir`, `out_root`, `dup_threshold`, `recent_chapters`,
`recurring_min` and `parts` from that group; a flag always wins. With no
summaries directory from either place it refuses (see
[the refusal table](#every-refusal-and-exit-code-decoded)).

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
campaign root); `--registry` overrides it. A pair the registry holds apart
(`distinct` or `rejected_aliases`) is not listed.

### Two ways to clear a listing

**1. Fix the summary files (the usual answer).** Correct the spelling at the
`file:line` shown, re-run `validate`, and the pair disappears. If you had
already built, `build --force`.

**2. Rule that the two are genuinely different**, in `canon.yaml`
(`<out-root>/canon.yaml`, default `docs/summary_native/canon.yaml`; `--canon`
overrides). It is hand-authored, shared by every range, and read-only to the
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

`synth <doc>` renders one document from the built corpus. `<doc>` is one of
`world_state`, `campaign_state`, `party`, `planning`. It makes exactly the
model calls you ask for (one, or `--parts` many), and nothing else.

**Order matters, and the human checkpoint is between the calls.** A later
document may read an earlier *draft*, but only one you name and only after you
have reviewed it. The tool never picks up an unreviewed draft on its own.

```bash
# 1. world_state, from the corpus alone
summary_native synth world_state --summaries-dir docs/summaries --since 2 --until 70

#    ... you review drafts/world_state.draft.md, fixing it ...

# 2. campaign_state, with the reviewed world_state as context
summary_native synth campaign_state --summaries-dir docs/summaries --since 2 --until 70 \
    --world-state docs/summary_native/ch002-070/drafts/world_state.draft.md
```

### What goes into the prompt

Always: the full chronology, all memorable moments, and the **selected**
dossiers. Selection (deterministic, recorded in `selection.json`):

1. **named** — any dossier whose subject matches a `--name` (case-insensitive
   equality; an unmatched name is a refusal);
2. **recent** — a dossier whose last chapter is within `--recent-chapters`
   (default **4**) of the range end; `0` means every dossier;
3. **recurring** — a dossier with at least `--recurring-min` observations
   (default **10**).

`planning` selects NPC dossiers only. Each dossier is tagged in the prompt
with why it was chosen. Then, depending on the document:

| Flag | Doc | What it does |
|---|---|---|
| `--world-state FILE` | `campaign_state`, `party`, `planning` | A GM-reviewed world_state draft, supplied as an `UPSTREAM DRAFT (GM-reviewed)` block for consistency. Never a substitute for the summaries. Refused for `world_state`. |
| `--campaign-state FILE` | `party`, `planning` | Same, for a reviewed campaign_state draft. Refused for `world_state` and `campaign_state`. |
| `--audit FILE …` | `campaign_state` only | Tracking/planning/module files, supplied under `AUDIT QUESTIONS — NOT EVIDENCE`. Each item is checked against the summaries and tagged; a claim with no support is labelled `NOT FOUND IN SUMMARIES` rather than stated as history. **Default:** `campaign_state.track_files` from `config/grounding.yaml`. With none, the `## Audit: Tracking Claims` section is still required and says so in one line. Refused for other docs. |
| `--party-config FILE` | `party` only | The roster. Default `<config dir>/party.yaml`. Each character's sheet, backstory and arc-score mechanic is included, labelled by path. A missing or empty roster, or a missing sheet/backstory/arc-score file, is a refusal. Refused for other docs. |
| `--planning-config FILE` | `planning` only | Tracked NPCs/factions and arc scores. Default `<config dir>/planning.yaml`; an *absent default* means "no arc scores configured", an *absent explicit* path is a refusal. Refused for other docs. |

Relative paths resolve against the campaign root. Every flag in this table is
refused (exit 2) for a document it does not apply to, e.g.
`--world-state does not apply to world_state`.

### Outline check, `--parts`, `--max-tokens`

Each document has a fixed ordered outline (the H2 headings in
`pipelines/summary_native/prompts/<doc>.outline.yaml`):

| Doc | Headings, in order |
|---|---|
| `world_state` | Party · Factions and Powers · Key NPCs · Locations · Items and Artifacts · Active Threats and Open Pressures · Canon Events Timeline |
| `campaign_state` | Completed Encounters & Quests · Resolved Plot Threads · NPC Current States · Active Quests & Open Threads · Party Current Situation · Audit: Tracking Claims |
| `party` | Party Overview · Characters · Party Dynamics |
| `planning` | Threat Tracker · NPC Dossiers · Faction States · Active Plots · DM Notes |

After the call the output is checked **deterministically** against the outline:
no text before the first heading, every heading present exactly once and in
order, no extra `## ` heading, and a non-empty body under each. A document that
fails is never written as a draft.

- `--parts N` splits the outline into N contiguous groups and makes N calls,
  each told the full outline but asked for only its group; each part is
  checked against its own group. `0` or `1` (default) is a single call.
  Use it when a document is too long for one response.
- `--max-tokens N` is per call; default **16000**.

### The Threat Tracker sentinel

For `planning`, when the planning config configures **no** arc score (or there
is no config), the `## Threat Tracker` body must be **exactly** the single line

```text
_No arc scores configured._
```

Anything else — an invented table, an empty section — fails the check
(`threat tracker must be empty: no arc scores configured`). The sentinel is
required, not just allowed: an empty section cannot be told apart from a
dropped or truncated one. With arc scores configured the model lists those and
only those, as candidate events with the trigger quoted verbatim — never a
current value or a threshold crossed.

### Backend and model

Same flags as the other synthesis tools: `--backend
{anthropic,dgx,openrouter,claude-code,codex-cli}`, `--model`, `--endpoint`
(with `--backend dgx`), `--batch` (anthropic only), and the
`--codex-reasoning-effort` / `--claude-code-effort` / `--[no-]claude-code-thinking`
knobs. The default backend is `anthropic` and the default model is whatever
`--help` prints (`claude-fable-5` today). A backend/model pair that cannot work
together is a refusal. `ANTHROPIC_API_KEY` is needed only for the `anthropic`
backend; each backend refuses for itself at the call.

### `--dump-only`

```bash
summary_native synth world_state --summaries-dir docs/summaries --dump-only
```

Writes the run directory (below) with the exact prompts and `record.json`,
makes no model call, writes no draft, and exits 0. It still requires a fresh
built corpus. Use it to read what the model would be given. It also skips the
existing-draft `--force` check, because nothing is overwritten.

### Where everything goes

```text
docs/summary_native/ch002-070/
  drafts/
    world_state.draft.md           ← complete: passed the outline check
    world_state.incomplete.md      ← failed it (exit 3)
    world_state.vs-live.diff       ← from compare
  runs/world_state/20261005T154310Z/
    selection.json                 ← which dossiers, and why each
    part-1.system.md               ← the exact prompts sent
    part-1.user.md
    part-1.out.md                  ← the model's raw output (absent for --dump-only)
    record.json
```

A new `runs/<doc>/<run_id>/` is created on every invocation and earlier runs
are never touched. `run_id` is a UTC timestamp (`20261005T154310Z`), with `-1`,
`-2`… appended if two runs start in the same second. `record.json` holds:
`doc`, `backend`, `model`, `max_tokens`, `parts`, `range`, the sha256 of the
corpus manifest, each `upstream` / `audit` / `config` file with its path and
sha256, the full `outline`, the `check` result (`{complete, problems}`, or
`"not run"` for `--dump-only`, or `{complete: false, error}` when the run died
before or during the model call), and `started` / `finished`.

A complete draft begins with a one-line HTML comment naming the doc, the range,
the run's `record.json` and the corpus manifest sha256.

### An incomplete draft: `.incomplete.md` and exit 3

```text
Incomplete: docs/summary_native/ch002-070/drafts/world_state.incomplete.md
  - missing heading: ## Canon Events Timeline
Retry with --parts N to write the outline in separate calls, or raise --max-tokens.
```

The output is kept for inspection as `<doc>.incomplete.md` and the command
exits **3**. An incomplete draft is not promotable. An existing
`<doc>.draft.md` is **kept** (stderr says `previous draft kept:
drafts/<doc>.draft.md (from run <id>)`); an existing `.incomplete.md` never
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
now (auto-discovered `docs/entity_registry.yaml`, or the `--registry` you pass;
none if absent) and compares it with the one recorded in `manifest.json`. If it
changed, it refuses:

```text
Error: entity registry changed since build — run `summary_native build --force`
```

`canon.yaml` does **not** make a corpus stale: it holds not-a-duplicate rulings
that change validation findings only, never the corpus. Pass `synth` the same `--registry` you gave `build`, or an auto-discovered registry will be compared instead.

---

## Step 6 — the other two documents

```bash
# party needs config/party.yaml (or --party-config)
summary_native synth party --summaries-dir docs/summaries --since 2 --until 70 \
    --world-state docs/summary_native/ch002-070/drafts/world_state.draft.md

# planning reads config/planning.yaml for arc scores; without one, the sentinel applies
summary_native synth planning --summaries-dir docs/summaries --since 2 --until 70 \
    --world-state docs/summary_native/ch002-070/drafts/world_state.draft.md \
    --campaign-state docs/summary_native/ch002-070/drafts/campaign_state.draft.md
```

Each is its own call, its own run directory and its own draft. Pass an
upstream draft only after you have reviewed it.

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

The tool never writes `docs/<doc>.md`. To promote:

1. Read `drafts/<doc>.draft.md` against the diff.
2. Fix what is wrong, in the draft. (Fix a *summary* error in the summary, then
   `build --force` and `synth --force` again — never patch around it.)
3. Copy it over the live file yourself, deleting the first-line HTML provenance
   comment if you do not want it in the live document. `git diff` and the commit
   are your record.

---

## The web page

Sidebar **Grounding Docs → Summary-native** (`/grounding/summary-native`). The
page invokes the CLI and reimplements none of it. Four numbered steps —
Validate, Build corpus, Synthesize a draft, Compare with the live document —
then the validation report (possible duplicates listed separately) and a draft
list marking each `draft` or `incomplete`.

What it exposes per run: the summaries directory, the range (with **All
chapters**), the duplicate threshold, build `--force`, and for synthesis the
document, upstream draft paths, party/planning config, audit files, named
subjects, recent chapters, recurring minimum, parts, max tokens, dump-only,
force, and the model/backend selection. `recent_chapters`, `recurring_min`,
`parts` and `dup_threshold` fall back to `grounding.yaml`.

What it deliberately does **not** do: promote a draft, or edit `canon.yaml`.
Those are judgment steps and stay by hand.

**`--registry`, `--canon` and `--out-root` are CLI-only.** They are
campaign-layout paths set once, so the routes never pass them and the CLI
resolves its own defaults: `docs/entity_registry.yaml` auto-discovery,
`<out-root>/canon.yaml`, and `grounding.yaml summary_native.out_root`. A
per-run control for them would invite two runs of the same range using
different canons, and the page would not show it. Set `out_root` in
`grounding.yaml`, or use the CLI flag.

The page's Compare always diffs against `docs/<doc>.md`.

---

## Every refusal and exit code, decoded

| Exit | Meaning |
|---|---|
| `0` | Success (`validate`/`build`: no blocking problem; `synth`: draft written or `--dump-only`; `compare`: done). |
| `1` | `validate`, `build` or `synth` found **blocking** validation problems. The report was printed (`validate`/`build` also write it). |
| `2` | A refusal (bad range, bad input, mixed corpus, existing output, stale corpus, bad flag/config) or an argparse usage error. Message on stderr, prefixed `Error:`. |
| `3` | `synth` produced an incomplete document. `<doc>.incomplete.md` was written. |
| `4` | `synth`: the model call failed. See below. |

| Message (abridged) | What to do |
|---|---|
| `no summaries directory: pass --summaries-dir or set grounding.yaml summary_native.summaries_dir` | Give it a directory. |
| `…: lives under docs/ensemble; summary-native and ensemble corpora must never be mixed` | Point `--summaries-dir` at the real summaries, not at ensemble output. |
| `…: not a directory` / `…: no *.md summaries found` | Wrong path, or the directory holds no top-level `*.md`. |
| `no summary has a numeric chapter prefix; chapters present: none` | Every filename lacks a `NNN-` prefix. Rename them. |
| `--since N matches no file; chapters present: …` (also `--until`) | Pick a chapter in the list. |
| `--since A is after --until B; chapters present: …` | Swap or fix them. |
| `range A-B contains no file; chapters present: …` | Widen the range. |
| `--registry D: no entity_registry.yaml found under D/docs/` | Pass the registry file, or a campaign root that has `docs/entity_registry.yaml`. |
| `invalid entity registry …` | The registry will not load; fix it (`registry check`). |
| `canon.yaml records not-a-duplicate rulings only; fix duplicates in the summary files` | `canon.yaml` has a key other than `not_duplicates`. Remove it; fix the summary instead. |
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
| `--world-state does not apply to <doc>` / `--campaign-state does not apply to <doc>` | Drop it; see the flag table for which documents take it. |
| `--world-state X: no such file` / `--campaign-state X: no such file` | Check the path. |
| `audit file X: no such file` | A `track_files` entry or `--audit` path is wrong. |
| `…/<doc>.draft.md exists; pass --force to overwrite it` | You reviewed that draft. `--force` only if you mean to replace it. |
| `--party-config …: not found` / `…: unreadable (…)` / `…: no characters declared` / `party config: <name> sheet file missing: …` | Fix `config/party.yaml` or its sheet/backstory/arc-score paths. |
| `--planning-config X: no such file` | An explicit path that does not exist. (A missing *default* is not an error.) |
| `planning config: <name> arc score file missing: …` | Fix the arc-score path. |
| `no dossier has subject: X` (planning adds `(planning selects NPC dossiers only)`) | A `--name` matched no dossier subject. Check spelling against `dossiers/`. |
| a backend setup or model message | Missing key/endpoint, or an unsupported backend/model pair. |
| `no draft file at …` / `no live file at …` (compare) | Run `synth` first / check `--live`. |
| `Incomplete: …` + problem list (exit 3) | See [incomplete draft](#an-incomplete-draft-incompletemd-and-exit-3). Problems are `missing heading`, `headings out of order`, `unexpected heading`, `empty body`, `text before the first heading (no preamble allowed)`, `threat tracker must be empty: no arc scores configured`. |

A model-call failure mid-run (a rate limit that exhausts retries, a dropped
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
# → drafts/world_state.draft.md   (exit 3 instead? retry with --parts 3)
```

Read and correct `docs/summary_native/ch002-070/drafts/world_state.draft.md`.

**6. campaign_state from the reviewed world_state, audited against your
tracking files.**

```bash
summary_native synth campaign_state --summaries-dir docs/summaries \
    --world-state docs/summary_native/ch002-070/drafts/world_state.draft.md \
    --audit <your tracking files>
```

(Omit `--audit` to use `campaign_state.track_files` from `grounding.yaml`.)
Anything in the tracking files that no summary supports comes back labelled
`NOT FOUND IN SUMMARIES`.

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
document, or call a model outside `synth`. Each absence is a requirement with a
test behind it (`tests/test_summary_native_no_llm.py`, the retrieve/render
isolation test), not a missing feature.
