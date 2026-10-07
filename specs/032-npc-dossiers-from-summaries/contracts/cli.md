# CLI Contract: `summary_native npc-*` and the migration

All five subcommands extend the existing `summary_native` console script (`pipelines/summary_native/cli.py`). They resolve config after `parse_args`, the same way 031 does.

## Shared flags (spelled exactly as in 031, Principle XII)

`--summaries-dir`, `--since`, `--until`, `--out-root` (the 031 corpus root), `--registry`, `--canon`, `--config`. New: `--npc-root DIR`, default `docs/npcs/summary_native`, with precedence flag > `npc_dossiers.yaml npc_root` > schema default.

Precedence for everything shared with 031 is flag > `grounding.yaml summary_native.<key>` > default, using 031's `resolve.py`.

Every subcommand runs 031's full validation first and refuses on blocking problems (exit 1), as 031 FR-005b requires.

## `summary_native npc-link`

Deterministic. No model.

| Flag | Meaning |
|---|---|
| (shared) | |
| `--force` | Rewrite existing `evidence/` and `link_manifest.json` for the range |

- **Refuses (exit 2)** when:
  - the corpus for the range is missing or incomplete ("run `summary_native build`");
  - summaries or the registry changed since the build ("run `summary_native build --force`");
  - `canon.yaml link_rulings` holds a ruling on an ambiguous form (the message names the form and each `(type, canonical)` it collides with);
  - `canon.yaml` is malformed;
  - linked output exists and `--force` was not given.
- **Writes:** `<R>/link_manifest.json`, `<R>/link_report.{md,json}`, `<R>/evidence/<stem>.md` for **every** NPC corpus dossier (FR-012a).
- **Stdout:** a per-run summary: NPCs linked, total scenes and moments linked, and withheld forms by kind.
- **Stderr:** the run-end **warning** when any form is withheld: `warning: 3 ambiguous, 5 generic (unruled) name forms withheld from linking — see <R>/link_report.md`.
- **Exit:** 0 when linking succeeded, even with warnings.

## `summary_native npc-draft`

The only model step (GM ruling, 2026-10-06). One call per selected NPC, over its evidence dossier plus the numbered Manual edits from its authored file. Secrets never enter the prompt (they are read through `load_manual()`, which does not return them). After each NPC, it runs verification, including the manual-edit check (FR-018c), and composes the GM dossier. A skipped NPC is still re-composed, so a Secrets-only edit takes effect with no model call.

Model calls per selected NPC: one (`--mode one-shot`), or one per chunk plus one (`--mode chunked`, the default; research R17).

| Flag | Meaning |
|---|---|
| (shared) | |
| `--name NAME…` | Narrow to these global NPCs. A name that is not a global NPC refuses, with the reason (`not in registry` / `registry scope …: local`) |
| `--recent-chapters N` / `--recurring-min N` | Narrow with 031 `select.py` rules (applied within the global NPCs) |
| `--all` | Explicitly every global NPC with evidence in range. Mutually exclusive with the narrowing flags |
| `--model`, `--max-tokens`, `add_backend_args` flags | Standard (`--backend anthropic\|dgx\|openrouter\|claude-code\|codex-cli`, `--endpoint`, …). Backend and model default from `npc_dossiers.yaml draft.backend` / `draft.model` (`dgx` / `qwen3.8-flash-next`). The draft model default applies only when the resolved backend is the draft default; any other backend without `--model` uses the repo default (`CAMPAIGN_MODEL`, else `claude-fable-5`) |
| `--mode chunked\|one-shot` | Drafting mode (default `npc_dossiers.yaml draft.mode`, which defaults to `chunked`) |
| `--chunk-chars N` | Chunk size limit in characters for chunked mode (default `draft.chunk_chars`, 60000) |
| `--dump-only` | Write prompts, the selection and the record. No model call. Index untouched. In chunked mode, writes the map prompts only (the reduce prompt needs map output) |
| `--force` | Re-draft even when the draft key is unchanged |

With no narrowing flag and no `--all`, the CLI behaves as `--all` (FR-012 default). The UI always sends one of them explicitly.

