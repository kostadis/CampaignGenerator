# File Contracts: Authored File, Link Rulings, Citations, Draft / GM / Published Dossiers

## Authored file — `docs/npcs/authored/<slug>.authored.yaml`

`docs/npcs/authored/` also holds hand-built dossiers (`<slug>.md`, e.g. `gm-npc-build` output, which this feature reads only whole, for publishing). `<slug>` is the lowercase hyphenated canonical name.

GM-written. No tool overwrites one. `npc-compose --init` creates an empty one only when none exists.

```yaml
subject: Jimjar            # must equal the NPC's canonical subject (refused otherwise)
manual:                    # numbered by position: the first item is [manual 1]
  - Jimjar is a deep gnome, not a drow; the ch 12 summary misnames his people.
  - He has a standing bet with Eldeth about who reaches the surface first.
secrets: |
  Owes 400 gp to a Blingdenstone fence; the party doesn't know.
```

- Allowed keys: `subject` (required); `manual` (optional list of non-empty Markdown strings); `secrets` (optional Markdown string). Any other key is refused, and so is a `manual` that is not a list.
- **`manual` goes into the draft prompt**, numbered `[manual 1]`, `[manual 2]` and so on in list order. Re-ordering the list renumbers the edits and therefore changes the publish key.
- **`secrets` never goes into any prompt.** Compose copies it byte-for-byte into the GM dossier and nowhere else.

## Link rulings — added to 031's `canon.yaml`

```yaml
not_duplicates:            # unchanged (031)
  - {category: npc, a: Sarith, b: Sarith Kzekarit}
link_rulings:              # new (032), generic forms only
  - {form: Stool, ruling: safe}
  - {form: Spider, ruling: never}
```

- Each entry is exactly `{form, ruling}`, where `ruling` is `safe` or `never`. `form` is an exact, case-sensitive string.
- **Refused:** a ruling on a form that is ambiguous in this run, or a duplicate `form`.
- **Reported (non-blocking):** `link-ruling-unneeded` for a form that is neither generic nor ambiguous, and `stale-link-ruling` for a form that occurs nowhere in range.
- The file still cannot express a merge or an alias, because no entry names an entity.

## Evidence dossier — `<R>/evidence/<stem>.md`

```markdown
---
subject: Jimjar
type: npc
global: true
exclusion: null
aliases_used: [Jimjar]
first_seen: 3
last_seen: 70
chapters: [3, 4, 5, ...]
n_entries: 33
n_scenes: 71
n_moments: 17
range: 2-70
source_kind: summary_native_npc_link
---

# NPC — Jimjar

## Chapter 021

### Entry — Jimjar
- Source: docs/summaries/021-session-untitled.md (line 329)

<entry body verbatim>

### Scene 021.05 — Choosing the Path West (mentioned)
- Source: docs/summaries/021-session-untitled.md (line 140)
- Mention lines: 144, 151

<whole scene body verbatim>

### Moment (mentioned)
- Source: docs/summaries/021-session-untitled.md (line 201)
- Scene: none
- Mention lines: 202

<moment block verbatim>
```

## Draft dossier — `<R>/draft/<stem>.md` (model output, a draft)

```markdown
<!-- summary_native npc draft | npc: Jimjar | range: ch002-070 | run: 20261007T101500Z | draft_key: <sha256> | manual sha256: … | model: … | backend: … -->
<computed header, inserted by code — identical to the evidence frontmatter facts>

## Identity
Jimjar is a deep gnome [manual 1] …
## Personality and Motivations
## History with the Party
- Guides the party out of Velkynvelve's pens. [ch 004 / 004.02]
- Bets Eldeth he will reach the surface first. [manual 2]
## Last Observed State
As of chapter 070: "…" [ch 070 / entry]
## Relationships
## Notable Quotes
> "…" — Jimjar [ch 021 / moment]
## Arc-Score Candidates
- Candidate: "…" [ch 033 / 033.04]
```

## Citation grammar

