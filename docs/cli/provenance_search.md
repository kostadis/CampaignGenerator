# Provenance-Aware Cross-Campaign Search

**Command:** `provenance` · **Authored data:** `~/src/campaigns/provenance.yaml` + `<campaign>/docs/corrections.yaml`
**Spec:** `specs/007-cross-campaign-search/` · **Ratified:** 2026-08-06 (task T031)

Read this when you need to search across all six campaigns, when `provenance check`
reports something, or when you are about to hand-edit the manifest or a corrections
file.

---

## 1. What this is, in one paragraph

The six campaigns under `~/src/campaigns` contain hand-written GM canon, pipeline
output that gets clobbered on the next run, half-finished staging drafts, and
documents that are *known wrong* and have been for weeks. Ordinary grep returns all
of it as flat, undifferentiated text — and the failure that motivated this feature was
exactly that: a generated file was read as canon and a correct recap got flagged as a
continuity error. This capability searches that corpus and returns every hit wrapped
in a **provenance envelope**: which campaign owns it, how much to trust it, whether a
pipeline wrote it, which chapter it belongs to, and any recorded correction, attached
inline. It reads only. It never writes, never touches identity data, and makes no LLM
call anywhere.

**The core promise is not "better search." It is that a hit can never arrive without
its trust label.** Everything below exists to keep that true.

---

## 2. Status — what actually runs today

Phases 1–2 of the build are complete. Be honest with yourself about the rest.

| Surface | State |
|---|---|
| `provenance check` | ✅ **Works fully.** Validates the authored data, reports findings. |
| `provenance capabilities` | ⚠️ Partial — reports workspace root, resolution rule, campaign list. Backend roster lands at T074. |
| `provenance search` | ⛔ Refusals work (scope, unknown campaign, missing root, no horizon). Execution exits **70**. |
| `provenance resolve` | ⛔ Same — refusals work, execution exits **70**. |
| `provenance_mcp` | ⛔ Declared in `pyproject.toml`; module not written yet. |

Exit **70** is deliberate and is *not* exit 0. A stub that returned "no results" would
be indistinguishable from a real search that found nothing — the precise silent
failure this feature exists to kill.

---

## 3. The two files you maintain by hand

Nothing populates these by inference. Not a scan, not a heuristic, not this tool
(FR-029). That is the point: a tier is a scope decision, and scope decisions are
yours.

### `~/src/campaigns/provenance.yaml` — the manifest

The single enumeration of which campaigns exist. **A directory on disk that is absent
here is invisible to search**, and naming it is refused by name. There is no
discovery-by-scan, because discovery would have to invent a tier for whatever it
found.

The real Phandalin block, annotated:

```yaml
version: 1
campaigns:
  Phandalin:                      # the key IS the name — never write `name:` inside
    root: Phandalin               # relative to the workspace root; no `..`, no absolute
    tiers:                        # all four keys required; an empty list is legal and means something
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: ["docs/*_extractions/**/*.md"]
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "characters/*.md", "voice/*.md",
                           "docs/*.yaml", "docs/*.json", "config/*.yaml"]
      staging:            ["notes/**"]
    generated:                    # "will be clobbered, may be stale" — a warning, not a credit
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
      - {paths: ["docs/planning.md"],       by: planning}
      - {paths: ["docs/party.md"],          by: party}
      - {paths: ["docs/npcs/*.md"],         by: planning, note: "--build-dossiers"}
    horizon: {latest: 46, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: docs/entity_registry.yaml, aliases: docs/aliases.json}
    corrections: docs/corrections.yaml
    provenance_ranges: []
    # search_extensions and exclude are omitted here, so they default to
    #   [.md, .txt, .vtt, .yaml, .json]
    #   [".git/**", "**/__pycache__/**", "node_modules/**"]
```

`provenance_ranges` (FR-026) is optional and currently used only by
out-of-the-abyss, whose chapters 1–15 are hand-written and 16+ are AI-assisted:

```yaml
    provenance_ranges:
      - {from: 1,  to: 15,   authorship: gm-written,  note: "hand-written by the GM"}
      - {from: 16, to: null, authorship: ai-assisted, note: "not voice-reference material"}
```

Both halves are canon for plot. They are **not** interchangeable for voice-reference
work, which is the entire reason the label exists. Ranges may not overlap; an open end
is `to: null`, and only the last range may have one.

