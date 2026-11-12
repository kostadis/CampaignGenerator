# Quickstart / Validation: Per-Item Source Custody (042)

Run everything from the worktree with `PYTHONPATH` pinned, so the main checkout's editable install cannot shadow the branch (research R15):

```bash
WT=/path/to/wt042
export PYTHONPATH=$WT
PY=~/.venv/bin/python
$PY -c "import pipelines; print(pipelines.__file__)"     # must print $WT/pipelines/__init__.py
BT="--basetemp=$HOME/.cache/pytest-042"
```

## 1. Unit and acceptance suites

```bash
$PY -m pytest $BT -q \
  tests/test_summary_native_review_custody.py \
  tests/test_summary_native_review_item_custody.py \
  tests/test_summary_native_npc_publish_custody.py \
  tests/test_summary_native_review_decisions.py \
  tests/test_summary_native_review_delegated.py \
  tests/test_summary_native_review_routes.py \
  tests/test_summary_native_review_http.py \
  tests/test_delta_freshness.py \
  tests/test_summary_native_no_llm.py
```

Expected: all pass. Each spec acceptance scenario has one named test (`test_us1_s1_…` through `test_us4_s3_…`).

## 2. Read-only stormgiants replay (SC-002, SC-005)

```bash
STORMGIANTS=~/storm-giant/stormgiants $PY -m pytest $BT -q -s tests/test_summary_native_custody_baseline.py
```

The replay writes nothing. It injects simulated file states. Expected:

- for every draft, simulating a change stales exactly that NPC's items, with no other NPC's;
- simulating a change to `010-session-the-seer.md` stales exactly the items of the 8 NPCs whose evidence names it;
- there is no difference between the predicted set and the computed set.

## 3. End-to-end on a scratch campaign

1. Build a two-NPC review the way the tests do (`tests/_custody_fixture.py::build`), or use any campaign with an `npc_verification` review.
2. Edit one line of NPC A's draft.
3. Run `summary_native review status <review> --json`. Expect `stale_by_npc` to list A only, with the draft path.
4. Approve B's sign-off: `summary_native review npc sign <review> --item <B signoff> --draft-sha256 <sha> …`. Expect it to be saved.
5. Approve A's sign-off. Expect exit 3, `REVIEW_STALE_CUSTODY`. The text names A's draft, the item ids and the refresh command, and nothing is written.
6. Run `summary_native review retract …` on an earlier decision of A. Expect it to succeed (FR-009).
7. Run `summary_native npc-publish --name A --name B`. Expect B published, and A held with its draft path in the reason.

## 4. Web faces

- **Launcher**: in `/api/reviews`, repeat step 5 through "Save decision". The result panel shows the `data` detail.
- **Capability viewer**: start it with `summary_native review service start`, then approve A's item. The save state lists the changed file and its items, and offers Reload.

## 5. Full suites

```bash
$PY -m pytest $BT -q tests/
cd frontend && npm test && npm run build
```
