# Quickstart: Validating Batched Scene Extraction

**Feature**: 013-batched-scene-extraction | **Date**: 2026-08-22

Runnable scenarios that prove the feature works. Each maps to success criteria
in [spec.md](./spec.md). Details live in [contracts/](./contracts/) and
[data-model.md](./data-model.md) — not duplicated here.

---

## Prerequisites

```bash
# The worktree's own checkout must be importable — the editable-install .pth
# hardcodes the MAIN checkout, so `import campaignlib` can silently resolve
# there. tests/conftest.py inserts REPO_ROOT for pytest; verify for ad-hoc runs:
cd /home/kroussos/src/CampaignGenerator-token-util
python -c "import campaignlib, pathlib; print(pathlib.Path(campaignlib.__file__).parent)"
# MUST print .../CampaignGenerator-token-util/campaignlib
```

```bash
# Console scripts resolve from the SERVER's venv, not $PATH:
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
```

**Test session** — a session with a reviewed summary, a VTT, and a known scene
count. `~/Phandalin/Phandalin/summaries/20260811/` is the calibration session
(8 scenes, 148 KB VTT, ~23K tokens of generated output).

---

## Scenario 1 — One transcript, one call *(SC-001, SC-001a)*

```bash
cd ~/Phandalin/Phandalin/summaries/20260811
mkdir -p /tmp/sx_batched
scene_extract *.transcript.cleaned.vtt \
  --summary session-summary.md \
  --output-dir /tmp/sx_batched \
  --batch-scenes \
  --backend claude-code --model claude-opus-5
```

**Expect**: report states `Requested: 8`, `-> 1 group`, `Transcript sent: 1x
(per-scene mode would have sent 8x)`; 8 files in `/tmp/sx_batched`.

**Fails if** transmissions > 1 on a session projecting under 32K, or file count
≠ 8.

---

## Scenario 2 — Files are structurally identical to per-scene *(SC-006)*

```bash
mkdir -p /tmp/sx_perscene
scene_extract *.transcript.cleaned.vtt --summary session-summary.md \
  --output-dir /tmp/sx_perscene --backend claude-code --model claude-opus-5

for f in /tmp/sx_batched/*.md; do
  diff <(sed -n '1,/^## Verbatim moments$/p' "$f") \
       <(sed -n '1,/^## Verbatim moments$/p' "/tmp/sx_perscene/$(basename $f)") \
    || echo "STRUCTURE DIFF: $(basename $f)"
done
```

**Expect**: no output. Everything above `## Verbatim moments` is assembled
locally by `format_scene_output` and must match exactly. Only the moments differ.

---

## Scenario 3 — Force and skip-if-exists *(SC-005a–d)* ⚠️ the easy one to get wrong

```bash
# 3a — partial session: only the missing scenes are REQUESTED
rm /tmp/sx_batched/0{6,7,8}_*.md
scene_extract … --output-dir /tmp/sx_batched --batch-scenes
```

**Expect**: `Already extracted: 5`, `Requested: 3`, and a projected output
roughly **three-eighths** of a full run's — not equal to it.

**This is the regression to watch for.** A build that sends all 8 and writes 3
produces correct files while spending the full projection (FR-008a). Read the
*projected output* line, not the file count.

```bash
# 3b — everything present, no force: ZERO calls
scene_extract … --output-dir /tmp/sx_batched --batch-scenes
```

**Expect**: "All scenes already extracted", `Transcript sent: 0x`, exit 0. No
API call at all (SC-005b).

```bash
# 3c — force: all 8 requested, existing snapshotted
scene_extract … --output-dir /tmp/sx_batched --batch-scenes --force
ls /tmp/sx_batched/*.prev | wc -l
```

**Expect**: `Requested: 8`; `.prev` files for every scene whose content changed
(unchanged content → no snapshot, per FR-014).

```bash
# 3d — mode crossover
rm -rf /tmp/sx_mixed && mkdir /tmp/sx_mixed
scene_extract … --output-dir /tmp/sx_mixed              # per-scene, interrupt after ~3
scene_extract … --output-dir /tmp/sx_mixed --batch-scenes
```

