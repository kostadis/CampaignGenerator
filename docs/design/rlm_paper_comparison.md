# Comparing CampaignGenerator + MemPalace to "Recursive Language Models"

> A note for Zhang, Kraska, and Khattab (and anyone who finds the RLM paper interesting and wants to see one concrete adaptation)

This document compares the system architecture of **CampaignGenerator + MemPalace** — an open-source D&D session-prep stack the author runs against a 2 TB local PDF library — to the model proposed in:

> Zhang, A.L., Kraska, T., Khattab, O. *Recursive Language Models*. arXiv:2512.24601v2.

The label "RLM" appears throughout our codebase and planning docs (e.g. branches `rlm-phase1` / `rlm-phase2`, `docs/rlm/rlm_architecture.md`, `docs/archive/rlm_integration_plan.md`) because the paper directly inspired the hierarchical-pruning insight that anchors our retrieval layer. The system is not, however, a re-implementation of an RLM. It adopts the *idea* and rejects the *mechanism*. This document explains where the line falls and why.

The intended audience is the paper's authors plus any practitioner who wants to see what it looked like to take RLM as inspiration in a domain (verbatim long-form retrieval over a typed schema with a human checkpoint) the paper does not directly target. It is not a critique. The paper's framing was load-bearing for our design.

---

## 1. Context — what the system does

CampaignGenerator orchestrates retrieval and prose generation for a Game Master prepping for tabletop sessions. The corpus is large, varied, and has hard precision requirements that distinguish it from the long-context QA tasks the RLM paper evaluates against.

| Pile | Shape | Size |
|---|---|---|
| **Canonical 5etools JSON** | typed schema (`monster`, `spell`, `item`, `class`, `data`/adventure entries, ...) | ~106 MB on disk; ~26,921 entities; ~99 adventures |
| **Unconverted RPG PDFs** | indexed catalog (`rpg-library`) | ~14 K PDFs, ~2 TB on filesystem |
| **Per-campaign content** | session summaries, NPC dossiers, distillations | small, ~10 MB per running campaign |

Retrieval is the bottleneck. A query like *"tell me about Velkynvelve"* could plausibly be answered by hits in any pile (or all three). The GM's downstream use of those hits has hard precision requirements — they must be **verbatim**, **attributable to a source page**, and surgical enough that the GM can paste them into a session document without re-checking the book. Failure modes look like: a paraphrased monster statblock with the wrong armor class; a summarized scene that reorders chronology; an NPC dossier that conflates two characters with similar names. These are exactly the failure modes the field calls "hallucination" but in our domain they ruin the session.

The architectural challenge: how do you reach across these three piles, get verbatim hits at sub-second latency, and keep the GM as the human in the loop deciding which sources are authoritative for the question they just asked?

The paper's framing of *"context rot"* and the necessity of inference-time decomposition is what made us treat this as a recursion-and-pruning problem rather than a search-and-summarize problem. Without the paper's argument that decomposition is fundamental to long-context processing, we would have built something less ambitious.

---

## 2. What we adopted from the paper

These are the load-bearing ideas we took directly. We cite the paper's wording where the design pressure was strongest.

### 2.1 Hierarchical decomposition as the answer to bounded context

The paper frames the problem as: *"frontier LLMs experience performance degradation (context rot) as input length increases"* and proposes RLMs as a way to *"scale the context size of general-purpose LLMs by orders of magnitude."*

We took the *inevitability* of decomposition as a starting axiom. The corpus we serve is multiple orders of magnitude beyond any usable context window, and naive flat retrieval over a corpus that large degrades ranking quality. Hierarchical pruning was the only path forward; we did not litigate that choice.

### 2.2 Symbolic vs. textual handle to the corpus

The paper's first key principle: *"a symbolic handle to the user prompt P, so the model can manipulate it without copying text into the root context window."*

