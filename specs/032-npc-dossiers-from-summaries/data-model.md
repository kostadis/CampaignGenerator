# Data Model: Summary-Native NPC Dossiers (032)

All paths are relative to the campaign root. `<slug>` = the lowercase hyphenated canonical name, used for everything directly in `docs/npcs/` and in `docs/npcs/authored/`. `<R>` = `docs/npcs/summary_native/ch<since:03d>-<until:03d>`. `<stem>` = the 031 corpus dossier stem (`npc_<slug>[_<hash8>]`).

## In-memory entities (Python, frozen dataclasses)

### NameForm
| Field | Type | Notes |
|---|---|---|
| `text` | str | Exact string, case preserved |
| `owner` | `(type, canonical)` | The entity it names, set only when unambiguous |
| `sources` | tuple[str] | `heading` and/or `registry` |
| `status` | enum `linkable` \| `ambiguous` \| `generic` \| `generic-safe` \| `generic-never` | Derived from the R2 ambiguity index, the R4 word list and canon `link_rulings` |
| `collides_with` | tuple[(type, canonical)] | Non-empty iff `ambiguous` |

Rules:
- `ambiguous` takes precedence over `generic`.
- A `link_rulings` entry on an `ambiguous` form makes the run refuse (exit 2).
- Linkable statuses are `linkable` and `generic-safe`.

### LinkedItem
| Field | Type | Notes |
|---|---|---|
| `kind` | `scene` \| `moment` | |
| `chapter` | int | From the filename prefix (031 authority) |
| `scene_id` | str \| None | `NNN.SS`. `None` for a moment, rendered as `none` |
| `title` | str \| None | Scene title |
| `source_file` | str | POSIX, relative to the campaign root |
| `line` | int | First line of the item |
| `text` | str | The full item verbatim (whole scene per FR-004, or the whole moment block) |
| `mention_lines` | tuple[int] | File lines where a linkable form of this NPC matched |
| `forms_matched` | tuple[str] | The forms that matched, sorted |

### EvidenceDossier
| Field | Type | Notes |
|---|---|---|
| `stem`, `subject` | str | `subject` = registry canonical, or the heading when there is no registry match |
| `global` | bool | R1: registry `npc` + `persistent`, and not a `players.yaml` player character |
| `exclusion` | str \| None | Why it is not eligible for drafting (`not in registry`, `registry scope chapter-12: local`, `player character (players.yaml)`) |
| `entries` | tuple[Observation] | 031 observations (`## NPCs` entries) |
| `items` | tuple[LinkedItem] | Ordered (chapter, scene_id or ∞ for moments, line) |
| `header` | ComputedHeader | |

Ordering within a chapter (FR-006): entries, then scenes in id order, then moments in line order.

### ComputedHeader (FR-008; also inserted into the draft dossier, FR-015)
`canonical`, `aliases_used` (forms that actually matched or headed an entry, sorted), `type`, `first_seen`, `last_seen`, `chapters` (sorted ints, including mention-only chapters), `n_entries`, `n_scenes`, `n_moments`, `range`.

### DraftSelection
`range`, `mode` (`all` \| `narrowed`), `named`, `recent_chapters`, `recurring_min`, `included: [{stem, subject, reason}]`, `excluded: [{stem|name, reason}]`. Exclusion reasons: `not in registry`, `registry scope …: local`, `no evidence in range`, `narrowed out`. An empty `included` makes the run refuse.

### DraftRecord (per run, FR-026)
`run_id`, `range`, `backend`, `model`, `max_tokens`, `corpus_manifest_sha256`, `link_manifest_sha256`, `registry_sha256`, `canon_sha256`, `wordlist_sha256`, `template_sha256`, `selection` (reference), and `npcs: {stem: {draft_key, evidence_sha256, manual_sha256, status: published|skipped-unchanged|incomplete|failed, problems[], verify: {verdict, counts}}}`. `manual_sha256` is the digest of the numbered Manual edits only, never of Secrets, plus `started` and `finished`.

### VerificationResult (per draft dossier)
`stem`, `citations: [{text, draft_line, status: ok|invalid|outside-evidence}]`, `quotes: [{text, draft_line, status: verbatim|typography-normalised|not-found, source?}]`, `uncited_history_bullets: [draft_line]`, `manual: [{n, text, status: cited|dropped, cited_at: [draft_line]}]`, `invalid_manual_citations: [{text, draft_line}]`, `advisories: [{kind: status-claim-unsupported, word, draft_line}]` (never affects the verdict), and `verdict: pass|fail` with totals. `pass` means zero invalid, zero outside-evidence, zero not-found, zero uncited, zero dropped and zero invalid manual citations. The report states that a `cited` manual edit was used, not that its meaning survived.

### AuthoredFile
`subject` (str, required), `manual` (list of non-empty str, optional; item N is cited as `[manual N]`), `secrets` (str, optional). Strict: any other key is refused. Drafting reads it only through `npc_authored.load_manual()`, which returns `manual` and never `secrets`.

### PublishedDossier
`slug`, `source` (`summary_native` \| `hand-built`), `range` and `draft_run` (summary_native only), `source_sha256`, `authored_sha256`, `verify` (`pass` \| `fail(forced)` \| `not applicable`), `published_sha256`. Recorded in the header and in `publish_log.json`.

### ClassificationEntry (migration)
`path`, `disposition` (`distilled` \| `authored` \| `unknown`), `flags` (`hand-edited`), `evidence` (`source_extracts_marker`, `git.added`, `git.later_commits`, `git.changed_since_added`, `sha256`). `--apply` refuses while any entry is `unknown` or any `sha256` mismatches the disk.

## Files on disk

