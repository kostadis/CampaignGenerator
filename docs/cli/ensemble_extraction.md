# Ensemble Extraction — How-To

`ensemble` (and its two sub-tools `ensemble_extract` + `ensemble_merge`)
run a multi-lens fact-extraction pass over session text using a local LLM endpoint.
This doc covers the common usage patterns — single file, multiple files, and the
flags that matter most.

See [`ensemble_workflow.md`](ensemble_workflow.md) for the full
extract-once-locally pipeline (ensemble_batch → facts_to_state → synthesis) that
builds all four grounding docs from local compute.

---

## Quickstart — single file, built-in 5-lens plan

```bash
ensemble session-summary.md --workdir gen-ch01/
```

This runs 5 passes (small / large / sweep / temporal / interiority) against
`session-summary.md`, then merges them into `gen-ch01/merged.json`. All 5
passes default to `annotate_pov: true` — chunks that don't open with their
own `## Speaker — Scene` or `### Speaker` heading get a carry-forward
`[Continuing — Speaker: X, ...]` banner prepended, so a chunk boundary
landing mid-scene doesn't strand first-person prose with no named subject.
It's a no-op on documents with no matching headings. Override per pass via
`--plan` (see below) if you need it off.

With both Sparks:

```bash
EP="--endpoints http://192.168.1.147:8001/v1 http://192.168.1.69:8001/v1 \
    --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
ensemble session-summary.md --workdir gen-ch01/ $EP
```

---

## Extracting from multiple files — the `--plan` YAML

The positional argument is a single default document. To point different passes at
different files, write a plan YAML and pass it with `--plan`.

**Minimal example** — 5 lenses on the summary, interiority pass on the gm-assist doc:

```yaml
# plan.yaml
document: session-summary.md     # default for passes that don't set their own

passes:
  - name: small
  - name: large
  - name: sweep
  - name: temporal
  - name: interiority
    document: gm-assist.md       # overrides the top-level default for this pass
```

```bash
ensemble --plan plan.yaml --workdir gen-ch01/ $EP
```

Relative `document` paths resolve against the plan file's directory, so you can
keep the YAML next to the session files and use short paths.

**Per-pass documents with no default** — every pass names its own file, no
positional argument needed:

```yaml
passes:
  - name: summary-small
    document: /path/to/session-summary.md
  - name: summary-large
    document: /path/to/session-summary.md
  - name: gmassist-interiority
    document: /path/to/gm-assist.md
  - name: notes-sweep
    document: /path/to/dm-notes.md
```

Pass names key the output files under `--workdir` — they must be unique.

---

## Key flags

| Flag | Default | What it does |
|---|---|---|
| `--samples N` | 1 | Run each pass N times and union the results. Re-sampling recovers facts a single run misses (extraction is nondeterministic). `n_samples` per fact is recorded in `merged.json` as a confidence signal for human review — nothing is auto-filtered. |
| `--dry-run` | off | Print the resolved plan (which file each pass reads) without extracting. Use this to verify your YAML before committing to a long run. |
| `--skip NAME` | none | Skip a named pass (repeatable). Useful when iterating on a prompt fix for one lens. Works with both built-in and plan passes. |
| `--chunk-parallel N` | 4 | In-flight chunk requests per endpoint. 4 matches the Sparks' `--max-num-seqs 4`; use 1 for sequential behaviour. |
| `--speculative` / `--no-speculative` | on | When one endpoint stalls, a free endpoint re-runs its unit; whichever finishes first wins. Use `--no-speculative` for attended runs where you may grab a Spark mid-job. Needs 2+ endpoints. |
| `--unit-timeout SEC` | 600 | Kill and re-queue a unit that exceeds this wall-clock cap. A degraded endpoint that dribbles tokens toward max_tokens usually recovers on a fresh connection. 0 disables the cap. |

---

## Separation of concerns

`ensemble` is a convenience wrapper that calls `ensemble_extract` then
`ensemble_merge`. When you need to iterate on merge settings without re-running
extraction (expensive), call them separately:

```bash
# 1. Run extraction only
ensemble_extract --plan plan.yaml --workdir gen-ch01/ $EP

# 2. Merge separately, tweaking settings
ensemble_merge --workdir gen-ch01/ --method embed --embed-threshold 0.88
```

`--plan` controls extraction (passes + documents).  
`--merge-config` / `--method` flags control merging.  
These are intentionally separate YAMLs — merge settings do not belong in the plan.

---

## Scene boundaries — where `scene_index` comes from

