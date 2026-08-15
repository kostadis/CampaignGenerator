# Contract — `/api/players/*`

Mounted by `server/main.py`:

```python
app.include_router(players_routes.router, prefix="/api/players", tags=["players"])
```

**The router must not set `prefix=` itself.** `party_routes.py` records the shipped
bug: setting it in both places mounts everything at `/api/players/api/players/*`.

Per-request dependency injection matches `party_routes.get_party_service`:

```python
def get_players_service(request: Request) -> PlayersConfigService:
    return PlayersConfigService(require_platform(request))
```

## Routes

| Method | Path | Body | Returns | Codes |
|---|---|---|---|---|
| `GET` | `/players` | — | list of player objects, each with a `problems` array | 200, 400 |
| `PUT` | `/players` | list of `Player` | the written list, each with `problems` | 200, 400, 409 |
| `POST` | `/players` | one `Player` | the created player | 201, 400, 409 |
| `GET` | `/players/{id}` | — | one player with `problems` | 200, 404 |
| `PUT` | `/players/{id}` | one `Player` | the updated player | 200, 400, 404, 409 |
| `DELETE` | `/players/{id}` | — | — | 204, 404 |
| `GET` | `/check` | — | the coherence report (read-only) | 200, 400 |

`PUT /players` is the endpoint the page uses. Row order is meaningful and per-row
CRUD cannot express a reorder, so the whole document is replaced in **one atomic
write** — the reasoning in `PartyConfigService.replace_all`'s docstring, where the
delete-all-then-recreate alternative leaves the file momentarily empty.

There are **no `/selection` routes**. This service spends no tokens, so it has no
model or backend override. Every sibling has them; this one deliberately does not.

## Status codes

| Code | When |
|---|---|
| 400 | The document on disk will not load, or the body fails shape validation. Detail names the field and the entry. |
| 404 | No player with that `id`. |
| 409 | Duplicate `id`; or a display name already held by another player. Detail names both sides and the shared value. |
| 204 | Delete succeeded. |

A 409 for a duplicate display name is a **refusal, not a warning** (FR-005b). It is
the one uniqueness rule this service enforces beyond the identifier, and it exists
because two players sharing a label leaves speaker normalisation with two valid
answers.

## The `problems` array — lenient save, reporting read

Every player object carries a `problems` array on the way out. It never blocks a
write (FR-017): the GM must be able to name a character they are about to add.

```json
{
  "id": "ben",
  "name": "Ben Pfaff",
  "display_names": ["Ben Pfaff"],
  "plays": ["Gyrgum"],
  "gm": false,
  "active": true,
  "dndbeyond_id": null,
  "problems": [
    {"kind": "unknown_character", "value": "Gyrgum",
     "detail": "no character named 'Gyrgum' in party.yaml"}
  ]
}
```

`kind` is one of `unknown_character`, `no_display_name`.

This mirrors `PartyConfigService._with_missing`, which attaches `missing_files` to
each character for exactly the same reason (`docs/config/grounding-isolation.md` D4).

## `GET /check`

The same report `players check` prints, as JSON, so the page can show it without
shelling out. Read-only; corrects nothing (FR-040).

```json
{
  "unplayed_characters": ["Thistle"],
  "unknown_characters": [{"player": "gabe", "character": "Zalthir"}],
  "players_without_display_name": ["akritas_player"],
  "undeclared_files": ["voice/vizeran_voice.md", "examples/thistl.md"],
  "missing_declared_files": [{"character": "Gyrgum", "field": "voice",
                              "path": "voice/grygum_voice.md"}],
  "clean": false
}
```

`unplayed_characters` excludes a character played only by an **inactive** player
(FR-011a) — a historical character is not a broken one.
