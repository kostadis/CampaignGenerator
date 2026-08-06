# Contract: Provenance Manifest

**File**: `~/src/campaigns/provenance.yaml` (workspace root, hand-authored)
**Model**: `provenance/manifest.py` — pydantic v2, `ConfigDict(extra="forbid")` throughout
**Requirements**: FR-027, FR-029, FR-030 | **Research**: [D2](../research.md#d2), [D3](../research.md#d3), [D7](../research.md#d7), [D8](../research.md#d8), [D14](../research.md#d14)

The single machine-readable transcription of the trust hierarchy that today exists only
as prose in `~/src/campaigns/CLAUDE.md`. **Hand-authored only** — nothing populates it by
inference (FR-029).

## Schema

```yaml
version: 1                            # int, must be 1; unknown version = load error

campaigns:                            # dict[str, Campaign], non-empty
  <campaign-name>:                    # must equal the directory name, case-sensitive

    root: <rel-path>                  # required; relative to workspace root; no ".." escape

    tiers:                            # required; all four keys required, lists may be empty
      authoritative:      [<glob>, …]
      search_accelerator: [<glob>, …]
      working_reference:  [<glob>, …]
      staging:            [<glob>, …]

    generated:                        # list, default []
      - paths: [<glob>, …]            #   required, non-empty
        by: <stage>                   #   required; console-script name, non-empty
        note: <str>                   #   optional

    horizon:                          # optional; absent ⇒ horizon filtering is REFUSED
      latest: <int>                   #   latest released chapter
      path_pattern: <regex>           # over the repo-relative PATH; exactly 1 capture group

    identity:                         # required block; either key may be null
      registry: docs/entity_registry.yaml | null
      aliases:  docs/aliases.json     | null

    corrections: docs/corrections.yaml | null

    provenance_ranges:                # list, default []
      - from: <int>
        to: <int> | null              #   null = open-ended
        authorship: <str>             #   e.g. gm-written, ai-assisted
        note: <str>                   #   optional

    search_extensions: [".md", ".txt", ".vtt", ".yaml", ".json"]   # default shown
    exclude: [".git/**", "**/__pycache__/**", "node_modules/**"]   # default shown
```

## Validation rules

| Rule | Failure mode |
|---|---|
| `version == 1` | Load error |
| Any unrecognised key, at any depth | Load error (`extra="forbid"`) |
| `campaigns` non-empty | Load error |
| Campaign key unique | Load error |
| `root` contains no `..` and stays inside the workspace root | Load error — never clamped |
| All four `tiers` keys present | Load error |
| `generated[].paths` non-empty, `generated[].by` non-empty | Load error |
| `horizon.path_pattern` compiles with exactly one capture group | Load error |
| `horizon.latest` is an `int` | Load error — horizon is chapter-only (data-model.md §7) |
| `provenance_ranges` do not overlap within a campaign | Load error |
| `root` does not exist on disk | **Not** a load error — reported by `capabilities` as `root-missing`; searches against it are **refused** |

**Loading is all-or-nothing.** One bad campaign block fails the whole load. There is no
partial manifest and no "skip the broken entry and carry on" — FR-030 exists because
partial data is how a defaulted tier gets served.

## Enumeration is closed

The manifest is the **only** source of "which campaigns exist." Nothing scans the
workspace for `config/config.yaml` to discover campaigns. A directory present on disk but
absent from the manifest is invisible to search, and naming it is refused by name (FR-009).
Discovery-by-scan would necessarily serve a defaulted tier — the exact failure the feature
exists to prevent.

## Worked example — the real six campaigns

Verified against the live workspace 2026-08-05. Note the three places a shared template
would have been wrong: stormgiants' and toee's root-level extraction dirs, obelisk's
`session_NNN_` chapter naming, and Phandalin's `lib/`.

```yaml
version: 1

campaigns:

  Phandalin:
    root: Phandalin
    tiers:
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: ["docs/*_extractions/**/*.md"]
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "characters/*.md", "voice/*.md",
                           "docs/*.yaml", "docs/*.json", "config/*.yaml"]
      staging:            ["notes/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
      - {paths: ["docs/planning.md"],       by: planning}
      - {paths: ["docs/party.md"],          by: party}
      - {paths: ["docs/npcs/*.md"],         by: planning, note: "--build-dossiers"}
    horizon: {latest: 46, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: docs/entity_registry.yaml, aliases: docs/aliases.json}
    corrections: docs/corrections.yaml
    provenance_ranges: []

  out-of-the-abyss:
    root: out-of-the-abyss
    tiers:
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: ["docs/*_extractions/**/*.md"]
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "voice/*.md", "examples/*.md",
                           "docs/*.yaml", "docs/*.json", "config/*.yaml"]
      staging:            ["notes/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: synthesise_world_state}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
      - {paths: ["docs/planning.md"],       by: planning}
      - {paths: ["docs/party.md"],          by: party}
      - {paths: ["docs/npcs/*.md"],         by: planning, note: "--build-dossiers"}
    horizon: {latest: 62, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: docs/entity_registry.yaml, aliases: docs/aliases.json}
    corrections: docs/corrections.yaml
    provenance_ranges:                       # FR-026 — the spec's named example
      - {from: 1,  to: 15,   authorship: gm-written,  note: "hand-written by the GM"}
      - {from: 16, to: null, authorship: ai-assisted, note: "not voice-reference material"}

  stormgiants:
    root: stormgiants
    tiers:
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      # NOTE: BOTH locations — root-level and under docs/. Verified on disk (D2).
      search_accelerator: ["distill_extractions/**/*.md", "planning_extractions/**/*.md",
                           "party_extractions/**/*.md",   "docs/*_extractions/**/*.md"]
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "voice/*.md", "examples/*.md",
                           "Storm King Thunder/**/*.md", "docs/*.yaml", "docs/*.json"]
      staging:            ["notes/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
      - {paths: ["docs/planning.md"],       by: planning}
      - {paths: ["docs/npcs/*.md"],         by: planning, note: "--build-dossiers"}
    horizon: {latest: 86, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: null, aliases: null}      # no identity store — degrades honestly
    corrections: docs/corrections.yaml
    provenance_ranges: []

  toee:
    root: toee
    tiers:
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: ["planning_extractions/**/*.md", "docs/*_extractions/**/*.md"]
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "voice/*.md", "examples/*.md",
                           "temple/**/*.md", "docs/*.yaml", "docs/*.json"]
      staging:            ["notes/**", "archive/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
      - {paths: ["docs/party.md"],          by: party}
      - {paths: ["docs/npcs/*.md"],         by: planning, note: "--build-dossiers"}
    horizon: {latest: 31, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: docs/entity_registry.yaml, aliases: docs/aliases.json}
    corrections: docs/corrections.yaml
    provenance_ranges: []

  Hillsfar:
    root: Hillsfar
    tiers:
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: []
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "docs/*.yaml", "docs/*.json"]
      staging:            ["notes/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
    horizon: {latest: 15, path_pattern: 'docs/chapters/chapter_(\d+)_'}
    identity: {registry: null, aliases: null}      # no identity store — degrades honestly
    corrections: docs/corrections.yaml
    provenance_ranges: []

  obelisk:
    root: obelisk
    tiers:
      # NOTE: session_NNN_, not chapter_NN_. A shared pattern silently fails here (D2).
      authoritative:      ["summaries/**/*.md", "summaries/**/*.vtt", "docs/chapters/*.md"]
      search_accelerator: []
      working_reference:  ["docs/*.md", "docs/npcs/*.md", "docs/background/*.md",
                           "characters/*.md", "docs/*.yaml", "docs/*.json", "config/*.yaml"]
      staging:            ["notes/**"]
    generated:
      - {paths: ["docs/world_state.md"],    by: distill}
      - {paths: ["docs/campaign_state.md"], by: campaign_state}
    horizon: {latest: 4, path_pattern: 'docs/chapters/session_(\d+)_'}
    identity: {registry: docs/entity_registry.yaml, aliases: docs/aliases.json}
    corrections: docs/corrections.yaml
    provenance_ranges: []
```

## Three authoring notes the GM should read before editing

1. **`docs/background/name_glossary.md` is working-reference by these globs, and that is
   correct but incomplete.** Incident 4 is that `check_consistency.py:61`
   (`_DEFAULT_CONFIG_DOCS = ["campaign_state", "world_state"]`) loads only *generated* docs
   and ignores the hand-curated glossary. This manifest makes the glossary visible and
   correctly labeled to *search*; it does not change what `check_consistency` loads. That
   remains a separate fix.
2. **Overlapping globs are expected, and reported.** `docs/*.md` (working reference) and
   `docs/*_extractions/**` (accelerator) can both match. Tiers are evaluated in the fixed
   order authoritative → accelerator → working_reference → staging, first match wins, and
   every additional match is recorded on the hit as `tier_ambiguous` and reported by
   `provenance check`. The tool never silently picks a winner without saying so
   (research [D8](../research.md#d8)).
3. **`.yaml` and `.json` are tiered working-reference, not left unclassified.**
   `search_extensions` includes them, so `docs/entity_registry.yaml`, `docs/aliases.json`,
   `docs/corrections.yaml` and `config/*.yaml` are searchable. Without an explicit glob
   they would all return as `unclassified` — technically correct under FR-013, but a large
   permanent block of unlabeled hits that `check`'s `unclassified-heavy` finding would
   flag forever. The identity stores genuinely *are* working reference, so they are
   declared as such. `config/*.yaml` is declared only for the three campaigns that have a
   `config/` directory (Phandalin, out-of-the-abyss, obelisk) — a glob matching nothing is
   legal but misleading.
