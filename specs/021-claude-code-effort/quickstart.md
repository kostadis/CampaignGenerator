# Quickstart: Validating Claude Code Effort Level

**Feature**: `021-claude-code-effort`

Runnable validation that the feature works end to end. Each section names what it proves.

---

## 0. Prerequisites — do these first

```bash
cd ~/src/CampaignGenerator/worktrees/021-claude-code-effort

# The server runs pipelines as installed console scripts, NOT repo-relative .py files.
# A fresh worktree has none, and every /run/* action fails with
# "Stream error — check terminal" until this is done.
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"

claude --help | grep -A2 -- --effort      # expect: low, medium, high, xhigh, max
grep -n effortLevel ~/.claude/settings.json   # note your pinned level — §4 depends on it
```

**Worktree caveat (issue #286)**: six test files skip silently in a worktree, so a green suite here is not evidence. Run with `-rs` and read the skip list, or run the suite from `~/src/CampaignGenerator`.

---

## 1. The option exists on the whole family — FR-001, SC-001

```bash
# Registered inside add_backend_args, so every model-bearing CLI inherits it.
for cli in sd_narrate scene_extract enhance_summary distill planning party; do
  printf '%-18s ' "$cli"
  "$cli" --help 2>/dev/null | grep -c -- --claude-code-effort
done
# expect: 1 for every CLI
```

**Proves**: family-wide parity by construction, not by 30 separate edits.

---

## 2. Precedence — FR-004, SC-002

```bash
# explicit beats environment
CG_CLAUDE_CODE_EFFORT=low sd_narrate --backend claude-code --claude-code-effort high --dump-only …
# expect banner: effort=high (explicit)

# environment when nothing explicit
CG_CLAUDE_CODE_EFFORT=medium sd_narrate --backend claude-code --dump-only …
# expect banner: effort=medium (CG_CLAUDE_CODE_EFFORT)

# whitespace-only env is omission, not an empty override
CG_CLAUDE_CODE_EFFORT="   " sd_narrate --backend claude-code --dump-only …
# expect: clamp or inherited — never an empty effort
```

**Proves**: the documented precedence, and that ambient emptiness does not outrank the tier above.

---

## 3. Refusals happen before any spend — FR-007, FR-009, SC-004

```bash
sd_narrate --backend claude-code --claude-code-effort ultra …
# expect: names the five accepted values; no child spawned

sd_narrate --backend dgx --claude-code-effort high …
# expect: "applies only to --backend claude-code; effective backend is 'dgx'"

# The conflict — thinking is OFF by default on this backend
sd_narrate --backend claude-code --claude-code-effort max …
# expect: refusal naming BOTH remedies, including CG_CLAUDE_CODE_THINKING=1 by name.
#   MUST NOT enable thinking. MUST NOT quietly run at 'high'.
#   MUST NOT spawn the child and let the provider reject it.

# ...and the same request succeeds once thinking is on
CG_CLAUDE_CODE_THINKING=1 sd_narrate --backend claude-code --claude-code-effort max …
# expect: effort=max (explicit) thinking=on

# always-thinking family: no conflict, no refusal, no clamp
sd_narrate --backend claude-code --model claude-fable-5 --claude-code-effort max …
# expect: accepted
```

**Proves**: FR-009 as the operator ruled it — refuse, name both fixes, never repair. And FR-009a: the refusal does not fire where no conflict exists.

Verify nothing spawned: `ps` shows no `claude` child, and no artifact was written.

---

## 4. Omission is unchanged, and the clamp now says so — FR-005, FR-020, SC-005, SC-008

This is the scenario the feature exists for. It needs `effortLevel: xhigh` in your `~/.claude/settings.json` — which you already have.

```bash
sd_narrate --backend claude-code --dump-only …
```

**Expect the banner to make all three facts readable without external help:**
1. the run used `high`
2. your pinned `xhigh` was **not** used
3. the reason is that thinking is off and the provider refuses `xhigh` without it

**Then prove behaviour did not move:**

```bash
git stash && sd_narrate --backend claude-code --dump-only … > /tmp/before.txt
git stash pop && sd_narrate --backend claude-code --dump-only … > /tmp/after.txt
diff <(grep -v effort /tmp/before.txt) <(grep -v effort /tmp/after.txt)
# expect: empty — the invocation is byte-identical; only the report is new
```

**Proves**: the clamp is preserved *and* disclosed. Before this feature, question 2 was unanswerable from any output.

---

## 5. Inherited claims no value — FR-018

```bash
CG_CLAUDE_CODE_THINKING=1 sd_narrate --backend claude-code --dump-only …
# expect: "effort=inherited from your ~/.claude/settings.json (no override sent)"
# MUST NOT print "xhigh" — we did not read that file and must not guess
```

**Proves**: the fourth source reports honestly rather than asserting a level it cannot know.

---

## 6. Dispatchers forward — FR-010, SC-001

```bash
ensemble_batch --backend claude-code --claude-code-effort medium --plan … --dry-run
# expect: EVERY child command line carries --claude-code-effort medium

# mixed-backend plan: only claude-code stages are touched
ensemble --plan mixed.yaml --claude-code-effort medium --dry-run
# expect: dgx/anthropic stages unchanged
```

**Proves**: forwarding reaches every child, and stops at the backend boundary.

---

## 7. UI parity and persistence — FR-012..FR-016, SC-003

```bash
./startup
```

For **each** of: sidebar · Session Doc Editor · scene KnobDrawer · Ensemble Setup —

1. Set backend to `claude-code`. **Expect**: an Effort control appears with six choices.
2. Set backend to `dgx`. **Expect**: it disappears.
3. Back to `claude-code`, choose `high`, reload. **Expect**: `high` still selected.
4. Switch to `codex-cli`, set a Codex reasoning effort, switch back. **Expect**: `high` intact, and the Codex value intact — neither clobbered the other.
5. Choose `Claude Code default`, reload. **Expect**: default, and the stored field is **absent** from the YAML — not `""`, not a copied platform value.

```bash
grep -n "claude_code_effort" <campaign>/config/session_doc.yaml
```

6. Launch a run. **Expect**: the copyable command shows `--claude-code-effort high` explicitly, and `StreamOutput` shows the identity banner.

**Proves**: Principle XI parity, tier isolation, and that omission persists as absence.

---

## 8. The suite

```bash
cd ~/src/CampaignGenerator            # NOT the worktree — issue #286
python -m pytest tests/ -rs

python -m pytest tests/test_claude_code_effort.py \
                tests/test_claude_code_effort_config.py \
                tests/test_claude_code_effort_ui.py -v

# other backends untouched — FR-023, SC-007
python -m pytest tests/test_codex_reasoning_effort.py \
                tests/test_codex_reasoning_config.py \
                tests/test_backend_seam_guardrails.py -v

cd frontend && npm run build
```

Read the `-rs` skip list. A skipped file is not a passed file.

---

## Acceptance summary

| Section | Covers |
|---|---|
| 1 | SC-001 — family-wide CLI parity |
| 2 | SC-002 — precedence, all four sources |
| 3 | SC-004 — refusals before spend, including the conflict ruling |
| 4 | SC-005, SC-008 — omission preserved *and* disclosed |
| 5 | FR-018 — inherited reports honestly |
| 6 | SC-001 — dispatcher forwarding |
| 7 | SC-003, SC-006 — UI parity, persistence, isolation |
| 8 | SC-007 — no regression elsewhere |


---

## Execution record — 2026-09-01

Executed during implementation. Recorded here rather than left for a follow-up:
#359's sibling specs have this exact debt open in three places (#313, #319, #335).

| § | Result |
|---|---|
| 0 | **Pass.** `uv pip install -e .` into `~/.venvs/main`; `npm install` in `frontend/` (the worktree had no `node_modules`, so `npm run build` failed with `vue-tsc: Permission denied` until it did). `claude --help` confirms exactly `low, medium, high, xhigh, max`. Operator's `~/.claude/settings.json` pins `effortLevel: xhigh`. |
| 1 | **Pass.** 28 console scripts expose `--claude-code-effort`; zero CLIs carry `--codex-reasoning-effort` without it. `grounding_sections` declares it on its `build` subparser, not at top level. |
| 2 | **Pass.** Explicit beats environment; environment beats omission; whitespace-only env is omission. A *padded* env value (`" high"`) is stripped and accepted, mirroring the Codex resolver — the initial test expected a refusal and was corrected, not the code. |
| 3 | **Pass.** All five refusals fire with `fake.spawned == 0`. The conflict message names the level, both remedies, and `CG_CLAUDE_CODE_THINKING=1` literally. `max` on `claude-fable-5` is accepted (FR-009a). |
| 4 | **Pass — the headline result.** Omission is **byte-identical** to the pre-feature baseline across all three states (clamped opus, always-thinking fable, thinking-on opus), captured before any source change and diffed after. The clamp now announces itself: `effort=high (compatibility clamp — thinking is off, and the provider refuses xhigh/max without it; your settings.json effortLevel was not used)`. That sentence is the answer to SC-008, which no output could give before. |
| 5 | **Pass.** `inherited` prints no level. |
| 6 | **Pass.** Six dispatchers forward; `test_no_dispatcher_forwards_codex_effort_without_the_claude_code_one` fails the build if one regresses. |
| 7 | **Partial — source-level only.** `tests/test_claude_code_effort_ui.py` (21 assertions) proves the control is present on all six surfaces, that the vocabulary is not hardcoded, that both efforts travel on every save, and that the editor writes to its own backend key. `npm run build` passes, `vue-tsc -b` included. **The browser steps were not clicked** — no component-test harness exists (#345) and no server was started. Clicking §7 remains open. |
| 8 | **Pass, against a measured baseline.** Worktree: 31 failed / 4586 passed. `main`: 30 failed / 4502 passed. The one difference, `test_extract_facts.py::test_cli_parallel_fully_cached`, was **proven pre-existing** by stashing every change and re-running — it still fails. Cause: `wiring_get("dgx_model")` returns `None` inside a worktree, so `_OpenAICompatClient` hands `None` to dgxlib. Same family as #286. |

### Two things worth carrying forward

- **`main` is red**, independently of this feature: 30 pre-existing failures, most of them #359-shaped test stubs (`test_make_client_routes_codex_cli` uses a lambda that does not accept `reasoning_effort`) plus `test_selection_preview` / `test_ui_batch_service_selection` families. Not touched here.
- **`wiring_get` resolves differently in a worktree.** #286 documents silent *skips*; this is a silent *failure*. Worth widening that issue.
