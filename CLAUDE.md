# CLAUDE.md

Guidance for Claude Code working in this repo.

Codebase search policy (structural queries, non-code fallback, stale-index handling) lives in the global `~/.claude/CLAUDE.md` under "Codebase Semantic Search (codebase-memory-mcp)" — no repo-specific override here.

MemPalace memory-search policy (search-first for past work/decisions, mining freshness, grep fallback) lives in the same global `~/.claude/CLAUDE.md` under "MemPalace Memory Search" — no repo-specific override here.

# CampaignGenerator

A D&D session-prep CLI that assembles campaign documents and session beats, calls the Claude API to generate encounter/narration documents, and integrates with rpglib + MemPalace for verbatim retrieval from a local RPG library.

## Project structure

```
# ── Web UI ──
startup                     # Launch script — builds frontend, starts FastAPI server
server/                     # FastAPI backend (routers, subprocess SSE streaming)
frontend/                   # Vue 3 + TypeScript + Pinia + Vue Router

# ── CLI tools ──
campaignlib.py              # Shared library — all scripts import from here
pipelines/session_prep/prep.py  # CLI: session beat / session arc prep
session_doc/sd_consistency.py  # CLI: Pass 1 — consistency check (sd_*.py replaced session_doc.py)
session_doc/sd_plan.py         # CLI: Pass 3 — narrative plan
session_doc/sd_narrate.py      # CLI: Pass 5 — per-scene narration
session_doc/sd_corrections.py  # CLI: generate *.transcript.cleaned.vtt from the raw
                             #   tape + transcript_corrections.yaml (#250 R4)
session_doc/                # Post-session pipeline CLIs (sd_*, assemble, scene_extract,
                             #   enhance_summary, …) + shared helpers (io, voice,
                             #   roster, examples, narrate)
server/migrate_session_doc.py # CLI: one-shot ui_state.yaml → session_doc.yaml — python -m server.migrate_session_doc --campaign-dir /path/to/campaign
server/migrate_ensemble_config.py # CLI: one-shot ui.ensemble → ensemble.yaml — python -m server.migrate_ensemble_config --campaign-dir /path/to/campaign
server/migrate_narrate_genre.py # CLI: one-shot narrate.genre (a paste) → paths.genre_file (a path) — python -m server.migrate_narrate_genre --campaign-dir /path/to/campaign
pipelines/grounding/npc_table.py        # CLI: generate NPC reference table
pipelines/grounding/distill.py          # CLI: convert summaries → world_state.md
pipelines/grounding/campaign_state.py   # CLI: generate completed-content grounding doc
pipelines/grounding/make_tracking.py    # CLI: extract trackable events from a module
pipelines/grounding/thread_registry.py  # CLI: narrative-thread canon — propose (harvest),
                            #   ratify (atomic accept), rule, add/log/set-status/alias,
                            #   list/proposals/check --json. Surfaced at /grounding/threads
pipelines/rlm/query.py      # CLI: search summaries
pipelines/grounding/planning.py         # CLI: NPC dossiers + arc scores → planning.md
pipelines/grounding/party.py            # CLI: character sheets + summaries → party.md
pipelines/summary_native/     # CLI: summary_native — validate | build | synth | compare; grounding-doc drafts straight from reviewed structured summaries
pipelines/content_ingest/dnd_sheet.py  # CLI: D&D Beyond PDF → markdown (vision API)
pipelines/workspace/new_workspace.py  # CLI: create a new campaign workspace
pipelines/session_prep/transform.py  # CLI: NotebookLLM dossiers → prep input

# ── RLM tools ──
pipelines/rlm/rpg_retriever.py    # Tiered retrieval (drawer / statblock / cost-tagged candidate)
pipelines/rlm/fivetools_catalog.py # Mtime-cached name index over canonical 5etools data
pipelines/rlm/dossier_proposer.py # Run retrieval → write docs/dossier_proposal.md
pipelines/rlm/proposal_loader.py  # Render pipelines consume approved proposals
pipelines/rlm/mempalace_client.py # Writes via MemPalace MCP
pipelines/rlm/mcp_server.py       # MCP tools: rpg_search, propose_dossier, suggest_conversion
pipelines/content_ingest/convert_book.py     # PDF → 5etools JSON (pdf-translators)
pipelines/content_ingest/fivetools_ingest.py # 5etools JSON → MemPalace drawers
pipelines/rlm/resolve_refs.py     # Resolve refs.yaml + refs.local.yaml → concrete JSON paths
pipelines/rlm/launch_5etools_mcp.py # Per-campaign 5etools MCP server launcher (reads refs.yaml)

# ── Config & docs ──
config/
  config.yaml               # Default paths to documents and agent prompts
  system_prompt.md          # Single-mode system prompt
  agents/                   # Pipeline-mode prompts (lore_oracle, encounter_architect, voice_keeper)
docs/                       # Default doc location (override via config)
  campaign_state.md, world_state.md, mechanics.md, planning.md, party.md
logs/                       # Auto-generated timestamped session logs
tests/test_prep.py          # Tests for campaignlib, prep, and session_doc logic
```

