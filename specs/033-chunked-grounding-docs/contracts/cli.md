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
| `--backend` `--model` `--endpoint` | backend family as registered by `add_backend_args`. `--endpoint` (singular) names the one box of a single-endpoint run | `summary_native.extract.backend` / `.model`, else `schema.DEFAULT_DRAFT_BACKEND` / `DEFAULT_DRAFT_MODEL` |
| `--endpoints URL…` | several OpenAI-compatible endpoints sharing **one** chunk queue (dgx only); spelling as in `facts_to_state`. One set of worker threads per endpoint pulls the next chunk when free, so a slower box takes fewer chunks and the tail does not stall on it. Duplicates are ignored. It coexists with `--endpoint` as a flag, but the two are **refused together** (exit 2) | the single resolved endpoint |
| `--parallel N` | concurrent in-flight calls **per endpoint** (`--endpoints A B --parallel 4` allows 8 calls). At least 1 | `schema.DEFAULT_EXTRACT_PARALLEL` (6), GM ruling 2026-10-07. Unlike `extract_facts` (default 1), because the Sparks serve several sequences at once |
| `--chunk-chars N` | chunk size limit (characters) | `summary_native.extract.chunk_chars`, else `schema.DEFAULT_CHUNK_CHARS` |
| `--max-tokens N` | per call | `schema.DEFAULT_MAX_TOKENS` |
| `--dump-only` | write prompts, chunks and the manifest; no model call | off |
| `--force` | re-extract every chunk, ignoring cache keys | off |

**Output**: one line per chunk (`chunk 07/60 ch 009-010 @spark2:8001 214s kept 61 dropped 2`; `cached` replaces the endpoint and time for a reused chunk), then totals, the drops summary and any outlier chunks. The run record names the endpoint that handled each chunk.

**Refusals (exit 2)**:
- the corpus for the range is missing, or stale against the summaries or registry;
- **preflight:** before the first chunk is sent, every endpoint (`--endpoints`, or the single `--endpoint`) is asked for `/models`. One that does not answer, or does not serve `--model`, refuses the whole run with exit 2, naming the endpoint and what it serves, and **no chunk is sent**. The run record keeps the refusal;
- `--endpoints` used with a non-dgx backend;
- `--endpoint` and `--endpoints` together;
- `--parallel` < 1;
- `--chunk-chars` < 1 (`--chunk-chars must be a whole number of at least 1`).

