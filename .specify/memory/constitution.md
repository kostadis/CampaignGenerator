# CampaignGenerator Constitution

This is a **sister doctrine** to the [mneme constitution](https://github.com/kostadis/mneme/blob/main/.specify/memory/constitution.md). Both descend from the Kostadis architectural doctrine; both name the anti-pattern each principle kills. The division of labor between them:

- **mneme** governs the *platform's state* — identity, databases, reconciliation, the DGX integration plane. Its enemy is corrupted or fragmented infrastructure state.
- **This constitution** governs *CampaignGenerator's pipeline* — how an LLM is used to render trustworthy campaign artifacts. Its enemy is the precision failure that breaks the fourth wall at the table.

Where the two overlap (Optimistic Lies, Split-Brain, Fragmented State), the anti-pattern names are shared deliberately. CampaignGenerator is one actor in a larger flow that also includes Zoom, gm-assist, MemPalace, the Anthropic API, and a set of Claude skills that live outside this repo. This constitution binds general principles to CG via concrete clauses; a principle without a clause that names a file, a test, or a workspace path is aspiration, not law.

## Core Principles

### I. Disk is Truth, the Model is a Draft

Markdown and YAML files on disk are the single source of truth. Every database in the system — the MemPalace palace, the vector DB behind it, the rpg-library index, the 5etools name catalog — is an *index over* or *cache of* that truth, never the truth itself. A database may be deleted and rebuilt from disk; disk may never be rebuilt from a database.

LLM output is a **draft** until a human has reviewed it. Generated text is not fact, not canon, and not input to the next step until a human has read it and let it through. The rough extraction pass is the ceiling of what the model can do unaided, not the floor.

*Kills: Optimistic Lies* — treating a confident-looking generated artifact as established fact.

### II. The Human Checkpoint is Non-Negotiable

LLMs render; humans decide. Scope (what belongs where), ordering (what came before what), and attribution (who said or did what) are **precision decisions** and they require a human checkpoint. No LLM output may feed another LLM call across a precision boundary without a human gate in between.

Before any LLM call is added, state what decision it removes from the human. If the answer is "a precision decision, fed automatically downstream," a human checkpoint is mandatory before the next call. If the answer is "none — the human reviews and corrects before it feeds anything," the call is safe.

*Kills: Error Compounding* — one call's silent 10% error inherited and amplified by the next.

### III. Retrieval and Render are Separated

A function retrieves or it renders — never both. This is enforced by `tests/test_retrieve_render_isolation.py`, which fails the build if any function body mixes a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`) with a render call (`stream_api`, `call_api`). Do not bypass the test; fix the structure.

Render pipelines (`prep.py`, `sd_narrate.py`, `planning.py`) refuse to run unless a human has approved `docs/dossier_proposal.md`. The choke point is `proposal_loader.py:require_approved_proposal`. Deciding *what content is in scope* is the human's; turning approved scope into prose is the model's.

*Kills: the Renderer Making Scope Decisions* — letting the prose pass also decide what's in the world.

### IV. Verbatim is Sacred

Quotes and transcript records are reproduced exactly, never paraphrased and never invented. The Zoom VTT is the only record of "what was said" at the table; gm-assist is the authoritative record of "what happened in what order." Neither may be embellished by a model that can see past its boundary.

The cost of violating this is not a bad diff — it is a player at the table asking why an NPC said something it never said, or why an action that should have rippled through the world quietly disappeared. A precision failure here breaks the fourth wall. That is the most expensive failure the system can produce.

*Kills: Hallucinated Dialogue* — fabricated or "improved" verbatim content.

### V. One Seam per Boundary

Every external dependency is reached through exactly one file, and that file is reached one direction:

- Anthropic API → `campaignlib.py` (the only module that imports `anthropic`; `make_client` / `stream_api` / `call_api` are the surface, and they already retry)
- MemPalace → `mempalace_client.py`
- DGX / local LLM per-model behavior → `dgxlib`
- CampaignGenerator capability exposed *outward* to other Claude sessions → `mcp_server.py`

When you need to change how CG talks to X, there must be exactly one file to open. New integration code that scatters `import anthropic` or talks to MemPalace outside its client is a constitutional violation, not a style nit.

*Kills: Fragmented Integration* — the same boundary crossed from five places that drift apart.

### VI. CLI is the Engine, UI is a Face

Every capability is a CLI tool first. The FastAPI server never reimplements pipeline logic — it shells out to CLI scripts via `server/subprocess_runner.py` and streams their output as Server-Sent Events. Fixing a bug in a script fixes it in the UI; exposing a flag means adding it to the corresponding `_build_*_cmd()` in the router, never reimplementing the behavior in the router.

*Kills: Split-Brain* — CLI and UI growing two divergent implementations of the same operation.

### VII. Extract Once, Synthesize Deliberately

The grounding-doc generators follow one shape: chunk the input, extract per chunk, cache the extractions on disk, then synthesize one document from the pile (`run_extract_pipeline` + `run_synthesize_pipeline` in `campaignlib.py`). Re-runs reuse cached extractions.

Do not collapse passes that each need depth. The killed chapter-extract consolidation is the cautionary tale: merging three extract passes into one per-chapter pass regressed all three grounding docs, because breadth in one pass came at the cost of depth in each. Prefer more, narrower passes over one wide pass that does each job worse.

*Kills: Depth Regression* — premature consolidation that trades per-job depth for fewer calls.

### VIII. State is Discoverable

The campaign workspace is self-describing. Which pipeline stage a session is in, what artifacts exist, what is still pending — all of it is discoverable from disk (the `summaries/{session}/` layout, the presence or absence of each stage's output file), not held in the operator's memory or in a skill's head. A question the system surfaces ("this scene has no approved quotes yet") matters as much as an answer it gives.

When the flow falls back to a skill or a manual step, that seam should be *visible* — an artifact on disk or a state the UI can represent — not tribal knowledge about which command to run next.

*Kills: Opacity / Tribal State* — the system's real status living only in the operator's head.

### IX. The UI Mechanizes; Claude Converses

UI workflows exist to make the *mechanical* parts of a pipeline easier — to walk a multi-step process one step at a time, run each step, and show what came out. They do **not** replace the Claude chat interface, and they are not the place where the thinking happens. The judgment between steps — reviewing a draft, deciding scope, correcting an attribution, choosing what to promote — happens in a Claude conversation or at the CLI. The UI's job is to remove the friction of *remembering and invoking* the steps in order, never to absorb the work that happens between them.

The expectation is explicit: between any two UI steps, the operator may drop to the CLI or to a Claude chat to do the real work, and lose nothing by doing so. A UI step that cannot be performed equivalently at the CLI is a step that has stolen judgment from the human.

Files are the interchange. Every step reads files and writes files; the file on disk is how information passes between the UI, the CLI, and the chat, and how all three stay consistent. The UI must never hold pipeline state that exists only in the browser — if a step produced something, it produced a file, and that file is equally visible to the CLI and to Claude. (This is Principles I, VI, and VIII applied to the UI surface: the file is the truth, the CLI is the engine, and the state is discoverable — so the human is never trapped inside the UI.)

The ensemble grounding-doc workflow is the canonical shape: the UI may step you Stage 1 → 2 → 3, but the `--list` scope review, the `aliases.json` edit, and the `diff`-before-promote happen at the CLI or in chat, and every stage hands off through a file (`merged.json`, `state_dossiers/*.md`, `*_draft.md`). The UI mechanizes the sequence; it does not synthesize the campaign.

*Kills: The Walled Garden* — a UI that swallows the whole workflow, hides the files, and locks the human out of the conversation and the CLI.

### X. Selection is Explicit; There is No Silent "All"

A batch operation acts on the set the human explicitly chose — never on an implicit "everything" inferred from an empty or absent selection. **"Select all" is a deliberate act that materializes the full set as the chosen set; it is not the state the system falls into when the human chose nothing.** An empty selection means *nothing is selected*: the operation refuses to run and says so, rather than guessing that the human meant the whole corpus.

Which inputs a token-spending pass touches is a **scope decision** (Principle II), and it is the human's — made explicitly, every time. A default that quietly expands to "all" removes that decision from the human exactly when it is most expensive to get wrong.

Concrete clause: the ensemble chapter picker stores `ui.ensemble.chapters_selected` as the literal set of chosen chapters; "Select all" writes every resolved path; `GET /api/ensemble/run/extract` refuses an empty `chapters` list instead of falling back to the glob (`tests/test_ensemble_chapters.py`). The CLI engine is exempt only because a glob *typed at the CLI* is itself an explicit act; the UI must never manufacture that act on the human's behalf.

*Kills: the Implicit Blast Radius* — a batch action that silently expands to "everything" because the set was never explicitly chosen.

### XI. Parity is Bidirectional; Every CLI Capability Has a Face

Principle VI points one way (the CLI is the engine, the UI is a face) and Principle IX points back (a UI step that cannot be performed equivalently at the CLI has stolen judgment from the human). This principle closes the loop: **every CLI capability is reachable from the UI**, and a new CLI tool or a new flag on an existing one ships its UI surface in the same feature, not in a follow-up.

The exemption is real but narrow: *unless the human explicitly asked for no UI*. An omission is not an exemption, "phase 2" is not an exemption, and "the operator can just run it" is not an exemption — an unstated decision is not a decision (Principle II's logic applied to scope of delivery). When a capability is deliberately CLI-only, that ruling is recorded in the feature's `## Constitution Check` in `plan.md`, naming who decided and why.

This does not license a walled garden. What the UI must expose is the **invocation** — the ability to reach the capability, choose its inputs, run it, and see what came out — never the judgment between steps, which Principle IX keeps at the CLI and in chat. Parity is about reach, not about relocating the thinking.

Concrete clause: a flag becomes reachable in `_build_*_cmd()` in `server/routers/*.py`. A flag the router hardcodes is a capability with no face — the engine offers a choice the human cannot make. `SessionDocEditor.vue:473` pinning `?force=1` on every Re-Extract click is the scar (#323, `specs/012-scene-extract-optional-force/`): `scene_extract`'s `--force`, `run_scene_extraction`'s skip-if-exists, and the route's own `force: int = 0` were all correct, and the UI silently forced anyway, re-spending tokens on already-reviewed scenes.

*Kills: the Orphaned Capability* — a flag that exists in the engine, works correctly, and no human can reach.

### XII. One Spelling per Option; No Configuration Drift Across CLIs

An option means one thing, is spelled one way, and defaults one way — across every CLI that shares its meaning. A new option is introduced **across its whole family or not at all**. Adding `--foo` to one script and leaving its siblings without it does not produce a small inconsistency; it produces a dialect, and the human must then remember which script speaks which — Principle VIII's tribal state in flag form.

The existing vocabulary is the vocabulary. `--config` is auto-detected identically everywhere via `find_default_config(__file__)` (`campaignlib/config.py`). `--backend` / `--model` mean the same thing on every CLI that calls a model. `--force` means "overwrite what is already there" and never anything else. `--campaign-dir` names the workspace on every migrator. When a concept already has a name, reuse the name; when it needs a new one, apply it to every sibling in the same change.

Defaults are declared once, in the config model that owns them — never re-spelled as a literal at a call site or a route edge. `server/ensemble_config_shared.py`'s `EnsemblePaths` / `EnsembleTuning` is the pattern: routes take a sentinel (`""`, or `None` where `0` is meaningful) and resolve from `EnsembleConfigService.resolved()`, and `tests/test_ensemble_config_defaults.py` fails the build if a defaulted literal reappears in the router. A default duplicated into a second place is a Split-Brain that has not diverged *yet*.

Superseding is also a family-wide act: `--registry` replaced `--aliases` / `--known-names` on every consumer at once and errors when combined with them, rather than landing on some CLIs and leaving others on the old flag.

*Kills: Dialect Drift* — the same idea spelled five ways across five scripts, so the human's knowledge of one tool is worthless at the next.

### XIII. Breaking State Changes Migrate Out of Band and Ship a Migration Document

When a feature changes the *shape* of state on disk — a config schema, a workspace layout, a filename convention — the change is performed by a **separate, one-shot migration CLI the human runs deliberately**. A feature never silently upgrades state as a side effect of running.

Two prohibitions follow:

- **No lazy in-place upgrade.** A pipeline that rewrites state because it happened to read it does the irreversible thing at the moment the human is least prepared for it, usually mid-run, usually against a workspace they were not thinking about.
- **No dual-location back-compat probe.** This is a single-user system: migrate and delete. Reading "the new place, falling back to the old place" is how the same fact comes to live in three locations and disagree with itself. The retired location is **refused with the migration command in the error message** — as `party.yaml`'s `player:` and `session_doc.yaml`'s `roster` are — not quietly ignored. Silent tolerance is the worse failure: `UIState` is `extra="allow"`, so an unmigrated `ui.ensemble` block loads, is dropped, and the page starts from schema defaults, losing hand-tuned selections without ever reporting a problem.

The migrators are the shape to copy: `server/migrate_*.py`, sharing `--campaign-dir` and a `--force` that refuses to clobber (Principle XII), reading the old file raw rather than through a live typed model so they can rescue fields no current schema declares, reporting unrecognised keys instead of dropping them, and each covered by a `tests/test_migrate_*.py`.

**The migration document is part of the feature's output, not a follow-up.** A feature that breaks state is not done until it ships a document stating: what changed shape, which workspaces are affected, the exact command to run, what happens to a workspace that never runs it, and how to verify it worked. It lives at `specs/<feature>/migration.md`, with the operator-facing instructions in `docs/`. A migration that exists only as a script the author remembers is Principle VIII's tribal state pointed at the most destructive operation in the system.

*Kills: the Silent Schema Break* — a state change that reaches a workspace as an unexplained failure, or as data quietly discarded, months after the author has forgotten it.

## Architecture is Destiny

Bad architectural choices are liabilities, and in this system the currency is twofold: **token spend** and **precision failures at the table**.

- **Token spend** is standing cost. Every LLM call must justify itself; the ensemble/Spark path exists precisely so that *extraction* can be made ~free locally and the API is spent only on *synthesis*. Caching (the scene-extract system-prefix cache, the enhance-summary cached prefix, the Batch API at 50% off) is not an optimization to add later — it is how the architecture stays affordable.
- **Precision failures** are the catastrophic cost. A token wasted is recoverable; a fabricated quote that reaches the table is not. This is why Principles I–IV exist and why they outrank convenience. The human checkpoint is not friction the architecture should engineer away — it is the load-bearing wall.

Every new database, daemon, cache, or LLM call is a recurring tax. Justify the tax against the truth on disk and the human gate, or do not add it.

## Authority & the Human Checkpoint

Humans author structure, identity, and schema. The LLM — including Spec Kit itself — renders within that boundary; it never decides it.

- Spec Kit `/speckit-*` plans, specs, and tasks are **drafts**. They are reviewed against this constitution before they feed implementation.
- A generated spec that decides scope, ordering, or attribution autonomously is exactly the precision-decision-without-a-checkpoint that Principle II forbids — catch it at review.
- Good pattern: LLM extracts → human reviews and imposes structure → LLM renders inside that structure. Bad pattern: LLM extracts → LLM structures → LLM renders. The second compounds errors silently and is prohibited here.

## Governance

This constitution supersedes conflicting specs, plans, and tasks. A conflict requires written justification or an amendment — not a silent override.

- **Principle precedence:** I (Disk is Truth) and II (The Human Checkpoint) outrank all other principles. When a convenience, a performance gain, or a cleaner abstraction collides with truth-on-disk or the human gate, truth and the gate win.
- Every spec and plan is tested, by name, against all thirteen principles before implementation begins.
- Amendments require a stated rationale, a version bump, and a check that dependent templates and docs stay in sync.
- Semantic versioning of this document:
  - **MAJOR** — a principle removed or redefined in a backward-incompatible way.
  - **MINOR** — a new principle or materially expanded section.
  - **PATCH** — clarifications, wording, non-semantic refinements.

Runtime development guidance lives in `CLAUDE.md` (this repo) and `~/.claude/CLAUDE.md` (global). Where those and this constitution agree, this is the canonical statement; where they drift, amend one to match the other.

**Version**: 1.3.0 | **Ratified**: 2026-06-27 | **Last Amended**: 2026-08-25

> **1.3.0** (MINOR) — Added three principles governing how a feature reaches the human and how it changes state underneath them. **XI** (*Parity is Bidirectional*) closes the loop VI and IX left open: every CLI capability is reachable from the UI in the same feature that adds it, and a CLI-only capability is an explicitly recorded ruling, never an omission — #323's hardcoded `?force=1` is the scar. **XII** (*One Spelling per Option*) forbids CLI dialect drift: an option is introduced across its whole family with one name, one meaning and one default, declared once in the config model that owns it. **XIII** (*Breaking State Changes Migrate Out of Band*) requires a separate one-shot migration CLI rather than a lazy in-place upgrade or a dual-location back-compat probe, and makes a migration document part of the feature's output.
>
> **1.2.0** (MINOR) — Added Principle X (*Selection is Explicit; There is No Silent "All"*), arising from the ensemble chapter picker: a batch pass acts only on an explicitly chosen set, and "Select all" must materialize that set rather than be an empty-means-everything default.
