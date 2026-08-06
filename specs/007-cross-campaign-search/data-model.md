# Data Model: Cross-Campaign Provenance-Aware Search Seam

**Feature**: `007-cross-campaign-search` | **Date**: 2026-08-05

Entities from [spec.md](./spec.md) §Key Entities, made concrete. Schemas for the two
hand-authored documents live in [contracts/manifest.md](./contracts/manifest.md) and
[contracts/corrections.md](./contracts/corrections.md); this file gives the model, its
validation rules and its state machines.

## Modelling rules (apply to every model below)

1. **Strict by construction.** Every pydantic model sets `ConfigDict(extra="forbid")`.
   An unrecognised key is a load error, not a silently ignored line — this is what makes
   FR-030 ("fail loudly, never proceed with partial data") real rather than aspirational.
2. **An empty string is never a way to spell "unset."** A field is either absent (taking
   its declared default) or carries a meaningful value. Same rule as
   `campaignlib/projection_config.py`.
3. **Absent ≠ empty ≠ not-consulted.** Any field whose absence the caller could
   misread as a negative answer carries a companion `*_status` enum. This is the
   structural expression of FR-005, FR-017 and FR-018 — the spec's recurring demand that
   three-way distinctions not be collapsed into two.
4. **Nothing is inferred.** No model has a field that a loader populates by guessing.
   Chapter numbers come from a manifest-declared filename regex, never from file bodies
   (research [D14](./research.md#d14)); tiers come from manifest globs, never from
   directory-name heuristics.
5. **Paths are stored as authored.** Repo-relative, POSIX-style, never `.resolve()`d into
   the model. Absolute paths are computed at the edge and never persisted.

---

## 1. Campaign

One game; the hard boundary of the feature.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Manifest key. Matches the directory name exactly, case-sensitive. |
| `root` | `str` | Path relative to the workspace root. |
| `tiers` | `TierGlobs` | §3 |
| `generated` | `list[GeneratedDecl]` | §4 |
| `horizon` | `Horizon \| None` | §7. `None` ⇒ horizon filtering is **refused** (FR-025). |
| `identity` | `IdentityDecl` | §8 |
| `corrections` | `str \| None` | Relative path to the corrections record; `None` ⇒ campaign declares none. |
| `provenance_ranges` | `list[ProvenanceRange]` | §9. Empty ⇒ envelope's range is `null`, never guessed. |
| `search_extensions` | `list[str]` | Default `[".md", ".txt", ".vtt", ".yaml", ".json"]`. |
| `exclude` | `list[str]` | Globs never scanned. Default `[".git/**", "**/__pycache__/**", "node_modules/**"]`. |

**Validation**

- `name` must be unique within the manifest.
- `root` must resolve inside the workspace root — a `..` escape is a load error, not a
  clamp. The feature reads six known directories; it does not read arbitrary paths.
- `root` need not exist on the current machine. A declared-but-missing campaign is
  reported by `capabilities` as `root-missing` and **refuses** searches, rather than
  returning zero hits (the Story-3 failure shape applied to directories).

**Relationships**: A Campaign owns 0–1 CorrectionRecord files, 0–2 IdentityStores
(`entity_registry.yaml`, `aliases.json`), and every Hit is labeled with exactly one
Campaign. Entities are **never** merged across Campaigns (FR-008).

---

## 2. ProvenanceManifest

The workspace-level, hand-authored root document. `~/src/campaigns/provenance.yaml`.

| Field | Type | Notes |
|---|---|---|
| `version` | `int` | Must be `1`. An unknown version is a load error. |
| `campaigns` | `dict[str, Campaign]` | Keyed by campaign name. Must be non-empty. |

**Rules**

- The manifest is the **only** enumeration of campaigns. Nothing discovers a campaign by
  scanning the workspace for `config/config.yaml` — a directory that appears without a
  manifest entry is invisible, and querying it is refused by name (FR-009). Discovery-by-scan
  would silently serve a defaulted tier, which is the exact failure the feature exists to
  prevent.
- Loading is **all-or-nothing**. One bad campaign block fails the whole load; there is no
  partial manifest (FR-030).

**Why workspace-level rather than per-campaign**: it is the one file that must answer
"which campaigns exist" (FR-023) without a guessing scan. Correcting the spec's stated
rationale — the six campaigns *do* share one git repo — see research [D3](./research.md#d3).

---

## 3. TrustTier / TierGlobs

`TrustTier` is a closed enum with a fixed ordinal used as the ranking tiebreak (FR-010):

| Tier | Ordinal | Canonical content |
|---|---|---|
| `authoritative` | 0 | Session summaries, VTT transcripts, chapter splits |
| `search_accelerator` | 1 | `distill_extractions/`, `planning_extractions/` |
| `working_reference` | 2 | Generated grounding docs, NPC dossiers |
| `staging` | 3 | `notes/` — unreviewed, deliberately excluded from mining |
| `unclassified` | 4 | Matched no glob (FR-013). **Not** authorable — assigned at query time only. |

`TierGlobs` holds one `list[str]` per authorable tier (the first four). All four keys
are required; an empty list is legal and explicit.

**Classification algorithm** (research [D8](./research.md#d8)):

1. Test the path against tiers in ordinal order 0 → 3. **First match wins.**
2. Continue testing the remaining tiers anyway; every additional match is recorded in the
   hit's `tier_ambiguous` list.
3. No match ⇒ `unclassified`. The hit is still returned, labeled — never dropped.

A pure first-match-wins rule would be the tool making a scope decision. Recording the
ambiguity in the envelope and reporting it from `provenance check` keeps the decision with
the GM (Constitution II), while still giving one deterministic answer per query.

**Why per-campaign globs are mandatory**: the accelerator tier lives at
`stormgiants/distill_extractions/` but at `Phandalin/docs/distill_extractions/`, and
several campaigns have both. A shared template mis-tiers real files
(research [D2](./research.md#d2)).

---

## 4. GeneratedDecl

Declares that files are pipeline output and will be clobbered on regeneration.

| Field | Type | Notes |
|---|---|---|
| `paths` | `list[str]` | Globs, repo-relative. Non-empty. |
| `by` | `str` | The generating stage — a console-script name (`distill`, `planning`, `party`, `campaign_state`, `synthesise_world_state`, …). Non-empty. |
| `note` | `str \| None` | Optional GM annotation. |

**Semantics (FR-003)**: a non-null `generated_by` on an envelope means *"will be
clobbered on regeneration, may be stale."* That is the whole contract — the field is not
a provenance credit line, it is a warning.

**The hand-edited-generated file** (spec edge case, live in the corpus): the manifest's
declaration governs. `toee/docs/npcs/calmer.md` is generated by `planning
--build-dossiers` **and** carries a hand-written correction banner at lines 4–6 that the
next run will destroy. It is labeled `generated_by: planning` and additionally flagged
`generated_but_hand_edited: true` when a correction record for that path exists — a
warning condition worth surfacing, per the spec, not a reason to re-tier the file
(research [D12](./research.md#d12)).

---

## 5. CorrectionRecord / Correction

Per-campaign, hand-authored, at the manifest-declared path (conventionally
`<campaign>/docs/corrections.yaml`).

`CorrectionRecord`: `version: int` (must be `1`), `campaign: str` (must equal the manifest
key), `corrections: list[Correction]`.

`Correction`:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Slug, unique within the record. Stable across edits so a GM can refer to one. |
| `applies_to.paths` | `list[str]` | Repo-relative globs. Non-empty. |
| `applies_to.subjects` | `list[str]` | Optional. Empty ⇒ applies to every hit in those paths. |
| `stale_claim` | `str` | What the file wrongly says. Human-readable; **never used for matching.** |
| `truth` | `str` | What is actually true. |
| `as_of` | `str \| None` | `chapter-43`, a date, or `None`. |
| `recorded` | `date` | When the GM recorded it. |
| `recorded_by` | `str` | Default `"GM"`. |
| `verified` | `bool` | Default `True`. `False` = the stale claim could not be reproduced on disk; the GM rules at the T031 gate. |
| `note` | `str \| None` | Free text. Required in practice when `verified: false` — it carries the evidence. |

**`verified` exists because one seed incident could not be reproduced.** Incident 3 (the
Sequioa/Zephyr species swap) is not visible in `toee/docs/party.md` as it stands:
Zephyr has a species (tiefling), Sequoia has none, and "fire resistance" appears only as a
*Potion of Fire Resistance* in two inventory lists — there is no statblock note. Rather
than assert it or drop it, the entry ships `verified: false` with the evidence in `note`,
and the GM rules on it at T031. A correction is hand-authored truth (FR-029); an
unreproducible one is a question for the human, not a fact the tool should quietly
publish. `provenance check` reports every `verified: false` entry so it cannot be
forgotten.

**Matching rule (research [D12](./research.md#d12) — the load-bearing decision)**: a
correction attaches when the hit's path matches `applies_to.paths` **and** (`subjects` is
empty **or** a subject appears, case-insensitively, in the query or the excerpt).
`stale_claim` is displayed, never matched.

This matters because incident 1's stale text is *already gone*: Phandalin's
`docs/world_state.md` was regenerated and now says the Manse was cleared. Text-matching
would have made that correction silently stop applying — the exact silent-degradation
class the feature exists to kill. Path-and-subject matching keeps it attached until the
GM prunes it.

**Stale-entry reporting** (spec edge case): a correction whose `applies_to.paths` match no
file on disk is reported by `provenance check` as `stale-correction-entry` so the GM can
prune it. It never crashes a query and is never auto-removed.

### Consultation status — the four states (FR-005)

Every envelope carries both a status and a payload. A two-state design (empty list vs.
absent field) cannot express the fourth row, which is precisely what FR-005 demands.

| `corrections_status` | `corrections` | `reason` | Means |
|---|---|---|---|
| `consulted` | `[…]` | — | Record loaded; these apply to this hit |
| `consulted` | `[]` | — | Record loaded; none apply to this hit |
| `no-record` | `null` | — | Campaign declares no corrections file |
| `not-consulted` | `null` | set | Declared but unreadable/unparseable |

---

## 6. ProvenanceEnvelope

The label set on every hit. Its completeness is the feature's core guarantee (SC-001), so
**every field below is always present** — a field with nothing to say carries `null` plus
its status field, never omission.

| Field | Type | Requirement |
|---|---|---|
| `campaign` | `str` | FR-002, FR-008 |
| `path` | `str` | Repo-relative, POSIX |
| `line` | `int` | 1-indexed |
| `excerpt` | `str` | Verbatim (Constitution IV) |
| `excerpt_encoding` | `"utf-8" \| "undecodable"` | See below |
| `context_before` / `context_after` | `list[str]` | Default 2 lines each; verbatim |
| `tier` | `TrustTier` | FR-002 |
| `tier_ambiguous` | `list[TrustTier]` | `[]` when unambiguous (D8) |
| `generated_by` | `str \| None` | Non-null ⇒ will be clobbered (FR-003) |
| `generated_but_hand_edited` | `bool` | §4 warning condition |
| `chapter` | `int \| None` | From the manifest filename pattern only (D14) |
| `provenance_range` | `str \| None` | e.g. `gm-written`, `ai-assisted` (FR-026) |
| `corrections` | `list[Correction] \| None` | §5 |
| `corrections_status` | enum | §5 — the four states |
| `matched_surface_form` | `str` | Which alias produced this hit (FR-019) |
| `relevance` | `float` | Deterministic score (§10) |
| `horizon_disposition` | enum \| `null` | `included` / `unattributable`; excluded hits are counted, not returned (FR-012) |

**Invariant, tested**: for every hit in every response, the set of keys equals the set
above exactly. `test_provenance_search.py` asserts this structurally rather than
spot-checking fields — SC-001 is "zero hits with a missing required field," which is a
statement about the key set.

**`excerpt_encoding` and Constitution IV.** rg's `--json` mode emits `{"bytes": "<base64>"}`
rather than `{"text": …}` for a line it cannot decode as UTF-8. Constitution IV forbids
"improving" verbatim content, and `errors="replace"` silently mangles it — so an
undecodable line is returned with `excerpt_encoding: "undecodable"` and the raw bytes
rendered as an escaped representation, never quietly substituted. This corpus contains
Windows `Zone.Identifier` streams and Dropbox attribute files, so the case is real rather
than defensive. Both scanners must agree on this handling; the parity test covers it
(research [D18](./research.md#d18)).

---

## 7. Horizon

| Field | Type | Notes |
|---|---|---|
| `latest` | `int` | Latest released chapter. |
| `path_pattern` | `str` | Regex over the **repo-relative path**, exactly one capture group. |

**Chapter-only, deliberately.** An earlier draft carried a `kind: "chapter" | "date"`
discriminator and a `date` envelope field. Both are removed: all six campaigns are
chapter-based, no `date_pattern` field ever existed to drive the date branch, and a
declared-but-unimplemented branch is a promise the schema cannot keep. FR-002's "chapter
**or** date" is served by `chapter`. If a date-horizoned campaign ever appears, the
discriminator comes back **with** its pattern field and a test — not before.

**Per-campaign by necessity**: five campaigns match
`docs/chapters/chapter_(\d+)_`; obelisk matches `docs/chapters/session_(\d+)_`. A shared
pattern would silently fail on obelisk (research [D2](./research.md#d2)).

**The path/content line (research [D14](./research.md#d14))**: the regex runs over the
**filename**, and it is hand-declared in the manifest. A regex over the file *body* would
be inference and would violate FR-029. The boundary is the file, and it is not negotiable.

**State machine**

| Manifest `horizon` | Caller passes horizon | Result |
|---|---|---|
| absent | no | Normal search; every `chapter` is `null` (no `date` field exists) |
| absent | yes | **Refused**, naming the missing marker (FR-025) |
| present | no | Normal search; chapters labeled |
| present | yes | Filter applied; excluded count reported (FR-012) |
| present | yes, file unattributable | Returned with `horizon_disposition: unattributable` — explicit, never silently dropped |

---

## 8. IdentityStore + IdentityResolution

`IdentityDecl` declares `registry: str | None` and `aliases: str | None` (relative paths).
Present for Phandalin, out-of-the-abyss, toee, obelisk; absent for stormgiants and
Hillsfar (verified — research [D10](./research.md#d10)).

**Reuse, do not re-parse.** `campaignlib/registry.py` already loads
`docs/entity_registry.yaml`, validates its invariants, and exposes `alias_to_canonical()`
and `known_names()` including the documented first-token rule (`"Kazryn"` →
`"Kazryn Nyantani"`). `provenance/identity.py` is a **read-only adapter over it**, not a
second parser. A second parser would be a Split-Brain on identity — the exact defect the
entity registry was built to end.

### `IdentityResolution`

| Field | Type | Notes |
|---|---|---|
| `status` | enum | `resolved` / `not-found` / `no-store` — §the three states |
| `surface_form` | `str` | What was asked |
| `canonical` | `str \| None` | |
| `type` | `str \| None` | `npc`/`location`/… |
| `aliases` | `list[str]` | |
| `known_confusions` | `list[KnownConfusion]` | §below |
| `known_wrong_variants` | `WrongVariants` | §the schema gap |
| `note` | `str \| None` | The registry's own note |

### The three states (FR-017, FR-018)

| `status` | When | Example |
|---|---|---|
| `resolved` | Surface form found | `Ilvara` → `Ilvara Mizzrym` (out-of-the-abyss) |
| `not-found` | Store exists; form absent | `Vera` in obelisk — Veyra is real (`characters/veyra.md`) but **unregistered** (research [D11](./research.md#d11)) |
| `no-store` | Campaign declares no identity store | Any name in stormgiants or Hillsfar |

`not-found` and `no-store` are different answers to different questions and are never
collapsed. **Name similarity is never evidence of identity (FR-016)**: nothing in this
module computes a string distance to *assert* a match. `provenance check` may surface
near-duplicates as GM-review findings — that is `registry check`'s existing, separate,
human-gated job, and it never feeds a resolution.

### KnownConfusion (FR-015)

Two real registry fields, kept distinct because they mean different things:

| `kind` | Registry field | Means |
|---|---|---|
| `distinct` | `distinct:` | Ruled to be different entities |
| `rejected-alias` | `rejected_aliases:` | A proposed alias link considered and refused |

Live data confirmed on disk: `[Topsy, Turvy]`, `[Ellen, Elian]`,
`[The Grygumite School, the Grygumite triangle]` (oota); `[Barkinar, Deggum]` (toee);
`[Meril's Staff, Staff of Birdcalls]` (Phandalin); rejected pairs `[Corbin, Corwin]`,
`[Shoor Vandree, Stool]`, `[Krell, Lieutenant Krell]`, and others. obelisk's registry has
**neither section** — so obelisk answers *consulted, none recorded*, not *not consulted*.

### The schema gap, stated rather than papered over

FR-014 asks for "known-wrong variants." **The registry schema has no such field** —
`Entity` is `name, type, aliases, provenance, source, scope, note`. In practice wrong
variants are stored as ordinary aliases: Phandalin lists `"Adabra Adabra Gwynn"`,
`"king_gnercli"` and `"Gnercli"` in the same `aliases:` list as legitimate short forms.

So `known_wrong_variants` returns `{status: "not-recorded-by-schema"}` — the caller learns
the distinction is unavailable rather than reading an empty list as "there are none."
Classifying some aliases as "wrong" by inspection would be exactly the name-similarity
reasoning FR-016 forbids (research [D10](./research.md#d10)).

### Alias expansion (FR-019)

When enabled, a search runs once per `{canonical} ∪ {aliases}`, and each hit records the
`matched_surface_form` that produced it. Hits found by more than one form are deduplicated
on `(campaign, path, line)` keeping the **longest** matched form, so the label names the
most specific match rather than a coincidental short one.

---

## 9. ProvenanceRange (FR-026)

`{from: int, to: int | None, authorship: str, note: str | None}` — `to: null` means
open-ended. Ranges within a campaign must not overlap; an overlap is a load error.

out-of-the-abyss declares `[{from: 1, to: 15, authorship: gm-written},
{from: 16, to: null, authorship: ai-assisted}]`. Both ranges are canon for plot; they are
not interchangeable for voice-reference work — which is the whole reason the label exists.
A hit whose chapter falls in no declared range carries `provenance_range: null`, never a
guess.

---

## 10. Relevance and ranking (FR-010, SC-009)

Deterministic, disk-only, no LLM (FR-033).

```
relevance = match_count_in_file
          + 2.0 if whole-word match
          + 1.5 if the matching line is a markdown heading
          + 1.0 if the query appears in the file's basename
```

Sort key, ascending: `(-relevance, tier_ordinal, campaign, path, line)`.

The `(campaign, path, line)` tail is load-bearing, not cosmetic: without it, ties resolve
by scan order. **rg is multithreaded and its file order is not stable between runs**, and
the Python fallback's `os.walk` order is stable but different again. SC-009 requires
identical results on rebuild, and a **total** order is what makes "identical" a checkable
claim across both scanners and both machines. Do not "simplify" this sort key on the
grounds that results already look sorted — `test_provenance_scanner_parity.py` fails
immediately without it (research [D18](./research.md#d18)).

---

## 11. Backend (FR-020 – FR-022)

`{name, status, reason, contributed, impl, impl_version}` where
`status ∈ {available, unavailable, not-wired}`.

| Backend | Increment 1 status | `impl` | Notes |
|---|---|---|---|
| `literal` | `available` | `rg` \| `python` | Always available — rg when discoverable, stdlib otherwise (D1) |
| `semantic` | `unavailable` on this host | — | MemPalace probed for real, per machine (D15) |

### `impl` — why the scanner identity is a first-class field

The `literal` backend has two interchangeable implementations with a **~60× latency
difference**: `rg` 15.1.0 (0.01 s over the full corpus) and the stdlib Python scanner
(0.63 s for the largest campaign). Which one runs depends on whether `shutil.which("rg")`
resolves in the server's `PATH` — and on this very host it resolved to `None` earlier the
same day and `/usr/bin/rg` later.

So `impl` and `impl_version` are reported on every search response and by `capabilities`.
An unreported 60× swing that varies by host is precisely the tribal per-machine state
Principle VIII exists to eliminate — the same argument Story 3 makes about MemPalace,
applied to the backend's own guts.

**The two implementations must return identical hit sets**, enforced by
`test_provenance_scanner_parity.py` over the fixture workspace and one live campaign.
Results that differ by machine would break SC-009 far more seriously than a slow scan
ever could. Two consequences follow, both load-bearing:

- **`.gitignore` is not a scope authority.** rg respects it by default and would hide 230
  real files here — 217 of them working-reference-tier. `--no-ignore --hidden` is
  mandatory; the manifest's `exclude` list is the single declaration driving both scanners
  (research [D17](./research.md#d17)).
- **rg's output order is not stable** (it is multithreaded), and differs from `os.walk`'s.
  The ranking tail in §10 normalizes both. That tail is no longer insurance — it is doing
  real work on every query.

The probe is the one already used at `pipelines/rlm/mcp_server.py:22-26`
(`from mempalace.searcher import search_memories` behind try/except) plus a palace-directory
check. It runs for real from day one, so the answer is truthful per machine — it will read
`available` on the WSL2 desktop and `unavailable` here — while `contributed` reads
`not-consulted (semantic backend not wired in increment 1)`.

Every search response repeats the roster under `backends_consulted`, so a result set is
never implicitly complete (FR-022). An uninstalled backend is **never** reported as zero
hits — that indistinguishability is the defect Story 3 names.

---

## 12. SearchRequest / SearchResponse

### `SearchRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | `str` | — | Required, non-empty |
| `campaigns` | `list[str]` | — | **Required, non-empty.** No default, no `all` token |
| `tiers` | `list[TrustTier] \| None` | `None` | `None` = no filter; suppressed hits are counted |
| `horizon` | `int \| str \| None` | `None` | Refused if the campaign declares no marker |
| `expand_aliases` | `bool` | `False` | Explicit act |
| `regex` | `bool` | `False` | `False` ⇒ the query is escaped as a literal |
| `case_sensitive` | `bool` | `False` | |
| `limit` | `int` | `50` | Truncation is **reported**, never silent |
| `context_lines` | `int` | `2` | |

**`campaigns` has no default anywhere in the stack** — not in the model, not in the CLI
argparse, not in the MCP tool signature. Constitution X, FR-006, SC-003. A missing or
empty value is refused with a message that enumerates the known campaigns so the caller
can re-issue explicitly. There is no `all` token in increment 1; Story 5's cross-campaign
act is naming N≥2 campaigns.

### `SearchResponse`

| Field | Type | Notes |
|---|---|---|
| `hits` | `list[ProvenanceEnvelope]` | Ranked (§10) |
| `total_matched` | `int` | Before any filter or limit |
| `suppressed_by_tier` | `dict[TrustTier, int]` | FR-011 |
| `suppressed_by_horizon` | `int` | FR-012 |
| `suppressed_by_exclude` | `int` | Files skipped by the manifest's `exclude` globs — see below |
| `truncated_by_limit` | `int` | Never a silently shortened list |
| `backends_consulted` | `list[Backend]` | FR-022 — each carries `impl` + `impl_version` (§11), so the caller sees whether rg or the fallback produced this result |
| `campaigns_searched` | `list[str]` | Echoed back; the caller sees what scope actually ran |
| `elapsed_ms` | `int` | Makes the spec's degraded-latency condition observable — read together with `impl`, since the two scanners differ ~60× |
| `warnings` | `list[str]` | Tier ambiguity, stale corrections, unattributable files |

**Suppression is never silent.** A tier filter that excludes everything returns
`hits: []` **with** `suppressed_by_tier: {working_reference: 12}` — the spec's required
"all N hits suppressed by filter," not an empty result set (FR-011, SC-005).

**`suppressed_by_exclude` closes the last silent narrowing.** Research
[D17](./research.md#d17) makes the manifest's `exclude` globs the *single authority* on
what is not searched — which is right, but it concentrates the risk: one glob added by a
GM would otherwise narrow every future search with nothing in any response to show for it.
Tier and horizon suppression are counted, so exclusion is too. The scanner must therefore
**count** excluded files rather than merely skipping them; both implementations do, and
the parity test (§11) covers the count as well as the hits.

---

## Entity relationship summary

```
ProvenanceManifest (1) ──< Campaign (6)
                              ├──< TierGlobs (1)          → classifies files into TrustTier
                              ├──< GeneratedDecl (0..n)   → sets generated_by on envelopes
                              ├──< Horizon (0..1)         → chapter attribution + filtering
                              ├──< ProvenanceRange (0..n) → authorship labeling
                              ├──> CorrectionRecord (0..1) ──< Correction (0..n)
                              └──> IdentityStore (0..2)   [read-only, via campaignlib.registry]

SearchRequest ──> [literal backend: scan → classify → annotate → rank] ──> SearchResponse
                                                                             └──< ProvenanceEnvelope (0..n)
```

Every arrow out of an IdentityStore or a campaign file is **read-only**. Nothing in this
model has a write path; `test_provenance_readonly.py` enforces that statically and with a
before/after hash sweep of the whole fixture workspace (FR-031, SC-010, research
[D16](./research.md#d16)).
