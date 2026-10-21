# CLAUDE.md — scabard_sdk

Python SDK for the [Scabard](https://www.scabard.com) world-building tool REST API.

## Structure

```
scabard_sdk/
  __init__.py          # re-exports all public symbols
  scabard_client.py    # ScabardClient, data types, exceptions
  scabard_sync.py      # campaign docs → Scabard pages (LLM extract, then sync)
  test_scabard_api.py  # integration test script (standalone, requires live credentials)
  SCABARD_SDK.md       # user-facing documentation
  CLAUDE.md            # this file
```

Unit tests (no network) live in `tests/test_scabard_client.py` at the repo root.

## Usage

```python
from scabard_sdk import ScabardClient

client = ScabardClient(username="you", access_key="your-key")
campaigns = client.list_campaigns()                     # list[Campaign]
thing_id = client.create_page(121, "character", "Grundar", aliases=["Grundar Q."])
client.update_page(121, "character", thing_id, secrets="Kraken Society.")  # partial
page = client.get_page(121, "character", thing_id)      # Page, with .connections
```

Run the live tests from the **project root**:
```bash
python -m scabard_sdk.test_scabard_api --username <u> --access-key <k> --campaign-id <id>
```
They create two pages and one connection per run, and the API cannot delete them.

## ScabardClient methods

| Method | Returns | Description |
|---|---|---|
| `list_campaigns()` | `list[Campaign]` | Campaigns the user is GM of (`id` parsed from the uri) |
| `get_campaign(campaign_id)` | `dict` | Raw response: `main` + `rows` (page summaries) |
| `list_pages(campaign_id, concept)` | `list[dict]` | Summary rows for a concept |
| `fetch_existing(campaign_id, concept)` | `dict[str, int]` | `{name: thing_id}` |
| `get_page(campaign_id, concept, thing_id)` | `Page` | Fields, `aliases: list[str]`, `last_edited`, `connections` |
| `create_page(campaign_id, concept, name, *, ...)` | `int \| None` | New page's thing_id (found by re-listing) |
| `update_page(campaign_id, concept, thing_id, *, ...)` | `Page` | **Partial update**: reads the page, overlays the fields passed, saves all |
| `list_connection_types(concept)` | `list[dict]` | Connection-type catalog (no campaign_id) |
| `list_connections(campaign_id, concept, thing_id)` | `list[Connection]` | A page's edges, from its `conns` |
| `create_connections(campaign_id, concept, thing_id, connections)` | `dict[str, dict]` | `{postParam: record}` |

Page fields (keyword-only): `brief_summary`, `description`, `secrets`, `gm_secrets`, `is_secret`, `aliases` (`list[str]`). On `update_page` every field defaults to `None`, meaning "keep"; pass `""` or `[]` to clear.

Every `concept` goes through `normalize_concept`, which accepts any case and raises `ValueError` for anything outside `CONCEPTS` (and names `place` when given `location`).

## Exceptions

All inherit from `ScabardError(Exception)`. Each has `.status_code` and `.detail` attributes.

| Exception | HTTP | Cause |
|---|---|---|
| `ScabardAuthError` | 401 | Bad or expired credentials |
| `ScabardForbiddenError` | 403 | No access to the resource |
| `ScabardNotFoundError` | 404 | Invalid uri (includes unknown concepts on the server side) |
| `ScabardRateLimitError` | 429 | Exhausted after 4 retries |
| `ScabardRequestError` | 200 | Write answered `isSuccess: false`; `.response` has the body |
| `ScabardError` | 5xx | Server error (base class) |

## API behaviours the docs don't describe (verified against the live API)

1. **Invalid campaign IDs return 500**, not 404/403.
2. **Rows carry `"uri"`, not `"id"`**, for campaigns and pages. The SDK parses ids from `/campaign/{id}/{concept}/{thing_id}` (`PageRef.from_uri`).
3. **Casing: URLs are lowercase, data values are Title Case** (`"concept": "Character"`, `source: "Place"`). The SDK title-cases body `concept`.
4. **Create returns only `isSuccess`.** `create_page` re-lists the concept after a 1-second pause and matches by name.
5. **Every connection-type entry has `isSymmetric`** (226 sampled).
6. **`postParam` is the key `/connect` takes**, formatted `{snake_rel}:{lowercase_target}`. Take it from `list_connection_types`; don't build it by hand.
7. **Bodies must be JSON.** The docs show form-encoded `-d` pairs everywhere. On the live API a form body to `/connect` answers `200 {"isSuccess": false}` (2026-05-10) and a form body to a page save answers **500** (2026-10-21). `_request` always sends JSON.
8. **`/connect` resolves the target by exact name** and returns its `uri`.
9. **`/connect` puts records at the top level**, keyed by postParam, next to `isSuccess`.
10. **Concept list:** `character, place, group, item, event, vehicle, category, attribute, note, folder`. **`location` 404s** (it is `place`). **`category` is listed but 404s** on the live API (2026-10-21); it stays in `CONCEPTS` because the docs list it.
11. **`aliases`** is a comma-separated string on every page and row. A JSON save with it stores it; a JSON save that omits it keeps the old value (2026-10-21). The SDK refuses an alias containing a comma.
12. **Page GETs return connections.** Besides `main`, the response has `conns` (each: `rel`, `explicit`, `name`, `uri`, `concept`, `isSecret`, `score`), plus `gm`, `isEditable`, `subscription`, `campaignDates`, `ancestors`. There is **no `relId`** on the read side, so edges are matched by `(rel, target)`.
13. **Newlines are collapsed.** A description saved with `\n\n` comes back with a single space in their place, so Markdown headings and lists do not survive. `description` and `rawDescription` have been identical on every page sampled. Open question for the API author: does `description` take HTML?
14. **No DELETE** for pages or connections. Test runs leave pages behind.

## Rate limiting

`_request` retries on 429 with exponential backoff: 4 attempts, waits of 5s / 10s / 20s / 40s. Raises `ScabardRateLimitError` if all attempts fail.

For bulk operations, add `time.sleep(0.4)` between calls (as `scabard_sync.py` does). `update_page` makes two calls (a GET and a POST).

## Authentication

- Headers: `username` + `accessKey`
- Keys expire **24 hours** after generation
- Generated at: `https://www.scabard.com/pbs/<username>` → down-arrow → API Access Key

## Adding new methods

All HTTP calls go through `_request()` (via `_get()` / `_post()`) — never call `requests` directly in public methods. That keeps error handling, JSON bodies, `isSuccess` checking and rate-limit retry the same across every endpoint. Validate concepts with `normalize_concept` / `_page_url`.
