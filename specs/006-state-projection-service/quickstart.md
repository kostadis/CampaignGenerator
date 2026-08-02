# Quickstart: validating State-Projection Rendering as its own service

**Feature**: 006-state-projection-service | **Date**: 2026-08-01

Runnable checks that prove the feature works end to end. Details of shapes and flags live in
[data-model.md](./data-model.md) and [contracts/](./contracts/) — not repeated here.

## Prerequisites

```bash
cd /home/kroussos/src/CampaignGenerator-phase1

# 1. The editable install must point at THIS tree, not the main checkout.
python -c "import campaignlib; print(campaignlib.__file__)"
#   → must print .../CampaignGenerator-phase1/campaignlib/__init__.py
#   If it prints .../CampaignGenerator/..., the .pth is shadowing the worktree and a green
#   run proves nothing (research: Environment notes).

# 2. Console scripts resolve from the venv the server runs under.
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
```

Two live campaigns exercise different branches:

| Campaign | Property | Exercises |
|---|---|---|
| `~/out-of-the-abyss/out-of-the-abyss` | 62 chapters, has `merged_dossiers/` | the curated path, behaviour-identical check |
| `~/Phandalin/Phandalin` | **no** `merged_dossiers/` | the `inputs.dossiers_fallback` branch |

Both have drafts at the pre-move locations, so both hit the legacy gate on first run — that is
expected, and is check 2 — clear it before running checks 3 and 4.

## 1. Automated suite

```bash
python -m pytest tests/test_projection_config.py tests/test_projection_isolation.py \
                 tests/test_projection_routes.py tests/test_fact_record_contract.py \
                 tests/test_config_location.py tests/test_layering.py \
                 tests/test_grounding_sections.py tests/test_event_spine.py \
                 tests/test_thread_registry.py
python -m pytest tests/            # then the whole suite
cd frontend && npx vue-tsc --noEmit && npx vite build && cd ..
```

Expected: all pass. `test_config_location.py` must stay green **with** `projections.yaml` added to
`CONFIG_FILENAMES` — proof the new document has exactly one declared location.

## 2. Legacy-draft gate (FR-007b, SC-011)

With `docs/campaign_state_draft.md` still present from before the move:

```bash
grounding_sections build --doc campaign_state
```

Expected: non-zero exit naming the file and stating that moving or deleting it clears the gate. The
file is **not** moved and **not** deleted. Then:

```bash
mkdir -p docs/_pre006 && mv docs/campaign_state_draft.md docs/_pre006/
grounding_sections build --doc campaign_state    # now proceeds
```

## 3. Behaviour-identical with no config file (SC-006, FR-012)

In out-of-the-abyss, with no `config/projections.yaml`:

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
grounding_sections list --doc campaign_state > /tmp/after_list.txt
diff /tmp/before_list.txt /tmp/after_list.txt     # captured before the change
grounding_sections build --doc campaign_state     # deterministic sections only, no --backend
```

Expected: `list` output byte-identical; `build` reports `rebuilt: nothing` and every section `fresh`.
Zero tokens spent — the run makes no model call without `--backend` (FR-019).

## 4. Non-interference (SC-001, User Story 1)

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
sha256sum docs/*_draft.md docs/ensemble/drafts/*_draft.md 2>/dev/null > /tmp/before.sha
grounding_sections build --doc campaign_state
sha256sum -c /tmp/before.sha        # every pre-existing draft unchanged
ls docs/projections/                 # the new output landed here
```

Expected: every listed hash verifies; new output appears only under `docs/projections/`.

## 5. Single-declaration override (SC-005, FR-009 — the bug this closes)

```bash
cp docs/ensemble/events.jsonl /tmp/events_alt.jsonl
cat >> config/projections.yaml <<'YAML'
stores:
  events: /tmp/events_alt.jsonl
YAML
grounding_sections list  --doc campaign_state     # recent_events → stale
grounding_sections build --doc campaign_state     # re-renders from the new path
event_spine render --output /tmp/re.md            # follows the same value
```

Expected: the freshness check **and** the read both follow the override, so the section goes stale
and re-renders. Before this feature the hash came from one literal and the content from another —
this is the regression check for that split.

**Teardown** (check 3 depends on there being no config file): `rm config/projections.yaml
/tmp/events_alt.jsonl` and rebuild once to restore the stamps.

## 6. Dossier fallback, reported (FR-024a, edge case)

```bash
cd ~/Phandalin/Phandalin
grounding_sections build --doc planning --npcs <slug> --backend dgx --endpoint <url> --model <m>
```

Expected: the outlook section renders from `inputs.dossiers_fallback` and the output **says so**.
Silent fallback is the failure.

## 7. Sibling independence (SC-003, User Story 2)

In a scratch campaign where only extraction and bundling have run:

```bash
grounding_sections build --doc campaign_state     # succeeds — spine + copy sections
grounding_sections build --doc world_state --backend …   # all four synthesis sections
```

Expected: both succeed without Dossier Synthesis having run. With bundling skipped as well,
`world_state` skips its four sections with `no dossiers matched` and exits zero.

## 8. Empty selection refuses (Constitution X, FR-013)

```bash
curl -N 'http://127.0.0.1:5000/api/projections/run/build?doc=campaign_state'
```

Expected: `400`. No section list means nothing was chosen — never "all".

## 8b. The retired ensemble keys (research D15) — expected breakage

Both live campaigns carry `paths.recent_events_out` in `config/ensemble.yaml`. After this change:

```bash
curl localhost:5000/api/ensemble/config          # → 400 naming recent_events_out
```

Fix by hand, once per campaign — remove `recent_events_out` from `paths:` and
`recent_events_window` from `tuning:` if present. Then:

```bash
curl localhost:5000/api/ensemble/config          # → 200
curl -N 'localhost:5000/api/projections/run/recent-events?corpus=docs/ensemble/per_chapter/*/merged.json'
```

Expected: the ensemble page recovers; recent-events now runs from the projections route and writes
`output.recent_events`. The server must still boot with the stale key present — only that one page
errors.

## 9. Config isolation (FR-010)

```bash
sha256sum config/ensemble.yaml config/grounding.yaml > /tmp/cfg.sha
curl -X PUT localhost:5000/api/projections/config \
     -H 'content-type: application/json' \
     -d '{"stores":{"events":"docs/ensemble/events.jsonl"}}'
sha256sum -c /tmp/cfg.sha
curl -X PUT localhost:5000/api/projections/config -d '{"stores":{"nope":"x"}}'   # → 400
```

## 9b. Checkpoints unchanged (FR-020, FR-021, FR-022, SC-009)

```bash
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
thread_registry set-status --id <id> --status resolved --chapter <n>
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'   # re-propose
```

Expected: the ruling survives the re-propose (FR-021), no proposal advances without one (FR-020,
SC-009 — zero automated promotions in the whole run), and summary-map approval, the lineage report
and draft promotion all still work from the CLI unchanged (FR-022).

## 10. UI (User Story 4)

Open `/grounding/projections`. Expected: staleness table with per-section state and the provenance
column; rebuilding one section leaves the others untouched; the selection panel makes any
cost-bearing run explicit; the rebuilt file is present on disk and identical to what the CLI
produces (FR-022a).
