# Scabard Python SDK

A small Python client for the [Scabard](https://www.scabard.com) REST API (`api/v0`).

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

client = ScabardClient(username="you", access_key="your-key")
```

## Quick Start

```python
from scabard_client import ScabardClient

client = ScabardClient(username="you", access_key="your-key")

for campaign in client.list_campaigns():
    print(campaign.id, campaign.name)

# Create a character page
thing_id = client.create_page(
    121, "character", "Grundar Quartzvein",
    brief_summary="Dwarven blacksmith and reluctant informant.",
    description="Operates a smithy in Phandalin.",
    secrets="He is working for the Kraken Society.",
    aliases=["Grundar"],
)

# Change one field; everything else on the page is kept
client.update_page(121, "character", thing_id,
                   brief_summary="Dwarven blacksmith, now openly an ally of the party.")

page = client.get_page(121, "character", thing_id)
print(page.name, page.aliases, [c.rel for c in page.connections])
```

## Concepts

A concept (page type) is one of:

`character`, `place`, `group`, `item`, `event`, `vehicle`, `category`, `attribute`, `note`, `folder`

Pass it in any case; the SDK sends lowercase in URLs and Title Case in bodies. Anything else raises `ValueError` before a request is made. **`location` is not a concept; use `place`.** (`category` is in the official list, but the live API answered 404 for it on 2026-10-21.)

## Data types

| Type | Fields |
|---|---|
| `Campaign` | `id`, `name`, `raw` |
| `PageRef` | `campaign_id`, `concept`, `thing_id`; `.uri`; `PageRef.from_uri(uri)` |
| `Page` | `ref`, `name`, `brief_summary`, `description`, `secrets`, `gm_secrets`, `is_secret`, `aliases` (`list[str]`), `last_edited` (`datetime` or `None`), `connections`, `raw` |
| `Connection` | `rel` (e.g. `"Paramour of"`), `explicit` (`"Is Paramour of"`), `target` (`PageRef`), `target_name`, `is_secret` |

## Method Reference

### Campaigns

- **`list_campaigns() → list[Campaign]`** — campaigns you are GM of.
- **`get_campaign(campaign_id) → dict`** — the raw response: `main` (campaign details) and `rows` (a summary of every page).

### Pages

- **`list_pages(campaign_id, concept) → list[dict]`** — summary rows (`name`, `uri`, `aliases`, `briefSummary`, `isSecret`, ...).
- **`fetch_existing(campaign_id, concept) → dict[str, int]`** — `{name: thing_id}`.
- **`get_page(campaign_id, concept, thing_id) → Page`** — one page, with its connections.

#### `create_page(campaign_id, concept, name, *, ...) → int | None`

| Keyword | Type | Default |
|---|---|---|
| `brief_summary` | `str` | `""` |
| `description` | `str` | `""` |
| `secrets` | `str` | `""` (GM-only) |
| `gm_secrets` | `str` | `""` (GM-only) |
| `is_secret` | `bool` | `False` |
| `aliases` | `list[str]` | `[]` |

Returns the new page's `thing_id`. The API's create response carries no id, so the SDK re-lists the concept and matches by name; it returns `None` if the page can't be found that way (for example, if two pages share the name).

#### `update_page(campaign_id, concept, thing_id, *, ...) → Page`

Takes the same keywords plus `name`, all defaulting to `None`. **Only the fields you pass change.** The SDK reads the page, applies your changes, and saves the whole page. Pass `""` (or `[]` for `aliases`) to clear a field. Returns the page as saved.

### Connections

- **`list_connection_types(concept) → list[dict]`** — the catalog for a source concept, shared across campaigns. Each entry has `rel`, `source`, `target`, `isSymmetric` and `postParam`.
- **`list_connections(campaign_id, concept, thing_id) → list[Connection]`** — a page's existing edges.
- **`create_connections(campaign_id, concept, thing_id, connections) → dict[str, dict]`** — `connections` is `{postParam: target_page_name}`; targets are matched by exact name and must exist. Returns `{postParam: record}`, where each record has `relId`, `uri`, `value`, `isFormer` and `isSecret`.

```python
types = client.list_connection_types("character")
home = next(t for t in types if t["rel"] == "Home" and t["target"] == "Place")

existing = {(c.rel, c.target_name) for c in client.list_connections(121, "character", 4500)}
if ("Home", "Phandalin") not in existing:
    client.create_connections(121, "character", 4500, {home["postParam"]: "Phandalin"})
```

The API cannot update or delete a connection, and posting one twice is not known to be idempotent, so check `list_connections` first.

## Limits of the API

- **No DELETE** for pages or connections.
- **Newlines in text fields are collapsed to spaces**, so Markdown structure in `description` does not survive.
- **Bodies must be JSON.** The official docs show form-encoded examples; on the live API they fail (`/connect` answers `isSuccess: false`, page saves answer 500). The SDK always sends JSON.

## Exception Reference

All exceptions inherit from `ScabardError` and expose `.status_code` and `.detail`.

| Exception | HTTP Status | Cause |
|---|---|---|
| `ScabardAuthError` | 401 | Invalid username or expired access key |
| `ScabardForbiddenError` | 403 | Valid credentials but no access to the resource |
| `ScabardNotFoundError` | 404 | Invalid uri |
| `ScabardRateLimitError` | 429 | Rate limit exhausted after 4 retries |
| `ScabardRequestError` | 200 | A write answered `isSuccess: false`; `.response` holds the body |
| `ScabardError` | 5xx | Base class; catch this to handle any Scabard error |

## Rate Limiting and Retries

The client retries `429 Too Many Requests` with exponential backoff: waits of 5, 10, 20 and 40 seconds, then raises `ScabardRateLimitError`.

For bulk work, pause between calls (`time.sleep(0.4)`). `update_page` makes two requests.

## Running the Integration Tests

```bash
python test_scabard_api.py \
    --username <username> \
    --access-key <key> \
    --campaign-id <id>
```

The script creates two test pages and one connection, checks every endpoint (including that a partial update keeps untouched fields), then relabels the pages `[TEST PAGE - SAFE TO DELETE]`. Delete them by hand in Scabard. Use `--keep` to skip the relabel.