Loading is **all-or-nothing**. One bad campaign block fails the whole load (exit 3).
There is no skip-the-broken-entry, because a half-loaded manifest answers "which
campaigns exist" wrongly and every other guarantee sits on that answer.

Three authoring traps, each of which is a hard load error rather than a silent
surprise:

- **Duplicate YAML keys.** `yaml.safe_load` keeps the last one silently; a copy-pasted
  campaign block or tier list would shadow the real one and nobody would notice. The
  loader rejects duplicates outright.
- **Any unrecognised key, at any depth.** `authorative:` is a typo, not a new tier.
  Every model is `extra="forbid"`.
- **`horizon.latest` must be a bare integer.** `latest: "46"` is rejected. A string
  there means you were thinking of dates, and horizon is chapter-only.

### `<campaign>/docs/corrections.yaml` — known-stale records

One per campaign, **inside the campaign**, so a campaign stays self-describing if
moved or cloned alone — and so `~/src/campaigns/CLAUDE.md`'s "never bundle changes
from multiple campaigns" rule stays intact. A workspace-wide corrections file would be
a standing merge point that violates it on every edit.

```yaml
version: 1
campaign: Phandalin              # must equal the manifest key exactly
corrections:
  - id: woodland-manse-empty     # unique in this file; stable across edits
    applies_to:
      paths: ["docs/world_state.md"]        # required, non-empty; campaign-relative globs
      subjects: ["Woodland Manse", "Grannoc"]  # optional; empty ⇒ every hit under those paths
    stale_claim: >-              # what the file wrongly says. DISPLAY ONLY.
      "Active; Grannoc performing ritual; NOT visited."
    truth: >-
      The Woodland Manse has been empty since Chapter 43.
    as_of: chapter-43            # or a date, or null
    recorded: 2026-08-04
    recorded_by: GM
    verified: true               # false ⇒ the stale claim is NOT reproducible on disk
    note: >-                     # carries the evidence, especially when verified: false
      ...
```

A campaign with nothing to correct ships `corrections: []` — **present but empty**, so
it answers `consulted` rather than `no-record`. Those are different answers and you
will want the difference.

---

## 4. The matching rule — the load-bearing decision

A correction attaches to a hit when:

1. the hit's path matches a glob in `applies_to.paths`, **and**
2. `subjects` is empty, **or** a subject appears (case-insensitively) in the query or
   the excerpt.

**`stale_claim` is shown to you and never used for matching.**

This is empirical, not stylistic. The Woodland Manse entry above is the proof:
`docs/world_state.md:9` was regenerated and now reads *"having cleared the Woodland
Manse of a Talosian cult"* — the stale sentence is **gone**. A tool that attached the
correction by finding `stale_claim` in the file would have silently stopped applying
it the moment `distill` ran, with nothing anywhere to show that it had. The symmetric
hazard closes too: text-matching would let a correction silently *start* applying to a
paraphrase it was never written for.

A correction is pruned by a human. Not by a regeneration, not by a text match, not by
this tool.

### `verified: false` — an unreproducible correction is a question

When the stale claim cannot be found on disk, publishing it as fact would assert
something unverified. The entry ships `verified: false` with the evidence in `note`,
`provenance check` reports it every run so it cannot be quietly forgotten, and a hit
it annotates is labelled unsettled rather than presented as settled.

### The four consultation states (FR-005)

Every hit carries `corrections_status`. Two states cannot express four answers, and
collapsing any two of them tells you something false.

| `corrections_status` | `corrections` | Means |
|---|---|---|
| `consulted` | `[…]` | Record loaded; these apply to this hit |
| `consulted` | `[]` | Record loaded; none apply to this hit |
| `no-record` | `null` | Manifest declares `corrections: null` |
| `not-consulted` | `null` + `reason` | Declared but unreadable/unparseable |

A malformed *corrections* file degrades that one campaign to `not-consulted`; a
malformed *manifest* is fatal, because it decides what gets searched at all.

---

## 5. Trust tiers

| Tier | Ordinal | Means |
|---|---|---|
| `authoritative` | 0 | GM-written canon |
| `search_accelerator` | 1 | Indexes and registries — use to find, not to quote |
| `working_reference` | 2 | Useful, not canon |
| `staging` | 3 | In-flight, unfinished |
| `unclassified` | 4 | Matched no glob — **still returned** |

Two rules:

