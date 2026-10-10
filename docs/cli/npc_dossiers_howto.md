# NPC dossiers from summaries — how to actually use it

> Task-oriented walkthrough for the GM. **Start here for NPC dossiers built from
> your reviewed summaries.** What to run, in what order, what every report
> means, and what every refusal says. The *design* lives in
> [`specs/032-npc-dossiers-from-summaries/`](../../specs/032-npc-dossiers-from-summaries/)
> (`spec.md` and its Clarifications, `research.md` R1–R17, `contracts/cli.md`,
> `contracts/files.md`); this page is the operator's manual and documents what
> the code does. Moving an existing `docs/npcs/` into the new layout is a
> separate one-time job: [NPC dossier layout migration](npc_dossiers_migration.md).
> This feature extends [summary-native grounding](summary_native_howto.md); read
> its Step 0–3 first, because every command here starts from a built corpus.

## The things that confuse everyone first

**1. Exactly one step calls a model: `npc-draft`.** The pipeline is five
subcommands of the `summary_native` console script:

| Subcommand | Model? | What it does | Writes |
|---|---|---|---|
| `npc-link` | no | attaches every scene and memorable moment that names an NPC to that NPC's evidence dossier | `evidence/`, `link_manifest.json`, `link_report.{md,json}` |
| `npc-draft` | **yes** | compresses one NPC's evidence into a readable dossier, then verifies and composes it | `draft/`, `gm/`, `runs/<stamp>/` |
| `npc-verify` | no | re-checks a draft against the evidence; edits nothing | `draft/<stem>.verify.md` |
| `npc-compose` | no | draft + your Secrets → the GM dossier; or creates an empty authored file | `gm/<stem>.md` |
| `npc-publish` | no | the only writer of `docs/npcs/<slug>.md` | `docs/npcs/<slug>.md`, `publish_log.json` |

What the model decides: **prose only** — how to compress verified evidence into
sentences. Identity (which NPC a line belongs to), order, attribution, scope
and status come from your authored summaries, the entity registry,
deterministic rules, or you. A draft is a leaf output: if one is 10% wrong,
nothing downstream inherits the error, because only a copy you have reviewed
and published reaches the gm-assistant skills.

**2. A draft is not a dossier until you publish it.** Nothing the pipeline
writes under `docs/npcs/summary_native/` is read by a skill. The skills read
`docs/npcs/<slug>.md`, and only `npc-publish` writes those files, only when you
name the NPCs (or say `--all`).

**3. Only global NPCs are drafted.** An NPC is *global* when it is a registry
entity of `type: npc` with `scope: persistent` **and** is not a player
character. A player character is any character named in
`config/players.yaml` `plays` (exact name or exact alias). Out of the Abyss
files Daz, Gyrgum, Zalthir and Thorin as `npc`; they are excluded by
`players.yaml`, not by type. Excluded NPCs are still *linked* (their evidence
file exists) — they are just never drafted. Everything else (one-off NPCs, local
NPCs) is the next feature.

