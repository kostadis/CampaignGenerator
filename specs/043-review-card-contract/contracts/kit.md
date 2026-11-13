# Contract: the shared review kit (mytools)

The kit lives at `dotfiles/shared/skills/_shared/review-artifact/`, and is linked as `~/.claude/skills/_shared/review-artifact` and `~/.codex/skills/_shared/review-artifact` (research R12). This feature changes the kit in the ways below. Every other per-skill items and decisions format is unchanged.

| File | After this feature |
|---|---|
| `build_review.py` | It gains `--save artifact\|local`, defaulting to `artifact` (today's Claude page). `local` is the retired Codex page's save surface: Copy output, a Save output download, and Save to VM when served. Extra card fields (`members`, `draftSha256`) pass through, as they do today. |
| `read_decisions.py` | It has three modes. `--html` is today's Claude mode, minus the class-card expansion. `--in decisions.json` is the Codex mode, with its `normalize()`. `--npc --html SAVED --review REVIEW --out FILE` writes a CampaignGenerator decisions file (card-files.md) from the saved page's state and `ITEMS`. |
| `npc_review_items.py` | A shim. It runs `summary_native review cards export REVIEW [--item …] [--action …] --out TMP --json`, maps each card to a kit item with every text field HTML-escaped, and sets `reviewId = packetId`. It reads no store file. |
| `serve_review.py` | Moved from the Codex fork unchanged, and imports `normalize` from `read_decisions.py`. |
| `CONTRACT.md` | One document. The NPC section points at CampaignGenerator's `contracts/card-files.md` and the two commands. The hand-translation instructions are deleted. |
| `tests/` | Both kits' tests are merged. New tests cover the shim (no store reads, escaping, and `members`/`draftSha256` reaching the page), the `--npc` reader (echoes come from the saved page) and the `--save local` page. |

## The NPC loop, end to end

```text
summary_native review cards export R --out /tmp/p.json --json      # via npc_review_items.py
build_review.py --in items.json --out page.html                    # publish / serve
… GM marks and saves …
read_decisions.py --npc --html saved.html --review R --out d.json
summary_native review cards decide R --decisions d.json --reviewer GM          # plan; show it to the GM
summary_native review cards decide R --decisions d.json --reviewer GM --write --plan-sha256 H
```

The agent never builds a decision batch by hand, and never runs `review decide` or `review npc sign` for page verdicts.
