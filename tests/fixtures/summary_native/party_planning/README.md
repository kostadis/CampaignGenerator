# party_planning fixture (spec 034)

A second campaign root, used with `tests/conftest_party.py`. Kept apart from `../state/` so that nothing
added for party, threads and planning can move a spec 033 test.

| Path | Seeds |
|---|---|
| `docs/summaries/002-004` | Ch 2: the party "reaches 9th level" (002.01), a "4th-level slot" (002.02), the companion Ront, a tinker called Dazz (not an entity), the Carver's march and a signet ring. Ch 3: "the Carver march" (a drifted name), a "9th-level spell scroll", House Mizzrym. Ch 4: the march breaks, the ring is lost, Daz is wounded. |
| `config/players.yaml` | Joe plays Daz, Amy plays Zalthir. |
| `config/party.yaml` | Daz (sheet says Level 8, backstory, an arc-score mechanic file) and Zalthir (sheet gives no level, `arc_score: null`: trackless). |
| `config/planning.yaml` | NPC Ilvara Mizzrym (published dossier, an arc-score mechanic file); faction House Mizzrym (trackless). |
| `docs/entity_registry.yaml` | Ilvara Mizzrym (alias Ilvara), Ront (a companion, not a player character), House Mizzrym, Brindol. Daz and Zalthir are deliberately absent: they are player characters through `players.yaml` and `party.yaml`. |
| `docs/thread_registry.yaml` | `carver-march` ("The Carver's march", alias "Carver march", open) and `signet-ring` (GM-set `resolved`). |
| `docs/npcs/ilvara-mizzrym.md` | A published dossier (`verify: pass`, correct body sha) with Identity, Personality and Motivations, Last Observed State, Relationships, and a `## Secrets` holding `SECRET-CANARY-034`. |

`tests/conftest_party.py` holds the canned extraction (`CANNED_PARTY`) and runs the real code check over
it (`checked_results()`), so the notes the tests use are what `extract` would keep: `[LEVEL] **Party** — 9`
survives, the two spell-level `[LEVEL]` rows and the subject-less bullet are dropped.