**Expect**: 8 files, and the batched run requests only the ones the per-scene run
did not finish (SC-005d).

---

## Scenario 4 — Verbatim fidelity *(SC-003, SC-004)* — the ship gate

```bash
sd_verify_quotes --scenes /tmp/sx_perscene \
  --vtt *.transcript.cleaned.vtt --out /tmp/verify_perscene.md
sd_verify_quotes --scenes /tmp/sx_batched \
  --vtt *.transcript.cleaned.vtt --out /tmp/verify_batched.md
```

**Expect**: the batched run's **`verified` (exact)** rate is within 5 points of
per-scene (SC-003), and no scene loses > 20% of its moments (SC-004).

**Read the exact rate, not the total.** A run that converts `verified` quotes
into `near` ones is a regression even with an identical count — `near` is "an
edit happened", never "safe": 0.92 can be a meaning-changing misquote while 0.94
is a harmless disfluency, and no threshold separates them (research D10).

**Check the tail specifically** (SC-004): a model rationing one budget across N
scenes thins out the *last* scenes. Compare per-scene moment counts in order —
a uniform 10% drop and a 40% drop concentrated in scenes 7–8 are different
failures, and only the second says batching is the cause.

---

## Scenario 5 — Partial response is survivable *(SC-005)*

Unit-level; no API call. Feed the splitter a response with scenes 1–5 closed and
scene 6 opened but not closed:

**Expect**: 5 files written; scene 6 `incomplete`, 7–8 `absent`; all three named;
exit **3**; a re-run without `--force` requests exactly those three.

**Also assert**: a scene whose section closes with an *empty* body is reported
`scenes_empty` and **not written** — otherwise the next run's skip-if-exists
treats unfinished work as done (data-model §5).

---

## Scenario 6 — Grouping and the ceiling *(SC-001b, SC-009)*

```bash
scene_extract … --batch-scenes --batch-max-tokens 8000   # force a split
scene_extract … --batch-scenes --batch-max-tokens 64000  # force one call
```

**Expect**: the low ceiling splits into ⌈projection ÷ 8000⌉ groups and says the
projection was exceeded; the high ceiling gives exactly one group. Same session,
same scenes, only the ceiling differs (SC-009).

Also assert (unit): grouping is deterministic — same inputs, same grouping every
time (DM-10) — and a single scene projecting over the ceiling forms a group
alone rather than being refused (DM-9).

---

## Scenario 7 — The metered path is untouched *(SC-008)*

```bash
python -m pytest tests/test_scene_extract.py tests/test_batch_api.py \
                 tests/test_session_editor_config_service.py -q
```

**Expect**: all green, including
`test_extract_tokens_defaults_to_scene_extract_cli_default` — `extract.tokens`
stays `8192` and still matches the CLI default (FR-017b).

Then confirm a per-scene metered run is unchanged: same request count, same
`cache_system=True`, same files.

---

## Scenario 8 — Editor wiring *(FR-007a, DM-20)*

1. Open the Session Doc Editor with `backends.active: claude-code`.
   **Expect**: "Batch scenes into one call" **checked** by default.
2. Switch to `anthropic`. **Expect**: **unchecked**.
3. Uncheck it on the subscription and run. **Expect**: streamed command shows
   `--no-batch-scenes` — the override reaches the subprocess.
4. Don't touch it and run. **Expect**: `--batch-scenes` appears explicitly; the
   command line is fully explicit either way (DM-19).
5. Check `KnobDrawer` ② : the batched token field is present, the per-scene help
   says "per-scene mode", and the stale *"always forwards `--force`"* sentence is
   gone (research D12).

---

## Full regression

```bash
cd /home/kroussos/src/CampaignGenerator-token-util && python -m pytest tests/ -q
```

Watch particularly `tests/test_retrieve_render_isolation.py`,
`tests/test_no_prefix_identity.py` and `tests/test_layering.py` — the standing
structural guards.