`ensemble_merge` stamps every fact with a `scene_index`: the index of the
header-delimited chunk its quote fell into. That number becomes the `scene`
component of `event_spine`'s `(chapter, scene, seq)` key, so **the source
document's headings are the scene key**.

`campaignlib.textproc.chunk_by_scenes` decides the boundaries with a strict
priority:

1. any `##` heading — split on those;
2. `###` headings — consulted **only when the document has no `##` at all**;
3. neither — fall back to character-count chunking.

### The gotcha when the source is a `session-summary.md`

A summary's own layout is `## Summary` / `## Scenes` / `## NPCs` — all H2s. So
`chunk_by_scenes` splits on *those*, the `###` scene titles are never reached,
and every scene in the chapter collapses into one `scene_index`:

```bash
ensemble session-summary.md --workdir gen-ch01/      # <-- 3 chunks, not 9 scenes
```

Slicing to the `## Scenes` section alone does not help — `## Scenes` is itself
an H2. And stripping every `##` from the whole file is worse: the
`### <NPC name>` entries under `## NPCs` are H3 too and become boundaries, so a
9-scene chapter yields 18 "scenes", half of them NPC paragraphs.

**`ensemble_batch --source auto` handles this for you.** When the lineage ladder
resolves a chapter to the `summary` rung it calls
`campaignlib.lineage.compose_summary_scenes`, which slices the `## Scenes`
body, drops its one wrapper line, carries the `# H1` over for context, and
writes `lineage_summary_scenes.md` into the chapter workdir. Extraction reads
that; the summary on disk keeps its H2s so `_summary_is_structured` still admits
it to the rung. Convention flips to `h3` and each scene gets its own chunk. If
the summary has no usable scene list, it falls back to the summary unchanged.

**Invoking `ensemble` directly on a `session-summary.md` does not slice** — it
has no ladder. Either go through `ensemble_batch`, or point `--plan` at a
pre-sliced document if you need per-scene `scene_index` from a one-off run.

Chapter prose has its own version of this problem: chapters organised by
in-world date (`## 8/1 of Taraksh 1495`) with POV names beneath (`### Soma`)
yield a `scene` meaning "which day", and chapters with no `##` at all fall to
character-count chunking.

### When the summary is *derived from* the chapter — use `scene_map` instead

The rung above assumes the summary is **upstream** of the prose: transcript →
`enhance_summary` → summary → memoir narration. There, moving to the summary
gains fidelity.

A summary generated *from* chapter prose inverts that. It is downstream, and
it is small: on the Phandalin corpus the `## Scenes` body is **26% of the
chapter's word count** (14,100 words against 55,036). Routing extraction to it
would trade three quarters of the source text for the scene key.

`scene_map` takes neither side of that trade. It uses the summary's scenes
**only as a boundary map** — titles and positions — and writes a derived copy
of the *chapter* with `## <Scene Title>` injected at each anchor. Extraction
then reads the full prose and still gets a real per-scene `scene_index`.

```bash
scene_map propose --summaries-dir summaries/haiku
#   → docs/ensemble/scene_map.yaml   (every chapter approved: false)
#   review it, then set approved: true per chapter
scene_map apply --dest docs/chapters_scened
ensemble_batch --chapters 'docs/chapters_scened/chapter_*.md' --source chapter
```

Anchoring is deterministic — no model call. Each scene is placed at the
densest cluster of its own chapter-rare tokens, constrained to fall at or
after the previous scene, then snapped back to a paragraph break. Existing
`##` headings in the chapter are demoted to `###` in the derived copy, so the
injected scene headings are the only structural boundaries; the in-world dates
stay visible but stop competing.

**A boundary is a scope decision** — put it in the wrong paragraph and events
are misattributed to the neighbouring scene — so `propose` writes the prose
found at each anchor into the map and `apply` ignores any chapter not marked
approved. It also flags scenes whose span comes out under 400 characters,
which almost always means two anchors landed on top of each other. On
Phandalin chapters 2–30 that was 13 flags across 12 of 29 chapters; 147 of 148
scenes anchored, one left unanchored (an unanchored scene merges into its
predecessor rather than guessing).

---

## Output

After a successful run, `--workdir` contains:

- `<pass-name>.jsonl` — per-pass raw facts
- `manifest.json` — maps each pass to its source document and output file
- `merged.json` — deduplicated fact list with `n_samples` confidence counts

`merged.json` is the input to `facts_to_state` for per-entity dossier
aggregation, and to `event_spine update` for the durable event store. Human
review of dossiers is the checkpoint before any synthesis call.
