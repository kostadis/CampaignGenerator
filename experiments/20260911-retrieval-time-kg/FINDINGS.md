# Retrieval, time, and a knowledge graph — 2026-09-10 → 09-11

**Evidence only.** No campaign canon, no chapter revision, no production change.
Tracking issue: [CampaignGenerator#463](https://github.com/kostadis/CampaignGenerator/issues/463).

A two-day investigation into how five retrieval tools answer campaign questions
from session summaries, run against the Obelisk campaign (11 written sessions,
one unwritten). It started as "configure cognee against the DGX Spark" and ended
at a design for an event-ordered knowledge graph built without any model.

**Read §8 first** — it is the result the rest supports. The practical method it
leads to — building the graph and generating `campaign_state` / `world_state` for
LLM prep, with the issues found — is in
[STATE_GENERATION_METHOD.md](STATE_GENERATION_METHOD.md).

---

## 1. Headline

1. **Every semantic tool failed the time question.** Asked for "the most recent
   session", cognee returned Chapter 8, zvec-grep returned session 6, mempalace
   returned session 8. The answer is session 11. None of them read the
   filename ordinal, which is the only authoritative ordering in the corpus.
2. **Cognee invents the record at ingest.** Its generated edge descriptions are
   1.18× the size of the source text and contain paraphrase drift, module
   imports, and false entity merges — stored as fact and served back as
   "the record".
3. **The verbatim tools never fabricated.** tgrep, zvec-grep, and mempalace
   returned source text in every run. Their failures were retrieval and ranking
   failures, never invented content.
4. **Enumeration and lookup are different jobs.** A state document needs
   exhaustive enumeration (regex); a question needs lookup (vector). The scene
   spine extracted by `tgrep` and by `zg --rg` was byte-identical — 72 scenes.
5. **The sequence of events is already authored.** Every summary's `## Scenes`
   section is in play order. A knowledge graph keyed on event ordinal — not
   calendar date — answers the time questions every other tool failed, and is
   built deterministically in about a second.

---

## 2. Setup

- **LLM:** `qwen3.8-flash-next` on spark1 (`192.168.1.147:8001`), vLLM,
  `--max-num-seqs 8`. spark2 served the same model id and was **idle the entire
  run** — cognee accepts one `LLM_ENDPOINT` and has no fan-out.
- **Embeddings:** `qwen3-embedding:0.6b` via Ollama on spark2 (`:11434`).
- **Corpus:** the Obelisk session summaries. For the tool comparison, the
  12-file set at `obelisk/docs/summaries` (incl. `009-session-not-written.md`).
- **Tools:** cognee (editable install of `~/src/cognee` @ 1.5.3), tgrep,
  zvec-grep (`zg`), mempalace (editable install of `~/src/Mempalace` @
  `kostadis-dev`), and a purpose-built event-ordinal KG (SQLite).

---

## 3. Cognee — configuration findings

Ordered by impact. All reproduced; evidence in `evidence/ingest_log_excerpts.md`.

| # | Finding | Evidence |
|---|---|---|
| 3.1 | **Reasoning consumes the whole completion budget.** On a 4,000-char extraction chunk the model spent all 8,000 tokens reasoning and emitted **0** content chars (251 s). With thinking off: 25,397 chars (172 s). | direct vLLM A/B |
| 3.2 | **Fix:** `LLM_ARGS='{"extra_body": {"chat_template_kwargs": {"enable_thinking": false}}}'` → 84 s, 32 nodes / 37 edges on the same chunk. | `llm_args` merged at `native_adapter.py:433` |
| 3.3 | **Silent path-to-text ingestion.** With `COGNEE_ALLOWED_LOCAL_FILE_ROOTS` unset, a path outside `[CWD, /tmp]` is ingested as its own string and `remember()` still reports `status='completed'`. | chunk text was the literal path, 19 tokens |
| 3.4 | **`AUTO_RATE_LIMIT` (default true) re-creates the #3870 failure** — timeouts trigger a 60-RPM limiter that paces admission, not in-flight work. | 6 activations, run 1 |
| 3.5 | **litellm's timeout is 3× the configured value** — three internal attempts before raising. `600 → 1801 s`, `1800 → 5401 s`. Lowering the timeout to fail faster does the opposite. | both samples in excerpts |
| 3.6 | **`data_per_batch` caps documents, not calls.** Each document gathers over its own chunks, so 8 documents ≈ 24 concurrent calls against 8 server slots. | vLLM queue depth |
| 3.7 | **`forget(data_id=…)` requires a `UUID` object and `dataset=`**, contrary to the docstring. | `'str' object has no attribute 'hex'` |

ToEE corpus, three runs:

| Run | Reasoning | Timeouts | Outcome |
|---|---|---|---|
| 1 — unbounded | on | 493 | killed at ~5 h, incomplete |
| 2 — `data_per_batch=8` | on | 14 | killed at 31 min, 0 extractions |
| 3 — thinking off | **off** | **0** | **completed, 26.8 min** |

The concurrency tuning in run 2 treated a symptom. The cause was 3.1.

---

## 4. Cognee — it invents the record

### 4.1 Volume

| | chars |
|---|---|
| Source chunk text ingested | 2,093,539 |
| **Model-generated text stored in the graph** | **2,468,434** (1.18×) |
| of which edge descriptions | 1,803,395 (73%) |

≈617k output tokens. This — not input size — is what drives ingest time.

### 4.2 What the generated layer contains

Three kinds of invention, all tagged as deriving from the play record:

| Kind | Example (stored `edge_text`) | Source actually says |
|---|---|---|
| Paraphrase drift | "Professor Orryn Voss is alive and in a **dangerous location**" | "not in a place where dead is easy" |
| Module import | "Gundren Rockseeker is being held by **King Grol** at Cragmaw Castle" | no session places Gundren anywhere after the ambush |
| Module import | "Droop… **knows Cragmaw Castle is in Neverwinter Wood**" | Droop fainted and was left behind |
| Entity collapse | "**Iarno Albrek, the Black Spider**" | Iarno *serves* the Black Spider |

327 edges assert something about Cragmaw Castle — a location the party has never
found.

### 4.3 Why — the extraction prompt instructs it

`generate_graph_prompt.txt`:

- *"Nodes… are akin to **Wikipedia** nodes"* — asks for encyclopedic synthesis,
  not a record of events.
- *"Every edge should include a description"* — mandates generation; the 73%.
- *"Coreference Resolution… always use the **most complete identifier**"* —
  the direct cause of the Iarno/Black Spider merge.
- *"Do not add outside knowledge"* — present, one clause, and it loses.

### 4.4 The schema overrides the prompt

A stripped prompt was A/B-tested on the 11 summaries (`scripts/prompt-exp/`):

| | Default | Stripped |
|---|---|---|
| Wall clock | 900.4 s | 668.2 s (−26%) |
| Generated chars | 205,306 | 149,041 (−27%) |
| **Edges with a description** | 1558 / 1558 | **1602 / 1602** |
| Iarno == Black Spider | fabricated | **fabricated** |

The prompt said *"LEAVE `description` NULL."* Every edge still got one. The
`Edge` schema's own field description — *"Concrete one-sentence fact expressed by
this edge"* — is serialised into `response_format` on every call. **With
structured output, the schema is the stronger instruction.** The route to
suppressing descriptions is `cognify(graph_model=…)` with a model that has no
such field, not a better prompt.

---

## 5. Cognee — mitigations tested

### 5.1 Provenance tiering (`node_set`)

Corpus re-ingested in five tagged tiers (`data/tier_manifest.json`): 187 files →
161 items (26 byte-identical duplicates), 7,726 s, 0 timeouts.

`search(node_name=["play_record"])` retrieval contained **0** mentions of
Cragmaw Castle, King Grol, or Nezznar across 90,420 chars. **The filter works at
the retriever.** It did not stop the model: with the default prompt, the answer
still placed Gundren at Cragmaw Castle — from training priors, with no
supporting context.

Unfiltered retrieval also surfaced **unplayed session prep** ("Gundren
Rockseeker is held unconscious in King Grol's quarters (Room C14)") as history.

### 5.2 Strict system prompt

`data/strict_prompt.txt` forbids outside knowledge and requires "Not recorded".

- Gundren: default leaked Cragmaw Castle; strict answered "location unknown".
- 36 repeat trials, six open threads × two arms × three reps
  (`data/trials.json`): **1 fabrication in 18 baseline runs, 0 in 18 strict.**
  Hedge rates 15/18 vs 18/18. A smaller effect than the first two questions
  suggested.
- It still fabricated elsewhere: "Voss may have been tracking the Black Spider"
  (no co-occurrence in the record) and quotation marks around "dangerous
  location".

### 5.3 Chunking

Droop's fate was one sentence inside an **18,987-char chunk covering 13 NPCs**;
its embedding represented all of them and it was never retrieved. Splitting
`## NPCs / Locations / Items` into 253 per-entity documents (avg 859 B) fixed
it. `## Spells` was not split, so "deliberately sparing Droop" stays
unretrievable — the same failure, one section left.

### 5.4 Method caveat

`search(only_context=True)` performs its **own** retrieval, independent of the
answering call. Probing context in one call does not show what the answering
call saw. Several "absent from context" readings during this work were
artifacts of this.

---

## 6. Retrieval tool comparison

Same seven questions, same 12 files.

| Question | cognee | tgrep | zg | mempalace |
|---|---|---|---|---|
| Gundren | ❌ invented Cragmaw Castle | ✅ | ✅ | ✅ |
| Droop | ✅ after re-chunking | ✅ | ✅ full sentence | ✅ sentence cut at drawer boundary |
| Glasstaff | ✅ with strict prompt | ✅ | ✅ found the teleport escape | ⚠️ missed the escape |
| Ruxithid | ❌ 4 fabrications | ✅ | ✅ | ⚠️ tangential |
| Obelisk | ✅ synthesis | — | ⚠️ anecdote | ⚠️ anecdote; definition ranked 2nd |
| Mind flayers | ✅ "Not recorded" | ✅ absent | ❌ unrelated hits | ❌ unrelated hits |
| Most recent session | ✅ | — | ❌ session 6 | ❌ session 8 |

### 6.1 Per-tool notes

- **tgrep** — exact, verbatim, 0.2 s rebuild. Cannot answer a question it
  cannot phrase as a pattern. **Its index went stale twice**: once missing 195
  of 1,092 files while `meta.json` read `"complete": true`, once 4.5 h older
  than a directory created that afternoon. Both times the failure was a
  shorter result list, indistinguishable from "no match".
- **zg** — the best lookup tool. Natural-language queries, verbatim results,
  and structural scope attached (`Session 2026-08-02::NPCs`). Returned Droop's
  complete fate as hit #1. Cannot report absence (always returns top-k) and
  cannot order by time. `--preview` defaults to `none` when piped.
- **mempalace** — "Verbatim always" held; no fabrication. 3 m 22 s to mine 12
  files into 607 drawers. Ranking is dominated by BM25: Droop outranked a
  higher-cosine Rondar hit (0.493 vs 0.545) on keyword score alone, and the
  Obelisk definition (cosine 0.383) lost to an anecdote (0.298). An AAAK index
  entry (`generated_by=unknown`) surfaced as a result.
- **cognee** — the only tool that can decline ("Not recorded") and the only
  one that synthesises. Also the only one that invents.

### 6.2 cognee generates, tgrep verifies

`scripts/retrieval/verify.py` checks (1) quoted strings verbatim and (2) proper
nouns present. On a planted document it caught **6 of 8** fabrications —
every imported name (King Grol, Neverwinter Wood, Zeond, Dark Hall, the
`Scraptors` corruption of `Scraptops`) and the paraphrased quote.

It **cannot** catch false relationships between real entities. The strict-prompt
Ruxithid answer contained four such fabrications ("Ruxithid's quarters",
"joining Brughor at Wyvern Tor", Daran's warning, Hamun's hypothesis); none were
flagged, because every name in them is real. A third check — entity-pair
co-occurrence — produced mostly false positives on real prose, because a state
document legitimately combines facts from different sessions.

---

## 7. Time — mempalace's knowledge graph

`mempalace_kg_query` is documented as the tool for time-bound facts. **Mining
does not populate it** — the KG is a SQLite triple store with
`valid_from → valid_to`, written by `add_triple()`. 71 triples were written
deterministically (`scripts/kg/populate_kg.py`): per-session appearances, plus
seven cited state changes with `invalidate()`.

| Test | Result |
|---|---|
| Where is Glasstaff? | `located_at Tresendar` → current=False; `status at large` → current=True ✅ |
| Party now | Old Owl Well, level 4 ✅ |
| Party **as of 2026-08-10** | Phandalin, level 3 ✅ — no other tool can answer this |
| Most recent session | **session 004** ❌ |

`timeline()` sorts `ORDER BY valid_from ASC NULLS LAST`, so undated facts land
*after* September. `003a` is genuinely undated ("Not recorded in the Zoom
summary"). `004` is dated ("Jun 17th, 2026") but in a format the population
parser did not accept — so one of the two misorderings was the parser's, not
the data's.

**The KG does not find time; it stores time it is given.** Glasstaff's
`invalidate()` was a human call from a cited line. If a model writes those
calls, this reproduces §4 with a validity window attached.

---

## 8. The event-ordinal knowledge graph

The sequence of events is already in the documents. Filename gives session
order, `## Scenes` gives scene order, the bullets give beat order. **Time is the
event ordinal, not the calendar.**

`scripts/kg/event_kg.py` builds it from `obelisk/docs/summaries` in ~1 s:

| Layer | Source | Decided by |
|---|---|---|
| **Time** — `events`, `beats` | `## Scenes` in file order | nobody — authored order |
| **State** — `snapshots` | `## NPCs / Locations / Items`, as of each session's last event | the summaries |
| **Identity** — `mentions` | `docs/aliases.json` | **the GM — the one precision decision** |

Result: 12 sessions, 72 events, 936 beats, 253 snapshots, 502 mentions — the
same 72 / 936 / 253 produced by three independent extractions.

| Query | Result |
|---|---|
| Most recent session | **011** ✅ (009 reported as unwritten) |
| Last 10 events, grouped by session | events 63–72 across sessions 010 / 011 ✅ |
| Undated sessions | `003` → `003a` → `004` → `005` ordered correctly ✅ |
| Gundren — last seen | event 38 of 72, session 006, **34 events ago** ✅ |
| Droop — as of event 40 | not yet in the record ✅ |

### 8.1 Identity is the precision decision

With canonical names only, Gundren had **4** mentions; via the reviewed
`aliases.json`, **15** across six sessions. The alias file correctly merges
`Glasstaff = Iarno Albrek` and does **not** merge Iarno with the Black Spider —
the merge cognee made.

It also maps `The Spider / the drow → Nezznar the Spider`. "Nezznar" appears
**zero** times in the session summaries; it comes from planning and the module
inventory. The alias file mixes two different decisions:

| Kind | Example | Known to |
|---|---|---|
| Surface-form equivalence | `Gundren` = `Gundren Rockseeker` | everyone |
| Secret identity | `The Spider` = `Nezznar` | the GM only |

**An identity revelation is itself an event.** The party learned Glasstaff was
Iarno in session 005. Storing `(Glasstaff, same_as, Iarno, from_event=30)` makes
"what did the party know as of event 25" answerable, and keeps GM-only
identities out of party-knowledge answers.

### 8.2 Open items

- Normalise quote characters — Iarno currently splits across two entities
  (`"Glasstaff"` vs `'Glasstaff'`).
- Split `aliases.json` into surface forms and GM-only identities.
- Record identity revelations as event-bounded facts.
- Split `## Spells` (and any remaining monolithic section) for retrieval.

---

## 9. Recommendations

1. **For state documents feeding session prep: `tgrep` or `zg --rg`.** No
   embeddings, no model, every line from source, rebuilds in seconds. Terse
   output is a feature for a downstream LLM: less interpretation to inherit.
2. **For natural-language lookup: `zg`**, wrapped by `/campaign-recall`
   (`skill/campaign-recall.SKILL.md`), which supplies filename ordering and an
   absence check — the two things vector search cannot do.
3. **For time: the event-ordinal KG** (§8), not dates. Dates are sparse and
   inconsistently formatted; ordinals are always present.
4. **Cognee for synthesis only**, never as a source of truth for anything a
   prep session consumes. If used, pair with `verify.py` and a human read.
5. **Rebuild indexes before use, and prove the instrument reads** with a
   positive control. Three separate tools this run reported success over work
   they had not done (§10).

---

## 10. Operational lessons — the silent-success pattern

Three tools reported success while having done less than claimed:

| Tool | What it said | What happened |
|---|---|---|
| cognee | `status='completed'` | ingested a file path as literal text |
| tgrep | `"complete": true` | 195 of 1,092 files not indexed |
| zg `--rg -l` | empty stdout | flag rejected on stderr; read as "not recorded" |

Plus: `zg --rg` prints `No matches.` to **stdout**, so `grep -c .` counts an
empty result as one hit.

**The defence is a positive control** — run the same check against a term known
to be present before trusting a negative. It caught the second stale tgrep
index before any content was built on it. It is now mandatory in
`/campaign-recall`.

---

## 11. Corrections made during this work

Recorded so the evidence can be read against them.

- "spark1's vLLM is wedged" — it was saturated at `--max-num-seqs 8`, not stuck.
- Run 1 was called a death spiral; it was grinding forward (844 extractions when
  killed).
- Lowering `request_timeout` to 600 s made things worse (§3.5).
- The Gundren fabrication was first attributed to model priors; the context
  dump showed it also came from ingested module text and unplayed session prep.
- The strict prompt was first blamed for Droop's false negative; the fact had
  never been retrieved (§5.3).
- `obelisk.md` was reported absent from the graph; hash-matching showed it was
  present.
- Hand-built `world_state.md` / `campaign_state.md` gave Gundren's last mention
  as Chapter 7; it is Chapter ~6 (directory `006`). Play-order position had been
  read as a chapter number. Fixed in `generated/`.