**Exit 3**: one or more chunks failed after one retry, either the call failed or the output lacked a `##` section of the outline (#515; `- (none)` is the empty form, an absent heading is not). They are listed with the missing sections, in the run output, `drops.md` and the record, and the next run extracts only those. A cached chunk whose raw output lacks a section is reported the same way with no model call.

**Exit 4**: the backend could not be reached at all.

## `summary_native synth world_state | campaign_state` (changed)

For these two documents, `synth` now builds from the checked notes. `party` and `planning` keep the one-shot path and their flags, unchanged.

| Flag | Meaning | Default |
|---|---|---|
| `--backend` `--model` (+ `--claude-code-effort`) | prose-step backend. The effort applies to `claude-code`; another backend refuses it where it does not apply | `summary_native.prose.backend` / `.model` / `.effort`, else `claude-code` / `claude-sonnet-5-5` / `medium` |
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
- **Retired flags:** `--parts` on these two docs; `--audit` on campaign_state (`the audit is its own step: summary_native audit`) — on world_state `--audit` is refused earlier, as `--audit applies to campaign_state only`.
- **Flags that do not apply:** `--name`, `--recent-chapters`, `--recurring-min` on campaign_state (it has no Key NPCs section); `--fallback-npc-lines` and `--npc-root` on every doc except world_state; `--world-state` and `--campaign-state` (upstream drafts) on both. Each is refused (exit 2), never silently ignored.

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

The tracking-file audit as its own step. Code picks each item's candidate chapters, a model judges that one item against only those chapters, and code accepts SUPPORTED only for a citation inside them and a verbatim span (research R11, FR-026). It needs the built corpus; it does **not** need extracted notes.

| Flag | Meaning | Default |
|---|---|---|
| `--track-file FILE` (repeatable) | a tracking file; same spelling and meaning as `campaign_state --track-file` (Principle XII). Relative paths resolve against the campaign root. Each `- ` line is an item, numbered `A1`.. across the files in the order given | `grounding.yaml campaign_state.track_files` |
| `--backend` `--model` `--endpoint` `--endpoints` `--parallel` | judge backend; same family, defaults, per-endpoint semantics and refusals as `extract` (including preflight, and `--endpoint` + `--endpoints` refused together). The shared queue holds items instead of chunks | as `extract` (`summary_native.extract.*`) |
| `--candidates N` | max candidate chapters per item | `schema.DEFAULT_AUDIT_CANDIDATES` (3) |
| `--max-tokens N` | per call | `schema.DEFAULT_MAX_TOKENS` |
| `--dump-only` | write the system prompt, each item's prompt and the run record under `state/runs/<stamp>/`; no model call; `state/audit/` is not touched | off |
| `--force` | re-judge every item, ignoring cache keys | off |

**Steps**:
1. Code numbers the items and, for each, finds its candidate chapters: registry name forms found in the item (a single generic word never counts), plus words of four or more letters outside the packaged word list (`npc_forms.load_wordlist`), matched as whole words in each chapter's summary. The top N chapters with at least one hit are kept (ties go to the earlier chapter).
2. An item with no candidates is **NOT FOUND (`no-candidates`)** and makes **no model call**.
3. Every other item is one call: the item (as a claim, not evidence) and the full text of its candidate chapters. The answer is `SHOWN` / `NOT SHOWN` on the first line; `SHOWN` gives `CITE: [ch NNN / target] "span"`.
4. Code checks the answer. **SUPPORTED** needs: a citation in a candidate chapter that resolves to a scene or section of it, and a quoted span of at least 8 characters that is verbatim in the cited chapter. Otherwise the verdict is **NOT FOUND (`unverified`)**, counted NOT FOUND, and `audit.json` and `audit.md` say which check failed (outside the candidates, unresolved target, span not verbatim, no `CITE` line, or an answer that began with neither word). **NOT SHOWN** is NOT FOUND (`not-shown`). Partial evidence is kept only where its citations resolve inside the candidates and its quotations are verbatim.
5. Verdicts are cached per item (a key over the prompts, backend, model and `--max-tokens`); a cached answer is **re-checked by the current code**, so a change to the check applies without a new call.

**Writes** (all under the range's `state/`): `audit/items.json` (items, candidate chapters, cache keys, the track-file digests and the notes-manifest digest that `freshness.check_audit_fresh` compares), `audit/audit.json` (a verdict per item with the model's answer, which is the cache), `audit/audit.md`, and `runs/<stamp>/record.json` with `audit.<id>.user.md` / `.out.md` per judged item.

**Output**: one line per judged item, then `audit: 443 items — 171 SUPPORTED, 249 NOT FOUND (31 no candidates, 18 unverified)` and a count of judged and cached items. When any SHOWN answer was downgraded, a line says so; `audit.md` carries each item's reason.

**`synth campaign_state`** renders its Audit section from `audit.json` (`state_sections.audit_md`). With no audit run it reads "Audit not run for this range."; with a stale audit (a track file added, removed or changed, or the notes re-extracted) it refuses, naming `summary_native audit`.

**Refusals (exit 2)**: no track files (neither `--track-file` nor config), a track file that does not exist, track files holding no items; the corpus missing or stale against the summaries or registry; `--candidates` < 1; the `extract` endpoint refusals.

**Exit 3**: one or more items failed after one retry. They are recorded as `NOT JUDGED` in `audit.json`, and `audit.md` and campaign_state say so; the next run judges only those. **Exit 4**: no item could be judged (the backend could not be reached).

## Unchanged

`validate`, `build`, `compare`, the `npc-*` commands, and `synth party|planning`.
