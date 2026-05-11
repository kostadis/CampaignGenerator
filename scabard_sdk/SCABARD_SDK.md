# Scabard Python SDK

A minimal Python client for the [Scabard](https://www.scabard.com) REST API (`api/v0`).

## Installation

Copy `scabard_client.py` into your project. Install the one dependency:

```bash
pip install requests
```

## Authentication

Every request needs your Scabard username and an API access key.

To get your access key:
1. Go to your Scabard profile page: `https://www.scabard.com/pbs/<username>`
2. Click the down-arrow button → **API Access Key**
3. Copy the key — it expires **24 hours** after generation

**Important**: Store the key securely. Do not commit it to source control. Prompt your users to regenerate if they receive a `ScabardAuthError`.

```python
from scabard_client import ScabardClient

client = ScabardClient(username="stolph", access_key="8301789723432159092")
```

## Quick Start

```python
from scabard_client import ScabardClient, ScabardAuthError

client = ScabardClient(username="you", access_key="your-key")

# List your campaigns
campaigns = client.list_campaigns()
for c in campaigns:
    print(c["id"], c["name"])

# Create a character page
ok, thing_id = client.create_page(
    campaign_id=121,
    concept="character",
    name="Grundar Quartzvein",
    brief_summary="Dwarven blacksmith and reluctant informant.",
    description="## Background\n\nGrundar operates a smithy in Phandalin...",
    secrets="He is working for the Kraken Society.",
)
print(f"Created: {ok}, ID: {thing_id}")

# Update it later
client.update_page(
    campaign_id=121,
    concept="character",
    thing_id=thing_id,
    name="Grundar Quartzvein",
    brief_summary="Dwarven blacksmith, now openly an ally of the party.",
)
```

## Method Reference

### `ScabardClient(username, access_key, timeout=30)`

Constructor. No network call at construction time.

| Parameter | Type | Description |
|---|---|---|
| `username` | `str` | Your Scabard username |
| `access_key` | `str` | API access key (24-hour expiry) |
| `timeout` | `int` | HTTP timeout in seconds (default: 30) |

---

### `list_campaigns() → list[dict]`

Returns all campaigns for which the user is GM.

```python
campaigns = client.list_campaigns()
# [{"id": 121, "name": "Lost Mine of Phandelver", ...}, ...]
```

---

### `get_campaign(campaign_id) → dict`

Returns campaign details plus a summary of every page.

```python
result = client.get_campaign(121)
campaign = result["main"]   # campaign details
pages    = result["rows"]   # list of page summaries
```

---

### `list_pages(campaign_id, concept) → list[dict]`

Returns all pages of a given concept type.

| Parameter | Type | Description |
|---|---|---|
| `campaign_id` | `int` | Campaign ID |
| `concept` | `str` | Page type — see [Concepts](#concepts-reference) |

```python
characters = client.list_pages(121, "character")
# [{"id": 4500, "name": "Grundar Quartzvein", ...}, ...]
```

---

### `get_page(campaign_id, concept, thing_id) → dict`

Returns full details for a specific page.

```python
page = client.get_page(121, "character", 4500)
print(page["name"])
print(page["description"])
```

---

### `fetch_existing(campaign_id, concept) → dict[str, int]`

Returns a `{name: thing_id}` mapping for all pages of a concept. Useful for checking existence before creating.

```python
existing = client.fetch_existing(121, "character")
if "Grundar Quartzvein" in existing:
    thing_id = existing["Grundar Quartzvein"]
```

---

### `list_connection_types(concept) → list[dict]`

Returns the catalog of valid connection (relationship) types for a given concept. Connection types are shared across all campaigns — there is **no `campaign_id`** in the URL.

| Parameter | Type | Description |
|---|---|---|
| `concept` | `str` | Source concept (lowercase): `"character"`, `"group"`, `"place"`, `"event"`, etc. |

Each returned dict has these keys:

| Key | Type | Description |
|---|---|---|
| `rel` | `str` | Relationship label (e.g. `"Acquaintance of"`, `"Steward"`) |
| `source` | `str` | Source concept, Title Case — matches the URL concept (e.g. `"Character"` for `/conntypes/character`) |
| `target` | `str` | Target concept, Title Case (e.g. `"Event"`, `"Place"`) |
| `isSymmetric` | `bool` | Whether the relationship is bidirectional. Present on every live entry observed; treat missing as `False` defensively. |
| `postParam` | `str` | Undocumented in the API reference — looks like the parameter token for a future connection-CRUD endpoint (e.g. `"acquaintance_of:character"`, `"steward_of:place"`). Not consumed by the SDK; surfaced for experimentation. |

```python
conn_types = client.list_connection_types("character")
for ct in conn_types:
    arrow = "↔" if ct.get("isSymmetric") else "→"
    print(f"{ct['source']} —[{ct['rel']}]{arrow} {ct['target']}")
# Character —[Acquaintance of]→ Character
# Character —[Ally of]↔ Character
# Character —[Steward of]→ Place
# ...
```

---

### `create_connections(campaign_id, concept, thing_id, connections) → tuple[bool, dict]`

Creates one or more connections from a single source page to other pages. Multiple connections are sent in a single API call.

| Parameter | Type | Description |
|---|---|---|
| `campaign_id` | `int` | Campaign ID |
| `concept` | `str` | Source page concept (lowercase) |
| `thing_id` | `int` | Source page ID |
| `connections` | `dict[str, str]` | `{postParam: target_page_name}` — postParams come from `list_connection_types(concept)` |

The target page is resolved server-side by **exact name match** — the value is the target's name, not its `thing_id`. The target must already exist.

**Returns**: `(isSuccess, {postParam: record})`. Each `record` dict contains:

| Key | Type | Description |
|---|---|---|
| `relId` | `int` | New connection ID. The only handle for this edge — persist it if you need to reference the connection later. |
| `uri` | `str` | Path to the resolved target page (e.g. `/campaign/121/place/158`) |
| `value` | `str` | The target page's name as resolved server-side |
| `isFormer` | `bool` | Whether the connection is marked "former" (always `False` on a fresh create — the request shape for setting it is undocumented) |
| `isSecret` | `bool` | Whether the connection is GM-only (always `False` on a fresh create — request shape undocumented) |

```python
# Discover a valid postParam from the connection-type catalog
conn_types = client.list_connection_types("character")
mother_of = next(ct for ct in conn_types
                 if ct["rel"] == "Mother of" and ct["target"] == "Character")

ok, records = client.create_connections(
    campaign_id=121,
    concept="character",
    thing_id=4500,           # Cersei
    connections={
        mother_of["postParam"]: "Joffrey",
        "home:place":           "King's Landing",
    },
)
for post_param, record in records.items():
    print(f"{post_param} → {record['value']} (relId={record['relId']})")
```

**Notes:**
- The API does not (yet) expose update / delete / list-existing connection endpoints. The returned `relId` is the only handle for an edge.
- The official docs show this endpoint accepting form-encoded `-d key=value` pairs. **Empirically (verified 2026-05-10), the live server only accepts JSON** — form-encoded requests return `200 {"isSuccess": false}` with no error detail. The SDK sends JSON for this reason; callers don't see the wire format either way.

---

### `create_page(campaign_id, concept, name, ...) → tuple[bool, int | None]`

Creates a new page. Because the API does not return the new page's ID in the create response, this method re-fetches the page list to discover it.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `campaign_id` | `int` | required | Campaign ID |
| `concept` | `str` | required | Page concept (lowercase) |
| `name` | `str` | required | Page name |
| `brief_summary` | `str` | `""` | 1-2 sentence player-facing summary |
| `description` | `str` | `""` | Full player-facing markdown body |
| `secrets` | `str` | `""` | GM-only text (hidden from players) |
| `gm_secrets` | `str` | `""` | Additional GM-only notes |
| `is_secret` | `bool` | `False` | Mark page as secret |

**Returns**: `(True, thing_id)` on success, `(True, None)` if ID could not be discovered, `(False, None)` if the API reported failure.

```python
ok, thing_id = client.create_page(
    campaign_id=121,
    concept="location",
    name="Tresendar Manor",
    brief_summary="Ruined manor on the east edge of Phandalin.",
    description="The manor has a dungeon beneath it...",
    secrets="The Redbrands use the dungeon as their hideout.",
)
```

---

### `update_page(campaign_id, concept, thing_id, name, ...) → bool`

Updates an existing page. All text fields default to empty string — omitted fields will be cleared on the page.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `campaign_id` | `int` | required | Campaign ID |
| `concept` | `str` | required | Page concept (lowercase) |
| `thing_id` | `int` | required | Page ID |
| `name` | `str` | required | Page name |
| `brief_summary` | `str` | `""` | Short player-facing summary |
| `description` | `str` | `""` | Full player-facing markdown body |
| `secrets` | `str` | `""` | GM-only text |
| `gm_secrets` | `str` | `""` | Additional GM-only notes |
| `is_secret` | `bool` | `False` | Mark page as secret |

**Returns**: `True` if the API reported success, `False` otherwise.

```python
ok = client.update_page(
    campaign_id=121,
    concept="character",
    thing_id=4500,
    name="Grundar Quartzvein",
    brief_summary="Dwarven blacksmith, now an ally.",
    description="...",
)
```

---

## Exception Reference

All exceptions inherit from `ScabardError`.

| Exception | HTTP Status | Cause |
|---|---|---|
| `ScabardAuthError` | 401 | Invalid username or expired access key |
| `ScabardForbiddenError` | 403 | Valid credentials but no access to the resource |
| `ScabardNotFoundError` | 404 | Resource does not exist |
| `ScabardRateLimitError` | 429 | Rate limit exhausted after 4 retries |
| `ScabardError` | — | Base class; catch this to handle any Scabard error |

Each exception exposes:
- `.status_code` — the HTTP status code
- `.detail` — the raw response body

```python
from scabard_client import ScabardAuthError, ScabardError

try:
    campaigns = client.list_campaigns()
except ScabardAuthError:
    print("Key expired — please generate a new API key on your profile page.")
except ScabardError as e:
    print(f"API error {e.status_code}: {e}")
```

## Rate Limiting and Retries

The client retries automatically on `429 Too Many Requests` with exponential backoff:

| Attempt | Wait before retry |
|---|---|
| 1 | 5 seconds |
| 2 | 10 seconds |
| 3 | 20 seconds |
| 4 | 40 seconds (final) |

After 4 failed attempts, `ScabardRateLimitError` is raised.

When making bulk requests (e.g. syncing many pages), add a short delay between calls to avoid hitting the rate limit:

```python
import time

for entity in entities:
    client.create_page(campaign_id, concept, **entity)
    time.sleep(0.5)
```

## Key Expiry

Access keys expire **24 hours** after generation. If you are building an app:

1. Prompt your users for their key each session — do not store it persistently
2. Catch `ScabardAuthError` and redirect the user to their profile page to regenerate
3. Profile URL: `https://www.scabard.com/pbs/<username>`

## Common Patterns

### Sync a list of entities (create or update)

```python
existing = client.fetch_existing(campaign_id, concept)

for entity in entities:
    name = entity["name"]
    if name in existing:
        client.update_page(campaign_id, concept, existing[name], **entity)
    else:
        ok, thing_id = client.create_page(campaign_id, concept, **entity)
        if ok and thing_id:
            existing[name] = thing_id
    time.sleep(0.5)
```

### Check if a page exists before creating

```python
existing = client.fetch_existing(121, "character")
if "Grundar Quartzvein" not in existing:
    client.create_page(121, "character", name="Grundar Quartzvein", ...)
```

### Handle auth errors gracefully

```python
from scabard_client import ScabardAuthError, ScabardRateLimitError

try:
    client.sync(...)
except ScabardAuthError:
    print("Your API key has expired. Generate a new one at scabard.com.")
    sys.exit(1)
except ScabardRateLimitError:
    print("Too many requests. Wait a few minutes and try again.")
    sys.exit(1)
```

## Concepts Reference

Concepts are the page types Scabard supports. Use the lowercase string in API calls.

| Concept | Description |
|---|---|
| `character` | Named NPCs and player characters |
| `group` | Factions, guilds, cults, organisations |
| `location` | Named places: cities, dungeons, keeps, regions |
| `event` | Campaign events: battles, discoveries, deaths |

Additional concepts may be available — check the Scabard UI for the full list. Any concept shown in the UI can be used in the API.

## Running the Integration Tests

A standalone test script is included to verify the API is working with your credentials:

```bash
python test_scabard_api.py \
    --username <username> \
    --access-key <key> \
    --campaign-id <id>
```

This creates a temporary test page, exercises all endpoints, then marks the page for deletion. Use `--keep` to skip cleanup and inspect the created page in Scabard.
