# Research: Chunked, Code-Checked Grounding Documents

Every decision below is grounded in the experiment (`experiments/20261007-chunked-state-docs/`, `RESULTS.md` rounds 1–7; prototype code in the same folder) or in existing repo precedent. No `NEEDS CLARIFICATION` remains.

## R1. Two commands, not one: `extract` then `synth`

- **Decision**: Split the work into `summary_native extract` (the map step: per-chunk model calls plus the code check, writing checked notes to disk) and the existing `summary_native synth world_state|campaign_state` (code-owned sections plus prose calls, reading the checked notes). Annotation runs at the end of `synth` and is also its own deterministic command, `summary_native annotate`. The audit is `summary_native audit`.
- **Rationale**:
  - **One `--backend`/`--model` per command keeps Principle XII intact.** FR-022 needs a different backend per step. Two flag families on one command (`--map-backend`, `--prose-model`, …) would be a new dialect.
  - **The checked notes become a file on disk between steps** (Principles VIII and IX). The GM can read `drops.md` before spending prose calls, and a rebuild that changes only prose never re-extracts (FR-006, SC-007).
  - **It matches the ensemble precedent:** extraction and synthesis are separate commands there too.
- **Alternatives considered**: One command with two flag families (rejected: XII). One command with the prose backend in config only (rejected: XI, because a run-shaping choice must be reachable per run).

## R2. Chunking: whole chapters up to a character limit

