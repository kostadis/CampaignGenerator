# CLI Contract: `summary_native` extract | synth | annotate | audit

All commands run from the campaign root and resolve config after parsing (`find_default_config()`). They share 031's common flags, with unchanged spellings and meanings: `--summaries-dir --since --until --out-root --registry --canon --config`.

Exit codes follow 031/032 (`contracts/cli.md` there):

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | blocking validation problems |
| 2 | refusal (message names the fix) |
| 3 | incomplete (a section or chunk is missing) |
| 4 | model call failed |

Precedence everywhere: **flag > `grounding.yaml summary_native` > `schema.py`**.

## `summary_native extract`

The map step: per-chunk model calls, then the code check. It writes `state/notes/`.

| Flag | Meaning | Default |
|---|---|---|
| `--backend` `--model` `--endpoint` | backend family as registered by `add_backend_args` | `summary_native.extract.backend` / `.model`, else `schema.DEFAULT_DRAFT_BACKEND` / `DEFAULT_DRAFT_MODEL` |
| `--endpoints URL…` | several OpenAI-compatible endpoints sharing one chunk queue (dgx only); spelling as in `facts_to_state` | the single resolved endpoint |
| `--parallel N` | concurrent calls per endpoint | `schema.DEFAULT_EXTRACT_PARALLEL` (6) |
| `--chunk-chars N` | chunk size limit (characters) | `summary_native.extract.chunk_chars`, else `schema.DEFAULT_CHUNK_CHARS` |
| `--max-tokens N` | per call | `schema.DEFAULT_MAX_TOKENS` |
| `--dump-only` | write prompts, chunks and the manifest; no model call | off |
| `--force` | re-extract every chunk, ignoring cache keys | off |

**Output**: one line per chunk (`chunk 07/60 ch 009-010 @spark2 214s kept 61 dropped 2`), then totals, the drops summary and any outlier chunks.

**Refusals (exit 2)**:
- the corpus for the range is missing, or stale against the summaries or registry;
- an endpoint is unreachable or does not serve `--model`, with the endpoint and what it serves;
- `--endpoints` used with a non-dgx backend;
- `--chunk-chars` < 1.

**Exit 3**: one or more chunks failed after one retry. They are listed, and the next run extracts only those.

**Exit 4**: the backend could not be reached at all.

## `summary_native synth world_state | campaign_state` (changed)

For these two documents, `synth` now builds from the checked notes. `party` and `planning` keep the one-shot path and their flags, unchanged.

| Flag | Meaning | Default |
|---|---|---|
| `--backend` `--model` (+ `--claude-code-effort`) | prose-step backend | `summary_native.prose.backend` / `.model` / `.effort`, else `claude-code` / `claude-sonnet-5-5` / `medium` |
| `--recent-chapters` `--recurring-min` `--name` | world_state Key NPCs selection (031 rules) | 031 defaults |
| `--fallback-npc-lines` | world_state only: when a selected NPC has no published, verified dossier, write a code-built line marked `(no published dossier — from checked notes)` instead of refusing. **Per run; never read from config** | off |
| `--npc-root` | world_state only: where draft verifications and the publish log live, used to explain a missing dossier. Same spelling and resolution as the `npc-*` commands | `npc_dossiers.yaml npc_root`, else `schema.DEFAULT_NPC_ROOT` |
| `--max-tokens N` | per prose call | `schema.DEFAULT_MAX_TOKENS` |
| `--dump-only` `--force` | as 031 | off |

**Steps**:
1. Code builds the timeline, completed list, NPC status table, reference files and the audit section (from `state/audit/` if present).
2. The prose calls run, one per prose section, plus one Key NPCs call.
3. Code checks the prose calls' output (each section's heading is present, and Key NPCs lines pass their checks).
4. `annotate` runs automatically.
5. The drafts are written.

**Refusals (exit 2)**:
- **No checked notes:** `no checked notes for ch002-070; run: summary_native extract --since 2 --until 70`.
- **Stale notes:** the notes are stale against the summaries, registry or `players.yaml`.
- **Missing dossiers (default, world_state):** one or more selected NPCs lack a published, verified dossier. The message lists each NPC as `<Name>: not drafted`, `<Name>: failed verification (not-found 2)` or `<Name>: drafted, not published`, then the commands to draft, verify and publish them, and the `--fallback-npc-lines` alternative.
- **Retired flags:** `--parts` on these two docs; `--audit` on campaign_state (`the audit is its own step: summary_native audit`).

**Exit 3**: a prose section is missing from its output. The doc is written as `*.incomplete.md`, never as a draft.

**Report lines**: the budget per world_state section (`Locations: 279/450 words`), Key NPCs fallbacks or substitutions, and the annotation counts.

## `summary_native annotate world_state | campaign_state`

This step is deterministic, with no model call. It runs the detectors on an existing draft and rewrites only its annotations: existing annotation sub-bullets are replaced, and line text is never changed. Use it after publishing a dossier or editing a summary when you don't want a full rebuild.

| Flag | Meaning |
|---|---|
| `--dry-run` | print the hits, write nothing |

**Output**: `annotations: 8 later, 7 since, 2 unverified; 0 removed`.

**Refusals**: no draft exists for the doc, or the notes are stale.

## `summary_native audit`

The tracking-file audit as its own step.

| Flag | Meaning | Default |
|---|---|---|
| `--track-file FILE` (repeatable) | a tracking file; same spelling and meaning as `campaign_state --track-file` (Principle XII) | `grounding.yaml campaign_state.track_files` |
| `--backend` `--model` `--endpoint` `--endpoints` `--parallel` | judge backend; same family and defaults as `extract` | as `extract` |
| `--candidates N` | max candidate chapters per item | `schema.DEFAULT_AUDIT_CANDIDATES` (3) |
| `--dump-only` `--force` | as above | off |

**Output**: `audit: 443 items — 171 SUPPORTED, 249 NOT FOUND (31 no candidates, 18 unverified)`.

**Refusals**: no track files; a corpus or notes freshness problem; an endpoint preflight failure.

## Unchanged

`validate`, `build`, `compare`, the `npc-*` commands, and `synth party|planning`.
