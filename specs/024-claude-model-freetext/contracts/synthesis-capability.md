# Contract: `synthesis_capable(model)`

**Module**: `server/routers/ensemble.py`
**Replaces**: the `SYNTHESIS_CAPABLE` set (deleted — research R3)
**Call site**: the sub-Sonnet warning in the synthesize run handler

```python
# before
if backend != "anthropic" and model and model not in SYNTHESIS_CAPABLE:

# after
if backend != "anthropic" and model and not synthesis_capable(model):
```

The `backend != "anthropic"` guard is **retained unchanged**. It is why the
warning never misfired on the metered API and only ever misfired on `claude-code`
— see research R2.

---

## Signature

```python
def synthesis_capable(model: str | None) -> bool
```

## Truth table

Evaluated **in this order**. The order is part of the contract.

| # | Condition | Result | Example | Why |
|---|---|---|---|---|
| 1 | falsy / whitespace-only | `True` | `""`, `None` | Nothing was chosen; the resolved default applies, and the platform default must never warn about itself |
| 2 | contains `_SUB_SONNET_TIER` (case-insensitive) | `False` | `claude-haiku-4-5`, `claude-haiku-6` | **FR-013** — the one real capability judgement, and it must beat rule 3 |
| 3 | starts with `claude-` | `True` | `claude-opus-5`, `claude-opus-6` | Any Anthropic API id at or above the bar |
| 4 | starts with `anthropic/claude-` | `True` | `anthropic/claude-opus-5` | The OpenRouter spelling of the same thing (research R4a) |
| 5 | in `_THIRD_PARTY_SYNTHESIS_CAPABLE` | `True` | `openai/gpt-5`, `google/gemini-2.5-pro` | Frontier non-Anthropic ids; not derivable, stays hand-maintained |
| 6 | otherwise | `False` | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` | A local model genuinely may underperform at synthesis; the warning is doing its job |

| Requirement | Contract |
|---|---|
| S1 | Rule 2 MUST be evaluated before rules 3–4. Reversed, every future Haiku id becomes "capable" and FR-013 is silently gone. |
| S2 | Absence from any list MUST NOT by itself yield `False`. Rules 3 and 4 exist to make unknown-but-Anthropic ids capable. |
| S3 | Rule 6 preserves today's behaviour for local and unrecognised ids. This feature widens the `True` set; it never widens the `False` set. |
| S4 | No I/O, no network, no clock. A pure function of one string. |
| S5 | `_THIRD_PARTY_SYNTHESIS_CAPABLE` keeps its `anthropic/claude-*` entries harmlessly (rule 4 already covers them); they are not load-bearing and may be pruned, but pruning is not required. |

---

## Warning text

Unchanged:

```
⚠️  '<model>' is not on the synthesis-capable list — synthesis assumes a model at
least as capable as Sonnet; output quality may degrade. Proceeding anyway.
```

It still warns and still does not block. The only change is *which* models reach
it.

> **Optional copy nit, not required by any FR**: "is not on the
> synthesis-capable list" describes a mechanism that no longer exists after this
> change. `'<model>' looks weaker than Sonnet` would describe the judgement being
> made. Flagged for `$speckit-tasks` to include or drop; changing it means
> updating `WARNING_FRAGMENT` in the test module.

---

## Test migration

`tests/test_synthesis_capable_registry.py` — re-point at the predicate.

| Existing test | Fate |
|---|---|
| every registry model above Haiku is capable | **Holds** — via rule 3 instead of set membership |
| the Haiku tier is excluded | **Holds** — rule 2 |
| frontier third-party ids survive | **Holds** — rule 5 |
| the platform default never warns about itself | **Holds** — rule 3 |
| no warning for a current registry model | **Holds** — behavioural, unchanged |
| `claude-sonnet-4-20250514` is gone | **Changes** — see below |

**The one flip.** That test asserted a retired date-suffixed id was absent from
the derived set. Under the predicate it is capable: it is a Sonnet, and the bar is
"at least as capable as Sonnet". This is correct, for two reasons — the assertion
pinned *snapshot freshness*, a property that ceases to exist once nothing is
snapshotted; and "may be too weak" was always the wrong diagnosis for a retired
model, which the provider reports by refusing the call. Replace it with a test
asserting a **future, unreleased** Anthropic id is capable — the property the
module now needs to guarantee, and the one the old set could never satisfy.

New tests required:

- an unreleased-looking id (`claude-opus-6`) is capable — the regression this
  feature exists to prevent;
- an unreleased-looking Haiku id (`claude-haiku-6`) is **not** capable — S1, the
  ordering, which no test of known ids can catch;
- `anthropic/claude-opus-6` is capable — rule 4;
- the whole path end-to-end: a `claude-code` synthesize run with an unlisted
  Claude model emits **no** `WARNING_FRAGMENT`, and one with an unlisted Haiku id
  still does.