**Precedence is fixed and first-match-wins — but ambiguity is reported.** The
classifier keeps testing after it has an answer. Every *additional* tier whose globs
also matched is recorded on the hit as `tier_ambiguous` and surfaced by
`provenance check`. One deterministic answer, with the disagreement visible. Authoring
order in the file does not matter.

**No match is an answer, not a failure.** An unclassified file is labelled and
returned (FR-013). Dropping it would be the silent narrowing this whole feature
exists to prevent. `unclassified` is deliberately *not* authorable — nobody writes
"this is unclassified"; it is what the absence of a declaration looks like.

Globs use **rg / gitignore semantics**, matching the `-g` flags you already write:

| Pattern | Matches |
|---|---|
| `*` | any run of characters **within one path segment** |
| `?` | exactly one character, not `/` |
| `**/` | zero or more whole segments |
| `**` (trailing) | everything below this point |
| `[abc]`, `[!abc]` | character class, `!` or `^` negates |

`docs/*.md` does **not** match `docs/npcs/keeper.md`. That is the whole reason the
matcher is hand-rolled rather than `fnmatch` — `fnmatch`'s `*` crosses `/` and would
mis-tier every dossier in the corpus.

---

## 6. Using the CLI

```bash
provenance check                                   # validate authored data (works today)
provenance check --campaign toee --json
provenance capabilities                            # where am I reading from?
provenance search "Woodland Manse" --campaign Phandalin --campaign toee
provenance resolve "Vera" --campaign obelisk
```

### Scope is always explicit

`--campaign` is repeatable and **has no default**. There is no `--all`, no `*`, no
magic token. Omitting it is a **refusal (exit 1)** whose message enumerates the
campaigns — deliberately not an argparse error (exit 2), which would teach you a usage
string and nothing about which campaigns exist.

`check` is the single exception: with no `--campaign` it checks every campaign, which
is safe because it reads and reports rather than answering a question.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Refusal — a deliberate, explained "no" (also: `check` found error-level findings) |
| 2 | Usage error from argparse |
| 3 | Load error — manifest or corrections file invalid |
| 70 | Not implemented yet. **Never 0.** |

### Which corpus am I reading?

`--campaigns-root` → `$CAMPAIGNS_ROOT` → `campaignlib.constants.CAMPAIGNS_ROOT`.

`capabilities` always reports **which rule won**, not just the path. The same command
reads a different corpus depending on an environment variable you may not remember
setting; "state is discoverable" means the tool says so rather than leaving you to
infer it from surprising results.

---

## 7. What a hit will carry

Every field is **always present**. A field with nothing to say carries `null` plus its
status field — never omission. That invariant is the feature's core guarantee and is
asserted structurally, on the key set, not by spot-checking fields.

`campaign` · `path` · `line` · `excerpt` · `excerpt_encoding` · `context_before` /
`context_after` · `tier` · `tier_ambiguous` · `generated_by` ·
`generated_but_hand_edited` · `chapter` · `provenance_range` · `corrections` ·
`corrections_status` · `matched_surface_form` · `relevance` · `horizon_disposition`

Two worth knowing:

- **`generated_by`** non-null means *"will be clobbered on regeneration, may be
  stale."* That is the entire contract — a warning, not a credit line.
- **`generated_but_hand_edited`** is the toee `calmer.md` case: a file the manifest
  declares generated, which also carries a hand-written banner. Hand edits do **not**
  re-tier it. It stays labelled generated *and* raises this flag.

---

## 8. Routine maintenance

The loop is: **run `check`, read the findings, decide, edit by hand.** Nothing in that
sentence is automatable, and the tool never edits your data.

```bash
provenance check --campaigns-root ~/src/campaigns
```

Exit 1 means at least one error-level finding. Exit 0 with informational findings is
normal and expected — the current baseline is **15 findings, 0 error-level**.

| Kind | Level | What to do |
|---|---|---|
| `campaign-root-missing` | ERROR | The manifest names a directory that isn't there. Fix the path or remove the campaign. |
| `identity-store-missing` | ERROR | `identity:` points at a file that doesn't exist. |
| `corrections-unreadable` | ERROR | Declared corrections file won't parse. That campaign is answering `not-consulted`. |
| `stale-correction-entry` | ERROR | A correction's paths match **no file on disk**. Prune it or fix the glob. Never auto-removed. |
| `unreadable-directory` | ERROR | Permissions or a broken link inside the corpus. |
| `no-identity-store` | info | Campaign has no registry/aliases. `resolve` will be limited. |
| `unverified-correction` | info | A `verified: false` entry. Confirm, correct, or prune. |
| `tier-ambiguous` | info | Two tiers claim the same paths. First-match-wins is applying; tighten a glob if that isn't what you meant. |
| `unclassified-heavy` | info | A directory is mostly unclassified. Files are still searched and returned — labelled. Add a glob if you want them tiered. |
| `horizon-unattributable` | info | A file under the horizon directory that the pattern can't extract a chapter from. |

