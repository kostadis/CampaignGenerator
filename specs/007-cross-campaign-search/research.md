# Research: Cross-Campaign Provenance-Aware Search Seam

**Feature**: `007-cross-campaign-search` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

All measurements taken on host `Linux-Alien`, 2026-08-05, against the live workspace
`~/src/campaigns`. This file is the codebase-and-corpus survey behind
[plan.md](./plan.md); extend it rather than re-deriving it.

Decisions are numbered D1–D18 and referenced from plan.md, data-model.md and the
contracts.

> **Revised 2026-08-05 (same day), after the GM installed ripgrep.** D1 previously
> rejected ripgrep because `shutil.which("rg")` returned `None`. `rg` 15.1.0 is now at
> `/usr/bin/rg` and resolves from a spawned Python process. D1 is rewritten below;
> **D17 and D18 are new** and cover the correctness traps that adopting rg introduces.
> The original objection — *"an MCP server that silently degrades depending on how it was
> launched"* — was never an objection to rg's speed, and it is answered by reporting the
> scanner rather than by refusing to use it.

---

## D1 — Scanner: ripgrep primary, stdlib Python fallback, and the active scanner is always reported

**Decision**: The literal backend has two interchangeable implementations behind one
interface:

- **`rg` (primary)** — used whenever `shutil.which("rg")` resolves. Invoked with a pinned
  flag set (D17) and parsed from `--json` output (D18).
- **stdlib Python (fallback)** — `os.walk` + `read_bytes()` + a compiled `bytes` regex as a
  whole-file fast reject, decoding only surviving lines. Used when `rg` is absent.

**Which one ran is reported in every search response and by `capabilities`, with the rg
version string.** That is the entire content of the original objection, and it is now
satisfied directly: the caller can always see whether they got the 0.01 s path or the
0.63 s path, so per-machine variance is observable rather than invisible (Principle VIII,
FR-022).

**Rationale — measured, all on this host, 2026-08-05**:

| Scanner | Corpus | Files | Bytes | Elapsed |
|---|---|---|---|---|
| **`rg` 15.1.0, production flags** | **all 6 campaigns** | **11,914** | **131 MB** | **0.01 s** |
| **`rg` 15.1.0, production flags** | **out-of-the-abyss (largest)** | **4,255** | **58.2 MB** | **0.01 s** |
| Python, `bytes` + fast reject | all 6 campaigns | 11,914 | 131.3 MB | 1.49 s |
| Python, `bytes` + fast reject | out-of-the-abyss (largest) | 4,255 | 58.2 MB | 0.63 s |
| Python, `bytes` + fast reject | Phandalin | 1,488 | 12.6 MB | 0.17 s |
| Python, decode-to-`str` per file | all 6 campaigns | 11,914 | 130.6 MB | 2.45 s |

rg is **~60× faster** on the largest single campaign and ~150× on the full corpus, and it
collapses the difference between "one campaign" and "all six" to nothing. SC-007's 2 s
budget stops being a constraint the design has to respect and becomes a number with three
orders of magnitude of headroom — which is what makes Story 5's cross-campaign search
(P5) cheap rather than the slowest operation in the feature.

**Why the Python fallback is kept rather than deleted**, three reasons, all load-bearing:

1. **It is the differential-test oracle.** Two scanners that disagree produce results that
   differ by machine, which would break SC-009 far more seriously than a slow scan ever
   could. `test_provenance_scanner_parity.py` asserts both return an identical
   `(path, line, excerpt)` set over the fixture workspace and over one live campaign. That
   test is only possible because both exist.
2. **rg is not guaranteed present.** It was absent from this very host's `PATH` earlier
   today. CI, a fresh clone, a container, and the WSL2 desktop are all unverified. A
   feature whose core operation hard-fails on a missing optional binary is worse than one
   that runs 60× slower and says so.
3. **It costs ~80 lines.** The measured fallback already meets SC-007 unaided.

**Alternatives rejected**:

- **rg as a hard requirement (no fallback).** Rejected for reason 2 above, and because it
  would make the parity test impossible — losing the only mechanical check that the two
  code paths agree.
