# State Projection — how to actually use it

> Task-oriented walkthrough for the GM. What to run, in what order, and what
> each error message means. The *design* lives in
> [`docs/system/flow-state-projections.md`](../system/flow-state-projections.md)
> (the flow) and [`docs/config/projection-isolation.md`](../config/projection-isolation.md)
> (the config split) — this page is the operator's manual.

## The one thing that confuses everyone first

**State Projection has two halves, and only the second one has a UI.**

```
   half 1 — BUILD THE STORES              half 2 — RENDER THE SECTIONS
   (CLI only, no UI, you run these)       (CLI or the /grounding/projections page)

   event_spine update      ──┐
   thread_registry propose ──┼──►  docs/ensemble/events.jsonl      ──┐
   thread_registry add/log ──┘      docs/thread_registry.yaml        │
                                    docs/ensemble/thread_proposals.yaml
   (already yours from ensemble)    docs/ensemble/merged_dossiers/  ──┼──►  grounding_sections build
   (already yours by hand)          docs/party.md, planning_notes.md  │        │
                                    docs/tracking*.txt              ──┘        ▼
                                                            docs/grounding_sections/<doc>/*.md
                                                                       │
                                                                       ▼
                                                            docs/projections/<doc>_draft.md
                                                                       │
                                                            you diff + promote by hand
```

If you open the **State Projection** page in the web UI on a campaign where
half 1 has never run, every row says `unbuilt` or `no-input` and the rebuild
button produces errors. That is the expected behaviour, not a bug — the page
renders *projections of stores*, and the stores do not exist yet.

Neither `~/out-of-the-abyss/out-of-the-abyss` nor `~/Phandalin/Phandalin` has
an `events.jsonl` or a `thread_registry.yaml` today (checked 2026-08-01), so
both need half 1 before the page shows anything useful.

## Step 0 — one-time setup (do this first, it is probably your actual blocker)

The three CLIs are new console scripts. If your venv predates them, the CLI
says `command not found` and the **UI page returns a 500 / "Failed to load
sections"** — the server shells out to `grounding_sections list --json` and
the file isn't there.

```bash
cd ~/src/CampaignGenerator
uv pip install -e . --python ~/.venvs/main/bin/python   # the venv the server runs under

ls ~/.venvs/main/bin/ | grep -E 'event_spine|thread_registry|grounding_sections'
#   → all three must be listed
```

Verify which venv a running server uses if you are unsure:

```bash
tr '\0' '\n' < /proc/$(pgrep -f 'server.main' | head -1)/environ | grep VIRTUAL_ENV
```

No server restart is needed after the install — `console_script()` resolves
per request. **But** a server process started *before* the feature landed has
no `/api/projections` router at all; the symptom is different — the API URL
returns the SPA's `index.html` instead of JSON. That one needs a restart.

```bash
curl -s 'http://127.0.0.1:5001/api/projections/sections?doc=campaign_state' | head -c 80
#   JSON        → good
#   <!doctype   → stale server process, restart it
#   Internal Server Error → console scripts missing, see above
```

## Step 1 — you need an extraction corpus

Everything downstream reads the ensemble's per-chapter corpus:

```bash
ls docs/ensemble/per_chapter/*/merged.json | wc -l
```

If that is empty, this feature has nothing to project. Run the ensemble
workflow first ([`ensemble_workflow.md`](ensemble_workflow.md)).

`--corpus` is **required** on every CLI that takes it, deliberately: there is
no config default, so nothing can quietly mean "all chapters".

## Step 2 — build the event spine (deterministic, free)

```bash
cd ~/out-of-the-abyss/out-of-the-abyss

event_spine update --corpus 'docs/ensemble/per_chapter/*/merged.json'
#   → store docs/ensemble/events.jsonl: 1234 rows; replaced chapter(s): 1, 2, 3, …
```

Zero model calls. Re-running replaces rows only for chapters present in the
corpus; chapters absent keep theirs. Never hand-edit the store.

### If every event in a chapter reports the same `scene`

Rows are ordered by `(chapter, scene, seq)`, where `scene` is the `scene_index`
`ensemble_merge` stamped at extraction time — the index of the header-delimited
chunk the fact's quote came from. So the spine's scene resolution is decided
**upstream, by the headings of whatever document was extracted**, and cannot be
improved here. Re-running `event_spine update` on the same corpus will not
change it.

