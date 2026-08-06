# Quickstart: Two-Phase Extraction Agent

Runnable validation scenarios proving the feature works end-to-end. Contracts
live in [`contracts/`](./contracts/); design rationale in
[`research.md`](./research.md).

## Prerequisites

```bash
# Console scripts MUST be installed into the venv the server runs under,
# or the UI Verify button fails with "Stream error — check terminal."
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"

# Confirm the new entry points resolve
which sd_verify_quotes sd_agent
```

> **Worktree warning.** The editable-install `.pth` hardcodes
> `/home/kroussos/src/CampaignGenerator`, so in a worktree `import campaignlib`
> can resolve to **main's** copy. Before trusting any test run:
>
> ```bash
> python -c "import campaignlib, session_doc; print(campaignlib.__file__)"
> ```
>
> If that prints a path outside this worktree, you are testing the wrong code.

---

## Scenario 1 — Classification correctness (US1, the core proof)

Builds a fixture with one exact quote, one disfluency-edited quote, one
fabricated quote, and one editorial marker, then asserts all four verdicts.

```bash
mkdir -p /tmp/cgq && cd /tmp/cgq
cat > s.vtt <<'EOF'
WEBVTT

1
00:00:01.000 --> 00:00:04.000
David Mendenhall: I do, like, cross promotions.

2
00:00:05.000 --> 00:00:09.000
Wade Brown: The town has been protected by the strength of Lathander.
EOF

cat > session-summary.md <<'EOF'
# Session

## Memorable Moments

> "The town has been protected by the strength of Lathander."
> — Wade

> "I do cross promotions."
> — David

> "I have always hated the sea and everything in it."
> — Wade

> "[inaudible]"
> — Wade
EOF

sd_verify_quotes --vtt s.vtt --summary session-summary.md --out report.md --report-only
echo "exit=$?"
```

**Expected**: exit `1` (findings present).

| Quote | Verdict | Why |
|---|---|---|
| `"The town has been protected…"` | `verified` | Exact substring |
| `"I do cross promotions."` | `near` (~0.93) | Disfluency `like,` removed — D1's dominant case |
| `"I have always hated the sea…"` | **`unverified`** | Nothing like it in the transcript |
| `"[inaudible]"` | `exempt` | Editorial marker (D3) |

This scenario is the feature: exactly one accusation, and it is the right one.

---

## Scenario 2 — Nothing is rewritten, and re-runs are inert (FR-006, FR-007)

```bash
cd /tmp/cgq
cp session-summary.md pristine.md

sd_verify_quotes --vtt s.vtt --summary session-summary.md --out report.md
sha1sum session-summary.md > after-first

sd_verify_quotes --vtt s.vtt --summary session-summary.md --out report.md
sha1sum session-summary.md > after-second

diff after-first after-second && echo "PASS: idempotent (SC-006)"

# Quote TEXT must be untouched; only an appended marker may differ
diff <(grep -o '"[^"]*"' pristine.md) <(grep -o '"[^"]*"' session-summary.md) \
  && echo "PASS: no quote text modified (SC-007)"
```

**Expected**: both PASS. The only diff versus `pristine.md` is a trailing
`<!-- cg:unverified -->` on the fabricated quote's line.

---

## Scenario 3 — Refuses to run without a transcript (FR-011)

```bash
cd /tmp/cgq
sd_verify_quotes --vtt /nonexistent.vtt --summary session-summary.md --out r.md
echo "exit=$?"   # expect 2, with a clear message
```

**Expected**: exit `2`. **Not** a report claiming every quote is unverified —
that is the failure mode this requirement exists to prevent.

---

## Scenario 4 — Real session, real scale (SC-004)

```bash
S=~/campaigns/Phandalin/summaries/20260623
time sd_verify_quotes \
  --vtt "$S"/GMT20260624-035836_Recording.transcript.vtt \
  --scene-extractions "$S/scene_extractions_new" \
  --out "$S/narration/quote_report.md" --report-only
```

**Measured** on this exact session (522 quotes, 1,244 cues, threshold 0.85):

| verdict | count | share |
|---|---|---|
| `verified` | **339** | 65% |
| `near` | 139 | 27% |
| `unverified` | **39** | 7% |
| `unscored` | 3 | 1% |
| `exempt` | 2 | 0% |

Wall clock **1.2 s**, zero tokens.

A materially different `verified` share means the parser regressed, not that
the session changed.

**Why 39 and not a handful:** this corpus was extracted *before* `6e00f54`, so a
large share of the unverified findings are the D13 alias substitution, not model
fabrication — `"Brewbarry made a quiet mental note"` where the tape says
`"Gruberry…"`, `"Lord Neverember"` for `"Lord Nevember"`, `"Alagondar"` for
`"allegondre"`, `"Brother Aldric"` for `"Brother Aldrich"`. The verifier is
correct (those are not what was said) and it independently rediscovered the bug
PR #231 fixed. **A post-`6e00f54` re-extraction should drop this count
substantially** — and comparing before/after is itself a good check that the
fix worked.

The remainder are ellipsis-stitched quotes, flagged as **Likely stitched** in
the report.

---

## Scenario 5 — The refactor is inert (D10)

Guards the `locate_quote` rewire of the live ensemble pipeline.

```bash
cd /home/kroussos/src/CampaignGenerator/.claude/worktrees/dgx-two-phase-extraction
python -m pytest tests/test_locate_quote_parity.py -v
```

**Expected**: every `quote_verified` boolean and every `quote_offset` value
identical before and after the rewire, over a real corpus sample. **If this
fails, drop the refactor and duplicate the matcher** — the ensemble corpus is
not worth risking for a tidiness win (see `plan.md` Complexity Tracking).

---

## Scenario 6 — Orchestrated stage run (US3)

Dry run first — costs nothing and shows exactly what would be spent:

```bash
S=~/campaigns/Phandalin/summaries/20260623
sd_agent --stage summary --session-dir "$S" \
  --context ~/campaigns/Phandalin/docs/campaign_state.md \
            ~/campaigns/Phandalin/docs/world_state.md \
  --backend dgx --model deepseek-… \
  --dry-run
```

**Expected**: three numbered commands printed, nothing executed, no key shown.

Then the real run, and the acceptance checks that matter:

```bash
sd_agent --stage summary --session-dir "$S" --context … --backend dgx --model deepseek-…
```

- Steps run in order ①→②→③ (FR-016)
- Verification findings **do not** abort the consistency step (FR-019)
- Run **stops** after ③ — no scene extraction (FR-018, Principle II)
- Closing block states nothing was auto-corrected

---

## Scenario 7 — UI surface

```bash
./startup
```

1. Open **Session Doc Editor**. A **Verify** action sits beside Enhance/Extract.
2. Status strip shows a verify dot: `cold` before any run.
3. Click Verify — output streams; on completion the dot shows the `unverified`
   count.
4. Edit `session-summary.md` and reload — the dot goes `warn` (report now stale).

**No restart needed** after installing console scripts: `console_script()`
resolves per request.

---

## End-to-end acceptance

| Spec item | Scenario |
|---|---|
| SC-001 no fabricated quote passes | 1 |
| SC-002 reflow produces no findings | 1, 4 |
| SC-004 < 30 s, zero cost | 4 |
| SC-005 3 actions → 1 | 6 |
| SC-006 idempotent | 2 |
| SC-007 no quote text modified | 2 |
| FR-011 refuses without transcript | 3 |
| FR-018 stops at the stage boundary | 6 |
| D10 refactor inert | 5 |