We translate this into our design as: **the retrieval layer never returns raw drawer text to the orchestration layer except at the leaves.** Wing-level and room-level indices are *projections* — symbolic compressions of the underlying drawers — that the retriever can score against without ever materializing drawer prose into a higher layer. The Python idiom is different (we don't run a REPL with a `P` variable), but the architectural property is the same: scoping decisions happen against a symbolic representation, not against pasted text.

### 2.3 Pruning at intermediate levels

The paper describes RLMs as doing *"chunking strategies: RLMs learn to decompose context through regex filtering, keyword searches, or uniform chunking"* and *"selective processing: the LM's ability to filter input context without explicitly seeing it."*

Our retriever's hierarchical descent (wing → room → drawer) is the same shape: each level prunes the candidate pool before the next level pays the cost of scoring. By the time drawer-level vector search runs, the candidate pool has already been narrowed by two metadata-filtered queries. Drawers in unselected wings/rooms are never scored. This is exactly the *"the LM's ability to filter input context without explicitly seeing it"* property, applied to a corpus larger than any prompt.

### 2.4 The "only sub-calls when needed" insight

The paper's ablation finding: *"On information-dense tasks like OOLONG or OOLONG-Pairs, we observed several cases where recursive LM sub-calling is necessary"* but *"RLM performance is slightly worse on smaller input lengths,"* with a break-even point.

We took this seriously. Our retriever's hierarchical descent is parameterized by `max_depth ∈ {0, 1, 2}`, which the integration plan calls out for L1/L2 wake-up integration (Phase 4) precisely because *not every query needs a full descent*. A wake-up that asks "does this palace have anything about the current campaign?" should pay only the wing-index cost. A real session-prep query pays the full descent. The break-even insight from the paper is what made us bother with the depth knob.

---

## 3. Where we diverged — and why

Three places where we took a sharply different path. Each is a deliberate trade: we give up something the paper's design has, in exchange for something our domain requires.

### 3.1 No LLM in the index path. Ever.

**The paper's mechanism:** *"the LLM generates code that can peek into, decompose, and invoke itself recursively over programmatic snippets"* of the input. The LLM is the architect of every decomposition; intermediate processing is *"sub-LLM calls"* through *"code executing in the REPL."*

**Our mechanism:** intermediate-level indices are **deterministic rank-bucketed AAAK projections** of leaf closets (themselves a deterministic compression of drawers). No LLM call happens during indexing; no LLM call happens during pruning. The wing index is a frequency-sorted, top-N union of room indices. The room index is the same operation over leaf closets. The descent runs through a Python function; the LLM is invoked exactly once per query, at the rendering step that consumes the retrieved drawers.

**Why we diverged.** Our domain has a hard recall guarantee — the design rule in MemPalace's `CLAUDE.md` is *"100% recall is the design requirement — the target every search path is measured against. Anything less means forgetting."* If an LLM summarizes a wing's contents, two failure modes appear:

1. **Drift.** The same wing scored against the same query at two different times produces different rankings, because the LLM's output varies. A user who saw their NPC dossier yesterday may not see it today.
2. **Recall loss at the prune step.** If the wing-index summary drops a token that drawers under the wing actually carry, the wing gets pruned at step 1 and the relevant drawer is unreachable at step 3. Pruning was supposed to be a cheap accelerator over an exhaustive baseline; with LLM intermediate compression it becomes a precision-losing step you can't audit.

The deterministic projection is auditable. The wing index for query `q` is a pure function of the leaf closets under that wing, and the leaf closets are a pure function of the drawer text. If a wing prune removes the right answer, we can trace which leaf token caused it. We have a CI gate (`tests/benchmarks/test_hierarchical_aaak_gate1.py`) that asserts recall@10 = 1.0 on a 281-entry benchmark fixture against a flat-search baseline. As of the Phase 1 merge, the hierarchical path is **19.82× cheaper than flat search at 0% recall@10 loss**.

We could not have made that claim — and would not have built the system — if intermediate compression were LLM-driven.

We acknowledge this is a domain choice. For the long-context QA benchmarks the paper targets (BrowseComp-Plus, OOLONG-Pairs), an LLM that can re-read the prompt under different decompositions per call is the right shape. For verbatim retrieval over a typed schema with a recall floor, deterministic compression is.

### 3.2 The human is in the loop between retrieve and render

**The paper's pattern:** the LLM is the architect, the executor, and the renderer. RLM execution co-locates *"the LM's ability to filter input context"* with the LM's ability to produce the final answer, all inside one REPL session.

**Our pattern:** retrieve and render are **two separately invoked stages with a mandatory human checkpoint between them.** The retriever produces a structured candidate list (drawers + statblocks + cost-tagged candidates). A separate command (`dossier_proposer`) writes those into a markdown proposal file with a status banner reading "candidates only." The human GM reviews the file, deletes irrelevant candidates, reorders, and changes the banner to "approved by `<name>` on `<date>`." Only then will the render scripts (`prep.py`, `session_doc.py`, `planning.py`) accept it as grounding for an LLM call. Without an approved banner, those scripts refuse to run and exit non-zero before any token is sent to Claude.

This is enforced by a CI invariant — `tests/test_retrieve_render_isolation.py` walks every Python file in the repo and fails if a function body contains both a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`, ...) and a render call (`stream_api`, `call_api`, ...). The check passes for 48 cases at the time of writing.

**Why we diverged.** This is a domain trade. In our setting:

- Scope decisions ("which sources are authoritative for *this* question?") are precision decisions. The GM lives with the choice for ten weekly sessions; an LLM's autonomous scope choice that's wrong introduces a contradiction the GM has to retcon.
- The render stage produces text that the GM will read aloud at the table. Cost asymmetry: a wrong drawer fetched is cheap (one re-query); a wrong drawer rendered into prose and then read aloud is a session-derailing error.
- Retrieval errors at session-prep time happen at GM-speed (minutes, the GM is at a keyboard); render errors at session-time happen at improvisation-speed (seconds, the GM is mid-encounter). The asymmetric tolerance means we want the human in the loop *before* the render stage commits to anything.

We borrow the global LLM-pipeline rule from `~/.claude/CLAUDE.md` (the author's personal practice): *"LLM extracts → human imposes structure → LLM renders inside structure."* The paper's RLM is closer to *"LLM extracts → LLM structures → LLM renders,"* which the rule explicitly rejects. Both shapes are defensible; they answer different questions about who is responsible when the output is wrong.

### 3.3 Verbatim, persistent storage as the substrate

**The paper's substrate:** the prompt is a Python REPL variable, in memory, scoped to the lifetime of the call. *"the prompt is stored as a variable in a Python REPL environment with metadata exposed."* RLM execution is stateless across calls — each invocation rebuilds the symbolic decomposition from scratch.

**Our substrate:** drawers live in a per-palace ChromaDB collection that persists across sessions, weeks, campaigns. Wing and room indices live in sibling collections that the indexer rebuilds incrementally via a dirty-flag mechanism. A drawer written in 2026-04 is still retrievable in 2026-05 with the same `drawer_id`. The indices stay fresh because every drawer write marks its parent room dirty, and `recursive_indexer.rebuild_dirty()` drains the queue at the next call.

**Why we diverged.** Our corpus and our user are both stateful. The GM has been running this campaign for 26 sessions; an NPC introduced in session 4 is referenced in session 26. Asking the user to paste the cumulative campaign state into every prompt is the very thing the paper rejects (context rot); but rebuilding the symbolic decomposition from scratch on each query also fails — the corpus is too big, and the cost of scanning it is too high. Persistent verbatim storage with incremental hierarchical indexing is the shape that makes session-to-session retrieval cheap.

This is the cleanest example of where our domain extends past the paper's framing. The paper's RLM treats *the prompt* as the corpus; we treat *the persistent palace* as the corpus, and the prompt is just the per-query lens.

---

## 4. Where we extend

These are properties our system has that we did not see in the paper. They aren't claims of novelty (some are well-known elsewhere); they're places where adapting RLM to our domain forced design we had to make ourselves.

### 4.1 Multi-source merge with cost-tagged candidates

The paper's RLM operates over a single corpus (the prompt). Our retriever consults **three awareness sources** on every query:

- the per-campaign palace (already-ingested verbatim content),
- a `fivetools_catalog` mtime-cached name index over the canonical 5etools tree,
- the rpg-library HTTP API over the unconverted-PDF catalog.

Hits are merged into one ranked tiered list with a `kind / cost` discriminator (`drawer | statblock | candidate(cost: cheap | expensive)`). Cheap candidates carry a one-line `fivetools_ingest` command; expensive candidates carry a `pdf_to_5etools_v2 convert` + `fivetools_ingest` command pair plus a `(book_id, relative_path, product_id)` identifier triple for re-index resilience.

The cost tag surfaces a decision the paper's design doesn't have to make: **what should I do about hits in the corpus that aren't ingested yet?** Paying ML inference cost (Marker + Claude pass) for a third-party PDF is meaningful; ingesting from canonical JSON is millisecond-scale. The retriever doesn't decide; it surfaces both as candidates with their costs explicit, and the GM picks. This is the "RLMs learn to decompose context" insight extended past decomposition into a *should we materialize this part of the corpus at all?* question.

### 4.2 Schema-aware indexing as a bridge between the two paradigms

The paper's RLM works over arbitrary text. Our retrieval is bridged by **5etools — a typed JSON schema** that already structures the corpus into ~30 typed entity wrappers with a polymorphic `entries` block for prose. We dispatch ingest on the wrapper key (`monster` / `spell` / `item` / `class` / `data`), apply a Python port of 5etools's `_copy` resolver for entity inheritance, render typed statblocks, and route entities into typed wings (`wing_bestiary` / `wing_spells` / `wing_items` / etc.).

This is what makes our deterministic intermediate compression work. AAAK projections are token frequency operations; the rank-bucketing assumes the leaf content has *meaningful tokens*. Untyped prose (the paper's setting) has tokens, but they're unlabeled. Typed schema content has the ability to carry per-entity facets (CR, level, school, rarity, edition) into Chroma metadata, which means our `where`-clause filters during the hierarchical descent are not just over wing/room IDs but over filterable entity attributes. A query for "fey forest encounter mid-level" can prune wings *and* facet-filter to `creature_type=fey, environment=forest, CR ∈ [5,10]` before any vector search runs.

The trade-off: we depend on the schema. Content that doesn't fit 5etools (a third-party PDF, a homebrew adventure not yet converted) is invisible to the retriever until it's converted. The paper's RLM has no equivalent dependency.

### 4.3 Ingest as a GM-driven on-demand step

We **explicitly reject bulk ingest.** The integration plan and the architecture doc both have a §16 "What we explicitly chose not to do" enumerating this. The reasons:

- Total system corpus (5etools + 14K PDFs + per-campaign content) is too large to index whole.
- Cold content pollutes retrieval — irrelevant drawers crowd the candidate pool.
- The GM-as-checkpoint discipline keeps the system honest. If you didn't ingest it, you can't accidentally render off it.

The paper's RLM has no analog because the prompt *is* the corpus — there is no "ingestion" step distinct from invocation. In our system, every drawer is in the palace because the GM decided it was relevant to the current campaign and approved a cheap-path or expensive-path ingest command. This is the same human-checkpoint discipline as §3.2, applied to a different stage of the pipeline.

### 4.4 The retrieve/render isolation invariant as a CI test

To our knowledge the paper does not propose enforcing the LLM-extract-vs-LLM-render separation as a static-analysis CI check. We do, via `tests/test_retrieve_render_isolation.py`. The test parses every `.py` file in the repo into an AST and fails the build if any function body contains both a retrieval call and a render call. There are 48 modules covered; the test passes at the time of merge.

This is a small thing but it's the shape of a discipline the paper invites and that we found we needed to encode mechanically. We mention it in case other RLM-inspired systems hit the same temptation to co-locate the two and benefit from a similar guard.

---

## 5. Limitations the paper named that we don't incur

The paper closes with a frank limitations section. Several of those limitations don't apply to our system because of the divergences in §3:

| Paper's limitation | How our system relates |
|---|---|
| *"synchronous sub-calls inside of a Python REPL environment"* | We have no sub-calls. One MCP call per query, fanned out in-process via three deterministic awareness queries. Async-ifying the awareness queries is a one-line change if we need it. |
| *"max recursion depth of one (i.e. sub-calls are LMs); deeper recursion is unexplored"* | Our hierarchical descent has a fixed three-level structure (wing/room/drawer) determined by the corpus structure, not by LLM behavior. Depth is parameterized at the query, not at training time. |
| *"large differences in iteration length depending on task complexity, with sharp increases at the tail end"* | Our per-query cost is bounded and predictable: one wing-index Chroma query, one room-index Chroma query (with a `where` filter), one scoped drawer search, one rpg-library HTTP call, one in-process catalog scan, one merge step. There is no tail; cost variance comes from the size of the candidate pool, not from LLM behavior. |
| *"the distinction between final answers and intermediate thoughts is brittle for RLMs, requiring templated tags (FINAL(), FINAL_VAR())"* | Our retrieval returns a structured response shape `{kind, cost, ...}` parsed by deterministic code. There is no "is this a final answer or intermediate thought?" question because the layer that does retrieval doesn't render. |
| *"Training underexplored — fine-tuning is a very small scale exercise"* | We do no fine-tuning. Everything in the index path and pruning logic is rule-based. |

We don't take this as a refutation of the paper's design — the paper's setting requires the things that produce these limitations. We list them only to make explicit what we gave up in exchange.

---

## 6. Limitations we incur that the paper doesn't

For symmetry, here are limitations our domain choices introduce that the paper's RLM does not have:

- **Schema dependency.** Content has to fit 5etools (or get converted into it) before it's reachable. Third-party homebrew that doesn't match the schema is opaque. The paper's RLM works over arbitrary text.
- **Ingest discipline as a UX cost.** Every drawer is in the palace because the GM said so. This is good for precision and bad for "I just want to ask a question and get an answer." We mitigate with the cost-tagged candidate flow but the friction is real.
- **No ad-hoc decomposition.** If the GM asks something the wing taxonomy doesn't cover well, the system can't reorganize on the fly. The paper's RLM lets the LLM choose decomposition per-query; we have a fixed decomposition baked in.
- **Persistent storage means persistent corruption.** A bad ingest sticks around until someone deletes it. RLMs are stateless across calls and don't have this risk. We mitigate with a `--replace` flag (currently a no-op pending a MemPalace MCP delete-by-metadata tool — it's the one operational gap we've documented).
- **Per-query latency lower-bounded by the slowest awareness source.** rpg-library HTTP takes ~10–50 ms; Chroma queries take ~5–20 ms; the in-process catalog is sub-millisecond. The merge waits on the slowest.

---

## 7. Open questions where the paper's framing might extend us further

We have not implemented these but the paper's discussion suggests they are worth investigating:

- **Asynchronous awareness queries.** The paper's "asynchronous sub-calls" discussion is the right shape for our merge step. Today the three awareness sources are queried sequentially; nothing forces that.
- **Adaptive `max_depth`.** Today we hardcode `max_depth=2`. The paper's break-even insight (RLMs underperform on small inputs) suggests we should sometimes pick `max_depth=0` based on a fast estimator of "is this query likely to have a hit?" The wake-up integration (Phase 4) is the place this would land.
- **An RLM-style ad-hoc decomposition for the "I don't know what wing this fits" case.** When `fivetools_catalog` and the campaign palace both come back empty, today we just emit an expensive candidate. An RLM-shaped sub-call that re-decomposes the query against the rpg-library NLQ endpoint might find a better match. We have not built this; it's the closest thing in our backlog to a true sub-LLM-call.
- **Training a small model on the deterministic descent's trajectories.** The paper post-trains RLM-Qwen3-8B with a 28.3% improvement over base. The analog for us would be training a small model on `retrieve()` traces to predict which `max_depth` and which awareness sources to consult per query. This would be small-scale; it's not on the roadmap.

---

## 8. References

**Paper:**
- Zhang, A.L., Kraska, T., Khattab, O. *Recursive Language Models*. arXiv:2512.24601v2.

**Codebases (all under github.com/kostadis):**
- `kostadis/CampaignGenerator` `main` @ `1f13f44` (PR #18 merged 2026-05-02) — orchestration, retrieval, render pipeline.
- `kostadis/mempalace` `kostadis-dev` @ `a0d6a4d` (PR #5 merged 2026-05-02) — verbatim memory palace with hierarchical retrieval.

**Internal architecture references:**
- `CampaignGenerator/docs/rlm/rlm_architecture.md` — three-pile model + chosen-not-to-do log.
- `CampaignGenerator/docs/archive/rlm_integration_plan.md` — the original plan that names the paper as inspiration.
- `CampaignGenerator/docs/rlm/retrieval_architecture.md` — implementation reference for the retrieve path described in §3.1.
- `CampaignGenerator/docs/archive/fivetools_ingest_audit.md` — schema-aware ingest audit.

**Benchmarks:**
- `mempalace/tests/benchmarks/test_hierarchical_aaak_gate1.py` — Gate 1 (recall@10 = 1.0 at 19.82× cost reduction vs flat).
- `CampaignGenerator/tests/benchmarks/test_rlm_benchmark_rpg_gate2.py` — Gate 2 (top-3 ≥ 90% on 15 RPG queries).

---

If any of the framing here misreads the paper, please point at the offending paragraph — I'd rather correct than mislead. And if the "deterministic compression at intermediate levels" trade-off is something you've seen explored elsewhere in the long-context literature, I'd be glad to read it; it felt like the most interesting design decision and the one I'm least sure I got right.

— Kostadis Roussos (kostadis@gmail.com)