- **Refuses (exit 2)** when:
  - there is no registry ("no global NPCs are declared; build a registry with `registry init` / `registry import-inventory`", FR-012b);
  - link output is missing or stale against the corpus manifest ("run `summary_native npc-link --force`");
  - summaries changed since the build;
  - the selection is empty (prints the counts per exclusion reason);
  - a `--name` is ineligible.
- **Writes:** `<R>/runs/<stamp>/…`, `<R>/draft/<stem>.md` (or `.incomplete.md`), `<R>/draft/index.json`, `<R>/draft/<stem>.verify.md`.
- **Stdout:** per NPC, `drafted | skipped (unchanged) | incomplete (missing: …) | failed`, then verification totals.
- **Exit:**
  - 0: all selected NPCs drafted or skipped;
  - 3: any incomplete;
  - 4: a model call failed (the remaining NPCs are not attempted, and the record notes where it stopped).
  - A dropped manual edit is a verification failure: it is reported per NPC (`warning: Jimjar: manual edit 2 dropped — "…"`) but, like other verification results, does not change the exit code.
  - Verification failures do **not** change `npc-draft`'s exit code; they are reported. Gate on them with `npc-verify`.

## `summary_native npc-verify`

Deterministic. No model. Never edits drafts.

| Flag | Meaning |
|---|---|
| (shared) | |
| `--name NAME…` | Limit to these NPCs (default: every `draft/<stem>.md` in range) |

- **Writes:** `<R>/draft/<stem>.verify.md` for each NPC checked.
- **Stdout:** per NPC, `pass | fail (invalid N, outside-evidence N, not-found N, citation-mismatch N, uncited N, manual-dropped N, manual-invalid N)`, plus advisories `typography-normalised N`, `status-claim-unsupported N` and `placeholder-speaker N`. `not-found`: a quoted span (a Notable Quote or any `"…"` span elsewhere) is not verbatim in this NPC's evidence. `citation-mismatch`: a Notable Quote is in the evidence but not in the item its citation names, or has no citation, then totals.
- **Stderr:** `warning: <NPC>: manual edit N dropped — "…"` for each dropped manual edit (also printed by `npc-draft`).
- **Exit:**
  - 0: all pass;
  - **5**: any fail;
  - 2: refusal (no draft dossiers in range; no evidence for a named NPC).

## `summary_native npc-compose`

Deterministic. No model.

| Flag | Meaning |
|---|---|
| (shared) | |
| `--name NAME…` | Compose GM dossiers for these NPCs (default: every NPC with a draft dossier or an authored file). Use after editing Secrets only; no model call |
| `--init NAME…` | Create an empty `docs/npcs/authored/<slug>.authored.yaml` for each name. Refuses per name if the file exists; the other names are still created, and the exit is 2 if any name refused. Composes nothing |

- **Refuses (exit 2)** when:
  - an authored file is malformed, or has a `subject` that does not match its stem;
  - a named NPC has neither a draft dossier nor an authored file.
- **Writes:** `<R>/gm/<stem>.md` (draft dossier + Secrets).
- **Stderr:** `warning: <file> had an unrecorded hand-edit; discarded (put corrections in docs/npcs/authored/<slug>.authored.yaml)` for each composed file whose content differed from what its recorded sources produce.
- **Exit:** 0 on success.

## `summary_native npc-publish`

Deterministic. No model. The only writer of `docs/npcs/<slug>.md` (FR-031).

| Flag | Meaning |
|---|---|
| (shared) | `--since/--until` select the range whose GM dossiers are published |
| `--name NAME…` | Publish these NPCs |
| `--all` | Every NPC with a GM dossier in range |
| `--authored-all` | Every hand-built `docs/npcs/authored/<slug>.md` (FR-031c), e.g. after the migration |
| `--source summary_native\|hand-built` | Required when an NPC has both a GM dossier and a hand-built dossier |
| `--force` | Publish despite a failed verification, a target this feature did not publish, or a hand-edited target |