- **GNU `grep`.** 0.088 s, so nearly as fast, but its output is ambiguous to parse: a path
  or a matched line containing `:` breaks naive splitting, and it has no structured output
  mode. rg's `--json` (D18) eliminates that class of bug.
- **An index (SQLite FTS / embeddings).** Out of Scope in the spec, and now even less
  justifiable: the uncached full-corpus scan is 0.01 s. Every index is a recurring tax
  against disk truth (Constitution I, "Architecture is Destiny").

**Consequence unchanged**: SC-009 ("delete every derived artifact and rebuild → identical
results") is satisfied because the feature derives no artifact at all. The only files it
produces are the two hand-authored ones (FR-027, FR-028), which are inputs. rg is a
process, not a cache.

---

## D2 — Corpus shape: per-campaign layouts genuinely differ, so tier globs must be per-campaign

**Finding**: The six campaigns do not share a directory layout.

| Campaign | Top-level dirs | Searchable files | Size |
|---|---|---|---|
| Phandalin | `characters/ config/ docs/ lib/ notes/ summaries/ voice/` | 1,488 | 12.6 MB |
| out-of-the-abyss | `config/ docs/ examples/ lib/ logs/ notes/ summaries/ voice/` | 4,255 | 58.2 MB |
| stormgiants | `Storm King Thunder/ distill_extractions/ docs/ examples/ notes/ party_extractions/ planning_extractions/ summaries/ voice/` | 3,111 | 15.3 MB |
| toee | `archive/ docs/ examples/ notes/ planning_extractions/ summaries/ temple/ voice/` | 2,346 | 27.8 MB |
| Hillsfar | `docs/ logs/ notes/ summaries/` | 485 | 12.0 MB |
| obelisk | `characters/ config/ docs/ notes/ summaries/` | 201 | 4.1 MB |

Critically, the **search-accelerator tier lives in two different places**:
`stormgiants/distill_extractions/` and `toee/planning_extractions/` sit at the campaign
root, while `Phandalin/docs/distill_extractions/` and `out-of-the-abyss/docs/planning_extractions/`
sit under `docs/`. Several campaigns have **both** (`toee/planning_extractions/` *and*
`toee/docs/planning_extractions/`).

Chapter naming also diverges: five campaigns use `docs/chapters/chapter_NN_<slug>.md`;
**obelisk uses `docs/chapters/session_NNN_<slug>.md`** and has only 4 files there.

**Decision**: One glob set per campaign in the manifest — no shared template, no
inherited defaults. A single workspace-wide glob list would silently mis-tier
`stormgiants/distill_extractions/` (accelerator read as unclassified) or mis-tier
`toee/archive/`. FR-027 already demands per-campaign declaration; this is the evidence
for why.

**Corpus counts** (for fixture sizing): 243 chapter files, 72 VTTs, 1,079 NPC dossiers,
175 notes files, 9,273 markdown files, 408 MB on disk.

---

## D3 — The workspace is ONE git repo, not six. The spec's stated rationale is wrong; its conclusion is right

**Finding**: `~/src/campaigns/.git` exists and is the **only** `.git` in the tree. There
are no per-campaign repositories.

The spec's Assumptions section says the manifest must be a single workspace-level file
"since it must describe campaigns that do not share a commit history." That premise is
false — they do share one.

**Decision**: Keep both spec conclusions unchanged; correct the rationale.

- The **manifest stays workspace-level** (`~/src/campaigns/provenance.yaml`), because it
  is the one file that must describe *all six campaigns at once* — a per-campaign
  fragment could not answer "which campaigns exist" (FR-023) without a scan that guesses.
- The **corrections records stay per-campaign** (`<campaign>/docs/corrections.yaml`),
  and the shared repo makes this *more* important, not less: `~/src/campaigns/CLAUDE.md`
  imposes a hard rule — *"Never bundle changes from multiple campaigns into a single
  commit or PR"* — and a workspace-wide corrections file would be a standing merge point
  that violates it on every edit. The manifest is exempt under that same rule's
  carve-out for "root-level shared infrastructure."

---

## D4 — MCP registration: the workspace root already is the registration point

**Finding**: `~/src/campaigns/.mcp.json` exists and is the **only** `.mcp.json` in the
tree — no per-campaign files. It currently registers three servers, all three hard-pinned
to `out-of-the-abyss`:

```json
{"mcpServers": {
  "campaign":  {"command": "mcp_server",         "args": ["--campaign-dir", ".../out-of-the-abyss"]},
  "5etools":   {"command": "launch_5etools_mcp", "args": ["--campaign-dir", ".../out-of-the-abyss"]},
  "registry":  {"command": "registry_mcp",       "env":  {"CAMPAIGN_DIR": ".../out-of-the-abyss"}}
}}
```

This is the spec's "no cross-campaign front door" measured directly: searching Phandalin
requires editing this file and restarting the session.

`pipelines/workspace/configure_mcp.py` already writes this file at the **git repo root**
(`git_root()`), not per campaign, precisely because Claude Code only reads `.mcp.json`
there.

**Decision**: The new server registers as a fourth entry, `provenance`, with **no
campaign argument at all** — that absence is the feature. `configure_mcp` gains a gated
block (gated on the workspace manifest existing, mirroring how `registry` is gated on
`docs/entity_registry.yaml`). Because the block is workspace-scoped rather than
campaign-scoped, it is emitted once per repo root, not once per campaign.

---

## D5 — Workspace-root discovery: reuse the constant that already exists, and report it

**Finding**: `pipelines/workspace/configure_mcp.py:44` already hardcodes
`CAMPAIGNS_ROOT = Path("~/src/campaigns").expanduser()`. `campaignlib/wiring.py` exists
for external, mneme-rendered paths; `campaignlib/constants.py` holds shared internal
defaults with an env override (`DEFAULT_MODEL`, `CONFIG_DIR_NAME`).

**Decision**: Add `CAMPAIGNS_ROOT` to `campaignlib/constants.py` with the resolution
order `--campaigns-root` flag → `CAMPAIGNS_ROOT` env → `~/src/campaigns`, and
**refactor `configure_mcp.py` to import it** rather than keeping a second literal. The
resolved root *and which of the three rules produced it* are reported by `capabilities`
(Principle VIII — the spec explicitly says root discovery "must be discoverable, not
tribal").

**Alternative rejected**: `wiring.yaml`. `wiring.py` is for values mneme *renders*
(endpoints, DGX models, shared data roots). The campaigns workspace is not an external
service and mneme does not render its location; adding it there would put a
hand-managed value in a "do-not-edit, stamped with a source hash" file.

---

## D6 — Package placement: a new top-level `provenance/` package, mirroring `entity_registry/`

**Decision**: New top-level package `provenance/`, added to `ENGINE_PACKAGES` in
`tests/test_layering.py`.

**Rationale**: `entity_registry/` is the exact precedent — a capability that owns an
on-disk document, exposes a CLI (`registry`), and exposes an MCP server wrapping that
CLI (`registry_mcp`). This feature has the same three parts. Constitution V's "one seam
per boundary" is satisfied: `provenance/provenance_mcp.py` is the single file through
which this capability is exposed outward.

**Alternatives rejected**:

- `pipelines/provenance/`. The `pipelines/` tree is render/extract pipelines that spend
  tokens; this one makes no LLM call at all (FR-033). Filing it there invites a future
  reader to add one.
- Extending `pipelines/rlm/mcp_server.py`. Rejected in the spec already; the survey
  confirms why — that server resolves a fixed `campaign_dir` at *module import time*
  (`pipelines/rlm/mcp_server.py:29-46`), loads that campaign's `config.yaml`, and builds
  a doc index from it. Unpinning it is not an argument change, it is a rewrite of its
  import-time bootstrap.
- Putting the models in `campaignlib/`. The `projection_config.py` precedent applies
  when **both** a CLI engine and `server/` need the shape. Nothing in `server/` consumes
  this feature. If a UI is added later, the models move then — not speculatively.

---

## D7 — Manifest filename and format: `~/src/campaigns/provenance.yaml`, strict pydantic

**Decision**: `~/src/campaigns/provenance.yaml`, modelled with pydantic v2
`BaseModel` + `ConfigDict(extra="forbid")`, following `campaignlib/projection_config.py`.

Filename chosen to sit alongside the workspace-level `mempalace.yaml` and `config.yaml`
already at that root, and to name what it declares rather than who reads it.

**Environment confirmed**: Python 3.14.4, pydantic 2.13.4, `mcp` importable.
`pyproject.toml` declares `requires-python = ">=3.9"` and does not list `pydantic`
directly — it arrives via `fastapi`. Since this package uses pydantic without fastapi,
**add `pydantic` as an explicit dependency** rather than relying on a transitive one.

`extra="forbid"` is what makes FR-030 ("fail loudly on a malformed manifest") real: an
unrecognised key is a load error, not a silently ignored line.

---

## D8 — Tier precedence: fixed order, first match wins, ambiguity reported not resolved

**Problem**: Tier globs overlap in practice. `docs/*_extractions/**` (accelerator) and
any broad `docs/**` (working reference) both match the same file.

**Decision**: Tiers are matched in the fixed order **authoritative → search_accelerator
→ working_reference → staging**, first match wins. But the resolution is never silent:

- The envelope carries `tier_ambiguous: [<other tiers that also matched>]` when more
  than one glob set matches.
- `provenance check` reports every multi-tier path as a finding for the GM to fix.

**Rationale**: A pure first-match-wins rule *is* a scope decision made by the tool
(Constitution II). Surfacing the ambiguity keeps the decision with the GM while still
giving a deterministic answer at query time — the same shape as `registry check`, which
reports grouping drift for GM review rather than auto-merging.

Files matching no tier glob are labeled `unclassified` (FR-013) and are **still returned**
— dropping them would be a silent scope decision in the other direction.

---

## D9 — Ranking: deterministic, total-ordered, no LLM

**Decision**: Sort key, ascending, entirely from disk facts:

1. `-relevance` — match count in the file, plus a whole-word bonus, plus a bonus when
   the match falls in a markdown heading or the file's basename.
2. `tier_ordinal` — authoritative 0, search_accelerator 1, working_reference 2,
   staging 3, unclassified 4. This is FR-010's tiebreak.
3. `campaign`, then `path`, then `line` — the total-order tail.

**Rationale for the tail**: without it, ties resolve by filesystem walk order, which
varies between machines and after any `git checkout`. SC-009 demands identical results on
rebuild; a total order is what makes "identical" checkable. No LLM anywhere (FR-033), and
`tests/test_retrieve_render_isolation.py` passes vacuously because nothing in the package
imports `campaignlib.api`.

---

## D10 — Identity stores: 4 of 6 present, and the schema has no "known-wrong variant" field

**Finding**: Confirmed on disk — `docs/entity_registry.yaml` **and** `docs/aliases.json`
both present for Phandalin, out-of-the-abyss, toee, obelisk; **neither** for stormgiants
or Hillsfar. Matches the spec exactly.

`campaignlib/registry.py` already loads the registry and exposes the projections
(`alias_to_canonical()`, `known_names()`), including a documented first-token rule
(`"Kazryn"` → `"Kazryn Nyantani"`). **Reuse it as-is** — do not write a second parser.
`resolve_registry_arg` / `find_registry` are the existing resolution helpers.

**Schema gap, stated plainly**: FR-014 asks for "canonical entity, aliases, **and
known-wrong variants**." The `Registry` dataclass has `name, type, aliases, provenance,
source, scope, note` — there is **no known-wrong-variant field**. In practice, wrong
variants are stored *as ordinary aliases*: Phandalin records `"Adabra Adabra Gwynn"`,
`"king_gnercli"` and `"Gnercli"` in the same `aliases:` list as legitimate short forms.

**Decision**: Report aliases as aliases. Do **not** invent a heuristic that classifies
some aliases as "wrong" — that would be name-similarity reasoning, which FR-016 forbids
outright. The resolution response carries an explicit
`known_wrong_variants: {status: "not-recorded-by-schema"}` so the caller learns the
distinction is unavailable rather than reading an empty list as "there are none."

**Known confusions (FR-015)** map onto two *real* registry fields, kept distinct because
they mean different things:

- `distinct:` — ruled to be different entities. Live data: Phandalin
  `[Meril's Staff, Staff of Birdcalls]`; out-of-the-abyss `[Topsy, Turvy]`,
  `[Ellen, Elian]`, `[The Grygumite School, the Grygumite triangle]`; toee
  `[Barkinar, Deggum]`.
- `rejected_aliases:` — a proposed alias link that was considered and refused. Live data:
  Phandalin `[Corbin, Corwin]`, `[Elara, Elara Seasong Meliamne]`, `[Meril, Miral]`;
  out-of-the-abyss `[Shoor Vandree, Stool]`, `[Aliinka, Plinki]`, `[Elbeth, Eldeth Feldrun]`;
  toee `[Dren, Dren Halveth]`, `[Krell, Lieutenant Krell]`, `[Rannos, Ranos Davl]`.

obelisk's registry has **neither** section — so obelisk answers "no confusions recorded,"
consulted-and-empty, not "not consulted."

---

## D11 — Two of the spec's Story-2 fixtures are not in the corpus. This blocks a demo, not the feature

**Finding — verified by grep, both negative**:

- `grep -i "veyra\|vera" obelisk/docs/entity_registry.yaml` → **no entity match.** Veyra is
  real (`obelisk/characters/veyra.md` exists) but is **not registered**, so "Vera" cannot
  resolve to her. Spec Story 2, AS-1's *Given* is false today.
- `grep -ri "kazneporium\|kostadinious" */docs/entity_registry.yaml` → **zero hits across
  all four registries.** Spec Story 2, AS-2's *Given* is false today.

**Decision**: Split the acceptance surface in two, and say which is which.

- **Contract tests** (Story 2, AS-1 and AS-2) run against pinned synthetic fixture
  registries under `tests/fixtures/provenance/`. They prove the *mechanism* —
  alias resolution and the non-identity note — independent of corpus drift, which is what
  a contract test should do anyway.
- **Live-corpus tests** assert against the confusions that **do** exist (D10's real
  `distinct` / `rejected_aliases` data). `resolve("Vera", "obelisk")` is asserted to
  return the honest **`not-found-in-identity-store`** answer, which is itself FR-018
  behaving correctly.
- **A GM action item, outside this feature's scope**: making the two documented pairs
  resolve on the live corpus requires `registry alias` / `registry mark-distinct` runs
  against obelisk and Phandalin. FR-032 and the spec's Out of Scope forbid this feature
  from writing them. Recorded here so the gap is visible rather than discovered at demo
  time.

This does **not** reduce the feature. It records that two of the five documented
incidents were never entered into the identity stores in the first place — which is
itself an instance of the problem the feature exists to make visible.

---

## D12 — Two of the five incidents have drifted since the spec was written

**Finding**:

- **Incident 1 (Phandalin / Woodland Manse).** The stale text is **gone**.
  `docs/world_state.md:9` now reads *"the party is now returning from Falcon's Hunting
  Lodge, having cleared the Woodland Manse of a Talosian cult"* — the file was
  regenerated between the spec's writing and today. The stale claim the correction
  describes is no longer present in the file it points at.
- **Incident 2 (toee / Calmer).** Still live, and **richer than the spec describes**.
  `toee/docs/npcs/calmer.md` line 40 still says `**Status:** Dead.` — *and* lines 4–6
  carry a hand-edited banner: *"Calmer was raised from the dead by Terjon and is alive,
  operating under deep cover."* This is a live, in-corpus instance of the spec's edge case
  *"a file is both machine-generated and hand-edited afterward."* The next `planning
  --build-dossiers` run clobbers that banner. It is the best fixture in the corpus.
- **Incident 4 (obelisk).** Confirmed exactly as specified.
  `session_doc/check_consistency.py:61` reads `_DEFAULT_CONFIG_DOCS = ["campaign_state",
  "world_state"]` — generated docs only — while `obelisk/docs/background/name_glossary.md`
  exists and is never loaded.
- **Incidents 3 and 5** not re-verified in detail; incident 3's exact species-swap line
  was not located in `toee/docs/party.md` on a quick pass.

**Decision — this is the load-bearing consequence**: corrections are matched on
**file path and subject, never on the stale text string.** A correction whose text has
been regenerated away must not silently stop applying; a correction must not silently
start applying to a paraphrase. Path-and-subject matching means the correction keeps
attaching to `docs/world_state.md` until the GM prunes it, which is exactly FR-029
(nothing populated by inference) and the edge case *"a correction references a file that
no longer exists → reported as a stale correction entry so the GM can prune it."*

Correspondingly, SC-002's five test cases assert **labeling**, not stale-string presence
— which is what SC-002 literally requires ("the misleading source is labeled such that a
reviewer identifies it as stale *without opening the file*"). Incidents whose text has
drifted get a pinned fixture for the contract test plus a live-corpus test that asserts
only the envelope.

---

## D13 — Corrections record: hand-authored, path+subject scoped, three-state consultation

**Decision**: `<campaign>/docs/corrections.yaml`, strict pydantic, per-campaign
(D3). Each entry declares `applies_to.paths` (repo-relative, globs allowed) and
optional `applies_to.subjects`; a hit is annotated when its path matches **and**
(no subjects declared, or a declared subject appears in the query or the excerpt).

FR-005 needs three distinguishable states, so the envelope carries a status, not just a
list:

| `corrections_status` | `corrections` | Means |
|---|---|---|
| `consulted` | `[…]` | Corrections file loaded; these apply |
| `consulted` | `[]` | Corrections file loaded; none apply to this hit |
| `no-record` | `null` | Campaign declares no corrections file |
| `not-consulted` | `null` | File declared but unreadable — with `reason` |

A two-state design (empty list vs. absent field) cannot express the fourth row, which is
precisely the failure FR-005 names.

---

## D14 — Chapter attribution and horizon come from the manifest, never from file content

**Decision**: The manifest declares, per campaign, a `horizon` block with an explicit
filename regex and the latest released chapter:

```yaml
horizon: {latest: 46, path_pattern: 'docs/chapters/chapter_(\d+)_'}
```

obelisk needs its own (`session_(\d+)_`, D2), which is the point — a shared pattern would
have quietly failed there.

> **Amended 2026-08-05 (analysis pass).** An earlier draft of this block carried a
> `kind: chapter | date` discriminator. It is removed. All six campaigns are chapter-based,
> and the date branch had no schema field to drive it — `date_pattern` was referenced in
> data-model.md and declared nowhere, so with `extra="forbid"` it was unauthorable and the
> envelope's `date` field had no population path. FR-002's "chapter **or** date" is served
> by `chapter`. **GM ruling: horizon is chapter-only.** If a date-horizoned campaign ever
> appears, the discriminator returns *with* its pattern field and a test — not before.

**Rationale**: The spec's Assumptions require chapter attribution to come from the
manifest, "not from parsing file contents — inferring it would violate FR-029." A regex
over the **filename**, declared by hand in the manifest, is a manifest declaration; a
regex over the **file body** would be inference. The line is drawn at the file boundary.

A file the pattern cannot attribute keeps `chapter: null`. FR-025 / the edge case then
apply: a horizon filter over a campaign with no `horizon` block is **refused**, and
unattributable files under an active horizon are reported with an explicit disposition
(`horizon_disposition: unattributable`) rather than dropped.

**Provenance ranges** (FR-026) are declared in the same block — out-of-the-abyss gets
`[{chapters: [1, 15], authorship: gm-written}, {chapters: [16, null], authorship: ai-assisted}]`.
Absent ranges mean the envelope's `provenance_range` is `null`, not guessed.

---

## D15 — Backends: two, both reported honestly, only one wired in increment 1

**Finding**: `pipelines/rlm/mcp_server.py:22-26` already does the exact probe this needs:
`try: from mempalace.searcher import search_memories / except ImportError:` behind a
`_HAS_MEMPALACE` flag. `~/.mempalace/palaces/` is empty on this host.

**Decision**: `capabilities` reports a list of backends, each with a status drawn from a
closed set:

| status | Meaning |
|---|---|
| `available` | Installed and wired; contributes to results |
| `unavailable` | Reason recorded (e.g. *"mempalace not importable on this host"*) |
| `not-wired` | Implemented elsewhere but not consulted by this increment |

Increment 1 ships `literal: available` and `semantic: unavailable | not-wired` — the
probe runs for real so the answer is per-machine truthful (it will say `available` on the
WSL2 desktop's install and `unavailable` here), and the contribution field says
`not-consulted (semantic backend not wired in increment 1)`.

Every search response repeats the backend roster under `backends_consulted` (FR-022), so
a result set is never implicitly complete.

**Rejected**: reporting a not-installed backend as zero hits (the current, invisible
behaviour — this is the defect Story 3 names).

---

## D16 — Read-only and LLM-free are enforced statically, not by convention

**Decision**: Two new AST-walking guard tests over the `provenance/` package, in the
style of `tests/test_layering.py` and `tests/test_retrieve_render_isolation.py`:

- `test_provenance_readonly.py` — fails if any module in `provenance/` references a write
  sentinel (`open(..., "w"|"a"|"x")`, `write_text`, `write_bytes`, `mkdir`, `unlink`,
  `rename`, `replace`, `shutil.copy*`, `shutil.move`, `os.remove`, `atomic_write_text`).
  Plus a behavioural test that hashes every file in a fixture workspace before and after
  exercising every operation and asserts the manifest of hashes is byte-identical
  (SC-010).
- `test_provenance_no_llm.py` — fails on any import of `anthropic`, `campaignlib.api`, or
  any reference to `make_client` / `stream_api` / `call_api` / `run_batch` (FR-033).

`provenance/` is also added to `ENGINE_PACKAGES` in `tests/test_layering.py` so it can
never import `server/`.

**Rationale**: FR-031 and FR-033 are absolute prohibitions. A prohibition enforced only
by code review is a prohibition that survives until the first hurried change. The
constitution's own precedent is that a principle needs "a clause that names a file, a
test, or a workspace path."

**Additional guard now that rg is in play (D1)**: `test_provenance_readonly.py` also
asserts that every `subprocess` invocation in the package is `rg` with a flag set drawn
from the pinned allow-list in D17. A search tool that shells out is a search tool that
could shell out to something else after the next edit.

---

## D17 — rg's defaults would silently hide 230 real files. The flag set is pinned, and `.gitignore` is not a scope authority

**This is the correctness finding that matters most about adopting rg**, and it is
measured, not theoretical.

**ripgrep respects `.gitignore` by default.** The workspace has a root `.gitignore` **and
one in every single campaign** — all six. Comparing rg's default file set against the
Python scanner's:

```
rg --files (default)                      → 11,688 files
rg --files --no-ignore --hidden           → 11,914 files   ← matches the Python scanner exactly
                                             difference:  230 files silently hidden
```

**What those 230 files are:**

| Count | What | Manifest tier |
|---|---|---|
| 213 | `Phandalin/docs/npcs/merged_sidecars/**` (via `docs/npcs/merged_sidecars/`) | **working_reference** |
| 5 | `out-of-the-abyss/logs/**`, `out-of-the-abyss/voice/logs/**` | working_reference |
| 3 | `toee/temple/wiki/**` (via `temple/.llm-wiki/`, `temple/.obsidian/`) | **working_reference** |
| 1 | `stormgiants/Storm King Thunder/wiki/entities/dragonbarrow.md` | **working_reference** |
| 4 | `obelisk/.mneme/*`, `toee/.mneme/*` | unclassified |
| 4 | `.claude/**` at the workspace root | outside every campaign |

Authoritative-tier casualties this time: **zero**. That is luck, not design — the six
`.gitignore` files are maintained for version-control reasons and change independently of
the manifest. `Phandalin/.gitignore` already excludes `summaries/old/`, and `summaries/**`
is declared authoritative; one directory rename away, rg's default would be silently
dropping canon.

**Decision**: `--no-ignore --hidden` are mandatory, and **the manifest's `exclude` list is
the single authority on what is not searched.** `.gitignore` governs what git tracks; it
has no vote on what is true on disk.

The workspace's own documentation already reached this conclusion independently —
`~/src/campaigns/CLAUDE.md` says: *"Prefer `.mempalaceignore` to decouple mining
exclusions from version-control concerns."* Same principle, same workspace, a different
tool. Letting `.gitignore` silently define search scope would put scope in six files
nobody edits with search in mind — a Fragmented State on the one decision (Constitution
X, FR-006) this feature insists must be explicit.

### The pinned flag set

Every flag below is required for correctness or determinism, not for taste. Deviating from
this list is what `test_provenance_readonly.py`'s allow-list guards.

| Flag | Why it is mandatory |
|---|---|
| `--no-ignore` | Otherwise 230 real files vanish (above) |
| `--hidden` | Otherwise dot-directories like `.mneme/` vanish |
| `-g '!.git/**'` | Re-excludes only the object store, the one thing `--hidden` would wrongly admit |
| `-g '*.md' …` | One per `search_extensions`; pushes the extension filter into rg |
| `--no-config` | **Critical.** rg reads `$RIPGREP_CONFIG_PATH`; a user config injecting `--smart-case` or extra globs would silently change results per machine. Unset on this host — which is exactly why it must be pinned rather than assumed |
| `--json` | Structured output; see D18 |
| `-F` unless `regex=True` | A literal query is matched literally |
| `-e <pattern>` | A query beginning with `-` is a pattern, never a flag |
| `-i` / `-s` explicitly | **Never `--smart-case`** — it makes behaviour depend on the query's own casing, so `Ilvara` and `ilvara` would silently search differently |

The manifest's `exclude` globs are appended as further `-g '!…'` arguments, so one
declaration drives both scanners.

---

## D18 — Parse rg's `--json`, not its line output; and normalize its thread nondeterminism

**Decision**: Invoke rg with `--json` and parse the JSON Lines stream.

**Verified output shape** (real, from this corpus):

```json
{"type":"begin","data":{"path":{"text":"Phandalin/docs/world_state.md"}}}
{"type":"match","data":{"path":{"text":"Phandalin/docs/world_state.md"},
  "lines":{"text":"…having cleared the Woodland Manse of a Talosian cult…\n"},
  "line_number":9,"absolute_offset":234,
  "submatches":[{"match":{"text":"Woodland Manse"},"start":280,"end":294}]}}
```

**Why `--json` rather than the default `path:line:text`**:

1. **Paths and matched lines contain colons.** This corpus has real filenames with spaces
   and punctuation (`out-of-the-abyss/voice/logs/2026-03-24_181240_vtt_voice_ben pfaff.md`),
   and markdown prose is full of `:`. Naive splitting is a latent bug; `--json` removes the
   category.
2. **Non-UTF-8 bytes are handled explicitly.** rg emits `{"bytes": "<base64>"}` instead of
   `{"text": …}` for lines it cannot decode as UTF-8, so the excerpt path has a defined
   behaviour instead of a `UnicodeDecodeError` mid-scan. Constitution IV (Verbatim is
   Sacred) makes this non-optional: an excerpt must be reproduced exactly or reported as
   undecodable, never silently mangled by `errors="replace"`.
3. **`submatches` gives exact offsets**, which feeds the whole-word bonus in the ranking
   formula (D9) without a second regex pass over the line.

**Thread nondeterminism — now a real concern rather than a theoretical one.** rg is
multithreaded and its output order across files is **not stable between runs**. The
Python scanner's `os.walk` order is stable but differs from rg's. Either way, ranking's
total-order tail `(campaign, path, line)` (D9) normalizes both to one canonical order.

That tail was written as insurance against filesystem-walk order varying across machines.
It is now doing real work on every single query, and the parity test in D1 would fail
immediately without it. Worth stating plainly so nobody later "simplifies" the sort key
having noticed the results already look sorted.

**Version reporting**: `capabilities` reports the rg version string (`ripgrep 15.1.0`
here). The `--json` format has been stable since rg 0.9, but a scanner whose version is
invisible is exactly the tribal per-machine state Principle VIII exists to eliminate.
