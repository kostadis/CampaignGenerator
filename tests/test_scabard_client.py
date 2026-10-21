"""Tests for ScabardClient's page payloads — the `aliases` field.

The live save endpoint accepts `aliases` in a JSON body and keeps a page's
existing aliases when the key is omitted (verified 2026-10-21 against
campaign 7207889). So the SDK sends `aliases` only when the caller passes
one, and never sends a default that would clear it. No network calls here:
_post and fetch_existing are replaced.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scabard_sdk import scabard_client  # noqa: E402
from scabard_sdk.scabard_client import ScabardClient  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    c = ScabardClient(username="u", access_key="k")
    c.posts = []

    def fake_post(url, payload):
        c.posts.append((url, payload))
        return {"isSuccess": True}

    monkeypatch.setattr(c, "_post", fake_post)
    monkeypatch.setattr(c, "fetch_existing", lambda cid, concept: {"Abbathor": 42})
    monkeypatch.setattr(scabard_client.time, "sleep", lambda s: None)
    return c


def test_create_page_sends_aliases_when_given(client):
    ok, thing_id = client.create_page(121, "character", "Abbathor", aliases="Abby, The Greedy")
    assert (ok, thing_id) == (True, 42)
    url, payload = client.posts[0]
    assert url.endswith("/campaign/121/character")
    assert payload["aliases"] == "Abby, The Greedy"
    assert payload["concept"] == "Character"


def test_create_page_omits_aliases_by_default(client):
    client.create_page(121, "character", "Abbathor")
    assert "aliases" not in client.posts[0][1]


def test_update_page_sends_aliases_when_given(client):
    assert client.update_page(121, "place", 158, "Invidia", aliases="The Envious City")
    url, payload = client.posts[0]
    assert url.endswith("/campaign/121/place/158")
    assert payload["aliases"] == "The Envious City"


def test_update_page_omits_aliases_by_default(client):
    """Omitting the key keeps aliases set in the Scabard UI."""
    client.update_page(121, "place", 158, "Invidia")
    assert "aliases" not in client.posts[0][1]


def test_update_page_empty_string_clears_aliases(client):
    client.update_page(121, "place", 158, "Invidia", aliases="")
    assert client.posts[0][1]["aliases"] == ""