**4. Your words live in a file no tool writes.** Corrections and GM-only secrets
go in `docs/npcs/authored/<slug>.authored.yaml`. Manual edits reach the model;
Secrets never do. See [Writing an authored file](#writing-an-authored-file).

**5. Fix the summaries, not the dossier.** A wrong fact in a draft is almost
always a wrong or missing line in a summary. A hand-edit to a generated file is
discarded by the next run (compose even warns you). Corrections that belong to
the dossier go in the authored file.

---

## Step 0 — one-time setup

1. **Migrate `docs/npcs/`** if the campaign has loose files there. The readers
   refuse with the migration command until you do. See
   [the migration page](npc_dossiers_migration.md).
2. **Install the console script into the server's venv**
   (`uv pip install -e . --python ~/.venvs/main/bin/python`) so the web page can
   spawn `summary_native npc-*`. The packaged word list (used by `npc-link`) ships
   with the package; an editable install resolves it. Symptom when skipped: the
   page's buttons fail with `Stream error — check terminal.`
3. **Have a registry.** `npc-draft` refuses without `docs/entity_registry.yaml`
   (see [Every refusal](#every-refusal-and-exit-code-decoded)). `npc-link` and
   `npc-verify` still run; without a registry linking matches only each NPC's own
   headings. Build one with `registry init` / `registry import-inventory`.
4. **Build the corpus** for the range you want:
   `summary_native build --since 2 --until 70` (summary-native how-to, Step 3).
5. **Optional: `config/npc_dossiers.yaml`.** A strict file; an unknown key
   refuses. Every key is optional:

   ```yaml
   npc_root: docs/npcs/summary_native   # default
   recent_chapters: 4                   # default; narrowing flag defaults
   recurring_min: 10                    # default
   max_tokens: 16000                    # default
   draft:
     backend: dgx                       # default
     model: qwen3.8-flash-next          # default
     mode: chunked                      # chunked | one-shot
     chunk_chars: 60000                 # default
   ```

   Precedence is flag > this file > default. There is no `endpoint` key (see
   [Which endpoint](#which-endpoint-the-dgx-backend-uses)). `summaries_dir`,
   `registry`, `canon_file` and the chapter range stay in `grounding.yaml
   summary_native` — they are spelled in one place.

Run every command **from the campaign root**, with the same `--since`/`--until`
at every step. The range names the folder everything lives in:
`docs/npcs/summary_native/ch002-070/`. Below, `R` means that folder.

```text
R/
  link_manifest.json   link_report.md   link_report.json
  evidence/<stem>.md             one per NPC corpus dossier (222 in OOTA 2-70)
  draft/<stem>.md                the model's draft (or <stem>.incomplete.md)
  draft/<stem>.verify.md         the trust report
  draft/index.json               draft keys, for "skipped (unchanged)"
  gm/<stem>.md                   draft + Secrets, composed
  runs/<stamp>/                  every prompt, every model output, record.json
```

`<stem>` is the corpus stem (`npc_jimjar`); `<slug>` is the published name
(`jimjar`, `ilvara-mizzrym`: lowercase, every run of non-alphanumerics becomes
`-`). Generated folders use the stem; everything under `docs/npcs/` and
`authored/` uses the slug.

---

## Step 1 — link

```bash
summary_native npc-link --since 2 --until 70
```

Deterministic, no model, byte-identical on unchanged input. For every NPC in
the corpus it writes `evidence/<stem>.md`: the NPC's own `## NPCs` entry from
each summary, plus **every scene and every memorable moment** whose text names
the NPC, whole and verbatim, in chapter order, each with file and line. Linked
items are labelled `(mentioned)`, and the lines that name the NPC are listed
under `Mention lines`. The header (`first_seen`, `last_seen`, `chapters`,
`n_entries`, `n_scenes`, `n_moments`) is computed.

A *moment* starts at a paragraph that opens with `>`, `**` or `- `; any other
paragraph attaches to the moment before it. Each `- ` line is its own moment.

Stdout, from the Out of the Abyss run on chapters 2–70:

```text
NPCs linked: 222
scenes linked: 1619
moments linked: 1045
withheld forms: 8 ambiguous, 11 generic (unruled), 0 generic (ruled never)
evidence: docs/npcs/summary_native/ch002-070/evidence
```

and, on **stderr**, the run-end warning whenever any form is withheld:

```text
warning: 8 ambiguous, 11 generic (unruled) name forms withheld from linking — see docs/npcs/summary_native/ch002-070/link_report.md
```

Exit is still `0`. A warning is a fix list, not a failure.

### How a name form is decided

A *form* is an exact string that names an NPC: a heading in the NPC's corpus
dossier, or the registry entity's exact `name` / `aliases`. Nothing is
inferred — no first-name alias, no case folding, no similarity. A form is:

- **ambiguous** when the exact string belongs to more than one
  `(type, canonical)` across the registry and every heading of every category
  (`Bahamut` is a deity and an NPC). Withheld. **It cannot be ruled**; the
  summaries are fixed.
- **generic** when it is a single word found (case-folded) in the packaged
  English word list (`Stool`, `Spider`, `Rust`). Withheld until you rule on it.
- otherwise **linkable**. Ambiguous beats generic.

A form inside a longer form is not a separate occurrence: `Sarith` inside
`Sarith Kzekarit` belongs to the longer name.

### Ruling on a generic form

Edit `docs/summary_native/canon.yaml` (the same file that holds 031's
`not_duplicates`):

```yaml
link_rulings:
  - {form: Stool, ruling: safe}     # link every "Stool" to the NPC
  - {form: Spider, ruling: never}   # a creature, never the NPC; keep it withheld
```

Each entry is exactly `{form, ruling}`; `form` is an exact, case-sensitive
string; `ruling` is `safe` or `never`. Changing `canon.yaml` makes the link
output stale, so re-run with `--force`:

```bash
summary_native npc-link --since 2 --until 70 --force
```

`never` keeps the form withheld but removes it from the warning count (the
stdout line shows it as `generic (ruled never)`). The file still cannot express
a merge or an alias; no entry names an entity.

### Reading `link_report.md`

`link_report.json` is the same data for the UI. Sections, in order:

| Section | Meaning | What you do |
|---|---|---|
| **Ambiguous forms** (withheld) | one block per form: `Collides with: deity Bahamut, npc Bahamut`, then every `file:line` where it occurs | Fix the summaries so each name belongs to one entity, or fix the registry (`Dawnbringer`, a sentient sword filed as an item *and* an NPC, is fixed at source: registry `type: npc`, its `## Items` entries refiled under `## NPCs`). Then `build --force` and `npc-link --force`. |
| **Generic forms** (withheld unless ruled `safe`) | the form and every occurrence (`Stool`: 122 occurrences) | Rule it in `canon.yaml` as above. |
| **Registry NPCs named without a heading (no dossier)** | `mention-without-heading`: a registry NPC that scenes or moments name but no summary gives a `## NPCs` heading (OOTA: 19, including the player characters Daz, Gyrgum and Zalthir) | Add a heading in the summary if the NPC matters. Nothing is linked for it. |
| **`players.yaml` `plays` names that match no registry entity** | `player-character-unresolved`: you declared that a player plays a character the registry does not know, so it cannot be excluded as a PC | Fix the name in `players.yaml` or add the alias to the registry. Never guessed. |
| `stale-link-ruling` / `link-ruling-unneeded` | a ruling for a form that occurs nowhere in range, or one that is neither generic nor ambiguous (so it has no effect) | Non-blocking. Delete the dead ruling when convenient. |

A one-letter name that is not in the word list (OOTA's `Y`) is *not* withheld
by any rule; it is tracked in CampaignGenerator#503.

### Global or not: the evidence header

```yaml
subject: Thorin
global: false
exclusion: player character (players.yaml)
```

`global: true, exclusion: null` is what `npc-draft` selects. Other exclusions you
may see: `not in registry`, `registry scope chapter-4: local` (a non-persistent
registry scope is deferred to the local-NPC feature).

---

## Step 2 — draft

```bash
summary_native npc-draft --since 2 --until 70 --name Jimjar "Ilvara Mizzrym" --dump-only   # inspect first
summary_native npc-draft --since 2 --until 70 --name Jimjar "Ilvara Mizzrym"               # the real run
```

One model call per chunk plus one (the default **chunked** mode), or exactly
one call per NPC (**one-shot**). Then, for each NPC and with no model, it
verifies the draft and composes the GM dossier.

### Choosing the NPCs

| Flag | Selects |
|---|---|
| `--name NAME…` | exactly these global NPCs. A registry alias resolves (`Ilvara` → `Ilvara Mizzrym`); nothing else is guessed |
| `--all` | every global NPC with evidence in range (222 linked in OOTA 2–70, fewer global) |
| `--recent-chapters N` / `--recurring-min N` | 031's rules (seen in the last N chapters; at least N entries), applied within the global NPCs, plus any `--name`d |
| *(none of the above)* | same as `--all` |

`--all` cannot be combined with a narrowing flag. Every run writes
`runs/<stamp>/selection.json`: who was included and why, and every excluded NPC
with its reason (`narrowed out`, `no evidence in range`, `player character
(players.yaml)`, `registry scope …: local`, `not in registry`).

### Chunked, the default

Whole chapters, in order, are packed into chunks of at most `--chunk-chars`
(default 60000) characters; a chapter is never split. Jimjar's 39 chapters become
6 chunks. For each chunk:

```text
chunk (code) → map call → map check (code) → stitch (code) → reduce call → assemble (code)
```

- **Map call** writes `## History with the Party`, `## Notable Quotes` and
  `## Arc-Score Candidates` for that chunk only.
- **Map check** is code, not a model. It drops any History or Arc bullet with no
  citation, an invalid citation, or a citation outside the chunk; any bullet
  with a `"…"` span that is not verbatim in the chunk; and any Notable Quote
  that is not verbatim, has a bad citation, or is not in the item it cites.
  Nothing a map call wrote reaches the reduce call unchecked. Every drop is
  logged — see [Reading `drops.md`](#reading-dropsmd).
- **Stitch** joins the survivors in chapter order and removes exact duplicates.
  Nothing is merged or reworded.
- **Reduce call** reads the verified notes and the last chunk's evidence and
  writes the remaining sections (`Identity`, `Personality and Motivations`,
  `Last Observed State`, `Relationships`).
- **Assembly** puts the sections in outline order. A map section whose every
  item was dropped reads `_(none verified)_`.

Why chunked is the default: coverage. A one-shot call over a large pack
under-reads; chunking makes the model attend to every chapter and lets code check
each piece before the next call sees it.

Progress prints as each call returns:

```text
Jimjar: map 1/6 (ch 002-007) 49.7s
...
Jimjar: reduce 55.9s
Jimjar: drafted
  verify: fail (not-found 2); advisories: typography-normalised 5
```

### One-shot, and other backends

```bash
summary_native npc-draft --since 2 --until 70 --name Jimjar --mode one-shot
summary_native npc-draft --since 2 --until 70 --name Jimjar --backend anthropic --model claude-sonnet-5-5
summary_native npc-draft --since 2 --until 70 --name Jimjar --backend claude-code     # subscription
```

- Default backend/model are `dgx` / `qwen3.8-flash-next`: the local Spark model,
  the cheapest. Sonnet 5.5 read better in the A/B; it is a flag away.
- `--backend` accepts `anthropic | dgx | openrouter | claude-code | codex-cli`.
  `anthropic` needs `ANTHROPIC_API_KEY`; `claude-code` (subscription) and `dgx`
  need no key. `--batch` is Anthropic-only (50% cost, blocks and polls).
- A backend other than the default with no `--model` uses the command-wide default
  model (`CAMPAIGN_MODEL`, else `claude-fable-5`), never the Spark model id.
- `claude-code` also takes `--claude-code-effort` and
  `--claude-code-thinking | --no-claude-code-thinking`; `codex-cli` takes
  `--codex-reasoning-effort`.
- The one-shot prompt carries the whole evidence file; it fits the Spark's context
  even for the largest OOTA pack (Glabbagool, about 431K characters), but chunked
  is still the default, for coverage rather than fit.

### Which endpoint the `dgx` backend uses

The endpoint is deliberately **not** declared in `npc_dossiers.yaml`. It resolves,
in order, through the shared client:

1. `--endpoint URL`
2. the `DGX_ENDPOINT` environment variable
3. the `dgx_endpoint` entry in `~/.config/campaigngenerator/wiring.yaml` (or the
   file `MNEME_WIRING` selects)

If none is set it refuses, and does not fall back to the Anthropic API:

```text
Error: --backend dgx: no endpoint. Pass --endpoint, set DGX_ENDPOINT, or render `dgx_endpoint` into ~/.config/campaigngenerator/wiring.yaml or the selected MNEME_WIRING file. Refusing to fall back to the Anthropic API — you asked for the local box.
```

(Exit 2, and the run's `record.json` has `stopped_at.error`.) The OOTA validation
runs passed `--endpoint` for exactly this reason. The same `--endpoint` flag also
works in the UI's argv.

### `--dump-only`, `--force`, "skipped (unchanged)"

`--dump-only` writes `runs/<stamp>/` (`selection.json`, `record.json`, the prompts)
and calls no model; the index is untouched. In chunked mode it writes the map
prompts only — the reduce prompt needs map output. Read `<stem>.map01.user.md`
to see exactly what the model will be given; **confirm no Secrets are in it** (they
cannot be, see below).

Each NPC has a *draft key*: a hash of the prompt inputs, backend, model,
`max_tokens`, mode and chunk size. If the key is unchanged and the draft exists,
the NPC is `skipped (unchanged)` — no model call, but it is still re-verified and
re-composed. `--force` re-drafts regardless. Changing a summary, the registry,
`canon.yaml`, `players.yaml`, a `manual` item, the backend, the model, the mode or
the chunk size changes the key. Changing only `secrets` does not, so a
Secrets-only edit takes effect with no model call.

### Outcomes and exit codes

Per NPC, one of:

| Line | Meaning |
|---|---|
| `Jimjar: drafted` | `draft/<stem>.md` written, `.incomplete.md` removed |
| `Jimjar: skipped (unchanged)` | nothing re-drafted |
| `Jimjar: incomplete (missing: …)` | the outline check failed; `draft/<stem>.incomplete.md` written, no `<stem>.md`, **not published or verified** |
| `Jimjar: failed` | a model call failed; the run stops |

| Exit | Meaning |
|---|---|
| `0` | every selected NPC drafted or skipped (verification results do **not** change this) |
| `1` | blocking summary-validation problems; the report is printed |
| `2` | a refusal (see the table below) |
| `3` | at least one NPC `incomplete` |
| `4` | a model call failed. The remaining NPCs are not attempted; `record.json` has `stopped_at: {stem, stage, error}` (`stage` is `map03`, `reduce`, …) |

Gate on verification with `npc-verify` (exit 5), not on `npc-draft`.

---

## Writing an authored file

```bash
summary_native npc-compose --since 2 --until 70 --init Jimjar
# created docs/npcs/authored/jimjar.authored.yaml
```

`--init` creates an empty file for each name, and refuses a name for which one
exists (`… already exists; it is yours and is never overwritten`). It composes
nothing. The file is yours: **no tool ever overwrites or edits it.**

```yaml
subject: Jimjar            # must equal the NPC's canonical name (refused otherwise)
manual:                    # numbered by position: the first item is [manual 1]
  - Jimjar is a deep gnome, not a drow; the ch 12 summary misnames his people.
  - He has a standing bet with Eldeth about who reaches the surface first.
secrets: |
  Owes 400 gp to a Blingdenstone fence; the party doesn't know.
```

Allowed keys: `subject` (required), `manual` (a list of non-empty strings),
`secrets` (a string). Anything else is refused, and so is a `manual` that is not
a list.

### `manual` — corrections the draft must obey

- Goes into the draft prompt, numbered `[manual 1]`, `[manual 2]`… in list order.
  The model is told these take precedence over the evidence and must cite them.
- **Re-ordering the list renumbers the edits**, so it changes the draft key and the
  next `npc-draft` re-drafts. Append new edits at the end.
- Add a manual edit when the summaries are wrong in a way you will fix later, or
  when you want a fact the evidence never states. If you can fix the summary, do
  that instead — a summary fix makes every pipeline right.
- After editing `manual`, run `npc-draft --name …` (it will say `drafted`), then
  read the verify report's *Manual edits* section.

### `secrets` — GM-only, never seen by a model

- Read only by `npc-compose` (and `npc-draft`'s compose step), which copies it
  **byte-for-byte** into `gm/<stem>.md` under `## Secrets` and nowhere else.
- It is structurally outside every prompt: drafting reads the authored file through
  a function that returns `manual` and has no way to return `secrets`. Error
  messages never quote file content, so a YAML mistake does not echo a secret into
  a log. A test asserts that the secrets text appears in no draft and in no
  `runs/*/*.user.md`.
- The published dossier **does include Secrets** (the gm-assistant skills are GM
  tools and some need GM-only facts). Publish is a GM-only act; do not paste
  `docs/npcs/<slug>.md` to players.
- After a Secrets-only edit, run `npc-compose --name Jimjar` (or `npc-draft`): the
  new secret is in `gm/`, with no model call.

### Dossier edits that are not allowed

Do not edit `draft/<stem>.md`, `gm/<stem>.md` or `docs/npcs/<slug>.md` by hand. The
next `npc-draft` or `npc-compose` rewrites `draft/` and `gm/` (compose warns
`… had an unrecorded hand-edit; discarded (put corrections in
docs/npcs/authored/jimjar.authored.yaml)`), and `npc-publish` refuses to replace a
published file whose content you changed. Put the correction in `manual`.

---

## Step 3 — verify

```bash
summary_native npc-verify --since 2 --until 70 --name Jimjar
```

Deterministic. Checks `draft/<stem>.md` against that NPC's evidence, writes
`draft/<stem>.verify.md`, and **never edits the draft**. `npc-draft` already runs
the same check per NPC (the `verify:` line); run `npc-verify` on its own after you
have touched a draft, an authored file or a summary, or to gate a script on exit 5.
Without `--name` it checks every `draft/<stem>.md` in range (not `.incomplete.md`).

```text
Jimjar: fail (not-found 2); advisories: typography-normalised 5
warning: Jimjar: manual edit 2 dropped — "He has a standing bet with Eldeth ..."   (stderr, only when a manual edit is dropped)
verified 1 drafts: 0 pass, 1 fail (not-found 2)
```

| Exit | Meaning |
|---|---|
| `0` | every draft passes |
| `5` | at least one fails |
| `2` | refusal (below) |

### Reading `<stem>.verify.md`

```text
# Verification: Jimjar
**Verdict: fail**
## Totals          citations 281 (281 valid); 82 notable quotes (moment 35, scene 47);
                   31 other quoted spans; 85 history bullets needing a citation; 0 manual edits
## Failures        - not-found (line 24): "is not interested in winning. He is interested in betting" -- quoted span not verbatim in this NPC's evidence
## Manual edits    (the caveat, then each [manual N] beside the draft lines that cite it)
## Advisories (do not change the verdict)
```

Every finding carries the **draft line** it came from. The verdict is `fail` if
there is any failure and `pass` otherwise; advisories never change it.

**Failures** (counted in the stdout line):

| Status | Meaning | What you do |
|---|---|---|
| `invalid` | a citation that is not in the in-range corpus (`[ch 035 / 005.05]`: scene id's chapter part must equal the chapter) | Re-draft, or fix the line with a `manual` edit. |
| `outside-evidence` | a real citation, but to an item that does not name this NPC | Same. The model cited a neighbour's scene. |
| `not-found` | a quoted span (a Notable Quote, or any `"…"` span in History, Last Observed State, Arc candidates) is not verbatim in this NPC's evidence. The detail says when it is verbatim *elsewhere in the summaries* | A paraphrase in quote marks, or a span stitched across a gap. Re-draft or reword. |
| `citation-mismatch` | a Notable Quote is in the evidence but not in the item its citation names, or has no citation | Same. |
| `uncited` | a History bullet with no citation (`[ch NNN / …]` or `[manual N]`). A bullet with cited bullets nested under it is a *label* and needs none | Re-draft. |
| `manual-dropped` | a `[manual N]` for N in the authored list that is cited **nowhere** in the draft | Re-draft; if the model keeps dropping it, shorten the edit. |
| `manual-invalid` | a `[manual N]` with N outside the list | Re-draft; it usually means you removed an item and the draft is stale. |

**Advisories** (listed, never failing):

| Advisory | Meaning |
|---|---|
| `typography-normalised` | the quote matches the evidence only after treating curly and straight quote marks and apostrophes as equal. The summaries mix both styles, the transcripts have none. Safe to publish; the fix is in the summaries (kostadis/campaigns#371) |
| `status-claim-unsupported` | a Last Observed State or History line uses a status word (`alive, dead, died, killed, slain, missing, departed, captured, freed`) that appears **nowhere** in this NPC's evidence. It is a prompt to check, not a finding — the word may be a fair paraphrase |
| `placeholder-speaker` | a Notable Quote's attribution is missing or a placeholder (`Speaker`, `Unknown`, `Narrator`, `Someone`, `N/A`) |

Quotes about an NPC may be spoken by anyone, and may come from an entry, a scene
or a moment, as long as they are verbatim in *this NPC's* evidence and cited to the
item they come from (`— Speaker [ch 021 / moment]`). A quote anywhere in the
summaries but outside this NPC's evidence is `not-found` — the report says so.

### "Used, not meaning"

The *Manual edits* section opens with a fixed caveat:

> This check confirms each manual edit was used (cited at least once). It does not
> confirm that the edit's meaning survived the rewrite: read each cited passage
> beside its edit.

That is literal. The check proves `[manual 1]` appears; it cannot prove the sentence
it sits in still says "deep gnome, not a drow". Under each edit the report lists the
draft lines that cite it, or `DROPPED: not cited anywhere in the draft`. **Read the
cited line beside the edit before you publish.** A passing verify is a mechanical
trust report, not a review.

### Reading `drops.md`

Chunked drafting writes `runs/<stamp>/<stem>.drops.md`: everything the map check
removed before the reduce call, with the reason. Verify checks the *final* draft;
`drops.md` is the audit of what never got that far.

```text
# Map-check drops: Ilvara Mizzrym
2 dropped across 3 chunks. Every drop is listed with its reason.
## Chunk 050-052
kept {'history': 15, 'quotes': 2, 'arc': 4}, dropped {'history': 0, 'quotes': 1, 'arc': 0}, typography-normalised 0
- [quotes] not-found: > "The bride — Zuggtmoy herself — bringing chaos and mayhem." — Ilvara (via GM description) [ch 051 / entry]
## Chunk 053-054
- [history] uncited: - Status not established in the summaries.
- [quotes] kept, typography-normalised: > "daddy issues" or "mommy issues" — Kaelira [ch 053 / 053.04]
```

Drop reasons you will see: `uncited`, `invalid-citation`, `outside-chunk` (a
citation to a chapter that is not in this chunk), `quoted-span-not-found` (a
`"…"` span in a History or Arc bullet is not verbatim), `not-found` and
`citation-mismatch (…)` (Notable Quotes). Lines marked `kept, typography-normalised`
and `kept, advisory placeholder-speaker` were kept and are listed for your attention.
Many drops of one kind point at one prompt or model weakness; one or two per NPC
is routine.

A section header of `_(none verified)_` in the draft means every item of that section
was dropped in every chunk.

---

## Step 4 — compose

`npc-draft` composes for you. Run `npc-compose` yourself only after editing
`secrets`, or to compose an NPC that has an authored file but no draft:

```bash
summary_native npc-compose --since 2 --until 70 --name Jimjar
# Jimjar: composed docs/npcs/summary_native/ch002-070/gm/npc_jimjar.md
```

Without `--name` it composes every NPC that has a draft or an authored file.
Everything is validated before anything is written, so a bad authored file stops
the run with no partial output. Compose never touches the draft or the authored
file.

`gm/<stem>.md` is the draft (minus its provenance comment) followed by
`## Secrets` (byte-for-byte, or `_(none authored)_`). An NPC with no draft yet
composes as `_(not yet drafted)_` plus its Secrets; `npc-publish` refuses that.
A hand-edit to a `gm/` file is detected from the sha256 in its own header and
reported on stderr before being overwritten:

```text
warning: docs/npcs/summary_native/ch002-070/gm/npc_jimjar.md had an unrecorded hand-edit; discarded (put corrections in docs/npcs/authored/jimjar.authored.yaml)
```

---

## Step 5 — publish

```bash
summary_native npc-publish --since 2 --until 70                    # refuses: no selection
summary_native npc-publish --since 2 --until 70 --name Jimjar
summary_native npc-publish --since 2 --until 70 --all              # every NPC with a GM dossier
summary_native npc-publish --since 2 --until 70 --authored-all     # hand-built dossiers, verbatim
```

Publishing is always an explicit act: `--name`, `--all` or `--authored-all`.
`npc-publish` writes `docs/npcs/<slug>.md` and
`docs/npcs/summary_native/publish_log.json`, and nothing else; it never deletes and
never writes under `authored/`.

Two sources, one gate:

- **summary_native** — `gm/<stem>.md`. Every `[manual N]` is rewritten to `[GM]`
  (the published file does not carry the numbered list); chapter citations stay;
  `## Secrets` is included. Needs a passing verification.
- **hand-built** — `docs/npcs/authored/<slug>.md` (for example `gm-npc-build`
  output), copied verbatim. No verification applies.

Both sit under a one-line provenance header:

```text
<!-- published by summary_native npc-publish | source: summary_native | npc: Jimjar | range: ch002-070 | draft run: 20261006T230652Z | draft sha256: … | authored sha256: … | verify: pass | published sha256: … -->
<!-- published by summary_native npc-publish | source: hand-built | path: docs/npcs/authored/eelrich-vane.md | sha256: … | verification: not applicable | published sha256: … -->
```

`published sha256` is the digest of everything below that line; it is how the next
publish notices you hand-edited the file. `verify: fail(forced)` and
`verify: unverified(forced)` mark a `--force` over a failed or missing verdict.

Stdout, one line per NPC; **a refusal for one never stops the others**:

```text
Jimjar: published (summary_native)
Ilvara Mizzrym: refused (verification failed; see docs/npcs/summary_native/ch002-070/draft/npc_ilvara_mizzrym.verify.md)
```

Exit `0` when every selected NPC published; `2` when any refused.

When an NPC has both a GM dossier and a hand-built dossier, pass
`--source summary_native|hand-built`, or it refuses.

### `--force`

`--force` publishes despite (a) a failed or missing verification, (b) a target file
the tool did not publish (no provenance header), or (c) a target whose content
differs from `publish_log.json` (hand-edited). It records each override in the
output (`published (summary_native) [forced: verification failed]`). Use it only
after you have read the verify report. For (c), prefer moving the correction into
the authored file and re-publishing.

---

## A/B the Spark against Claude

The point of the exercise is a fair comparison: same NPC, same evidence, same
verifier. A draft keys on backend and model, so a second run re-drafts rather than
skipping — but it **overwrites** `draft/<stem>.md`, so copy the first one aside.

```bash
R=docs/npcs/summary_native/ch002-070
summary_native npc-draft --since 2 --until 70 --name Jimjar --backend anthropic --model claude-sonnet-5-5
summary_native npc-verify --since 2 --until 70 --name Jimjar
cp -r $R/draft /tmp/ab-claude
summary_native npc-draft --since 2 --until 70 --name Jimjar --backend dgx --force
summary_native npc-verify --since 2 --until 70 --name Jimjar
diff <(grep -A12 '^## Totals' /tmp/ab-claude/npc_jimjar.verify.md) <(grep -A12 '^## Totals' $R/draft/npc_jimjar.verify.md)
```

Both get a `verify.md` of the same shape, so citation validity, quote fidelity,
uncited bullets and dropped manual edits are directly comparable. Also compare
`runs/<stamp>/<stem>.drops.md` for each run (the Spark's map call is where its
weakness shows) and `runs/<stamp>/record.json` for per-chunk `secs`. Remember what
the check cannot see: **style and reading quality**. Read the two drafts.

Use `--mode one-shot` on one side to compare chunked against one-shot with the same
model. No `--endpoint` is needed when the wiring file carries `dgx_endpoint` (see
the endpoint section). Note that `spark` resolves only through `~/.ssh/config`, so
an HTTP endpoint must use the address, not the alias.

---

## Every refusal and exit code, decoded

| Exit | Meaning |
|---|---|
| `0` | Success. For `npc-draft`: every NPC drafted or skipped. For `npc-publish`: every selected NPC published |
| `1` | Blocking summary-validation problems (all `npc-*` commands run 031's validation first). The report is printed |
| `2` | A refusal. Message on stderr, prefixed `Error:`. `npc-publish`: at least one NPC refused (the others still published) |
| `3` | `npc-draft`: at least one NPC `incomplete` |
| `4` | `npc-draft`: a model call failed |
| `5` | `npc-verify`: at least one draft fails |

`validation has blocking problems; fix the summaries, then build --force` follows
the report on exit 1. Everything in the summary-native refusal table
([summary-native how-to](summary_native_howto.md#every-refusal-and-exit-code-decoded)) —
bad range, missing summaries directory, malformed `canon.yaml`, bad registry —
applies here too, with the same fixes.

### `npc-link`

| Message (abridged) | What to do |
|---|---|
| `…; run summary_native build` (corpus missing or incomplete) | `summary_native build --since A --until B` for this range. |
| `summaries changed since build — run summary_native build --force` / `entity registry changed since build — run summary_native build --force` | Rebuild, then link. |
| `<R>: linked output already exists; pass --force to rewrite it` | `--force`. Safe: output is deterministic and no hand-authored file lives in `R`. |
| `<R>: evidence/ already exists without a link manifest; pass --force to rewrite it` | Same. |
| `<R>/link_manifest.json is not an npc_link manifest; refusing to overwrite it` | Another tool owns that folder. Choose another `--npc-root`. |
| `link ruling on 'X': the form is ambiguous (it names deity 'X' and npc 'X'); an ambiguous form cannot be ruled - fix the summaries so each name belongs to one entity, then remove the ruling from canon.yaml` | Fix the summaries or registry, delete the ruling. |
| `…canon.yaml: link_rulings must be a list of {form, ruling}` / `link_rulings entry N must be exactly {form, ruling}` / `entry N: form must be a non-empty string` / `entry N: ruling 'x' is not one of safe, never` / `entry N: form 'X' is ruled twice` | Fix `canon.yaml`. |
| `canon.yaml records not-a-duplicate rulings and link rulings for generic forms only; …` | `canon.yaml` has a key other than `not_duplicates` or `link_rulings`. |
| `npc_dossiers.yaml: <key>: <problem>` | The config has an unknown key or invalid value (an `endpoint` key, a blank `npc_root`, `chunk_chars: 0`). |

### `npc-draft`

| Message (abridged) | What to do |
|---|---|
| `no global NPCs are declared (no entity registry found); build a registry with registry init / registry import-inventory` | There is no registry. Build one. |
| `…; run summary_native build` / the stale-summaries and stale-registry messages above | Rebuild. |
| `no link output for this range; run summary_native npc-link` | Link first. |
| `link_manifest.json is unreadable; run summary_native npc-link --force` / `… is not an npc_link manifest; …` | `npc-link --force`. |
| `link output is stale (corpus manifest\|registry\|canon\|wordlist\|players changed); run summary_native npc-link --force` | One of the inputs changed since you linked. `npc-link --force`. The `players` case is a `players.yaml` edit. |
| `evidence/ no longer matches link_manifest.json; run summary_native npc-link --force` | An evidence file was edited or removed. Re-link; never edit `evidence/`. |
| `--all cannot be combined with --name, --recent-chapters or --recurring-min` | Pick one. |
| `--name X: not a global NPC (not in registry)` | `X` is not a registry NPC (or an alias of one). |
| `--name X: not a global NPC (no evidence in range)` | In the registry but named in no summary heading in this range. |
| `--name X: not a global NPC (player character (players.yaml))` | A declared player character. Never drafted. |
| `--name X: not a global NPC (registry scope chapter-N: local)` | A non-persistent registry scope. Deferred to the local-NPC feature. |
| `the selection is empty (N narrowed out, M player character (players.yaml), …)` | Your narrowing flags matched nothing; the counts say why. |
| `two selected NPCs share a slug and would share one authored file; drafting refused for both (…)` | Two canonical names slug to the same file name. Rename one in the registry. |
| `docs/npcs/authored/<slug>.authored.yaml: …` (see the authored-file table below) | Fix the authored file. |
| `--chunk-chars must be a positive integer` | Pass a positive number. |
| a backend setup message, notably `--backend dgx: no endpoint. …` | [Which endpoint](#which-endpoint-the-dgx-backend-uses). |
| `Error: model call failed for X at map03: … (see <R>/runs/<stamp>/record.json)` (exit 4) | Rate limit, dropped connection, endpoint down. Re-run the same command: NPCs already drafted are `skipped (unchanged)`. |
| `warning: X: the model wrote its own header; stripped (the header is computed)` | Harmless. The header is always computed by code. |

`incomplete (missing: …)` problems are the outline check's: `missing heading: …`,
`headings out of order (…)`, `unexpected heading: …`, `empty body: …`, `text before the
first heading (no preamble allowed)`. The model stopped early or restructured the
document. Re-run with `--force`, or a larger `--max-tokens`.

### `npc-verify`

| Message (abridged) | What to do |
|---|---|
| `no draft dossiers in range; run summary_native npc-draft` | Draft first. An `.incomplete.md` is not a draft. |
| `--name X: no evidence for this NPC in range` | Check the spelling against `evidence/`. |
| `--name X: no draft dossier in range; run summary_native npc-draft` | Not drafted yet. |
| an authored-file message | Fix `authored/<slug>.authored.yaml`. |

### `npc-compose`

| Message (abridged) | What to do |
|---|---|
| `<name>: no NPC with that name has evidence or a draft in this range` | Spelling, or wrong range. |
| `<name>: has neither a draft dossier nor an authored file to compose from` | Draft it or `--init` it. |
| `--init composes nothing; do not combine it with --name` | One or the other. |
| `Error: <name>: not a known NPC (no evidence in this range, not a registry NPC)` (`--init`) | Not a name the tool knows; nothing is created for it. |
| `Error: …/<slug>.authored.yaml already exists; it is yours and is never overwritten` (`--init`) | Expected; edit the existing file. Exit 2, but names already free were created. |

### Authored-file errors (`npc-draft`, `npc-verify`, `npc-compose`)

| Message (abridged) | What to do |
|---|---|
| `…: not valid YAML at line N` | Fix the syntax. The message never quotes the file, so a secret is not echoed. |
| `…: must be a mapping with a subject (and optional manual and secrets)` | The file is empty or a list. |
| `…: unknown key(s) x; allowed: manual, secrets, subject` | Remove or rename the key. |
| `…: subject is required` | Add `subject:`. |
| `…: subject 'A' does not match the NPC 'B'; was the file renamed or copied?` | `subject:` must equal the canonical name that the file name's slug belongs to. |
| `…: manual must be a list of non-empty strings` / `manual item N must be a non-empty string` | Fix the list. |
| `…: secrets must be a string` | Use a block scalar (`secrets: |`). |

### `npc-publish`

| Message (abridged) | What to do |
|---|---|
| `no selection: give --name NAME, --all or --authored-all (publishing is always explicit)` (exit 2, whole request) | Say which. |
| `…publish_log.json: unreadable publish log (…); fix or remove it (it can be rebuilt from the headers in docs/npcs/)` | Fix or delete the log. |
| `no GM dossier in ch002-070 and no hand-built dossier for this name` | Nothing to publish under that name. |
| `no GM dossier in ch002-070; run summary_native npc-draft` | Not drafted or composed. |
| `…/gm/<stem>.md has no GM-dossier header; run summary_native npc-compose` | Compose it. |
| `…/gm/<stem>.md has no draft dossier behind it (not yet drafted)` | A Secrets-only GM dossier. Draft first. |
| `…/draft/<stem>.md: draft header missing or unreadable; re-run npc-draft` | Re-draft. |
| `verification failed; see …/draft/<stem>.verify.md` | Read the report; re-draft or fix. `--force` only after reading it. |
| `not verified; run summary_native npc-verify (or --force)` | No verdict exists (e.g. only an `.incomplete.md`). |
| `both sources exist: … and …; choose with --source summary_native\|hand-built` | Say which. |
| `no hand-built dossier docs/npcs/authored/<slug>.md` | `--source hand-built` with no such file. |
| `slug collision: A, B all map to 'x'` | Two canonical names share a slug. |
| `docs/npcs/<slug>.md exists and was not published by summary_native (no provenance header)` | A hand-made file is in the way. Move it into `authored/`, or `--force`. |
| `docs/npcs/<slug>.md was edited by hand since it was published; move the correction into docs/npcs/authored/<slug>.authored.yaml` | Do that and re-publish, or `--force`. |

---

## A first run, end to end — Out of the Abyss

On a copy of the OOTA workspace (67 summaries, chapters 2–70), validated on
2026-10-06 against this feature's real code. The live campaign was not written to.

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
summary_native build --since 2 --until 70
summary_native npc-link --since 2 --until 70
```

Link results (the goldens, GM ruling 2026-10-06): 222 NPCs, 1619 scenes, 1045
moments linked; 8 ambiguous and 11 generic forms withheld.

| NPC | entries | scenes | moments |
|---|---:|---:|---:|
| Jimjar | 33 | 71 | 43 |
| Glabbagool | 30 | 94 | 48 |
| Eldeth Feldrun | 24 | 36 | 8 |
| Stool | 16 | 0 (withheld, generic) | 0 |
| Ilvara Mizzrym | 6 | 26 | 14 |

Withheld ambiguous forms: Bahamut, Clan Ironhead, Clan Thrazgad, Council of
Savants, Gray Ghosts, Dawnbringer (236 occurrences), Entémoch, Ogrémoch. Withheld
generic: Gargoyle, Irony, Nibbles, Rust, Sergeant, Skeletons, Spanner, Spectator,
Specters, Sprig, Stool (122 occurrences). Ilvara's evidence spans ten chapters
(2, 3, 31, 32, 49–54), where her `## NPCs` entries cover only six: the scenes and
moments are what was missing. Thorin reads `global: false`, `exclusion: player
character (players.yaml)` and is still linked (261 moments). Ruling `Stool` `safe` in
`canon.yaml` and re-running `npc-link --force` links its scenes and moments.

Then draft three NPCs with the defaults (chunked, `dgx`, `qwen3.8-flash-next`,
60000 characters):

```bash
summary_native npc-draft --since 2 --until 70 --name Jimjar "Ilvara Mizzrym" "Eldeth Feldrun"
```

| NPC | Chunks | Spark time | Citations valid / total | Notable Quotes | Map drops | `npc-verify` |
|---|---:|---:|---|---|---:|---|
| Jimjar | 6 | 277 s (reduce 56 s) | 281 / 281 | 82 (35 moment, 47 scene) | 6 | fail: not-found 2; 5 typography-normalised |
| Ilvara Mizzrym | 3 | 125 s (reduce 38 s) | 131 / 131 | 12 (6 moment, 6 scene) | 2 | **pass**; 1 typography-normalised |
| Eldeth Feldrun | 3 | 140 s (reduce 46 s) | 169 / 171 | 11 (1 entry, 2 moment, 8 scene) | 2 | fail: invalid 1, outside-evidence 1; 1 status-claim-unsupported |

How to read it:

- **Ilvara passes.** Her `verify.md` lists no failures; the one advisory is
  `"daddy issues" or "mommy issues"` matching only after quote-mark folding. Her
  `drops.md` shows the two items the map check removed before the reduce call —
  one quote that was not verbatim (`"The bride — Zuggtmoy herself — …"`) and one
  uncited History bullet (`Status not established in the summaries.`). They never
  reached the draft.
- **Jimjar fails on two spans**, both inside History bullets: a paraphrase in quote
  marks (`"is not interested in winning. He is interested in betting"`) and a
  stitched quote (`"either I win 10 platinum pieces or we're all dead. …"`).
  Neither is a Notable Quote; every Notable Quote passed. Re-draft with `--force`
  (a draft is non-deterministic, so the spans will usually change), or fix the
  wording another way. Nothing publishes while the verdict is `fail`.
- **Eldeth fails on citations in one paragraph** (draft line 22, in Personality and
  Motivations): `[ch 035 / entry; ch 035 / 005.05]` is `invalid` (a scene id whose
  chapter part is 005, not 035), and `[ch 008 / 008.02; ch 008 / moment]` is
  `outside-evidence` (real items, but they do not name Eldeth). Her one
  `status-claim-unsupported` advisory is on the Last Observed State paragraph:
  `"departed" appears nowhere in the evidence`. It is a prompt to open chapters 54
  and 55 and decide whether "departed the group" is a fair paraphrase of what the
  summaries say, not a defect on its own.
- **Without a narrowing flag**, `npc-draft` is `--all`. The run's `selection.json`
  lists every other NPC as `narrowed out`, and Thorin as excluded for `player
  character (players.yaml)`.
- Every model call, prompt and output for the run is under
  `runs/20261006T230652Z/`, with a `record.json` holding per-chunk timings, drop
  counts and the verification verdict per NPC.

Then the human part:

```bash
summary_native npc-compose --since 2 --until 70 --init Jimjar     # write manual / secrets
$EDITOR docs/npcs/authored/jimjar.authored.yaml
summary_native npc-draft   --since 2 --until 70 --name Jimjar --force
summary_native npc-verify  --since 2 --until 70 --name Jimjar     # read verify.md, incl. Manual edits
summary_native npc-publish --since 2 --until 70 --name Jimjar
head -1 docs/npcs/jimjar.md                                       # published by … verify: pass
```

Check afterwards: the draft cites `[manual 1]` and never repeats a corrected
fact; `grep -c 'SECRET' draft/npc_jimjar.md runs/*/npc_jimjar.*` finds 0;
`docs/npcs/jimjar.md` carries `[GM]` where the draft carried `[manual N]` and
contains your Secrets.

---

## The web page

**NPCs → Dossiers** runs the same subcommands with the same argv (the server log
shows it) and shows the same files; Link, Draft, Verify, Compose and Publish are
buttons. Draft stays disabled until you choose a selection mode, and Publish needs
explicit NPC names or an explicit "all". The Grounding → Summary-native page has
no NPC stages. The NPC page does not edit an authored file; you edit it in your
editor.

## What it does not do

## Scheduling and verification

`npc-draft` accepts the same `--endpoints`, `--parallel`, and `--resume` spellings
as the summary-native model operations. `npc-verify --parallel` remains local:
verification is deterministic and model-free, and never submits an LLM call.

- It never creates or edits a summary, an authored file, a hand-built dossier or
  the registry.
- It does not draft one-off or local NPCs (a registry scoped by time and place is
  the next feature), or player characters.
- It does not publish automatically, and it never writes `docs/npcs/<slug>.md`
  except through `npc-publish`.
- It does not rewrite the existing distilled dossiers. The migration moves them,
  byte-identical, into `docs/npcs/distilled/`.
- It cannot judge whether a draft is *good*. Verification proves every quote is
  real, every citation points at this NPC's own evidence and every manual edit was
  used. Whether the dossier reads right is yours to decide before you publish it.