## Detailed docs (read on demand)

| File | When to read it |
|---|---|
| `docs/core/architecture.md` | **Start here.** System map: layers, pipelines, on-disk state, recurring concepts, "common task → start here" table |
| `docs/cli/cli_tools.md` | Per-script invocations and flags (prep, campaign_state, planning, party, distill, query, …); typical new-campaign workflow |
| `docs/cli/session_doc_pipeline.md` | post-session pipeline: sd_consistency / sd_plan / sd_narrate flags, voice files, dialogue handling, recap context, player-name mapping, token scaling, plus design rationale |
| `docs/cli/player_identity_howto.md` | **Start here for who is at the table.** Task-oriented: set a campaign up, a player's Zoom name changed, somebody left, a character was renamed, a narrator sounds wrong. Every refusal decoded, and what to do about a voice/example file that nothing declares |
| `docs/config/players-isolation.md` | The reference behind it — the service, `players.yaml`'s schema, what `party.yaml` and `session_doc.yaml` lost, and why a declaration replaced the name-prefix rule |
| `docs/cli/genre_rulebook_howto.md` | **Start here for the genre rulebook.** One file per campaign (`voice/_genre.md`) addressed by `paths.genre_file`; migrating a campaign, every migration refusal, why a render reads generic, and how to prove a rulebook rule actually arrives |
| `docs/design/GenreRulebook_implementation.md` | The *why* behind it — three copies, the two fixes, the decision table, and what the verification render found |
| `docs/cli/quote_verification_howto.md` | Using quote verification: `sd_verify_quotes` / `sd_agent`, the five verdicts, why `near` ≠ safe, raw-vs-`.cleaned` VTT choice, every error message. Deterministic, zero-token, no backend — optional and auto-corrects nothing |
| `docs/cli/state_projection_howto.md` | Using State Projection: `event_spine` → `thread_registry` → `grounding_sections` order, staleness states, every skip/refuse message, `projections.yaml`, the `/grounding/projections` page — **and the Threads page** (`/grounding/threads`): harvest → rule → build, the two candidate bands, why an accepted thread keeps resurfacing, every refusal decoded |
| `docs/cli/summary_native_howto.md` | **Start here for summary-native grounding docs.** Task-oriented: the summary format, `validate` (every finding code), range choice, `build`, possible duplicates (fix the summaries; `canon.yaml` rulings), `synth` for all four docs, `compare`, promoting by hand, every refusal and exit code decoded, and an Out of the Abyss worked example |
| `docs/cli/npc_dossiers_howto.md` | **Start here for NPC dossiers from summaries.** Task-oriented: `summary_native npc-link → npc-draft → npc-verify → npc-compose → npc-publish`, the authored file (manual edits numbered, Secrets never reach a model), ruling on generic name forms, reading `link_report.md` / `verify.md` / `drops.md` (incl. the "used, not meaning" caveat), the Spark/Claude A/B, `dgx` endpoint resolution, every refusal and exit code decoded, and an Out of the Abyss worked example |
| `docs/cli/npc_dossiers_migration.md` | One-shot, two-step (`--propose` then `--apply`) move of loose `docs/npcs/*` into `distilled/` and `authored/`, the GM classifying every file the tool cannot prove is distilled. Readers refuse with this command until it is run |
| `docs/cli/provenance_howto.md` | **Start here for `provenance`.** Task-oriented: trust a hit or don't, scope to canon, chapter horizons, resolve a name, cross-campaign, what to do when results look wrong |
| `docs/cli/provenance_search.md` | The reference behind it — the two hand-authored files (`~/src/campaigns/provenance.yaml`, per-campaign `docs/corrections.yaml`): trust tiers, corrections matching, all ten `check` findings |
| `docs/web/web_ui.md` | FastAPI/Vue UI: pages, Session Doc Editor, Quote Ledger, Connection Graph, `ui_config.yaml`, dev workflow |
| `docs/rlm/dossier_aliases.md` | Dossier merge rules and cross-pipeline alias propagation |
| `docs/rlm/rlm_pipeline.md` | Three-state retrieval, ingest flow, MCP tools, palace/rpglib path resolution |
| `docs/rlm/refs_yaml_reference.md` | Full field reference for `refs.yaml` + `refs.local.yaml` (5etools MCP scope declaration) |
| `docs/rlm/rlm_architecture.md` | RLM architecture deep dive — three-pile model, MCP surface, retrieval contract |
| `docs/rlm/retrieval_architecture.md` | Palace internals — hierarchical descent algorithm, dirty-flag index lifecycle, 100% recall guarantee, failure modes, operational checklist |
| `docs/cli/session_prep_workflow.md` | End-to-end session-prep walkthrough |
| `docs/cli/ensemble_extraction.md` | `ensemble` how-to: single-file, multi-file `--plan` YAML, key flags, output layout |
| `docs/cli/ensemble_workflow.md` | End-to-end ensemble workflow: chapters → `ensemble_batch` → `facts_to_state` → synthesis (API + subscription paths); Phandalin worked example |
| `docs/mcp/mcp_servers.md` | The four MCP servers a campaign can wire into `.mcp.json` (`campaign`, `5etools`, `registry`, `kanka`) — what each does, what gates it, how to wire one in via `configure_mcp` |
| `docs/README.md` | Full doc index — every doc, organised by audience |

