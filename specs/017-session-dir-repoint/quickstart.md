# Quickstart: Validating Session Directory Re-Pointing

**Feature**: `017-session-dir-repoint` | **Date**: 2026-08-28

Runnable validation that the feature works end to end. Backend behaviour is
covered by pytest; the frontend has no test runner in this repo
(`frontend/package.json` exposes `dev` / `build` / `preview` only), so §1–§4
are manual and are the acceptance gate for Phase 4.

See [`contracts/editor-config.md`](./contracts/editor-config.md) for the wire
shape and [`data-model.md`](./data-model.md) for the classification rule; this
guide does not restate them.

## Prerequisites

```bash
cd ~/src/CampaignGenerator            # or the feature worktree
python -m pytest -q                   # baseline: green before you start
cd frontend && npm run build && cd .. # baseline: clean typecheck
```

A campaign with at least two session directories under `summaries/`.
`out-of-the-abyss` qualifies (`summaries/20260811`, `summaries/20260824`,
`summaries/20260825`). **Back up its config first** — these steps write to it:

```bash
OOTA=~/out-of-the-abyss/out-of-the-abyss
cp $OOTA/config/session_doc.yaml $OOTA/config/session_doc.yaml.bak
cp $OOTA/config/platform.yaml    $OOTA/config/platform.yaml.bak
```

Start the server against that campaign:

```bash
./start                               # or: python -m server.main --campaign-dir $OOTA
```

## §1 — User Story 1: the switch takes (P1)

1. Open **Session Config**. Note the current session directory.
2. Change it to `…/summaries/20260825`. Save.
3. Navigate to **Session Doc** — *without reloading the browser*.
4. Open the config drawer.

**Expected**: every session-scoped field resolves under `20260825`. The
`→ /abs/path` hint under each relative field (`PathField.vue:82`) shows the new
session directory. Campaign-scoped fields (voice, examples, party, genre) are
unchanged.

**Fails today as**: every path still reads `20260811` — the defect.

```bash
# Confirm from the API rather than the eye:
curl -s localhost:5000/api/editor/config | python -m json.tool \
  | grep -E '"(session_dir|session_recap|scene_extractions_dir|narration_dir)"'
# every session path must contain 20260825, none may contain the old date
```

## §2 — User Story 2: nothing pins the old session (P1)

1. With §1 done, change any knob in the drawer (e.g. narrate tokens) so the
   debounced auto-save fires.
2. Inspect the stored document:

```bash
grep -n "2026" $OOTA/config/session_doc.yaml
```

**Expected**: no session-scoped path contains any session date at all — they
are relative names (`scene_extractions`, `narration`, …). The only dates that
may appear are inside a per-session *filename* the GM chose, under the current
session.

**Expected**: `paths` in `session_doc.yaml` contains **no absolute path**
except a genuine out-of-tree override.

3. Now the ordering case (FR-002 scenario 2). On Session Config, change the
   session directory and click Save once:

```bash
# session_dir must be committed before the path write:
grep -n "session_dir" $OOTA/config/platform.yaml
grep -n "session_recap\|session_summary" $OOTA/config/session_doc.yaml
```

**Expected**: the path fields are relative names, interpreted against the new
`session_dir`. Neither write leaves a value anchored to the session just left.

## §3 — User Story 3: a damaged campaign heals (P2)

Poison a config deliberately, then confirm it recovers.

```bash
# 1. Pin a session path to a SIBLING session directory (the damage case)
python - <<'PY'
import yaml, pathlib
p = pathlib.Path.home()/"out-of-the-abyss/out-of-the-abyss/config/session_doc.yaml"
d = yaml.safe_load(p.read_text())
d["paths"]["scene_extractions_dir"] = \
    "/home/kroussos/out-of-the-abyss/out-of-the-abyss/summaries/20260811/scene_extractions"
# 2. And a genuine OUT-OF-TREE override, which must survive untouched
d["paths"]["narration_dir"] = "/tmp/shared-narration"
p.write_text(yaml.safe_dump(d, sort_keys=False))
PY

# 3. Read it back
curl -s localhost:5000/api/editor/config | python -m json.tool > /tmp/ec.json
grep -A 12 '"paths_stored"' /tmp/ec.json
grep -A 4  '"warnings"'     /tmp/ec.json
```