```
citation   := "[ch " CHAPTER " / " target "]"
CHAPTER    := 3 digits
target     := SCENE_ID | "entry" | "moment"
manual     := "[manual " N "]"                (N = 1-based position in the authored `manual` list)
SCENE_ID   := 3 digits "." 2 digits        (its chapter part must equal CHAPTER)
```

- Several citations may appear in one bracket, separated by `; `, each written in full: `[ch 004 / 004.02; ch 005 / entry]`. A shortened part (`[ch 004 / 004.02; 004.03]`) is not a citation.
- Every bullet under `## History with the Party` must end with at least one citation, either a chapter citation or a `[manual N]`. A bullet without one is counted as `uncited`, except a label: a bullet with nested bullets under it needs no citation of its own when every nested bullet is cited.
- **Notable Quotes:** each `>` blockquote must be verbatim (quote marks and apostrophes compared as equal, reported as `typography-normalised`) somewhere in the NPC's evidence (entry, scene or moment), else `not-verbatim`. Each quote names its speaker as the evidence gives it and cites the item it comes from (`— Speaker [ch NNN / NNN.SS|entry|moment]`); quotes are about the NPC and may be spoken by anyone.
- **Manual-edit check (FR-018c):** every N from 1 to len(manual) must be cited at least once anywhere in the draft dossier. An uncited N is reported as `dropped`, with its text. An N outside that range is reported as `invalid`. The report states that the check confirms each edit was *used*, not that its meaning survived.

## GM dossier — `<R>/gm/<stem>.md` (composed, deterministic)

```markdown
<!-- summary_native npc gm | npc: Jimjar | draft sha256: … | authored sha256: … | composed sha256: … -->
<draft dossier, minus its provenance comment, or "_(not yet drafted)_">

## Secrets
<secrets, byte-for-byte, or "_(none authored)_">
```

A test asserts that the `secrets` text appears in no draft dossier and in no `runs/*/<stem>.user.md`.

## Published dossier — `docs/npcs/<slug>.md` (written only by `npc-publish`)

**From a GM dossier:**

```markdown
<!-- published by summary_native npc-publish | source: summary_native | npc: Jimjar | range: ch002-070 | draft run: 20261007T101500Z | draft sha256: … | authored sha256: … | verify: pass | published sha256: … -->
<GM dossier body, with every [manual N] rewritten to [GM]; chapter citations unchanged; ## Secrets included>
```

**From a hand-built dossier:**

```markdown
<!-- published by summary_native npc-publish | source: hand-built | path: docs/npcs/authored/eelrich-vane.md | sha256: … | verification: not applicable | published sha256: … -->
<the hand-built file, verbatim>
```

`verify: fail(forced)` marks a dossier published with `--force` over a failed verification, and `verify: unverified(forced)` one published with `--force` when no verdict exists. The verdict is read from `draft/<stem>.verify.md` first (a standalone `npc-verify` rewrites it last), then from the newest `runs/*/record.json`; with neither, the NPC is unverified and refused without `--force`. `published sha256` is the digest of everything below the header line; publishing compares it against `publish_log.json` to detect a hand-edit.

## Migration classification — `docs/npcs/migration_classification.yaml`

```yaml
campaign: toee
proposed_at_commit: c0b6ded9            # HEAD when --propose ran, or null outside git
entries:
  - path: eelrich-vane.md
    disposition: unknown                # GM sets: distilled | authored
    evidence:
      source_extracts_marker: false
      git: {added: {sha: 590a434c, date: 2026-06-22, subject: "feat(toee): session 20260614 + Eelrich Vane NPC and water-temple juggernaut statblock"}, later_commits: [], changed_since_added: false}
      sha256: …
  - path: hedrack.md
    disposition: distilled
    flags: [hand-edited]
    evidence: {source_extracts_marker: true, git: {added: {…}, later_commits: [{sha: f833b1c2, subject: "fix(toee): campaign-wide canon repair …"}], changed_since_added: true}, sha256: …}
```

`--apply` re-hashes every entry and refuses if any `sha256` differs from the file on disk.