## Critical rules (apply to every task)

### `campaignlib.py` is the API surface

All file I/O, API calls, clipboard, and logging live in `campaignlib.py`. Every script imports from it.

| Function | Purpose |
|---|---|
| `find_default_config(optional=False)` | Returns `<cwd>/config/config.yaml`; raises `ConfigLocationError` if it is missing (unless `optional`) or a stray `<cwd>/config.yaml` exists. No fallback |
| `campaign_root_for_config(path)` | Returns the campaign root owning `<campaign>/config/config.yaml`; raises `ConfigLocationError` for a config outside `config/` |
| `load_config(path)` | Loads YAML, returns `(dict, config_dir_path)` |
| `load_file(path, base_dir)` | Reads a file; resolves relative paths against `base_dir` |
| `assemble_docs(config, labels, base_dir)` | Loads named docs from config, joins with separators |
| `make_client()` | Returns an `anthropic.Anthropic()` client |
| `stream_api(client, system, user, model, max_tokens, silent, verbose)` | Streams a Claude API call, returns full response |
| `call_api(...)` | Non-streaming call; accepts a string or list of content blocks (multimodal) |
| `copy_to_clipboard(text)` | Copies text via pyperclip |
| `save_log(log_dir, sections, stem)` | Saves a timestamped markdown log file |

```python
from campaignlib import find_default_config, load_config, assemble_docs, make_client, stream_api, call_api, save_log

parser.add_argument("--config", default=None)
args = parser.parse_args()
if args.config is None:
    args.config = find_default_config()   # resolve after parsing: it raises
config, base_dir = load_config(args.config)
docs = assemble_docs(config, ["world_state"], base_dir)
client = make_client()
response = stream_api(client, SYSTEM_PROMPT, docs, args.model)
```

**Never import `anthropic` directly in scripts.** All Claude API calls go through `campaignlib`. `stream_api` and `call_api` handle retries (rate limits, overload, connection errors) automatically — do not implement retry logic in scripts.

### Config auto-detection

The only valid config is `<campaign>/config/config.yaml` (see `campaignlib/constants.py` `CONFIG_DIR_NAME`). Without `--config`, scripts use `<cwd>/config/config.yaml`, so run them from the campaign root. There is **no fallback**: a missing config, or a stray root `config.yaml`, is an error. The old fallback to CampaignGenerator's own `config/config.yaml` silently ran campaigns against the toolkit's config. Resolve the default after `parse_args()`, never as an argparse `default=`, because it raises. Paths inside the config resolve against `config/` (`../docs/...`); campaign data such as `docs/entity_registry.yaml` resolves against the campaign root (`campaign_root_for_config`).

### Per-service config files (don't reach for `ui_state.yaml`)

Three services own a dedicated, strict (`extra="forbid"`) config file instead of a `ui.<section>` blob in `ui_state.yaml`. Writing to their retired section returns **404** — use the service's own route.

| Service | File | Route | Migrate an existing campaign |
|---|---|---|---|
| Session Doc Editor | `<config>/session_doc.yaml` | `GET`/`PUT /api/editor/config` | `python -m server.migrate_session_doc --campaign-dir DIR` |
| Ensemble | `<config>/ensemble.yaml` | `GET`/`PUT /api/ensemble/config` | `python -m server.migrate_ensemble_config --campaign-dir DIR` |
| Planning | `<config>/planning.yaml` | `/api/planning/*` CRUD | *(no migration — same file all along)* |
| Players | `<config>/players.yaml` | `/api/players/*` CRUD | `python -m server.migrate_players_config --campaign-dir DIR` |

Plus the platform tier: `<config>/platform.yaml` (`runtime.default_model`, `session_dir`) via `PUT /runtime`.

