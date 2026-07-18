"""
Minimal Kanka CE REST API client.
Covers the entity types needed for campaign world-building.

Usage (manual smoke test — this file has no console-script entry, it's a
library used by kanka_mcp / kanka_push / kanka_sync):
    python pipelines/integrations/kanka/kanka_client.py

Requires:
    pip install requests
"""

import os
import sys

import requests

KANKA_BASE_URL = os.environ.get("KANKA_BASE_URL", "http://localhost:8081")
KANKA_TOKEN = os.environ.get("KANKA_TOKEN", "")
API_BASE = f"{KANKA_BASE_URL}/api/1.0"


class KankaClient:
    def __init__(self, token: str, base_url: str = KANKA_BASE_URL):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.base = f"{base_url}/api/1.0"

    def _get(self, path: str) -> dict:
        r = self.session.get(f"{self.base}{path}")
        r.raise_for_status()
        return r.json()

    def _get_all(self, path: str) -> list:
        """Follow Kanka's pagination (30/page) and return every record.

        List endpoints page at 30 rows; `links.next` carries an absolute URL.
        Without this, a campaign with >30 NPCs silently loses the tail.
        """
        out: list = []
        url = f"{self.base}{path}"
        while url:
            r = self.session.get(url)
            r.raise_for_status()
            body = r.json()
            out.extend(body.get("data", []))
            url = (body.get("links") or {}).get("next")
        return out

    def _post(self, path: str, data: dict) -> dict:
        r = self.session.post(f"{self.base}{path}", json=data)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, data: dict) -> dict:
        r = self.session.patch(f"{self.base}{path}", json=data)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        r = self.session.delete(f"{self.base}{path}")
        r.raise_for_status()

    # ── Campaigns ────────────────────────────────────────────────────────────

    def list_campaigns(self) -> list:
        return self._get("/campaigns")["data"]

    def create_campaign(self, name: str, locale: str = "en") -> dict:
        return self._post("/campaigns", {"name": name, "locale": locale})["data"]

    # ── Locations ─────────────────────────────────────────────────────────────

    def list_locations(self, campaign_id: int) -> list:
        return self._get(f"/campaigns/{campaign_id}/locations")["data"]

    def create_location(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/locations", {"name": name, **kwargs})["data"]

    def get_location(self, campaign_id: int, location_id: int) -> dict:
        return self._get(f"/campaigns/{campaign_id}/locations/{location_id}")["data"]

    # ── Characters ────────────────────────────────────────────────────────────

    def list_characters(self, campaign_id: int) -> list:
        return self._get(f"/campaigns/{campaign_id}/characters")["data"]

    def create_character(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/characters", {"name": name, **kwargs})["data"]

    # ── Organisations ─────────────────────────────────────────────────────────

    def list_organisations(self, campaign_id: int) -> list:
        return self._get(f"/campaigns/{campaign_id}/organisations")["data"]

    def create_organisation(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/organisations", {"name": name, **kwargs})["data"]

    # ── Events ────────────────────────────────────────────────────────────────

    def list_events(self, campaign_id: int) -> list:
        return self._get_all(f"/campaigns/{campaign_id}/events")

    def create_event(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/events", {"name": name, **kwargs})["data"]

    # ── Notes ─────────────────────────────────────────────────────────────────

    def list_notes(self, campaign_id: int) -> list:
        return self._get_all(f"/campaigns/{campaign_id}/notes")

    def create_note(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/notes", {"name": name, **kwargs})["data"]

    # ── Paginated list helpers (full-campaign pulls) ──────────────────────────

    def list_all(self, campaign_id: int, entity_type: str) -> list:
        """Return every record of `entity_type` for a campaign, all pages.

        entity_type: one of locations, characters, organisations, events, notes.
        """
        return self._get_all(f"/campaigns/{campaign_id}/{entity_type}")

    # ── Generic create / update (uniform dispatch for sync tools) ─────────────

    def create(self, campaign_id: int, entity_type: str, **fields) -> dict:
        """Create one `entity_type` record.

        Generic counterpart to the per-type create_* methods, so a sync loop can
        dispatch by entity_type string without a method table.
        `fields` must include `name`.
        """
        return self._post(f"/campaigns/{campaign_id}/{entity_type}", fields)["data"]

    def update(self, campaign_id: int, entity_type: str, record_id: int,
               **fields) -> dict:
        """PATCH one existing `entity_type` record.

        entity_type: locations, characters, organisations, events, notes.
        Only the supplied `fields` are changed; omitted fields keep their value.
        """
        return self._patch(
            f"/campaigns/{campaign_id}/{entity_type}/{record_id}", fields
        )["data"]

    # ── Tags ──────────────────────────────────────────────────────────────────

    def create_tag(self, campaign_id: int, name: str, **kwargs) -> dict:
        return self._post(f"/campaigns/{campaign_id}/tags", {"name": name, **kwargs})["data"]

    # ── Generic entity attributes ─────────────────────────────────────────────

    def set_attributes(self, campaign_id: int, entity_id: int, attributes: list) -> dict:
        """
        attributes: [{"name": "Key", "value": "Val", "type": 0}, ...]
        type: 0=text, 1=list, 2=block, 3=checkbox, 4=section, 5=random_value
        """
        return self._post(f"/campaigns/{campaign_id}/entities/{entity_id}/attributes", attributes)


if __name__ == "__main__":
    token = os.environ.get("KANKA_TOKEN")
    if not token:
        print("Set KANKA_TOKEN env var to your API token")
        sys.exit(1)
    client = KankaClient(token)
    campaigns = client.list_campaigns()
    print(f"Found {len(campaigns)} campaign(s):")
    for c in campaigns:
        print(f"  id={c['id']}  name={c['name']}")
