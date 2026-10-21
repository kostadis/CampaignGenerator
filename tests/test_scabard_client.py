"""Tests for ScabardClient against recorded shapes of the live API.

No network calls: ScabardClient._request is replaced by a fake that serves
canned responses and records every request. The response shapes come from
the live API (campaign 7207889, 2026-10-21): page GETs return `main` plus a
top-level `conns` list; writes answer `{"isSuccess": bool}`.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scabard_sdk import (  # noqa: E402
    PageRef,
    ScabardClient,
    ScabardRequestError,
    normalize_concept,
    scabard_client,
    scabard_sync,
)

BASE = ScabardClient.BASE_URL

PAGE_RESPONSE = {
    "main": {
        "name": "Big Al Kalazorn",
        "briefSummary": "Retired sheriff.",
        "description": "Owns Butterskull Ranch.",
        "rawDescription": "Owns Butterskull Ranch.",
        "secrets": "Left Qelline at the altar.",
        "gmSecrets": "GM only.",
        "isSecret": False,
        "aliases": "Big Al, Al",
        "dateLastEditedUnix": 1775420381809,
        "concept": "Character",
        "uri": "/campaign/121/character/7201301",
    },
    "conns": [{
        "rel": "Paramour of", "explicit": "Is Paramour of", "isSecret": False,
        "name": "Qelline Alderleaf", "concept": "Character",
        "uri": "/campaign/121/character/7206978",
    }],
}


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def __call__(self, method, url, payload=None):
        self.requests.append((method, url, payload))
        return self.responses[(method, url)]

    def posts(self):
        return [(url, payload) for method, url, payload in self.requests if method == "POST"]


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(scabard_client.time, "sleep", lambda s: None)

    def make(responses):
        client = ScabardClient(username="u", access_key="k")
        api = FakeAPI(responses)
        monkeypatch.setattr(client, "_request", api)
        return client, api

    return make


# ── Concepts ──────────────────────────────────────────────────────────────────

def test_normalize_concept_accepts_any_case():
    assert normalize_concept("Place") == "place"


def test_location_is_rejected_with_a_pointer_to_place():
    with pytest.raises(ValueError, match="'place'"):
        normalize_concept("location")


def test_unknown_concept_fails_before_any_request(make_client):
    client, api = make_client({})
    with pytest.raises(ValueError):
        client.list_pages(121, "dragon")
    assert api.requests == []


# ── Reads ─────────────────────────────────────────────────────────────────────

def test_list_campaigns_parses_ids_from_uris(make_client):
    client, _ = make_client({("GET", f"{BASE}/campaign"): {
        "rows": [{"name": "kostadis' Campaign", "uri": "/campaign/7207889"}]}})
    [campaign] = client.list_campaigns()
    assert (campaign.id, campaign.name) == (7207889, "kostadis' Campaign")


def test_get_page_parses_fields_aliases_and_connections(make_client):
    client, _ = make_client({("GET", f"{BASE}/campaign/121/character/7201301"): PAGE_RESPONSE})
    page = client.get_page(121, "character", 7201301)
    assert page.ref == PageRef(121, "character", 7201301)
    assert page.aliases == ["Big Al", "Al"]
    assert page.gm_secrets == "GM only."
    assert page.last_edited.year == 2026
    [conn] = page.connections
    assert conn.rel == "Paramour of"
    assert conn.target == PageRef(121, "character", 7206978)
    assert conn.target_name == "Qelline Alderleaf"


# ── Writes ────────────────────────────────────────────────────────────────────

def test_create_page_sends_json_fields_and_returns_the_new_id(make_client):
    client, api = make_client({
        ("POST", f"{BASE}/campaign/121/character"): {"isSuccess": True},
        ("GET", f"{BASE}/campaign/121/character"): {
            "rows": [{"name": "Abbathor", "uri": "/campaign/121/character/42"}]},
    })
    thing_id = client.create_page(121, "Character", "Abbathor",
                                  aliases=["Abby", "The Greedy"], is_secret=True)
    assert thing_id == 42
    [(url, payload)] = api.posts()
    assert payload["aliases"] == "Abby, The Greedy"
    assert payload["concept"] == "Character"
    assert payload["isSecret"] == "true"


def test_rejected_write_raises(make_client):
    client, _ = make_client({("POST", f"{BASE}/campaign/121/character"): {"isSuccess": False}})
    with pytest.raises(ScabardRequestError):
        client.create_page(121, "character", "Abbathor")


def test_alias_containing_a_comma_is_refused(make_client):
    client, api = make_client({})
    with pytest.raises(ValueError, match="comma"):
        client.create_page(121, "character", "Abbathor", aliases=["Abby, the Greedy"])
    assert api.posts() == []


def test_update_page_changes_only_the_fields_passed(make_client):
    url = f"{BASE}/campaign/121/character/7201301"
    client, api = make_client({("GET", url): PAGE_RESPONSE, ("POST", url): {"isSuccess": True}})
    client.update_page(121, "character", 7201301, brief_summary="Sheriff, retired twice.")
    [(_, payload)] = api.posts()
    assert payload == {
        "name": "Big Al Kalazorn",
        "briefSummary": "Sheriff, retired twice.",
        "description": "Owns Butterskull Ranch.",
        "secrets": "Left Qelline at the altar.",
        "gmSecrets": "GM only.",
        "isSecret": "false",
        "aliases": "Big Al, Al",
        "concept": "Character",
    }


def test_update_page_empty_list_clears_aliases(make_client):
    url = f"{BASE}/campaign/121/character/7201301"
    client, api = make_client({("GET", url): PAGE_RESPONSE, ("POST", url): {"isSuccess": True}})
    client.update_page(121, "character", 7201301, aliases=[])
    assert api.posts()[0][1]["aliases"] == ""


def test_create_connections_returns_records_without_isSuccess(make_client):
    client, api = make_client({("POST", f"{BASE}/campaign/121/character/162/connect"): {
        "isSuccess": True,
        "home:place": {"relId": 16052101, "uri": "/campaign/121/place/158", "value": "Invidia",
                       "isFormer": False, "isSecret": False},
    }})
    records = client.create_connections(121, "character", 162, {"home:place": "Invidia"})
    assert list(records) == ["home:place"]
    assert records["home:place"]["relId"] == 16052101
    assert api.posts()[0][1] == {"concept": "Character", "home:place": "Invidia"}


# ── scabard_sync: legacy "location" ───────────────────────────────────────────

class FakeSyncClient:
    def __init__(self, username, access_key):
        self.updates, self.creates = [], []

    def fetch_existing(self, campaign_id, concept):
        return {}

    def update_page(self, campaign_id, concept, thing_id, **fields):
        self.updates.append((concept, thing_id, fields))

    def create_page(self, campaign_id, concept, name, **fields):
        self.creates.append((concept, name, fields))
        return 99


def test_sync_reads_legacy_location_as_place(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(scabard_sync, "ScabardClient",
                        lambda **kw: made.append(FakeSyncClient(**kw)) or made[-1])
    monkeypatch.setattr(scabard_sync.time, "sleep", lambda s: None)
    manifest = {"location": {"Phandalin": 7207032}}
    entities = [
        {"concept": "location", "name": "Phandalin", "briefSummary": "A town."},
        {"concept": "location", "name": "Leilon", "briefSummary": "A ruin.",
         "aliases": "Leilon Ruins"},
    ]
    result = scabard_sync.sync_entities(entities, 121, "u", "k", manifest,
                                        tmp_path / "m.json", dry_run=False)
    client = made[0]
    assert "location" not in result
    assert result["place"] == {"Phandalin": 7207032, "Leilon": 99}
    [(concept, thing_id, fields)] = client.updates
    assert (concept, thing_id) == ("place", 7207032)
    assert fields["aliases"] is None  # absent → keep the page's aliases
    [(concept, name, fields)] = client.creates
    assert (concept, name, fields["aliases"]) == ("place", "Leilon", ["Leilon Ruins"])