- **Decision**: Pack whole consecutive chapters until the next would exceed `chunk_chars` (default 60,000, the value spec 032 already declares as `DEFAULT_CHUNK_CHARS`). A chapter larger than the limit is its own chunk, and chapters are never split.
- **Rationale**: This is `npc_chunked.make_chunks`'s rule, already reviewed and tested. On OOTA chapters 2–70 it gives 60 chunks of about one chapter each. That was enough for the experiment's best results and keeps each call to roughly 15K tokens.
- **Implementation note**: Generalise `make_chunks` to accept any `(number, text)` sequence. The NPC path keeps calling it unchanged.
- **Alternatives considered**: Larger chunks (fewer calls, but more output per call; the experiment saw runaways grow with output length). Scene-level chunks (too many calls; they lose a chapter's NPC and location sections).

## R3. Note format and citation grammar

- **Decision**: Each extraction call writes six `##` sections: Events, Concluded, Threads, NPC Status, World, Party. There is no Audit section (R11). Every bullet ends in a citation `[ch NNN / target]`.
- **Citation targets**: a scene id (`NNN.SS`), or a section key: `moment`, `npcs`, `locations`, `items`, `spells`, `abilities`, `end`.
- **Section headings are accepted as their keys:** a section's own heading text, in any case (`NPCs`, `Memorable Moments`, `Session-End State`), maps exactly to its key. Anything else is invalid. This fix came from round 2: a strict drop of a correct row flipped Sarith's status (RESULTS round 2).
- **Tags**:
  - Threads take `[OPENED|ADVANCED|RESOLVED|ABANDONED] **Name** — …`.
  - World takes `[FACTION|NPC|LOCATION|ITEM|THREAT] **Subject** — …`.
  - An NPC Status row is `- Name | Status | Location | Disposition [cite]`, with Status one of Alive, Dead, Missing, Imprisoned, Departed or Unknown.
- **Dossier citations**: dossiers cite an NPC's own entry as `entry`. That maps exactly to `npcs` wherever dossier text is checked (R9).
- **Rationale**: This is the experiment's grammar after its fixes. It is exact, so no fuzzy citation matching is needed, and it is checkable by code.
- **Alternatives considered**: JSON output (rejected: the reader of the notes, and of `drops.md`, is the GM, and markdown bullets diff cleanly). Free-form citations (rejected: they can't be checked).

## R4. The code check, and what it reuses

- **Decision**: A new deterministic module, `notes.py`, checks each note.
  - **Citations:** every part must resolve to a scene or section that exists in that chunk's chapters. Failures are recorded as `invalid-citation` or `outside-chunk`.
  - **Quoted spans:** each must be verbatim in the summaries, using `npc_check`'s typography-folding comparison (`_contains`, `SPAN_RE`, `strip_quote_marks`). A failure is recorded as `quoted-span-not-found`.
  - **Tags and format:** `missing-thread-tag`, `missing-world-tag`, `malformed-row` and `nested-bullet`.
  - **Drops:** every dropped note goes to `drops.md`, with counts per chunk and per reason. A chunk whose drop count is an outlier (above 3× the run's median, with at least 20 drops) is flagged as a possible runaway. The experiment's runaway chunks fit that rule.
- **Rationale**: These are the experiment's checks, and quote matching stays shared with `npc_verify` (Principle V). The outlier flag makes a degenerate call visible.

## R5. The extraction cache

- **Decision**: Each chunk's raw output and its checked result are cached under `notes/` and keyed by a hash of:
  - the chunk's chapter texts,
  - the extraction system prompt and outline,
  - backend, model, `max_tokens` and `chunk_chars`.

  A chunk whose key matches is reused. `--force` re-extracts.
- **Rationale**: This mirrors `npc_draft`'s `draft_key`. It makes a run resumable after a failure (spec US1 scenario 7) and makes prose-only rebuilds free.

## R6. Several Spark endpoints sharing one queue

- **Decision**: `extract` accepts `--endpoints URL…`, the spelling that `facts_to_state` and `ensemble_batch` already use.
  - **Sharing:** every endpoint gets `--parallel` threads (default 6) that pull chunks from one shared queue. The spelling is `extract_facts.py`'s existing `--parallel N` ("concurrent in-flight chunk requests against the endpoint"), which has the same meaning (Principle XII).
  - **Preflight:** before any call, every endpoint must answer `/v1/models` and list the requested model, or the run refuses and names the endpoint.
  - **Default endpoint:** with no `--endpoints`, the single endpoint resolves as it does for `npc-draft` (`--endpoint`, `DGX_ENDPOINT`, wiring `dgx_endpoint`).
  - **Record:** the run record notes the endpoint that handled each chunk.
- **Rationale**: In the experiment this roughly doubled throughput with two boxes, and the slower box simply took fewer chunks. The flag spelling is the existing one (XII).
- **Endpoints stay out of campaign config.** They are machine wiring, not campaign state, which is also why `npc_dossiers.yaml` refuses an `endpoint` key.
- **Alternatives considered**: A fixed split per endpoint (rejected: one slow box stalls the tail, see memory `project_ensemble_tail_straggler`).

## R7. Backend defaults per step

- **Decision**: Defaults are declared once, in `schema.py`, and surfaced through `grounding.yaml summary_native`. There are new `extract:` and `prose:` blocks on the strict config model.
  - **`extract`:** `backend` defaults to `DEFAULT_DRAFT_BACKEND` (`dgx`) and `model` to the same Spark default spec 032 uses. The GM sets the model actually served (the experiment's best was `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`).
  - **`prose`:** `backend: claude-code`, `model: claude-sonnet-5-5`, `effort: medium`, passed as the existing `--claude-code-effort`.
  - **Precedence:** a flag beats `grounding.yaml`, which beats `schema.py`. This is 031's rule.
- **Rationale**: Round 7 showed Sonnet 5.5 at medium effort writing the most faithful prose (94% verbatim quotes, about 2 minutes, about $1–1.50 per rebuild at API rates, nothing extra on the subscription). Round 6 showed Spark models do the bulk extraction well. Nothing checks for an API key (FR-024; `tests/test_no_credential_gate.py`).

## R8. Routing notes to prose sections, and budgets

- **Decision**: Code routes the notes, never the model.
  - **world_state:**
    - Party ← Party notes, plus the last chunk's summaries for current state
    - Factions ← `[FACTION]` notes
    - Locations ← `[LOCATION]`
    - Items ← `[ITEM]`
    - Threats ← `[THREAT]` notes plus the thread ledger
    - Key NPCs ← published dossiers (R9)
  - **campaign_state:**
    - Resolved Plot Threads ← the thread ledger
    - Active Quests & Open Threads ← the thread ledger plus the last chunk
    - Party Current Situation ← Party notes plus the last chunk
  - **Word budgets** apply to world_state's prose sections. The defaults, from round 3: Party 700, Factions 450, Key NPCs 900, Locations 450, Items 450, Threats 600. They are configurable in `grounding.yaml summary_native.prose.budgets`.
  - **Overruns** are reported in the run record and never truncated.
- **Quotation rule**: the prose prompt allows quotation marks only around words spoken or written in the summaries, never around note text. This is round 7's Opus finding. A violation is caught by R10's non-verbatim detector and annotated.
- **Rationale**: In round 3, budgets with reference files took world_state from 237K to 16.5K characters with no detail lost.

## R9. Key NPCs from published dossiers, and what happens without one

- **Decision**: A deterministic module, `key_npcs.py`, does the following.
  - **Selection:** it picks NPCs with the existing `select.select_dossiers` recent/recurring rules over the global NPCs.
  - **Reading:** it reads each published dossier through `published_view()`, which returns only the dossier's name, header facts, `## Identity` and `## Last Observed State`, so it structurally cannot return Secrets. This mirrors `npc_authored.load_manual()` never returning `secrets`.
  - **Rendering:** a single model call, in `synth`, writes one line per NPC.
  - **Line check:** exactly one line per selected NPC, and no additions or reordering. Citations must come only from that NPC's dossier, and quotations must be verbatim. A failing line falls back to the dossier's own first cited sentence.
  - **Pointers:** each line ends `→ docs/npcs/<slug>.md`.
- **Missing dossiers** (GM ruling, 2026-10-07): by default, if any selected NPC has no published, verification-passing dossier, `synth world_state` refuses with exit 2. The refusal names each NPC and its state: not drafted, failed verification (listing the failing checks from `*.verify.md`), or drafted but not published. `--fallback-npc-lines` (per run, never in config) instead writes a line built by code alone from the NPC's latest status row and checked notes, verbatim with citations and marked `(no published dossier — from checked notes)`.
- **Rationale**: Round 4 showed the dossier-sourced section correct where the model-written one was wrong. The GM chose the strict default.

## R10. Annotation detectors

- **Decision**: A deterministic module, `annotate.py`, takes the experiment's `fixpass.py` detectors and drops its model fixer. Each detector annotates rather than rewrites:

  | Detector | Fires when | Annotation |
  |---|---|---|
  | stale | a line's newest citation is older than a later note about the line's subject (its bold subject, resolved through the registry) | `⚠ later:` plus the later note verbatim |
  | mentioned status change | judged per claim, where a claim is the text up to its own citation: a mentioned NPC's status row after that citation differs from the status row at or before it. No row before means no flag | `ℹ since:` plus that NPC's later status row |
  | cross-section | the same subject appears in another section citing a later chapter | `⚠ later: see <Section>: …` |
  | non-verbatim quote or invalid citation | a quote or citation fails the check | `⚠ unverified:` |
  | player character in an NPC section | — | the line is removed |

  Every annotation and removal is listed in `annotations.md`.
- **Reading contract**: world_state opens with a fixed block explaining the markers, what a citation points to, and where the timeline and reference files are. The text is fixed in code (as `CONTRACT` in the prototype's `annotate.py`).
- **Wording**: the unverified message says "not verbatim in the summaries" (round 5's correction), not "not in the summaries".
- **Rationale**: Round 4 showed a gated model fixer harms about a third of the lines it touches, including a real citation attached to a wrong meaning, which no gate can catch. Round 5 showed the annotations steer session prep to the right evidence.

## R11. The audit as its own step

- **Decision**: `summary_native audit` runs the tracking-file audit outside the extraction step.
  - **Items:** each `- ` line of the files in `grounding.yaml campaign_state.track_files`, numbered.
  - **Candidate chapters (code):** score each chapter by the item's distinctive tokens. Those are registry name forms found in the item, plus words of four or more letters outside the generic word list, matched as whole words in that chapter's summary. Keep the top 3 chapters with at least one hit. An item with no candidates is reported NOT FOUND with the reason "no candidate chapters", and no model call is made.
  - **Judgment (model):** one call per item, against only those chapters' full summaries. The answer is SHOWN or NOT SHOWN, and SHOWN must give a citation in a candidate chapter and a verbatim span from it.
  - **Check (code):** a SHOWN verdict is accepted only if the citation resolves within the candidates and the span is verbatim there. Anything else is reported "unverified" and counted NOT FOUND.
  - **Output:** verdicts go to `audit.json` and `audit.md`. `synth campaign_state` renders its Audit section from them, or says "audit not run".
  - **Cost:** calls are cached per item (same key scheme as R5) and run on the extraction backend and its endpoints. OOTA has 443 items and is a one-time cost per range.
- **Rationale**: Inside every map call the audit degraded: weak recall, one call listing all 443 items as "SHOWN in a prior session", and 42% of Qwen3-Next's output going to audit noise. Code-chosen candidates keep the scope decision out of the model's hands (Principle II), and the required span makes SHOWN checkable.
- **Alternatives considered**: Batching several items per call (fewer calls, but an item is then judged beside unrelated chapters, which is the old failure). Embedding-based candidate retrieval (more recall, but it adds a dependency; can come later).

## R12. Output layout and promotion

- **Decision**: Everything is written under the range's corpus directory, in a `state/` folder (layout in `data-model.md`): `notes/`, `runs/`, the drafts, `reference/`, the timeline, `annotations.md` and the audit files. Promotion stays manual, as in spec 031. A documented copy puts world_state, campaign_state, `reference/` and the timeline into `docs/`, which is where the reading contract points.
- **Rationale**: The output is additive. Nothing in the live `docs/` is written by a tool (FR-028).

## R13. The one-shot path for these two documents

- **Decision**: `synth world_state` and `synth campaign_state` require the checked notes from `extract`. Without them they refuse with exit 2 and the `extract` command to run. The one-shot path stays for `party` and `planning` only (FR-029).
  - `--parts` refuses for these two documents. The prose step already makes one call per section.
  - `--audit` refuses on `synth campaign_state`, naming `summary_native audit`.
- **Rationale**: This is a single-user system, so migrate and delete (memory `feedback_single_user_no_backcompat`, Principle XIII's no dual paths). No state changes shape, so no migration CLI is needed: the old drafts are simply files the next build replaces with `--force`.

## R14. The session-prep contract

- **Decision**: The contract lives in `contracts/session-prep.md`, with an operator copy in `docs/cli/summary_native_howto.md`. It covers:
  - the state documents are an index;
  - verify every on-stage entity against its latest summary;
  - the summary wins, and the disagreement is listed;
  - tags `[TABLE chNN NNN.SS]` and `[DOC unverified: <doc>]`;
  - "Doc errors found" at the end.

  The draft text is the experiment's `skills_variant/gm-session-prep-pointer/SKILL.md`. The skill change itself ships in the gm-assistant repo, as a follow-up issue filed from this feature.
- **Rationale**: In round 5 this contract gave the best preparation, found 8 real document errors, and took no extra wall time.
