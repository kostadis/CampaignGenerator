# Alias Pipeline Integration — Plan

Supersedes `feat/alias-propagation`. That branch lifted alias machinery into
`campaignlib` and retrofitted every extractor, but 5 of its 7 commits no
longer apply: the downstream scripts (`distill`, `campaign_state`, `party`,
`vtt_summary`) were migrated to the shared `run_extract_pipeline` /
`run_synthesize_pipeline` pattern after that branch was written, and
`planning.py`'s `parse_dossier` now returns a 4-tuple with `source_extracts`.

## Goal

Propagate the human-curated NPC alias map (YAML frontmatter in
`docs/npcs/*.md`) from `planning.py` into every other extractor in the
pipeline, so canonical docs stop fragmenting NPCs the human has already
merged.

Guiding invariant (per global CLAUDE.md): **LLMs render, humans decide.**
The alias map is the human-verified structure. The normalize step is a
pure regex — no LLM makes a scope/attribution decision about which variant
maps to which canonical.

## Design (cleaner than the feat branch)

Because every extractor now calls `run_extract_pipeline` /
`run_synthesize_pipeline`, we add two optional kwargs to both pipelines:

- `input_normalizer: Callable[[str], str] | None` — applied to `text`
  before chunking (extract) or to each file's contents before assembly
  (synthesize).
- `system_suffix: str` — appended to the system prompt so the LLM sees
  the "Known NPCs" roster alongside its extract/synth instructions.

Each retrofit script becomes a 4-line top-of-`main()` block:

```python
alias_map = load_alias_map(Path(args.dossier_dir).expanduser().resolve())
normalize, _ = build_alias_normalizer(alias_map)
roster = format_npc_roster(alias_map)
# pass normalize + roster into run_extract_pipeline / run_synthesize_pipeline
```

`load_alias_map` returns `{}` when the dir is missing or empty, which
makes `normalize` an identity function and `roster` the empty string —
no-op for campaigns without a planning workflow.

## Steps

1. Lift `parse_dossier`, `build_alias_normalizer`, `load_alias_map`,
   `format_npc_roster` into `campaignlib`. Reconcile `parse_dossier`
   with main's 4-tuple shape (keep `source_extracts` in the signature).
   `planning.py` imports from campaignlib; `write_dossier` stays local.
2. Add `input_normalizer` + `system_suffix` kwargs to
   `run_extract_pipeline` and `run_synthesize_pipeline`.
3. Retrofit one script at a time (`distill`, `campaign_state`, `party`,
   `vtt_summary`). `party.py` covers both the legacy flat-flag path and
   the `--party-config` path.
4. Retrofit `session_doc.py` Pass 4 — alias load hoisted above the
   per-scene loop; normalizer applied once to shared inputs.
5. Verify `planning.py --build-dossiers` still self-seeds the extract
   prompt with the existing roster.
6. Tests: new tests for the pipeline kwargs; unit tests for the
   campaignlib alias helpers; smoke tests per retrofit.
7. Docs: "Cross-pipeline alias propagation" subsection in CLAUDE.md
   under "Dossier merge workflow".

## Deliberately excluded

- `query.py` — user typing an alias expects hits on variants too
  (search-side expansion ≠ canonicalization).
- `prep.py` — reads pre-normalized grounding docs; nothing to
  canonicalize at its layer.

## Observation risks (same as feat branch's Step 5)

1. **Hallucination creep** — the roster prompt gives the LLM names it
   may not have seen in the current chunk. Spot-check extract files
   for backfilled facts that aren't in the raw text.
2. **Wrong resolutions** — `build_alias_normalizer` matches whole
   words, case-insensitive, longest-first. An alias assigned to two
   different canonical NPCs would collide. Unlikely with human-curated
   data, but worth verifying.
3. **Re-run friction** — cleaner extraction may surface more variants
   needing merging. That's the system catching what it used to drop
   silently — good problem, but track workload.

Fix path for each: tighten the roster prompt wording, don't roll back.