`unclassified-heavy` rolls up: it reports the shallowest heavy ancestor with a
per-child breakdown, so you get ~15 actionable lines instead of 227 near-identical
ones. A report nobody reads is not a review gate.

---

## 9. What was ratified at the T031 gate (2026-08-06)

Recorded so you don't re-litigate these, and so you know what you actually signed.

**Two horizon numbers were corrected against the spec's worked example**, both counted
from file counts that turned out to be wrong:

- **Hillsfar `15 → 16`** — 15 chapter files, but `chapter_08` doesn't exist; the newest
  is `chapter_16_`.
- **obelisk `4 → 3`** — 4 files in `docs/chapters/`, one of which is `mempalace.yaml`;
  the newest is `session_003_`.

A horizon one too low silently hides the most recent chapter from every horizon query.

**Deliberately left alone, all for the same reason:** narrowing scope is a GM decision,
and the error is asymmetric — an over-broad declaration produces noise you can prune,
an over-narrow one produces an absence you cannot see.

- `.mneme/**` is **not** excluded. Its files surface as `unclassified`.
- ~10 `docs/` subdirectories have **no invented globs** — chiefly `docs/ensemble/`
  (unclassified in five campaigns; 2659 files in out-of-the-abyss) and Phandalin's
  `docs/npcs/` sidecars, which `docs/npcs/*.md` doesn't reach.
- obelisk declares `docs/background/*.md` while four other campaigns with that same
  directory do not. Inherited inconsistency, left **visible** rather than harmonised by
  guesswork.

**One open question is shipped as open:** toee's `sequioa-zephyr-species-swap` carries
`verified: false`. Its evidence moved again between 2026-08-05 and ratification — every
PC now has a species, so there is no visible swap. It stays in the file, reported every
`check` run, until a human confirms or prunes it.

**Not this feature's job:** incident 5 (`"Vera"` → Veyra, `"KP"` must not reach
Kostadinious, `"Unla"`/`"Key"` are one halfling PC) is identity-store work.
`resolve("Vera", "obelisk")` returning `not-found-in-identity-store` is the design
working, not a bug. Entering those aliases is a `registry alias` /
`registry mark-distinct` act behind explicit human confirmation.

---

## 10. Hard rules

- **Never writes to campaign content**, under any circumstances (FR-031).
- **Never mutates identity data** — no registry writes, ever (FR-032).
- **Never makes an LLM call**, anywhere in the capability (FR-033). Enforced by an AST
  guard, `tests/test_provenance_no_llm.py`.
- **Never merges entities across campaigns** (FR-008). The campaign is a hard boundary.
- **Never infers authored data.** The manifest and corrections are hand-written or they
  don't exist (FR-029).
- **Never defaults scope to "all"** (Constitution X). Enforced three ways — an AST
  sweep for defaulted scope parameters, argparse introspection, and behavioural tests
  over magic tokens.
- **`.gitignore` gets no vote on scope.** The manifest's `exclude` list is the single
  authority (research D17).

---

## 11. Where the reasoning lives

| Document | Contents |
|---|---|
| `specs/007-cross-campaign-search/spec.md` | Requirements FR-001…FR-033, success criteria |
| `.../research.md` | D1–D18 — the codebase survey and every decision. **D8** tier ambiguity, **D12** why `stale_claim` is display-only, **D14** chapter from path not body, **D17** `.gitignore` has no vote |
| `.../data-model.md` | The envelope, and every model's field-by-field rationale |
| `.../contracts/manifest.md` · `corrections.md` · `cli.md` · `mcp.md` | Per-surface contracts |
| `.../tasks.md` | Build order. T031 was the ratification gate; Phase 3+ starts at T033 |

The module docstrings in `provenance/manifest.py`, `corrections.py`, and `tiers.py`
carry the same reasoning inline, next to the code it constrains. If you are about to
"simplify" one of those modules, read its docstring first — several of the apparent
redundancies are load-bearing and cost something to learn.
