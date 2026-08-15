# Quickstart — validating the Player Entity & Config Service

**Feature**: `009-player-entity-service` | **Date**: 2026-08-15

Runnable scenarios that prove the feature end to end. Each maps to a user story and
to the success criteria it settles. Shapes live in [`contracts/`](./contracts/) and
[`data-model.md`](./data-model.md) — they are referenced here, not repeated.

> **A green `pytest` run in a worktree is not sufficient evidence.** The editable
> install's `.pth` hardcodes the main checkout, so `import campaignlib` can resolve
> to `main`'s copy, and six test files skip silently in a worktree (#286,
> research D16). Every scenario below runs against a **real campaign directory** for
> that reason.

---

## Prerequisites

```bash
cd /home/kroussos/src/CampaignGenerator/.claude/worktrees/009-player-entity-service

# The console scripts resolve relative to the server's python, not $PATH.
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"

python -m pytest tests/ -q
```

Take a **before** reading. This is the baseline every later scenario is measured
against, and it is how you confirm you are testing this branch and not `main`:

```bash
python3 specs/009-player-entity-service/contracts/measure.py
```

Expect the state recorded in `research.md` M1–M5 — notably obelisk failing to load,
toee's 51,073-character global block, and stormgiants' `Thistle` with no examples.

---

## Scenario 1 — Author a player roster (US1 · FR-001…FR-018 · SC-007)

```bash
mkdir -p /tmp/qs-campaign/config
cd /tmp/qs-campaign
```

1. Start the server (`./startup` from the repo) and open **Setup → Players**.
2. With no `config/players.yaml` on disk, the page shows an **empty roster and is
   usable**. It is not an error. *(US1 scenario 1, FR-009)*
3. Add a player: id `wade`, name `Wade Brown`, display names `Wade` and `Wade Brown`,
   plays `Soma`. Save.
4. Reload. Both display names come back, **in the order authored**. *(US1 scenario 2,
   FR-003)*
5. `Soma` is not in `party.yaml`, so the row carries a `problems` entry naming the
   unresolved character — and **the save still succeeded**. *(US1 scenario 3, FR-017)*

```bash
cat config/players.yaml          # readable, hand-editable, defaults omitted
```

**Refusals.** Each of these must fail, naming both sides. Try them in the page and
again by hand-editing the file, since both surfaces must refuse the same way:

| Try | Expected |
|---|---|
| A second player with id `wade` | refused, both entries named *(FR-005a)* |
| A second player whose display names include `Wade` | refused, both players and the value named *(FR-005b, US1 scenario 8)* |
| A hand-edited unknown key | load refuses, naming key and entry *(FR-008, US1 scenario 4)* |
| A player with `gm: true` **and** `plays: [Calmer]` | **accepted** *(US1 scenario 5)* |
| Marking a player `active: false` | accepted; display names and bindings intact *(US1 scenario 9)* |

**Timing check (SC-007):** adding a player with two display names and one character
binding, from a cold page, in under two minutes.

---

## Scenario 2 — Adopt out-of-the-abyss (US4 · FR-032…FR-037 · SC-003)

