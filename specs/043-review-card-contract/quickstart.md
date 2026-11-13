# Quickstart / Validation: Review Card Contract (043)

Run from the worktree with `PYTHONPATH` pinned, so the main checkout's editable install cannot shadow the branch (research R15):

```bash
WT=/path/to/wt043
export PYTHONPATH=$WT
PY=~/.venv/bin/python
$PY -c "import pipelines; print(pipelines.__file__)"   # must print $WT/pipelines/__init__.py
mkdir -p $HOME/.cache && BT="--basetemp=$HOME/.cache/pytest-043"
```

## 1. Contract and acceptance suites

```bash
$PY -m pytest $BT -q \
  tests/test_summary_native_review_cards.py \
  tests/test_summary_native_review_cards_contract.py \
  tests/test_summary_native_review_action_table.py \
  tests/test_summary_native_review_noise_cli.py \
  tests/test_summary_native_review_delegated.py \
  tests/test_summary_native_review_routes.py \
  tests/test_summary_native_no_llm.py
```

Expected: all pass. Each spec acceptance scenario has a named test (`test_us1_s1_…` through `test_us4_s3_…`). The contract suite validates the golden files and every exported packet against the checked-in schemas. It also fails if the regenerated schemas differ from the checked-in ones (SC-005).

## 2. A manual round trip on a fixture review

```bash
cd $(mktemp -d) && $PY -c "from tests._custody_fixture import build; import pathlib; print(build(pathlib.Path('.')).root)"
ROOT=<printed root>; R=<review id from 'summary_native review list --campaign-dir $ROOT --json'>
$PY -m pipelines.summary_native.cli review cards export $R --campaign-dir $ROOT --out /tmp/p.json
```

Then write `d.json` by hand from `/tmp/p.json`, following [contracts/card-files.md](contracts/card-files.md): approve one sign-off and reject one finding.

```bash
$PY -m pipelines.summary_native.cli review cards decide $R --decisions d.json --reviewer GM --campaign-dir $ROOT
```

Expected: a plan with 2 records and the rest unmarked. Run the printed `--write --plan-sha256 …` command, then run the dry run again. Expected: 2 noops (SC-003).

Edit the draft of the approved sign-off's NPC. Change the rejected finding's card to `approve` in `d.json`. Plan again. Expected:

- the sign-off is listed as refused (`REVIEW_NPC_SIGNOFF_STALE`), but only if it is still unrecorded;
- the finding is listed as a supersede, `reject → approve`.

## 3. Bad inputs leave the store byte-identical (SC-002)

These are covered by `test_us2_*`. Each one hashes the review tree before and after with `conftest_npc.sha_tree`.

## 4. Scale (SC-007)

```bash
$PY -m pytest $BT -q tests/test_summary_native_review_cards.py -k scale
```

Expected: about 800 items. Export and a full decide each finish in under 60 s.

## 5. Web face

```bash
cd frontend && npx vitest run src/components/ReviewLauncher.test.ts && npm run build
```

Expected: the card-packet tests pass (export, then plan, then confirm, plus a refusal), and the type check is clean.

## 6. Kit (mytools worktree)

```bash
cd <mytools-wt>/dotfiles && bash check-skill-sync.sh && bash tests/test-codex-links.sh
~/.venv/bin/python -m pytest shared/skills/_shared/review-artifact/tests
grep -rn "review-page" claude codex shared && echo "FAIL: fork still referenced" || echo ok
grep -rnE "manifest\.json|/items/|/events/|docs/reviews" shared/skills/_shared/review-artifact/*.py && echo "FAIL: store read" || echo ok
```

Then run one NPC page end to end against the fixture review, following the loop in [contracts/kit.md](contracts/kit.md).

## 7. Full suite

```bash
$PY -m pytest $BT -q tests/
```

Expected: green. Any failure caused by #655's stricter action table is **stopped and reported to the GM**, not fixed by widening the table (research R4).