| Path | Written by | Deterministic | Notes |
|---|---|---|---|
| `docs/summary_native/ch…/` | 031 `build` | yes | **Read-only to this feature** |
| `<R>/link_manifest.json` | `npc-link` | yes | `{kind: "npc_link", range, corpus_manifest_sha256, registry_sha256, canon_sha256, wordlist_sha256, evidence: {stem: sha256}}` |
| `<R>/link_report.md` / `.json` | `npc-link` | yes | Withheld forms (kind, collisions, ruling status, every `file:line`), `stale-link-ruling`, `link-ruling-unneeded`, heading-less mentions. Regenerated each run |
| `<R>/evidence/<stem>.md` | `npc-link` | yes | Frontmatter = ComputedHeader + `global`/`exclusion`. Body: per chapter, the entry, then `### Scene NNN.SS — Title (mentioned)` with source line and the verbatim text (mention lines prefixed `▸ ` in a parallel "mention lines" list, never by altering the text), then moments |
| `<R>/draft/<stem>.md` | `npc-draft` | no (model) | Provenance comment, computed header, outline sections |
| `<R>/draft/<stem>.incomplete.md` | `npc-draft` | no | Missing-section output, never a draft |
| `<R>/draft/<stem>.verify.md` | `npc-draft`, `npc-verify` | yes | Given the same draft |
| `<R>/draft/index.json` | `npc-draft` | yes | `{stem: {draft_key, run_id}}`, last successful draft only |
| `<R>/runs/<stamp>/` | `npc-draft` | no | `selection.json`, `record.json`, `<stem>.system.md`, `<stem>.user.md`, `<stem>.out.md`, `verify.json`; in chunked mode also `<stem>.mapNN.{system,user,out}.md`, `<stem>.reduce.{system,user,out}.md`, `<stem>.drops.md` |
| `<R>/gm/<stem>.md` | `npc-draft` (for each NPC it drafts or skips), `npc-compose` | yes | The draft dossier, then `## Secrets` with the authored Secrets byte-for-byte. A missing part reads `_(not yet published)_` / `_(none authored)_` |
| `docs/npcs/<slug>.md` | `npc-publish` only | yes | The published dossier (FR-031). Provenance header + GM dossier with `[manual N]`→`[GM]`, or a hand-built file verbatim |
| `docs/npcs/summary_native/publish_log.json` | `npc-publish` | yes | `{slug: {source, range, run, published_sha256, published_at}}` |
| `docs/npcs/authored/<slug>.md` | **GM** / `gm-npc-build` | — | Hand-built dossier. Read whole by `npc-publish` only. Never written by this feature |
| `docs/npcs/migration_classification.yaml` | migration `--propose`; GM edits | yes (for a given repo state) | The proposal plus the GM's dispositions. Kept as a record after `--apply` |
| `docs/npcs/authored/<slug>.authored.yaml` | **GM** (`npc-compose --init` creates empty ones only) | — | Never overwritten by any tool |
| `docs/npcs/distilled/**` | migration (once) | — | Never written by this feature's stages |

GM dossiers carry a header comment with the sha256 of each source. `npc-compose` compares an existing composed file against what it would write. A mismatch that is not explained by changed sources is reported as `unrecorded hand-edit (discarded)` (FR-018b) before the file is overwritten.

## State transitions — draft dossier per NPC

```
(no evidence) ──npc-link──▶ evidence present
evidence present ──npc-draft──▶ drafted          (index.json updated; GM dossier composed)
                              └─▶ incomplete      (index unchanged; previous draft kept)
                              └─▶ failed          (exit 4; index unchanged)
drafted ──evidence/Manual edits/prompt/backend/model change──▶ stale ──npc-draft──▶ drafted
drafted ──Secrets-only change──▶ npc-compose (or npc-draft, which skips) ──▶ GM dossier re-composed, no model call
drafted ──unchanged──npc-draft──▶ skipped-unchanged   (--force ⇒ re-draft)
drafted ──npc-verify──▶ verified pass | verified fail   (draft never modified)
verified pass ──npc-publish (GM)──▶ published to docs/npcs/<slug>.md   ([manual N] → [GM]; provenance header)
verified fail ──npc-publish──▶ refused   (--force ⇒ published, failure recorded in the header)
published ──hand-edit in docs/npcs──npc-publish──▶ refused (--force ⇒ overwritten)
```

## Validation rules (traceability)

| Rule | Spec |
|---|---|
| Forms are only headings plus exact same-type registry strings, matched case-sensitively on word boundaries | FR-002 |
| Ambiguous forms cannot be ruled. Generic forms are rulable `safe`/`never`. Every withheld form produces a warning and a `link_report` entry | FR-003, FR-003a |
| Generic = single token in the pinned word list. The list's sha256 is recorded | FR-003b |
| A linked scene is the whole scene verbatim, with mention lines identified | FR-004 |
| Linked items are labelled "mentioned", never "present" | FR-005 |
| Only `global` NPCs can be drafted. With no registry, drafting refuses | FR-012, FR-012b |
| Drafting reads only the Manual edits from `docs/npcs/authored/`. Secrets never reach a prompt | FR-013, FR-018a |
| Publishing is explicit, deterministic and refuses on failed verification, foreign targets and hand-edited targets without `--force`. It rewrites `[manual N]` to `[GM]` | FR-031, FR-031a, FR-031b |
| Every manual edit is cited `[manual N]`; uncited ones are reported as dropped | FR-018c |
| The GM dossier reproduces Secrets byte-for-byte. The draft dossier never contains them | FR-018b |
| Nothing is written under `docs/npcs/distilled/`, `docs/npcs/authored/` or the 031 corpus. Only `npc-publish` writes directly in `docs/npcs/` | FR-022, FR-022a |
| The migration proposes from evidence. The GM's classification decides, and `unknown` blocks `--apply` | FR-022b |
