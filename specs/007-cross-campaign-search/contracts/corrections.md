# Contract: Per-Campaign Corrections Record

**File**: `<campaign>/docs/corrections.yaml` (path declared by the manifest, hand-authored)
**Model**: `provenance/corrections.py` — pydantic v2, `ConfigDict(extra="forbid")`
**Requirements**: FR-004, FR-005, FR-028, FR-029, FR-030 | **Research**: [D3](../research.md#d3), [D12](../research.md#d12), [D13](../research.md#d13)

A record that a specific file or subject is **known stale**, what is actually true, and as
of when. Hand-authored only (FR-029); seeded from the five documented incidents (FR-028).

**Why per-campaign, inside the campaign**: a correction is campaign truth and versions with
the game that owns it, so a campaign stays self-describing if moved or cloned alone. It
also keeps `~/src/campaigns/CLAUDE.md`'s hard rule intact — *"Never bundle changes from
multiple campaigns into a single commit or PR."* All six campaigns share one git repo
(research [D3](../research.md#d3)), so a workspace-wide corrections file would be a
standing merge point that violates that rule on every edit.

## Schema

```yaml
version: 1                     # int, must be 1
campaign: <name>               # must equal the manifest key exactly

corrections:                   # list, may be empty
  - id: <slug>                 # required; unique in this file; stable across edits
    applies_to:
      paths: [<glob>, …]       # required, non-empty; repo-relative to the campaign root
      subjects: [<str>, …]     # optional; empty ⇒ applies to every hit under those paths
    stale_claim: <str>         # required; what the file wrongly says. DISPLAY ONLY.
    truth: <str>               # required; what is actually true
    as_of: <str> | null        # optional; "chapter-43", a date, or null
    recorded: YYYY-MM-DD       # required
    recorded_by: <str>         # default "GM"
    verified: <bool>           # default true; false = stale claim NOT reproducible on disk
    note: <str> | null         # optional; carries the evidence when verified: false
```

### `verified` — an unreproducible correction is a question, not a fact

A correction is hand-authored truth (FR-029). When the stale claim it describes cannot be
found on disk, publishing it anyway would assert something unverified — so the entry ships
`verified: false` with the evidence in `note`, and the GM rules on it at the T031 review
gate. `provenance check` reports every `verified: false` entry as a finding so it cannot
be quietly forgotten, and a hit annotated by an unverified correction is labeled as such
rather than presented as settled.

This is not hypothetical: **incident 3 is currently unreproducible** (see its entry below).

## The matching rule — and why it is what it is

A correction attaches to a hit when:

1. the hit's repo-relative path matches any glob in `applies_to.paths`, **and**
2. `applies_to.subjects` is empty, **or** a declared subject appears
   (case-insensitively) in the search query or in the hit's excerpt.

**`stale_claim` is displayed to the reader and never used for matching.**

This is the load-bearing decision in the whole feature, and it is empirical. Incident 1's
stale text is *already gone*: Phandalin's `docs/world_state.md:9` was regenerated between
the spec's writing and 2026-08-05 and now reads *"having cleared the Woodland Manse of a
Talosian cult."* Text-matching would have made that correction **silently stop applying**
— which is precisely the silent-degradation class the feature exists to kill. Path-and-subject
matching keeps it attached until a human prunes it (research [D12](../research.md#d12)).

The symmetric hazard is also closed: text-matching would let a correction silently *start*
applying to a paraphrase it was never written for.

## Consultation status — four states (FR-005)

Every envelope carries `corrections_status` alongside `corrections`. A two-state design
(empty list vs. absent field) cannot express the fourth row, which is exactly what FR-005
demands.

| `corrections_status` | `corrections` | `reason` | Means |
|---|---|---|---|
| `consulted` | `[…]` | — | Record loaded; these apply to this hit |
| `consulted` | `[]` | — | Record loaded; none apply to this hit |
| `no-record` | `null` | — | Manifest declares `corrections: null` |
| `not-consulted` | `null` | set | Declared but unreadable/unparseable |

## Validation

| Rule | Failure mode |
|---|---|
| `version == 1` | Load error |
| Unrecognised key at any depth | Load error (`extra="forbid"`) |
| `campaign` matches the manifest key | Load error |
| `id` unique within the file | Load error |
| `applies_to.paths` non-empty | Load error |
| `stale_claim` and `truth` non-empty | Load error |
| A correction's paths match **no file on disk** | **Not** a load error — reported by `provenance check` as `stale-correction-entry` so the GM can prune it. Never crashes a query, never auto-removed. |

## Seed content — the five documented incidents

### `Phandalin/docs/corrections.yaml`

```yaml
version: 1
campaign: Phandalin
corrections:
  - id: woodland-manse-empty
    applies_to:
      paths: ["docs/world_state.md"]
      subjects: ["Woodland Manse", "Grannoc"]
    stale_claim: >-
      "Active; Grannoc performing ritual; NOT visited."
    truth: >-
      The Woodland Manse has been empty since Chapter 43. The party cleared the
      Talosian cult there. A consistency check that trusted world_state.md
      false-positived a correct recap as a continuity error.
    as_of: chapter-43
    recorded: 2026-08-04
    recorded_by: GM
```

> **Author's note, kept with the entry**: as of 2026-08-05 `docs/world_state.md` has been
> regenerated and no longer carries the stale sentence. The correction stays because
> `distill`/`synthesise_world_state` may reintroduce it on any future run, and because a
> correction is pruned by a human, not by a text match.

### `toee/docs/corrections.yaml`

```yaml
version: 1
campaign: toee
corrections:
  - id: calmer-alive-undercover
    applies_to:
      paths: ["docs/npcs/calmer.md", "docs/npcs/calmert.md", "docs/*.md"]
      subjects: ["Calmer", "Calmert"]
    stale_claim: >-
      "Status: Dead. Killed by Thalsor." (docs/npcs/calmer.md line 40)
    truth: >-
      Calmer is a LIVING PC. He was raised from the dead by Terjon and operates
      undercover as Supreme Prophet of the Upper Temple. The dossier's own
      hand-written banner (lines 4-6) says so, and the next
      `planning --build-dossiers` run will destroy that banner.
    as_of: null
    recorded: 2026-08-04
    recorded_by: GM

  - id: sequioa-zephyr-species-swap
    applies_to:
      paths: ["docs/party.md"]
      subjects: ["Sequioa", "Sequoia", "Zephyr"]
    stale_claim: >-
      Sequioa's and Zephyr's species are swapped, which attributes fire
      resistance to the wrong PC in a statblock note.
    truth: >-
      The species attributions are reversed. Verify against the character
      sheets before using any species-derived trait for either PC.
    as_of: null
    recorded: 2026-08-04
    recorded_by: GM
    verified: false
    note: >-
      NOT REPRODUCIBLE ON DISK as of 2026-08-05. docs/party.md gives Zephyr a
      species (tiefling, lines 75 and 87) and Sequoia none, so there is no
      visible swap; "fire resistance" appears only as a Potion of Fire
      Resistance in two inventory lists (lines 22, 125), and there is no
      statblock note. toee has no characters/ directory, so there are no
      sheets to check the claim against. The file also spells it "Sequoia",
      not "Sequioa". Either party.md was regenerated since the incident or
      the original description was imprecise. GM to confirm, correct, or
      prune at the T031 review gate.
```

> `calmer.md` is the corpus's live example of the spec's *"generated **and** hand-edited
> afterward"* edge case. The manifest declares it generated by `planning`, so it is labeled
> generated — the hand edits do not re-tier it — and because a correction exists for that
> path, the envelope additionally raises `generated_but_hand_edited: true`.

### `obelisk/docs/corrections.yaml`

```yaml
version: 1
campaign: obelisk
corrections:
  - id: naming-authority-is-the-glossary
    applies_to:
      paths: ["docs/world_state.md", "docs/campaign_state.md"]
      subjects: ["Dawnforge", "Forepot", "Foreput"]
    stale_claim: >-
      The generated world_state/campaign_state docs are treated as the naming
      authority. They false-flag canon surnames (Dawnforge) as unattested and
      share errors with each other (Forepot for Foreput).
    truth: >-
      The authoritative naming sources are the hand-curated
      docs/background/name_glossary.md plus characters/*.md.
      `session_doc/check_consistency.py` loads only campaign_state and
      world_state (_DEFAULT_CONFIG_DOCS, line 61) and never reads the glossary.
    as_of: null
    recorded: 2026-08-04
    recorded_by: GM
```

### Incident 5 — query-time alias failures — is **not** a corrections entry

Incident 5 ("Vera"→Veyra; "KP" must not reach Kostadinious the Sage; "Unla"/"Key" are one
halfling PC) belongs to the **identity store**, not to corrections. It is recorded here
only to say where it goes and why it is not resolved by this feature:

- Verified on disk 2026-08-05: obelisk's `docs/entity_registry.yaml` has **no Veyra
  entry** (though `obelisk/characters/veyra.md` exists), and **no registry in any campaign**
  contains Kazneporium or Kostadinious.
- FR-032 and the spec's Out of Scope forbid this feature from writing identity data.
  Entering these is a `registry alias` / `registry mark-distinct` act behind explicit human
  confirmation — the existing tooling's job.
- Until a human does that, `resolve("Vera", "obelisk")` correctly returns
  **`not-found-in-identity-store`**, which is FR-018 working, not a bug
  (research [D11](../research.md#d11)).

### `stormgiants/`, `Hillsfar/`, `out-of-the-abyss/`

Ship with an empty but present record, so every campaign answers `consulted` rather than
`no-record` — the difference the GM will actually want:

```yaml
version: 1
campaign: <name>
corrections: []
```

## Commit discipline

Six corrections files across six campaigns are **six commits**, one per campaign, per
`~/src/campaigns/CLAUDE.md`. `provenance.yaml` and `.mcp.json` are root-level shared
infrastructure and go in their own separate commit.