Two common causes, both fixed by re-extracting rather than by anything in this
page:

- **The chapter prose has no scene structure.** Chapters organised by in-world
  date (`## 8/1 of Taraksh 1495`) give a `scene` meaning "which day"; chapters
  with no `##` heading at all fall back to character-count chunking. A property
  of the source.
- **The extraction ran on a whole `session-summary.md`.** Its `## Summary` /
  `## Scenes` / `## NPCs` headings are H2s, so all the `###` scenes collapse
  into one chunk. `ensemble_batch --source auto` slices the scene body out
  automatically for the `summary` rung; a direct `ensemble session-summary.md`
  run does not. See
  [`ensemble_extraction.md`](ensemble_extraction.md#scene-boundaries--where-scene_index-comes-from).

To check what you actually have before building the spine:

```bash
python3 -c "
import json,glob,collections
for f in sorted(glob.glob('docs/ensemble/per_chapter/*/merged.json')):
    s=collections.Counter(x.get('scene_index') for x in json.load(open(f)))
    print(f.split('/')[-2][:44], 'distinct scenes:', len([k for k in s if k is not None]))"
```

A chapter reporting 1 distinct scene (or all `None`) will still project
correctly — events just order by `quote_offset` alone within the chapter,
losing the which-scene grouping.

Optionally project the standalone `recent_events.md` other pipelines read:

```bash
build_recent_events --corpus 'docs/ensemble/per_chapter/*/merged.json'   # update + render in one
# or just the render half:
event_spine render --window 4
```

`campaign_state`'s `recent_events` section reads the **store** directly, so
you do *not* need `recent_events.md` for it.

## Step 3 — threads (only needed for `planning`)

```bash
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
#   → wrote docs/ensemble/thread_proposals.yaml: 87 proposal(s), 87 pending GM review
```

Proposals are a harvest, not canon. Nothing is promoted automatically, and
your rulings survive a re-propose. Ratify the ones you want as canon:

```bash
thread_registry add --id demogorgon-rising --title "Demogorgon rising" --opened 12
thread_registry log --id demogorgon-rising --chapter 40 --change advanced \
                    --summary "The party learns the ritual site is Gauntlgrym" \
                    --quote "…"
thread_registry set-status --id demogorgon-rising --status resolved --chapter 61
thread_registry check          # invariants; runs automatically on every save
```

`--change` is one of `opened | advanced | resolved | reopened | abandoned`;
`--status` one of `open | dormant | resolved | abandoned` (resolving needs
`--chapter`). A save that fails `check` is refused outright.

Until `docs/thread_registry.yaml` exists, the `planning` doc's `threads`
section is `no-input` and a build of it fails loudly.

The one LLM verb here is `thread_registry speculate`, which writes to
`notes/thread_speculations.md` — clearly non-canon, and no pipeline reads it
except the optional `speculations` copy section.

## Step 4 — see what is stale

```bash
grounding_sections list --doc campaign_state
grounding_sections list --doc world_state
grounding_sections list --doc planning
```

```
dossiers: docs/ensemble/merged_dossiers (curated)
section          mode       state     inputs
recent_events    spine      stale     1 file(s)
tracking         tracking   optional  0 file(s)
party            copy       fresh     1 file(s)
```

| state | meaning | what to do |
|---|---|---|
| `fresh` | section file's `inputs-sha` matches its inputs' current bytes | nothing |
| `stale` | inputs changed since the last render | rebuild it |
| `unbuilt` | no section file yet | build it |
| `no-input` | a **required** input is missing on disk | go build that store (step 2/3) |
| `optional` | an optional input is missing | fine; it will be omitted from the draft |
| `per-npc` | the `npc_outlook` section — freshness is tracked per NPC block | see step 6 |

Freshness is content-derived (a sha of the exact input bytes), never mtime,
so `touch` changes nothing and a real edit is never missed.

## Step 5 — build the deterministic sections (free)

```bash
grounding_sections build --doc campaign_state
```

A build **without `--backend` never makes a model call.** Every LLM-bearing
section is skipped with a reason instead:

```
skipped: tracking (synthesis — pass --backend to render)
```

That is the no-implicit-spend guard, not a failure. Useful narrowing flags:

| flag | effect |
|---|---|
| `--sections a,b` | build only these (the UI always sends an explicit list) |
| `--force` | re-render even when the stamp says fresh |
| `--no-assemble` | render sections, skip writing the draft |
| `--window N` | override the spine section's chapter window (default 4; changing it makes the section stale) |

## Step 6 — build the LLM sections (this is where tokens are spent)

```bash
# world_state: four synthesis sections over type-scoped dossier subsets
grounding_sections build --doc world_state \
    --backend dgx --endpoint http://spark:8001/v1 \
    --model 'Qwen/Qwen3-Next-80B-A3B-Instruct-FP8'

# or on Claude
grounding_sections build --doc world_state --backend anthropic --model claude-opus-4-8
```

`--backend` accepts `anthropic | dgx | openrouter | claude-code`. `--batch`
(Anthropic only, 50% cost) is forwarded to the synthesis subprocess.

For `planning`'s per-NPC outlook blocks you must also say *which* NPCs —
salience is a GM decision and is never inferred from fact counts:

```bash
grounding_sections build --doc planning --sections npc_outlook \
    --npcs graz,jimjar,ront --backend dgx --endpoint … --model …
```

With no `--npcs`, the selection comes from `npc_*` entries in
`narrative_importance.yaml`'s `force_include`. With neither, the section is
skipped: `npc_outlook (no GM salience list)`.

## Step 7 — diff and promote by hand

The build assembles `docs/projections/<doc>_draft.md`. Promotion is unchanged
and still manual — nothing overwrites your live grounding doc:

```bash
diff docs/campaign_state.md docs/projections/campaign_state_draft.md
# happy? then:
cp docs/projections/campaign_state_draft.md docs/campaign_state.md
```

Read the top of the draft first. If any section was omitted, the draft opens
with an **`## INCOMPLETE DRAFT — N of M section(s) omitted`** block naming
each one and why. Diffing an incomplete draft against a populated live doc
makes the omitted sections look *deleted* — they were never rendered.

If *every* section was omitted, no draft is written at all (an empty draft
would diff as "delete everything"); the run says so on stdout instead.

## The web UI page

`/grounding/projections` → sidebar **Grounding Docs → State Projection**.

It does exactly two things: show the staleness table (the same rows as
`list --json`, provenance column included) and rebuild the sections you tick,
with the model/backend visible and overridable before the run.

It deliberately does **not** do: summary-map approval, the lineage report,
draft promotion, or editing `projections.yaml`. Those are judgment
checkpoints and stay CLI/skill-driven. There is no "rebuild all" default —
an empty selection is a 400, not "everything".

**Thread triage moved onto its own page (2026-08-26, #337).** This sentence
used to exclude it too. The exclusion had a cost nobody had priced: `threads`
is a *required* section of the `planning` doc, so `assemble()` refuses to
write any planning draft while `docs/thread_registry.yaml` is missing — and
no page mentioned that file, so every build dead-ended in a subprocess error
naming a path the UI gave you no way to create. See
[the Threads page](#threads-harvest-rule-maintain) below. The checkpoint did
not move: it is preserved by one-candidate-per-ruling and a form you confirm,
not by the absence of a button.

## Document → section reference

| doc | section | mode | reads | LLM? |
|---|---|---|---|---|
| `world_state` | `npcs` | synthesis | `npc_*` dossiers | yes |
| | `factions` | synthesis | `faction_*` dossiers | yes |
| | `locations` | synthesis | `location_*` dossiers | yes |
| | `world` | synthesis | `object_/monster_/event_/date_*` dossiers | yes |
| `campaign_state` | `recent_events` | spine | `stores.events` (window 4) | no |
| | `tracking` | tracking | `stores.tracking` glob + the spine | yes |
| | `party` | copy | `inputs.party` | no |
| `planning` | `threads` | threads | `stores.thread_registry` | no |
| | `emerging` | emerging | `stores.thread_proposals` (pending only) | no |
| | `npc_outlook` | npc_outlook | per-NPC dossier + registry | yes |
| | `speculations` | copy | `inputs.speculations` | no |
| | `factions` | synthesis | `faction_*` dossiers | yes |
| | `notes` | copy | `inputs.planning_notes` | no |

The section list itself is Python (`SPECS` in
`pipelines/grounding/grounding_sections.py`) and is not configurable — only
the *paths* it names come from config.

## `config/projections.yaml`

Optional. Every field has a working default, so a campaign with no file at
all behaves exactly as before. Location is fixed:
`<campaign>/config/projections.yaml` — there are no fallback probes.

```yaml
stores:
  events: docs/ensemble/events.jsonl
  thread_registry: docs/thread_registry.yaml
  thread_proposals: docs/ensemble/thread_proposals.yaml
  tracking: 'docs/tracking*.txt'          # a glob; zero matches just skips the section
inputs:
  dossiers: docs/ensemble/merged_dossiers
  dossiers_fallback: docs/ensemble/state_dossiers
  narrative_importance: docs/ensemble/narrative_importance.yaml
  party: docs/party.md
  planning_notes: docs/planning_notes.md
  speculations: notes/thread_speculations.md
output:
  sections_dir: docs/grounding_sections
  draft: 'docs/projections/{doc}_draft.md'   # MUST contain {doc}
  legacy_draft: 'docs/{doc}_draft.md'        # the pre-move path the gate checks
  recent_events: docs/recent_events.md
  recent_events_window: 0
selection: {}                                 # per-service model/backend override
```

There is **no UI editor** for this file. Edit it by hand, or:

```bash
curl -X PUT localhost:5001/api/projections/config \
     -H 'content-type: application/json' \
     -d '{"stores":{"tracking":"docs/tracking/*.txt"}}'
```

The schema is strict — an unknown key is a 400, and a `draft` without the
`{doc}` placeholder is rejected (it would collapse all three documents onto
one file).

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `grounding_sections: command not found` | console scripts not in the venv | step 0 |
| UI: `Failed to load sections` / 500 | same — the server shells out to that script | step 0 |
| API returns `<!doctype html>` | server process predates the router | restart the server |
| `error: section 'recent_events' input missing: ['docs/ensemble/events.jsonl']` | no event spine | step 2 |
| `error: section 'threads' input missing: [...thread_registry.yaml]` | no ratified registry | step 3 |
| `error: a pre-move draft still exists at docs/campaign_state_draft.md` | a draft from before the `docs/projections/` move | move or delete it by hand; the tool refuses rather than clobber it. Fires once per document |
| `skipped: tracking (no tracking lists)`, and `list` shows the section with `0 file(s)` | `stores.tracking` glob matched nothing | the default `docs/tracking*.txt` does **not** match files inside `docs/tracking/`. OOTA needs `stores.tracking: 'docs/tracking/*.txt'` |
| `skipped: … (synthesis — pass --backend to render)` | working as designed | pass `--backend`, step 6 |
| `skipped: … (no dossiers matched)` | the dossier dir has no `<prefix>_*.md` | run `facts_to_state` / the type-merge skill, or point `--dossiers-dir` at the right set |
| `skipped: npc_outlook (no GM salience list)` | no `--npcs`, no `npc_*` force_include | step 6 |
| section body opens with `_Dossiers: fallback (…state_dossiers)._` | no curated `merged_dossiers/` | expected on Phandalin; run the type-merge skill to get a curated set |
| `no draft written for X: nothing to assemble` | every section omitted | build the sections first — usually means the stores don't exist |
| Ensemble page 400s naming `recent_events_out` | those keys moved from `ensemble.yaml` to `projections.yaml` | delete `paths.recent_events_out` and `tuning.recent_events_window` from `config/ensemble.yaml` (both live campaigns already have a `.pre006.bak` from this) |

## A first run, end to end

```bash
cd ~/out-of-the-abyss/out-of-the-abyss

event_spine update --corpus 'docs/ensemble/per_chapter/*/merged.json'
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'

grounding_sections list  --doc campaign_state
grounding_sections build --doc campaign_state            # free
grounding_sections build --doc world_state \
    --backend dgx --endpoint http://spark:8001/v1 --model 'Qwen/…-FP8'

diff docs/world_state.md docs/projections/world_state_draft.md
```

Then, once you have ratified some threads, `--doc planning`.


## Threads: harvest, rule, maintain

`/grounding/threads`. The page that makes `docs/thread_registry.yaml` exist
without opening a terminal (#337). Everything on it is deterministic — **no
model is called and no credential is involved at any point**.

### The sequence

1. **Harvest.** Give one or more corpus globs (whitespace-separated), e.g.
   `docs/ensemble/per_chapter/*/merged.json`. **Resolve** lists the files that
   matched — files only, no chapter numbers — so you can see what you are
   about to read before reading it. **Run harvest** streams
   `thread_registry propose`. An empty corpus is refused: there is no
   configured default, because an implicit corpus is a silent "all".

   A harvest **never touches the registry**. It writes candidates only.

2. **Rule, one candidate at a time.** Each card shows the title, every other
   spelling the corpus used for it, the chapters it appears in, and its
   evidence — the paraphrased fact with the verbatim quote underneath it,
   visually distinct, unmodified.

   | Action | What it writes |
   |---|---|
   | **Accept** | Opens a form pre-filled from the candidate. Every field is editable, log rows can be added or removed, and **nothing is written until you press Confirm**. There is deliberately no one-click accept. |
   | **Reject** | Marks the candidate `rejected`. It stops appearing in the default view and never returns as pending — but stays findable by search. |
   | **Discuss** | Marks it `deferred` **and** appends it, with its evidence, to `stores.thread_adjudication` (`docs/ensemble/thread_adjudication.json`). Hand that file to a Claude conversation whole; it is self-sufficient. The card stays and can be ruled on again. |

3. **Build.** `grounding_sections build --doc planning --sections threads` now
   succeeds — or tick `threads` on the State Projection page.

### Why the queue looks smaller than the harvest

A 62-chapter corpus harvests to ~986 candidates, of which **16** span more
than one chapter. Candidates are keyed on the extraction lens's free-text
`subject`, which is not a thread identifier, so most of that number is noise.

The default view shows two named bands:

| Band | Rule |
|---|---|
| **Recurring** | appears in ≥2 chapters |
| **Single chapter, repeated** | fewer than 2 chapters, ≥2 mentions |

Everything else — mentioned exactly once — is **not shown**, and the page
states how many. There is no "Show all" button: reach the tail with the
search box (which covers titles, every spelling variant, and evidence prose)
or the chapter filter. Search spans candidates you have already ruled on, so
a rejected one is always retrievable.

Every count on the page is computed from what was loaded. None is written in.

### A thread you accepted keeps coming back — on purpose

Accepting a thread at chapter 41 does not silence it. When later chapters
mention it, the candidate is re-offered carrying **only the chapters not yet
logged**, matched to the thread you created, so ratifying again appends
rather than forking a second thread. A rejection is a one-way door; an
acceptance is not.

### Maintenance

Under **Ratified threads**, each thread offers *Add log row*, *Change status*
and *Add alias*. Resolving or abandoning requires a closing chapter — the form
says so and the engine enforces it. Consistency problems are shown both in the
health region and on the thread they belong to.

### Refusals, decoded

Every message below comes from `thread_registry` itself and is shown verbatim.

| Message | What to do |
|---|---|
| `corpus is required — pass at least one --corpus glob.` | Fill the corpus field before harvesting. |
| `pattern is required …` | Same, for **Resolve**. |
| `log row 1 has no chapter — a thread's chapters are yours to decide, not the harvest's` | The candidate had no chapter recorded. Type one into the log row. |
| `error: no proposal with norm 'X' — run propose first` | The queue is stale — reload, or re-harvest. |
| `error: thread id 'X' already exists` | Edit the `id` field, or accept onto the existing thread instead. |
| `error: title 'X' matches existing thread 'Y' — use log/alias on it instead` | This is the same thread under another name; add the alias to `Y`. |
| `error: alias 'X' already matches thread 'Y'` | That alias is taken. |
| `error: resolving/abandoning needs --chapter` | Supply the closing chapter. |
| `error: refusing to save a registry that fails check` | The per-problem lines follow it. Nothing was written. |

### What it does not do

No bulk ruling, no "accept remaining", no similarity-based grouping or
merging of candidates, and no server-side search. Each absence is a
requirement with a test behind it, not a missing feature: deciding that two
titles are the same thread is an identity assertion, and it is yours.