The best adoption subject: 4 of 4 characters carry a `player:`, and its stores are
known to disagree (campaigns#175).

```bash
python -m server.migrate_players_config \
  --campaign-dir ~/src/campaigns/out-of-the-abyss
```

| Expect | Requirement |
|---|---|
| Four players drafted: Gabe, Joe Beda, Ben Pfaff, Mike Hall | FR-032 |
| `Kostadis Roussos` drafted from `session_doc.yaml`'s `gm_player`, with `gm: true` | FR-015 |
| `voice`/`examples` declarations proposed for each character | FR-035 |
| **A conflict list**, not a resolution, wherever `party.yaml` and a sheet disagree | FR-032 |
| A second run **refuses** without `--force` | FR-033, US4 scenario 2 |

Then the campaigns with nothing to harvest:

```bash
python -m server.migrate_players_config --campaign-dir ~/src/campaigns/toee
python -m server.migrate_players_config --campaign-dir ~/src/campaigns/Hillsfar
```

Expect **a nearly empty result, stated as such** — 0 of 4 characters record a player
in either (research M1). Hillsfar's placeholder values must be recorded as *no
display name*, never as a person named `N/A`. *(FR-034, US4 scenario 3)*

And the blocked one:

```bash
python -m server.migrate_players_config --campaign-dir ~/src/campaigns/obelisk
```

Expect a **refusal naming the collision**: its `config/party.yaml` is a PC-name
exclusion list, not a roster, and which use wins is a GM ruling (research D12, M2).
It must not crash, and must not invent a roster.

---

## Scenario 3 — One edit reaches every consumer (US2 · SC-001)

The headline claim. Change one value, in one place, and touch nothing else.

```bash
cd ~/src/campaigns/Phandalin

# Wade's label drifted from "Wade" to "Wade Brown" between recordings.
# Both are already recorded. Add a third and change nothing else.
$EDITOR config/players.yaml        # display_names: [Wade, Wade Brown, wbrown]

scene_extract --party-config config/party.yaml \
              --players-config config/players.yaml \
              ...
```

| Expect | Requirement |
|---|---|
| A line starting `wbrown:` resolves to `Soma` | FR-020, US2 scenario 1 |
| So do `Wade:` and `Wade Brown:` — the old labels still work | FR-003 |
| No sheet was re-converted, and no second file was edited | **SC-001** |
| The prompt roster block names `Wade Brown`, the person | FR-019 |
| The GM's lines carry the game-master label | FR-021, US2 scenario 2 |
| `Mike` and `Mike Hall` in out-of-the-abyss each resolve to their own character | FR-020, US2 scenario 4 |

**FR-021a, the GM who also plays.** In toee, mark `kostadis` as `gm: true` with
`plays: [Calmer]`, then normalise a transcript:

```bash
grep -c '^GM:' out.vtt      # > 0
grep -c '^Calmer:' out.vtt  # 0 — the game-master label always wins
```

**FR-024, the refusal.** Remove a character's binding and re-run: the run must name
that character and exit non-zero **before** the first API call, not render with a
partial map.

---

## Scenario 4 — The Gyrgum replay (US3 · SC-005)

The case three existing detectors missed, in all three of its measured variants.
Work on a scratch copy so the live campaign is untouched.

```bash
cp -r ~/src/campaigns/out-of-the-abyss /tmp/qs-oota
cd /tmp/qs-oota
```

| Variant | Set up | Expect |
|---|---|---|
| **A. As found** | `party.yaml` says `Gyrgum`, files are `grygum_*` | `sd_narrate` **refuses**, naming `Gyrgum` and `voice/grygum_voice.md` *(FR-028, US3 scenario 1)* |
| **B. The partial repair** | rename the roster only | still refuses — there is no fall-through for the file to bleed through *(FR-030a)* |
| **C. Full repair** | rename the files and update the declarations | renders; `Gyrgum` gets its voice and examples *(US3 scenario 4)* |

All three variants are silent today. Variant B is the trap: the obvious one-line fix
currently converts a silent drop into a silent bleed of 12,572 characters.

**Then the second instance, found by Phase 0:**

```bash
players check --campaign-dir ~/src/campaigns/stormgiants
```

Expect `examples/thistl.md` reported as a file nothing declares, and `Thistle`
reported as a character with no examples. Both are silent today (research M3).

---

## Scenario 5 — Shared examples stay shared, deliberately (US3 · FR-030)

toee is the case the old docstring defended: six house-style files, no per-character
examples, 51,073 characters reaching every narrator through the fall-through.

```bash
cd ~/src/campaigns/toee
grep -A 8 '^shared_examples:' config/party.yaml   # all six, declared
players check
```

| Expect | Requirement |
|---|---|
| All six reach every narrator, as intended | US3 scenario 3 |
| **Nothing** reported as mis-routed | US3 scenario 3 |
| An example file removed from `shared_examples` reaches **no** narrator, and is reported as an orphan | FR-030a, FR-030b, US3 scenario 3a |

Same shape for obelisk's `house_style.md` (6,036 characters today).

---

## Scenario 6 — The check (US5 · SC-004)

```bash
cd ~/src/campaigns/out-of-the-abyss
players check                    # exit 0 on a coherent campaign, no tokens spent
echo $?
```

*(US5 scenario 3, FR-040)*

```bash
players check --vtt summaries/62/session.transcript.vtt
```

Point it at a transcript from a **different** campaign and confirm every expected
display name is reported as absent. Then restore three of four and break one: the
check must name **that one**. The existing pre-flight fires only when *zero* match,
which is the case that has never been the problem. *(FR-039, US5 scenario 2)*

Mark a departed player `active: false` and confirm their character is **not**
reported as unplayed. *(FR-011a, FR-038)*

---

## Scenario 7 — Nothing silent survives (SC-002 · SC-006)

The two countable outcomes.

```bash
# SC-006: zero prefix-matched identity joins in the render path.
grep -rn "routes_to\|examples_routing_problems\|_resolve_voice_key" --include=*.py .
# -> no hits outside this spec directory

python -m pytest tests/test_no_prefix_identity.py -q   # the guard test (research D15)
```

```bash
# SC-002: one authored home for a player's identity.
grep -rn "player:" ~/src/campaigns/*/config/party.yaml        # -> nothing
grep -rn "gm_player\|^  characters:" ~/src/campaigns/*/config/session_doc.yaml  # -> nothing
grep -c "^  - id:" ~/src/campaigns/*/config/players.yaml      # -> the one home
```

A retired field left in place must be **refused with a message**, not ignored
(FR-013, FR-037):

```bash
printf 'characters:\n- name: X\n  sheet: x.md\n  player: Someone\n' > /tmp/bad.yaml
python -c "import sys;sys.path.insert(0,'.');from pathlib import Path;\
from campaignlib.party_config import load_party_config;\
load_party_config(Path('/tmp/bad.yaml'))"
# -> ValueError naming the character, the retired field, and the adoption command
```

---

## Final: the after reading

```bash
python3 specs/009-player-entity-service/contracts/measure.py
```

Compared with the **before** reading taken in Prerequisites:

| Section | Before | After |
|---|---|---|
| A — campaigns recording a player | 2 of 6, obelisk unloadable | 5 of 6 in `players.yaml`; obelisk still blocked, **by a named refusal** |
| B — global block reaching every narrator | 6,036 / 7,285 / 51,073 chars in three campaigns, none of it chosen | only what `shared_examples` declares |
| B — narrators with no examples | `Thistle`, plus all four in toee | none unexplained; each one declared or reported |
| B — detector | `[]` in every row, including the broken ones | replaced by a refusal before the run |
| C — voice files no narrator reaches | 4 across 2 campaigns, invisible | the same 4, **reported as orphans** |
