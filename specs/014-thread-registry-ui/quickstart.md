# Quickstart: validating the Thread Registry Surface (014)

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Contracts**: [cli](./contracts/cli.md) · [api](./contracts/api.md) · [ui](./contracts/ui.md)

Every scenario below is deterministic and spends **zero tokens**. If any step
here needs an `ANTHROPIC_API_KEY`, something is wired wrong (research D6).

## Prerequisites

```bash
# The package must be editable-installed into the SAME venv the server runs
# under, or the console scripts the routes spawn will not exist (CLAUDE.md).
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
python -m pytest tests/ -q
```

A campaign workspace with per-chapter extraction output. Verified present on
this machine (2026-08-25):

| Workspace | `merged.json` | Candidates | Recurring (≥2 ch) | Single ch, repeated | Excluded |
|---|---|---|---|---|---|
| `~/out-of-the-abyss/out-of-the-abyss` | 62 | 986 | 16 | 54 | 916 |
| `~/toee/toee` | 31 | 415 | 2 | 19 | 394 |
| `~/Hillsfar/Hillsfar` | 15 | 119 | 3 | 12 | 104 |

These are the numbers the banded default view must reproduce **by computing
them** (FR-028a) — if any of them is hardcoded anywhere, the next corpus makes
it a lie.

**No campaign on this machine has a `thread_registry.yaml`** (`find ~ -name
thread_registry.yaml` → nothing). Every workspace is therefore a valid
first-time subject for Scenario 1, and every one of them currently reproduces
#337.

---

## Scenario 0 — Reproduce the bug first

```bash
cd ~/toee/toee
grounding_sections build --doc planning --sections notes
```

**Expect (before the fix)**: `error: missing section file
docs/grounding_sections/planning/threads.md — build it first`.

```bash
grounding_sections list --doc planning --json | python -m json.tool
```

**Expect**: the `threads` row with `"state": "no-input"` and its `inputs`
naming `docs/thread_registry.yaml`. After the fix the same row also carries
`"missing": ["docs/thread_registry.yaml"]` (research D11).

---

## Scenario 1 — US1: harvest and see candidates (no writes)

CLI:

```bash
cd ~/toee/toee
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
thread_registry proposals --json | python -c \
  "import json,sys; d=json.load(sys.stdin); print(d['counts'])"
```

**Expect**: `wrote docs/ensemble/thread_proposals.yaml: 415 proposal(s), 415
pending GM review`, and `{'pending': 415}`. **`docs/thread_registry.yaml` must
still not exist** — the harvest writes no canon (FR-006).

UI: open `/grounding/threads`.

**Expect**:
- The registry region says there are no threads yet — a normal state, not an
  error (spec edge case 1).
- The **Run harvest** button is disabled with the corpus field empty; clicking
  it with an empty corpus surfaces *"corpus is required — pass at least one
  --corpus glob."* and **not** a 422 (Constitution X).
- After resolving the glob, the file list shows the matched files by name.
  There are **no chapter numbers** in this list (research D20).
- After the harvest the queue shows **two bands**: *Recurring* with **2**, then
  *Single chapter, repeated* with **19**, and below them
  *"394 candidates mentioned exactly once are not shown — search or filter by
  chapter to reach them."* Cross-check each number against the table above.
- **There is no "Show all" control** (research D16). Typing `goblin` in the
  search box returns matches drawn from all 415, including any already ruled,
  each badged with its ruling. Filtering to chapter 12 lists every candidate
  found in that chapter.

---

## Scenario 2 — US2: accept, reject, discuss

Use the OOTA corpus, whose head is more interesting:

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
```

**Expect**: 986 proposals, all pending. The default view shows **16 recurring**
and **54 single-chapter-repeated**, with `Buppido's divine plan` (4 chapters)
first in the recurring band; **916** are excluded. Searching `divine` also surfaces the
separate `divine plan` candidate — the two stay separate cards until you ratify
one and alias the other (FR-022).

**Accept** it in the UI. **Expect**: the form opens pre-filled — id
`buppidos-divine-plan`, title from the proposal, `opened` = the lowest chapter,
one log row per chapter with the evidence fact as its summary and the verified
quote where one exists. Nothing is written until Confirm.