One more one-shot migration sits alongside these, inside the Session Doc Editor's own file: `python -m server.migrate_narrate_genre --campaign-dir DIR` relocates the genre rulebook from `narrate.genre` (the document's *text*, pasted) to `paths.genre_file` (a path). See "The genre rulebook is a file" below.

The migrations are one-shot and idempotent-ish (they refuse to clobber without `--force`) and report unrecognised keys rather than dropping them. **Skipping one is safe but not free:** `UIState` is `extra="allow"`, so a stale `ui.ensemble`/`ui.session_doc` block loads and is silently ignored — the page then starts from schema defaults, quietly losing hand-tuned selections like per-stage DGX backends and endpoint lists. Run the migration once per campaign before relying on those.

### A player is an entity; every other copy of them is rendered

`<config>/players.yaml` is the **one place** a player's identity is authored —
the person's name, every display name a recording has used for them, and which
characters they play. The roster block in a narration prompt, the speaker labels
in a transcript, and the `Player:` line stamped into a converted sheet are all
**rendered from it**. Nothing reads any of them back.

Two things follow, and both are enforced rather than documented:

- **A character's voice and example files are declared, not matched.**
  `party.yaml`'s `voice:` / `examples:` name them, and `shared_examples:` names
  the campaign-wide ones. There is no fall-through: a file nothing declares
  reaches nobody, and `players check` reports it. The rule this replaced matched
  a filename against a character's first name, which is a similarity-based
  identity assertion — the thing `provenance/identity.py` forbids everywhere
  else — and it produced five defects (#247, #300, #301, #315, campaigns#175).
  `tests/test_no_prefix_identity.py` fails the build if any of it comes back.
- **`party.yaml` has no `player:` field and `session_doc.yaml` has no `roster`
  group.** Both are refused with the migration command in the message, not
  ignored. See `docs/config/players-isolation.md`.

### A narrator must have been in the scene

`sd_plan` chooses a scene's narrator from a set computed **before** the model
call, never from the campaign roster. Two deterministic filters, no tokens:

- **Filter A — attendance.** `--vtt`'s speaker labels matched against
  `players.yaml` `display_names`. A character played only by absent players
  leaves the pool for the session.
- **Filter B — scene presence.** Within the pool, a character with no speaker
  label in a scene's extraction cannot narrate it.

They read different label spaces on purpose — a VTT carries player display
names, `scene_extract` output carries character names — so do not merge them
into one helper.

Four rules that are enforced rather than documented:

- **Presence is read from `moments`, anchored on `^**...**`.** Never from the
  gm-assist `summary`, and never by substring. In the session this comes from,
  the GM narrates *about* the absent character eleven times without ever
  labelling him, and the summary carries bold headers of its own — either
  reading marks him present in exactly the scene the planner must not give him.
- **A label is read verbatim; the roster decides who it names.** `session_doc/io.py`
  returns every line-start bold label as written — the GM, brackets, beat markers,
  unknown names — and `plan_eligibility` resolves each part against the roster by
  folded *equality*. Sessions disagree on the form (`**GM**`, `**[GM]**`,
  `**[GM, as the banker]**`, `**[GM / Brewbarry]**`), and the same bold-bracket
  shape is also scene apparatus (`**[Reroll With Advantage]**`), so no property of
  the text separates them. Discarding every bracketed label cost one session 39
  turns for one character and emptied its pool (#453). Equality is the load-bearing
  half: `**[scene tag — Vukradin demands a meeting]**` *contains* a roster name, and
  containment would place him in a scene on the strength of a beat marker.
  A label's shape decides only whether the text is tokenised — never identity, and
  never whether a comma introduces a qualifier or a second speaker, which is
  settled by whether the piece resolves. Every slot that resolves to nobody is
  reported *even when the rest of the label resolved*: `**[GM / Brewbarry / Valphine]**`
  credited Brewbarry and dropped `Valphine` with no trace until it did.
  `tests/test_speaker_label_grammar.py` fails the build if any of that returns.
- **`sd_plan` refuses without a tape or a roster, and refuses an empty pool.**
  A fallback to the unnarrowed roster is the defect (#385), not a graceful
  degradation.
- **Eligibility is presence, not volume.** One labelled turn is full
  eligibility; turn counts are evidence for the GM, never a threshold.

A scene with no eligible narrator produces three plans (`plan.a|b|c.md`) and no
`plan.md`; the missing file is the gate, and `sd_plan --choose` resolves it.
`sd_narrate --vtt` marks unvoiced characters in the roster block — as
*unvoiced*, never as absent from the fiction, since a GM may still have placed
them in a scene. See `docs/cli/session_doc_pipeline.md`.

### A gap is answered in a record, never in the generated file

`sd_narrate --gap-marking` leaves markers; `session_doc/blocks.py` reads them
back. Three files per scene — `.md` generated, `.authored.yaml` hand-authored,
`.composed.md` generated — and the rule is `transcript_corrections.yaml`'s: **the
record is the source of truth and the composed document is output.**

Four things here are enforced rather than documented:

- **The parser round-trips.** `join_blocks(parse_blocks(t)) == t`, asserted on
  four real narrations. Composing writes a document from these blocks, so a
  parser that loses a blank line makes every composed file differ from its
  narration *everywhere* — and the diff reads as compose misbehaving.
- **`unruled` is an absent entry, and `mine` is not `authored`.** The record
  stores only what the human contributed. But "ruled mine, not yet written" and
  "wrote an empty string" are different states, so the disposition is stored
  rather than inferred from whether `text` is present — that distinction *is*
  the phone-then-desk workflow, and inferring would erase what a triage pass
  produces.
- **The assembly gate reads documents, not records.** A file carrying a marker
  is unfit for a chapter whatever a record says, so the gate holds for a scene
  composed by hand or by anything else.
- **No module in this layer may call a model**, guarded by an AST walk in
  `tests/test_block_model_no_llm.py`. The evidence is on disk: asked to resolve
  its own eleven markers, the model discarded nothing and gave both of the GM's
  Order-of-the-Gauntlet lines to a player character, on the one passage the
  markers had protected.

The reviewer (`session_doc/review/reviewer.html`) is one static file with **no
network reference of any kind** — it is used on a phone, offline, at work. It is
never regenerated per session, which makes the export an interface; a test ties
the page's `SCHEMA_VERSION` to the exporter's and checks every field the page
reads exists. See `docs/cli/gap_review_howto.md`.

### The GM-attribution rule has one home, and the gap marker is content

`sd_narrate --gap-marking` makes the model emit
`[GM NARRATION — TO BE WRITTEN: …]` where the source attributes description or
explanation to the GM, instead of letting a character absorb it. Off by default.
Two facts about it are easy to get wrong from the surrounding code:

- **The rule is stated once, and selected by the mode.** `writing_brief.md` and
  `prose_mode.md` each carry a `{gm_attribution}` slot rather than a sentence;
  `session_doc/narrate.py` fills it inner-first, before the outer template fill.
  That ordering is load-bearing — `_fill` emits values verbatim without
  re-scanning, so a nested placeholder resolved by the outer call reaches the
  model as literal text. Do not add a second copy of the rule to a fragment: two
  restatements of one rule is #435, and they had already drifted when it was
  found. With the mode off the assembled prompt is **byte-identical** to the
  pre-feature one, proved against a frozen golden in
  `tests/test_prompt_golden_pre_feature.py`; do not regenerate that file to make
  a failure go away.
- **The gap marker is content, not apparatus.** It must NOT join
  `APPARATUS_MARKERS` — that registry drives `strip_audit_comments`, which would
  delete the feature's own output at assembly — and it must NOT be masked from
  the unknown-name scan, because a proper noun appearing only inside a marker is
  exactly the invention that check exists to catch. Both are the opposite of how
  the neighbouring audit comments are handled, and
  `tests/test_apparatus_marker_pairing.py` fails the build if either flips.

The contract is a repo prompt fragment, not a per-campaign file: register varies
per campaign, an attribution rule does not. Answering a gap belongs to #455.

### The genre rulebook is a file, never a pasted string

`paths.genre_file` in `session_doc.yaml` points at the campaign's genre/register document (conventionally `<campaign>/voice/_genre.md`). **That file is the single source of truth** — `sd_narrate --narration-genre-file` reads it at render time, and nothing mirrors its text back into config.

The retired `narrate.genre` held a *copy* of that document, and the copy is what broke: out-of-the-abyss' had lost every newline on the way into YAML (16,303 characters on one line, delivered as a one-line `GENRE:` label — #276 fix 1, #249) and had drifted to 0.9989 similarity against the file it came from. A third copy lived in `profiles[].knobs.narration_genre`, synced one way only (#220), so activating a profile could silently replace a hand-edit.

Consequences for anyone touching this:

- **The UI points, it does not edit.** The Session Doc Editor shows the path, whether it resolved, line/char counts and a capped preview. A browser textarea is what flattened 88 lines into one; editing happens in the file.
- **A missing file means no genre at all.** There is no YAML fallback any more, so `sd_narrate` warns loudly rather than rendering quietly without the register rules and banned-tic list.
- **Runs record identity, not a copy.** The per-scene `.knobs.json` stores `narration_genre_file` plus a content digest, so two scenes can be compared and a mid-session file edit is visible — instead of duplicating 16K of prose into every sidecar.
- **A profile owns exactly one path**, `paths.genre_file`. A profile wanting a different register needs its own file.

**Never add a default literal to `server/routers/ensemble.py`.** Every ensemble path and tuning knob is declared once, in `server/ensemble_config_shared.py`'s `EnsemblePaths`/`EnsembleTuning`; routes take a sentinel (`""`, or `None` for ints where `0` is meaningful) and resolve from `EnsembleConfigService.resolved()` at the route edge. `tests/test_ensemble_config_defaults.py` fails the build if a `docs/ensemble/`-shaped literal or `backend: str = "anthropic"` reappears there. Resolution happens *before* argv is built, so the copyable command `specs/002-ensemble-run-observability` promises stays fully explicit. See `docs/config/ensemble-isolation.md`.

### Entity registry (single authority for aliases)

`docs/entity_registry.yaml` is the single source of truth for entity identity — canonical spelling, aliases, and the anti-merge guards (`distinct`, `rejected_aliases`). It supersedes the legacy scattered stores (dossier `aliases:` frontmatter, `aliases.json`, `.alias_decisions.json`, module inventories, `.dedup_state.json`). Managed via `registry` (`init`/`add`/`alias`/`import-*`/`triage-candidates`/`check`/`project`); loaded via `campaignlib.registry` (`load_registry`, `find_registry`, `resolve_registry_arg`). Also exposed as an MCP server, `registry_mcp` (`entity_registry/registry_mcp.py`) — one tool per `registry` subcommand, registered per-campaign in `.mcp.json` (auto-added by `configure_mcp` when `docs/entity_registry.yaml` exists) — so a Claude session gets the CLI's full surface and ordering rules from the tool listing instead of re-deriving them each session.

**Consumers auto-adopt it when present:**
- `facts_to_state` and `synthesise_world_state`/`synthesise_facts`/`synthesise_polish` take `--registry` (an explicit dir/file wins; omit to auto-discover `docs/entity_registry.yaml` from the CWD). It supersedes the deprecated `--aliases`/`--known-names`, and errors if an explicit `--registry` is combined with them. The registry supplies **aliases only** — `--inventory` is separate human-authored module-canon grounding and is never substituted by it.
- The render CLIs (`distill`, `party`, `sd_narrate`, `scene_extract`, `campaign_state`, `planning`) call `load_alias_map(dossier_dir, registry_path=…)`: a resolved registry **replaces** the `docs/npcs/` dossier scan (via `find_alias_registry`, which prints an adoption notice so a partial registry never silently drops hand-curated dossier aliases).
- `planning --build-dossiers` seeds new dossiers' `aliases:` frontmatter from the registry.

**Building one:** there is no `import-source`. Produce a typed module inventory with the `gm-module-inventory` skill (published module → `docs/background/<module>-inventory.md`), then `registry import-inventory`. The `import-*` verbs fold the legacy stores in; `check` reports grouping drift + fuzzy near-dups for GM review.

### Retrieval/render separation (RLM)

Render pipelines (`prep`, `sd_narrate`, `planning`) must **not** consume raw `rpg_retriever` output. They consume a human-approved `docs/dossier_proposal.md` file instead. Retrieval is a scope decision; rendering is a prose decision; the proposal is the human checkpoint between them.

A CI test (`tests/test_retrieve_render_isolation.py`) fails if any function body contains both a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`, …) and a render call (`stream_api`, `call_api`). Don't bypass this — fix the structure.

See `docs/rlm/rlm_pipeline.md` for the proposal workflow and MCP tools.

### Provenance search: prefer an authoritative hit over a generated one

`provenance search` labels every hit with its trust tier and, when a pipeline wrote the file, the stage that will clobber it. **A `generated_by` hit is a draft with a countdown on it** — `docs/world_state.md`, `docs/campaign_state.md`, `docs/planning.md`, `docs/party.md` and `docs/npcs/*.md` are all regenerated output, and the incident this feature exists to prevent was a consistency check treating one of them as canon and flagging a *correct* recap as a continuity error.

So when a render pipeline or a consistency check needs a fact, and an authoritative-tier hit (a session summary, a VTT, a chapter split) disagrees with a `working_reference` one, **the authoritative hit wins** — and if only the generated one exists, say so rather than asserting it. `--tier authoritative` scopes a search to canon; the ranking already puts the more trusted tier first at equal relevance.

Two labels ride alongside and mean specific things: `generated_but_hand_edited: true` says the file carries a hand-written correction the next run will destroy, and an attached correction with `verified: false` is an open question for the GM, not a settled fact. Neither is a reason to re-tier the file.

Read-only, no LLM call, no writes — statically guarded (`tests/test_provenance_readonly.py`, `tests/test_provenance_no_llm.py`). See `docs/cli/provenance_search.md`.

### Never hand-edit a `*.transcript.cleaned.vtt`

It is **generated** (#250 R4). The raw `*.transcript.vtt` is the archive and is never written; `<session-dir>/transcript_corrections.yaml` is the hand-authored, cue-indexed record; `sd_corrections apply` turns one into the other. A hand-edit is discarded by the next `apply` and reported by `sd_corrections check` as an edit nobody wrote down.

This rule exists because the previous arrangement — a chat-driven spell pass editing the tape directly — put 74 unrecorded substitutions into Phandalin ch46, three of which inserted a surname no player spoke. To fix a mishearing, add an entry (`cue`, `was`, `now`, `verified`, `note`) and re-apply. `was` is checked against the tape on every apply, so a stale entry fails loudly rather than pasting an old repair over new words. See `docs/cli/transcript_corrections_howto.md`.

### `docs/npcs/` holds published dossiers; only `npc-publish` writes them

`docs/npcs/<slug>.md` is what the gm-assistant skills read. It holds **only published dossiers**, plus
three subdirectories: `authored/` (everything a person writes: `<slug>.authored.yaml` and hand-built
dossiers such as `gm-npc-build` output), `distilled/` (the retired distilled pipeline's files, moved
there by `server.migrate_npc_dossiers`) and `summary_native/` (generated range folders and
`publish_log.json`). Four rules, enforced rather than documented:

- **`authored/` is never written by a tool.** `npc-compose --init` creates an empty file only when none
  exists; nothing else opens one for writing. `tests/test_no_writes_to_authored.py` fails the build if a
  writer appears.
- **Only `npc-publish` writes `docs/npcs/<slug>.md`**, and only for NPCs the GM names or an explicit
  `--all` / `--authored-all`. It refuses a failed verification, a target it did not publish, and a target
  whose sha256 differs from `publish_log.json` (a hand-edit). On an unmigrated campaign (loose
  files directly in `docs/npcs/`), the readers (`planning --build-dossiers`, `registry check`) refuse with
  the migration command instead of reading them as distilled dossiers.
- **Secrets never enter a prompt.** Drafting reads an authored file through `load_manual()`, which
  returns the numbered `manual` list and has no way to return `secrets`; compose copies Secrets
  byte-for-byte into the GM dossier and nowhere else. A test asserts the text is in no draft and no
  `runs/*/*.user.md`. The published dossier **does** include Secrets: it is GM-only.
- **`npc_draft` is the only model step.** Every other `npc_*` module (`npc_link`, `npc_forms`,
  `npc_check`, `npc_chunked`, `npc_verify`, `npc_compose`, `npc_authored`, `npc_publish`, `npc_slug`) is
  AST-guarded no-LLM in `tests/test_summary_native_no_llm.py`, and chunked drafting puts a code check
  between every model call and the next, so no model output feeds another model call unchecked.

A draft is a leaf output (it removes only the prose decision from the GM); identity, order, attribution
and scope come from the summaries, the registry and `players.yaml`. Player characters (named in
`players.yaml` `plays`) are never drafted, and a name form that is ambiguous or generic is withheld from
linking rather than guessed. See `docs/cli/npc_dossiers_howto.md`.

### Grounding docs are an index; summaries are the authority

All four documents from the chunked build (`world_state`, `campaign_state`, `party` and `planning`;
`summary_native extract` → `synth` → `annotate`, plus `audit` for campaign_state) are for session prep to
**navigate by**, never to quote as fact. Every content line carries a citation `[ch NNN / target]` into
`docs/summaries/`, and a reader who uses a claim follows it to the latest mention. Where a document and a
summary disagree, the summary wins and the document is wrong. Three things are enforced rather than
documented:

- **Annotation adds, it never rewrites.** `annotate` appends `⚠ later:` (newer information about the
  same subject), `ℹ since:` (a mentioned NPC's later status) and `⚠ unverified:` (a quotation not
  verbatim in its cited chapter, or a citation that does not resolve) *under* a line. The line's text
  is never changed; the only removals are a player character listed as a companion and a Faction States
  block named for a player character. For party and planning it scans the model-written prose lines as
  well as bullets, and skips what code built or what is not a claim: the Threat Tracker, NPC Dossiers,
  Active Plots' dormant and unratified blocks, and the `#### Candidate Arc Score Events` subsection.
  `tests/test_annotate_never_rewrites.py` fails the build if a non-removed line's text differs after
  annotation, and `annotate` is AST-guarded no-LLM so a model cannot reword a line after the code check.
- **A draft is output, not a document.** Everything is written under `<range>/state/`, never to
  `docs/` (`tests/test_state_docs_no_live_writes.py`). A draft is regenerated by the next `--force`, so
  an error is fixed at its source (the summary, the registry, a dossier's authored file, a thread
  ruling); prose edits are made only after promotion into `docs/`.
- **No dossier-sourced NPC line without a published dossier, unless you say so for this run.** A missing
  dossier refuses the build of world_state's Key NPCs and planning's NPC Dossiers; `--fallback-npc-lines`
  is per run, never read from config, and its lines are marked `(no published dossier — from checked notes)`.

Three more rules are what make party and planning safe to navigate by:

- **Identity is code's, from an authority.** A party note is attributed to a character, the party, a
  companion or nobody by exact name or alias through the entity registry and `players.yaml`, and a
  character's level comes from a checked `[LEVEL]` row or is disclaimed as the sheet's figure. A thread
  note belongs to a thread only by exact title or alias in `docs/thread_registry.yaml`, the identity
  authority for threads, which only GM ratification writes. The extractor's own thread names are not
  identity (554 names, 550 seen once, on Out of the Abyss). `thread-propose` groups unattached notes, but a
  proposal is a candidate the GM ratifies, and each batch sees only checked notes and ratified threads.
- **Arc scores are never stated.** The documents list candidate events with a verbatim trigger from the
  GM's mechanic file (`arc_check` drops a line without a resolving citation or a verbatim trigger, or one
  that states a value); the score is the GM's.
- **Companions are described, not given sections.** They are in Party Overview and Party Dynamics and in
  `reference/party.md`; dormant threads are listed in their own code-built block of Active Plots.

"Citations resolve" is not "citations support the line": the documents cannot prove a claim, only make
it checkable. See `docs/cli/summary_native_howto.md` (Steps 5b and 6, and "What session prep may rely on").

### LLM renders, humans decide

Per the global rule in `~/.claude/CLAUDE.md`: scope/ordering/attribution are precision decisions and need a human checkpoint; rendering verified structure into prose is what LLMs do well. When designing new pipelines in this repo, the pattern is **LLM extracts → human reviews → LLM renders inside that structure** — never **LLM extracts → LLM structures → LLM renders**.

Concrete examples already in the codebase:
- `party` outputs candidate arc-score events with quoted triggers, never current values or thresholds
- `planning --build-dossiers` writes per-NPC files for human review before `--synthesize`
- The 4-stage `session_doc` pipeline (`docs/cli/session_doc_pipeline.md`) inserts a human review after each LLM pass
- `dossier_proposer` writes a proposal file; the GM approves it before render pipelines consume it

## Running tests

```bash
python -m pytest tests/
```

## Dependencies

```bash
pip install anthropic pyyaml pyperclip pyvis fastapi uvicorn
cd frontend && npm install   # Vue 3 frontend
```

`ANTHROPIC_API_KEY` must be set **for the `anthropic` backend**. It is not a
prerequisite for running the app: `claude-code` (subscription) and `dgx` (local
endpoint) read no credential, `openrouter` reads its own, and the deterministic
pipelines call no model at all. Nothing gates a run on whether a key is present
— each backend refuses for itself, at the call, when it needs something it does
not have (#342). Do not reintroduce a global "is a key set" probe;
`tests/test_no_credential_gate.py` fails the build if one appears.

For the OpenRouter backend (ensemble workflow synthesis/extraction), `pip install
openai` and set `OPENROUTER_API_KEY` in the environment. OpenRouter is reached
only through `campaignlib/api` (`make_client(backend="openrouter")`); select it on
a CLI with `--backend openrouter --model <openrouter-id>`, or via the
`CG_BACKEND=openrouter` env var.

### The package MUST be editable-installed into the server's venv

The web UI runs every pipeline as a subprocess via `console_script(name)`
(`server/subprocess_runner.py`), which resolves to
`<server's python dir>/<name>` — an installed `pyproject.toml [project.scripts]`
console script, **not** a `$PATH` lookup or a repo-relative `*.py`. So after any
source-tree restructure, a `[project.scripts]` change, or a fresh venv you MUST
(re)install:

```bash
# venv is uv-managed (its python has no pip). Install into the SAME venv the
# server runs under — verify with: cat /proc/<server-pid>/environ | tr '\0' '\n' | grep VIRTUAL_ENV
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"   # e.g. ~/.venv
```

**Symptom when missing:** a `/run/*` action fails and the Session Doc Editor
shows `Stream error — check terminal.` — the subprocess tried to spawn a
non-existent `<venv>/bin/sd_narrate` (or `scene_extract`, `enhance_summary`, …).
The server itself still boots fine because `startup` puts the repo on
`PYTHONPATH`, so imports resolve without the install — only the console scripts
are missing. **No server restart is needed** after installing; `console_script()`
resolves the path per-request.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/022-grounding-nav-hierarchy/plan.md
<!-- SPECKIT END -->
