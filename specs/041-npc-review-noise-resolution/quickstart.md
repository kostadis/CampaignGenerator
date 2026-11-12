# Quickstart / Validation: NPC Review Noise Resolution (041)

Run everything from the worktree with `PYTHONPATH` pinned, so the main checkout's editable install cannot shadow the branch (research R13):

```bash
WT=/path/to/wt621
export PYTHONPATH=$WT
python -c "import pipelines; print(pipelines.__file__)"   # must print $WT/pipelines/__init__.py
```

## 1. Unit and fixture suites

```bash
python -m pytest tests/test_summary_native_noise.py \
                 tests/test_summary_native_review_verification_adapter.py \
                 tests/test_summary_native_npc_verify.py \
                 tests/test_summary_native_review_noise_cli.py \
                 tests/test_summary_native_no_llm.py -q
```

Expected: all pass. The fixture suite reproduces every example in #617 and #618. Each class has a positive case and a boundary true positive (FR-019).

## 2. Full suite

```bash
python -m pytest tests/ -q
```

## 3. End-to-end on a small campaign fixture

1. Build a review from a fixture draft set, using the existing `review create` path the tests already use.
2. `summary_native review noise <review> --json`: classes appear in precedence order, and the counts match the fixture.
3. `summary_native review noise decide <review> --class label --verdict approve --reviewer GM --note "labels"`: a dry run that lists the item ids and writes nothing.
4. Repeat with `--write`. `review status` then shows those items approved, and `review history --item <id>` shows the class-verdict note.
5. Pass a policy file `{noise-idiom: "idioms"}` to `review policy --write`. Only `noise-idiom` items are approved.
6. Run `noise decide` on `label` again. It exits 2 with `REVIEW_NOISE_NOTHING_TO_DECIDE`.

## 4. Baseline measurement (where the stormgiants ch 1–86 build lives)

The build is not on this machine (research R12). Where it is:

1. Re-run `npc-verify` and `review create` for the same 177 drafts.
2. Count GM-facing `number-inconsistency` and `ordinal-inconsistency` items: **≤ 100** (SC-001).
3. Count `status-claim-unsupported` items on synonym or not-established sentences: **0** (SC-002).
4. Check that every one of the 80 true-positive tokens from #617 is still a GM-facing finding (SC-004). Use the token list from the #617 classifier.
5. `review noise --json` reports at most 6 classes (SC-007), and supported + noise + findings = examined (SC-005).