```bash
thread_registry list --json | python -c \
  "import json,sys; d=json.load(sys.stdin); print(d['count'], [t['id'] for t in d['threads']])"
thread_registry check
```

**Expect**: one thread, `check` clean, and the proposal now `ratified` with
`ruled_thread` set.

**Reject** a chaff candidate (e.g. *"ajar third-floor door"*), then **Discuss**
one you are unsure of. Then re-harvest:

```bash
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
thread_registry proposals --json | python -c \
  "import json,sys; print(json.load(sys.stdin)['counts'])"
```

**Expect (SC-006)**: the rejected and deferred candidates keep their status and
neither returns as `pending`; the ratified one is no longer proposed for the
chapters now logged.

**Then the assertion that nearly got missed (FR-009a, research D17b)** — add a
later chapter mentioning the same thread and re-harvest:

```bash
thread_registry propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
```

**Expect**: the ratified thread's candidate **is** offered again, carrying only
its unlogged chapters and showing `matches: buppidos-divine-plan`. If it does
not appear, `propose()`'s short-circuit was not narrowed (T032a) and every
accepted thread is frozen at the chapter you ratified it on.

```bash
python -m json.tool docs/ensemble/thread_adjudication.json
```

**Expect (SC-007)**: the discussed candidate with its full evidence, standing
alone — enough to hand to a Claude conversation without re-running anything.

### The negative tests that matter

- There is **no** "select all", "accept remaining" or multi-row action anywhere
  on the queue (SC-004, FR-007). Its absence is the test.
- There is **no** "Show all" control (FR-028). Its absence is also the test —
  the header states the hidden count and search reaches them.
- A rejected candidate is still findable by search and still shows its ruling
  (FR-030).
- Accepting a candidate whose `chapters` is empty is refused until a chapter is
  supplied (research D4).
- Accepting a candidate whose title collides with a ratified thread shows the
  CLI's own text: *"error: title 'X' matches existing thread 'Y' — use
  log/alias on it instead"* (FR-021).

---

## Scenario 3 — US3: maintain, then unblock planning

```bash
thread_registry log --id buppidos-divine-plan --chapter 47 --change advanced \
  --summary "…"
thread_registry set-status --id buppidos-divine-plan --status resolved
```

**Expect**: the second command refuses — *"error: resolving/abandoning needs
--chapter"*. Re-run with `--chapter 47`. Perform both again through the UI and
confirm the same refusal text appears inline.

Then the thing #337 is actually about:

```bash
grounding_sections build --doc planning --sections threads
grounding_sections build --doc planning --sections notes
```

**Expect**: both succeed. `docs/projections/planning_draft.md` exists and its
Threads section lists the ratified thread. **SC-001 is met when this sequence
is reachable entirely from the browser.**

---

## Scenario 4 — US4: the signpost

On a fresh workspace (`~/Hillsfar/Hillsfar`, which has no registry), open
`/grounding/projections`, select **Planning**.

**Expect**: the `threads` row shows state `no input`, names
`docs/thread_registry.yaml` in its Inputs cell with the path marked missing,
and offers a link to `/grounding/threads` — **before** any build is attempted
(FR-024, FR-025). Clicking Rebuild on `notes` still fails, but the failure now
names the section and repeats the link (FR-026).

---

## Scenario 5 — Run gating (#341, Phase 6b)

The point of this scenario is that the *last* step of Scenario 3 works on a
machine that has no metered API key. Run the server with the variable cleared:

```bash
env -u ANTHROPIC_API_KEY ./startup
```

1. `/grounding/projections`, Planning selected, `threads` row checked →
   **Rebuild**. **Expect**: it runs. The build is deterministic assembly and
   calls no model, and nothing asks about credentials first (FR-032). Before
   #343 the button was disabled under `ANTHROPIC_API_KEY not set`.
2. Sidebar → **BACKEND: DGX**, then any generative page (`/prep/session-prep`).
   **Expect**: runnable. `dgx` needs no environment credential (FR-032).
3. Sidebar → **BACKEND: API**, same page. **Expect**: the run *starts*, then
   refuses from the engine with a message naming `ANTHROPIC_API_KEY` **and** the
   two backends that need no key (FR-033). The button is never disabled.
4. `export OPENROUTER_API_KEY=…`, restart, sidebar → **OR**. **Expect**:
   runnable. Then unset it and restart: refused, naming `OPENROUTER_API_KEY` —
   never `ANTHROPIC_API_KEY`.