**Expected**:

- `paths_stored.scene_extractions_dir` is `"scene_extractions"` — re-pointed to
  a relative name (FR-004).
- `paths.scene_extractions_dir` resolves under the **current** session
  directory.
- `paths_stored.narration_dir` is still `"/tmp/shared-narration"` — a
  deliberate override, untouched and unreported (FR-005).
- `warnings` has exactly one entry, naming `scene_extractions_dir`, the stored
  value, and the value now in use (FR-006).
- The editor renders that warning where migration warnings already appear.

**No write on read** (FR-007):

```bash
stat -c %Y $OOTA/config/session_doc.yaml            # before
curl -s localhost:5000/api/editor/config > /dev/null
curl -s localhost:5000/api/editor/config > /dev/null
stat -c %Y $OOTA/config/session_doc.yaml            # must be IDENTICAL
```

**Idempotence** (FR-012): the two `GET`s above must return identical bodies.

**Then** trigger any editor write and confirm the healed value lands:

```bash
grep -n "scene_extractions_dir" $OOTA/config/session_doc.yaml
# now: scene_extractions_dir: scene_extractions
```

## §4 — User Story 4: missing targets are visible (P2)

1. Point the session directory at a session folder with no GM-assist recap and
   no `session-summary.md` (create an empty one if needed:
   `mkdir -p $OOTA/summaries/20260901`).
2. Open the Session Doc drawer.

**Expected**: `session_recap` and `session_summary` are re-pointed onto
`20260901` (their names preserved, not blanked — FR-008) and each is marked
**❌ not found**. `scene_extractions_dir` / `narration_dir` are marked
according to whether those directories exist. Editing a field to name a file
that does exist clears the mark without a reload.

**Note**: this is `PathField`'s existing behaviour
(`PathField.vue:37-54,72-73`). The feature does not add it — it makes it point
at the right value. Also check the narrate-context input
(`MultiPathField`) marks missing entries the same way.

## §5 — Boot override (FR-011)

```bash
python -m server.main --campaign-dir $OOTA --session-dir $OOTA/summaries/20260824
curl -s localhost:5000/api/editor/config | grep -E '"session_dir"|20260824'
```

**Expected**: paths resolve against `20260824`, healing applies to the resolved
view, and **nothing** is written to `platform.yaml` or `session_doc.yaml` —
the boot override is process-lifetime only.

```bash
diff <(cat $OOTA/config/platform.yaml) $OOTA/config/platform.yaml.bak   # no diff
```

## §6 — Regression surface

```bash
python -m pytest -q                                    # all green
python -m pytest -q tests/test_session_editor_config_service.py \
                    tests/test_editor_service_integration.py \
                    tests/test_config_routes.py \
                    tests/test_main_boot_overrides.py
python -m pytest -q tests/test_retrieve_render_isolation.py   # Principle III
cd frontend && npm run build && cd ..                  # vue-tsc clean
```

**Must also hold**:

- `git diff` touching any `_build_*_cmd()` in `server/routers/scene_editor.py`
  is **empty** (Principle VI — no run command changes).
- `git diff server/platform_config_service.py` is empty — `resolve_path` /
  `relativize_path` are the seam and are not modified.
- A campaign whose stored paths were already relative shows **no diff** in
  `session_doc.yaml` after a full open-and-save cycle.

## Restore

```bash
mv $OOTA/config/session_doc.yaml.bak $OOTA/config/session_doc.yaml
mv $OOTA/config/platform.yaml.bak    $OOTA/config/platform.yaml
```