- **Refuses (exit 2)** when:
  - no selection was given;
  - a name has no GM dossier and no hand-built dossier;
  - an NPC has both sources and no `--source`;
  - two NPCs map to one slug.
  - Without `--force`, it also refuses on a failed verification, a foreign target (no `published by summary_native` header), or a target whose sha256 differs from `publish_log.json` (hand-edited; the message points to `docs/npcs/authored/<slug>.authored.yaml`).
- **Writes:** `docs/npcs/<slug>.md` and `docs/npcs/summary_native/publish_log.json`. For a summary-native source, every `[manual N]` becomes `[GM]` and chapter citations are kept. A hand-built source is copied verbatim. Both get a provenance header (`contracts/files.md`).
- **Stdout:** per NPC, `published (summary_native|hand-built) | refused (<reason>)`.
- **Exit:** 0 when all selected NPCs published; 2 on any refusal (the NPCs that passed are still published, and each refusal is listed).

## Migration: `python -m server.migrate_npc_dossiers`

| Flag | Meaning |
|---|---|
| `--campaign-dir DIR` | Required. The campaign root |
| `--propose` | Write `docs/npcs/migration_classification.yaml`: every entry directly in `docs/npcs/` (except `distilled/`, `summary_native/`, `authored/`) with a proposed `disposition` (`distilled` / `authored` / `unknown`) and its evidence (`source_extracts:` marker; git adding commit, later commits, changed-since-added). Moves nothing |
| `--apply` | Follow the GM-edited classification file: `distilled` entries go to `docs/npcs/distilled/` and `authored` entries to `docs/npcs/authored/`, byte-identical (`os.replace` per entry), then rewrite config paths |
| `--force` | With `--apply`: allow replacing same-named entries already in `distilled/` or `authored/` |

Exactly one of `--propose` and `--apply` is required.

- **Proposal rules:**
  - marker present → `distilled`;
  - distilled sidecars and state files (`.new_notes.*`, `.dedup_state.json`, `.sidecar_merge_state.json`, `merged_sidecars/`) → `distilled`;
  - otherwise → `unknown`.
  - Commit-message wording is shown as evidence only, never used to decide.
  - A `distilled` file changed since it was added is flagged `hand-edited`.
  - Outside a git repository, the git evidence is `unavailable`.
- **`--apply` refuses (exit 1, nothing moved)** when:
  - any entry is `unknown`;
  - the classification file is missing or malformed;
  - an entry no longer matches the disk (file added, removed or changed since `--propose`);
  - a target exists and `--force` was not given.
- **Config rewrites** are comment-preserving and exact-value only:
  - `<config>/grounding.yaml` `planning.dossiers.dossier_dir` becomes `docs/npcs/distilled/`;
  - `<config>/planning.yaml` `npcs[].dossier` values follow their file's disposition.
- **Reports but does not change:**
  - config values pointing outside `docs/npcs/`;
  - `~/src/campaigns/provenance.yaml` globs mentioning `docs/npcs/`;
  - external skills that use `docs/npcs/` (`gm-npc-build`, see kostadis/campaigns#370; `/dossier-merge`, `vtt-spell-pass` and `consistency-check`).
- **Closing message:** says the skills see no NPCs until `summary_native npc-publish --authored-all` republishes the hand-built ones.
- **Idempotent:** on a migrated campaign, `--propose` prints `nothing to classify` and leaves the classification file as the record.
- **Re-propose keeps rulings:** when a classification file already exists, `--propose` carries over the `disposition` of every entry whose `sha256` is unchanged, so a re-run never discards a GM decision. Changed or new entries get a fresh proposal.
- **`--apply` with nothing loose:** if `docs/npcs/` holds no unclassified entry and there is no classification file (a config-only campaign such as Phandalin or obelisk), `--apply` performs the config rewrites only. If entries are loose and there is no classification file it refuses and says to run `--propose`.
- **`--apply` is resumable:** an entry that is no longer at its source but sits at its target with a matching `sha256` counts as already moved, so a repeated run, or a run after a partial failure, completes the rest. `--force` replaces files but never a directory (for example `merged_sidecars/`).
- **Exit:** 0 ok; 1 error (`Error:` on stderr; `--apply` stops at the first failed move and lists what moved).