```bash
# The same facts, without a browser:
curl -s localhost:8000/api/config/status | python3 -m json.tool
# Expect `{"cwd": "…"}` and nothing about credentials — #342 deleted the field.
```

Step 3's refusal now comes from the **engine**, at the call, not from a disabled
button: `_require_anthropic_credential` raises before the request, naming the
variable and the two keyless backends. Nothing pre-flights, so a run is never
refused for a credential it would not have used.

---

## Regression guards that must stay green

```bash
python -m pytest tests/test_projection_routes.py tests/test_projection_isolation.py \
                 tests/test_projection_config.py tests/test_thread_registry.py \
                 tests/test_layering.py tests/test_retrieve_render_isolation.py \
                 tests/test_no_credential_gate.py -q
```

- `test_projection_routes.py::test_no_literals_in_router` — no `docs/`-shaped
  literal may enter `server/routers/projections.py`; every new route resolves
  paths from `ProjectionConfigService.resolved()`.
- **`test_projection_isolation.py::test_no_docs_literals`** — the same rule for
  the four State Projection **engine** files, `pipelines/grounding/thread_registry.py`
  among them. Binding on the `rule` verb's `--adjudication` default and on
  `propose`'s new flags. `test_no_cross_service_config_read` covers the same
  directory.
- `test_projection_config.py` — `corpus`, `sections`, `specs` stay forbidden
  field names. `stores.thread_adjudication` is a legal addition (research D8).
- **`test_thread_registry.py`** — 10 existing tests over `propose`,
  `save_registry` and the verb refusals. `propose()` is called positionally
  there, so the new keyword flags are safe, but the short-circuit change
  (T032a) lands right underneath them.
- `test_layering.py` — nothing under `pipelines/` may import `server.*`.
- **`test_no_credential_gate.py`** (landed with PR #343, not this feature) —
  no credential-presence flag anywhere under `frontend/src/`, no
  `api_key_present` in the server, and all four Anthropic entry points guarded.
  The retired predicate cannot return by copy-paste.

### New guards this feature adds

These are deliverables, not regressions — but they are what keeps the four
*absences* from being prose. Run them alongside the block above:

```bash
python -m pytest tests/test_thread_registry_json.py tests/test_thread_registry_rule.py \
                 tests/test_thread_registry_ratify.py tests/test_thread_registry_routes.py \
                 tests/test_threads_ui_absences.py -q
```

- `test_threads_ui_absences.py` — `Threads.vue` may grow neither a fuzzy-match
  / clustering / "did you mean" helper (FR-031) nor a numeric literal where a
  band count or the excluded count belongs (FR-028a). The hardcoded count is
  the exact defect this feature replaced: **916** is right on OOTA, wrong on
  every other corpus.
- `test_thread_registry_routes.py` — carries three absence assertions besides
  its route coverage: no bulk `norm` endpoint (SC-004), no query or paging
  parameter on `/threads/proposals` (FR-028/research D16), no `--model` /
  `--backend` / `--endpoint` in the harvest argv (FR-004). Plus **the harvest
  writes no canon** (FR-006) and **no route writes on its own** (FR-018/019).
- `test_thread_registry_ratify.py` — the atomic verb's failure modes, including
  the registry-then-proposals ordering: on a proposals-write failure the thread
  exists and the candidate stays `pending`, which is the seam D18 chose
  deliberately over a half-applied ratification.

### CLI ↔ UI parity (SC-005, SC-009)

```bash
thread_registry add --id parity-check --title "Parity check" --opened 1
```

**Expect**: reloading `/grounding/threads` shows the thread with no further
action. Then ratify a candidate through the page and confirm
`thread_registry list --json` returns it identically — the two paths write the
same bytes because they are the same engine.

> **Worktree warning** (memory: `reference_worktree_editable_install_shadowing`):
> the editable-install `.pth` points at `/home/kroussos/src/CampaignGenerator`,
> so a green test run in this worktree is not proof you tested this branch
> unless `tests/conftest.py`'s `REPO_ROOT` insert is doing its job. Check
> `python -c "import campaignlib; print(campaignlib.__file__)"` resolves inside
> the worktree before believing a pass.
