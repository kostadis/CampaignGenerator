# CLAUDE.md — scabard_sdk

Python SDK for the [Scabard](https://www.scabard.com) world-building tool REST API.

## Structure

```
scabard_sdk/
  __init__.py          # re-exports all public symbols
  scabard_client.py    # ScabardClient class + exceptions
  test_scabard_api.py  # integration test script (standalone, requires live credentials)
  SCABARD_SDK.md       # user-facing documentation
  CLAUDE.md            # this file
```

## Usage

```python
from scabard_sdk import ScabardClient, ScabardAuthError

client = ScabardClient(username="you", access_key="your-key")
campaigns = client.list_campaigns()
ok, thing_id = client.create_page(campaign_id=121, concept="character", name="Grundar")
```

Run tests from the **project root**:
```bash
python -m scabard_sdk.test_scabard_api --username <u> --access-key <k> --campaign-id <id>
```

## ScabardClient methods

| Method | Returns | Description |
|---|---|---|
| `list_campaigns()` | `list[dict]` | All campaigns the user is GM of |
| `get_campaign(campaign_id)` | `dict` | Campaign details (`main`) + page summaries (`rows`) |
| `list_pages(campaign_id, concept)` | `list[dict]` | All pages of a concept |
| `get_page(campaign_id, concept, thing_id)` | `dict` | Single page details |
| `fetch_existing(campaign_id, concept)` | `dict[str, int]` | `{name: thing_id}` map for all pages |
| `create_page(campaign_id, concept, name, ...)` | `tuple[bool, int \| None]` | Create page; re-fetches list to discover new ID |
| `update_page(campaign_id, concept, thing_id, name, ...)` | `bool` | Update existing page |
| `list_connection_types(concept)` | `list[dict]` | Catalog of valid connection types for a concept (campaign-agnostic) |
| `create_connections(campaign_id, concept, thing_id, connections)` | `tuple[bool, dict[str, dict]]` | Create one or more connections from a page to other pages by name |

`create_page` and `update_page` share the same optional keyword fields:
`brief_summary`, `description`, `secrets`, `gm_secrets`, `is_secret`.

## Exceptions

All inherit from `ScabardError(Exception)`. Each has `.status_code` and `.detail` attributes.

| Exception | HTTP | Cause |
|---|---|---|
| `ScabardAuthError` | 401 | Bad or expired credentials |
| `ScabardForbiddenError` | 403 | No access to the resource |
| `ScabardNotFoundError` | 404 | Resource does not exist |
| `ScabardRateLimitError` | 429 | Exhausted after 4 retries |
| `ScabardError` | 5xx | Server error (base class) |

## Undocumented API behaviours (discovered via integration testing)

These differ from what the official API docs describe — handle them accordingly:

1. **Invalid campaign IDs return 500**, not 404/403. The SDK wraps all 5xx as `ScabardError`.
2. **List endpoint returns `"uri"` not `"id"`**. `fetch_existing` parses the thing_id from the URI path (`/campaign/{id}/{concept}/{thing_id}`).
3. **Concept casing rule: URLs are lowercase, data values are Title Case.** URL path segments use lowercase (`/campaign/{id}/character`); response bodies and request body fields use Title Case (`"concept": "Character"`, `source: "Place"`, `target: "Event"`). The SDK applies `.title()` to body `concept` fields automatically.
4. **Create response does not return the new page's ID.** `create_page` re-fetches the page list after a 1-second pause to discover the ID by name match.
5. **Connection-type entries always include `isSymmetric` in live responses.** The docs example shows entries without the field, but live testing across `character`/`place`/`event`/`group` (226 entries total) had `isSymmetric` on every entry. The SDK still defensively treats absence as `False` (`.get("isSymmetric", False)`) — harmless, in case the docs example reflects a real edge case.
6. **`postParam` is the form key consumed by `POST .../connect`.** As of the 2026-05 docs update, the previously-undocumented `postParam` field returned by `list_connection_types` is officially the form-parameter key the new connection endpoint accepts. Format is `{snake_rel}:{lowercase_target}` (e.g. `mother_of:character`, `steward:character`). `create_connections` takes a `{postParam: target_name}` dict, so callers should pull postParams from `list_connection_types(concept)` rather than hand-constructing them.

7. **`POST .../connect` docs lie about the body format.** The official docs show form-encoded `-d key=value` pairs (with `:` in keys, e.g. `mother_of:character=Khal`). Empirically (verified 2026-05-10 against the live API), form-encoded requests return `200 {"isSuccess": false}` with no error detail — the endpoint only accepts JSON. The SDK sends JSON via the standard `_post` helper. Same content type as every other POST in the SDK; no special encoding path. If the server later starts accepting form bodies the SDK won't need to change, but flag this if the docs get updated.

8. **`/connect` resolves the target by name, not `thing_id`.** The value side of each connection entry is the **exact name** of an existing target page. Callers must ensure the target exists and the name matches case-sensitively. The response includes the resolved `uri` (`/campaign/{id}/{concept}/{thing_id}`) so callers can recover the target ID after the fact.

9. **`/connect` response uses postParam strings as keys.** Response shape is `{"isSuccess": bool, "{postParam}": {relId, uri, value, isFormer, isSecret}, ...}` — the connection records sit at the top level alongside `isSuccess` rather than under a wrapper key. `create_connections` separates them: returns `(isSuccess, {postParam: record})`. `relId` is the **only handle** for an edge once created — there is no list-connections endpoint yet, so persist it if needed.

10. **Canonical concept list is now official.** The 2026-05 docs enumerate concepts as `character, place, group, item, event, vehicle, category, attribute, note, folder`. Note `place`, **not** `location` — `list_connection_types` confirms (`source: "Place"`). The project's `scabard_sync.py` and outer `SCABARD_SDK.md` "Concepts Reference" table still use `location` and have never been verified against the live API for that concept. Worth a focused pass on `scabard_sync.py` next; not addressed in this SDK update.

## Rate limiting

`_post` retries on 429 with exponential backoff: 4 attempts, waits of 5s / 10s / 20s / 40s. Raises `ScabardRateLimitError` if all attempts fail.

For bulk operations, add `time.sleep(0.4)` between calls (as `scabard_sync.py` does).

## Authentication

- Headers: `username` + `accessKey`
- Keys expire **24 hours** after generation
- Generated at: `https://www.scabard.com/pbs/<username>` → down-arrow → API Access Key

## Adding new methods

All HTTP calls must go through `_get()` or `_post()` — never call `requests` directly in public methods. This ensures consistent error handling and rate-limit retry across all endpoints.
