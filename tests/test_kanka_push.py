"""Tests for kanka_push.py — world_state.md → Kanka CE (inverse of kanka_sync).

Parser tests are pure (no network). Plan/apply tests use a FakeClient so the
create-or-update logic is exercised without touching a live Kanka instance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.integrations.kanka import kanka_push
from pipelines.integrations.kanka import kanka_sync


# ── parse_entity_block ─────────────────────────────────────────────────────────

def test_parse_block_name_type_and_body():
    block = (
        "**Sera Voss** — _Spymaster_\n"
        "- Spymaster of the Fourth Circle\n"
        "\n"
        "Operates from the shadows of the capital."
    )
    ent = kanka_push.parse_entity_block(block)
    assert ent["name"] == "Sera Voss"
    assert ent["type"] == "Spymaster"
    assert ent["title"] == "Spymaster of the Fourth Circle"
    assert ent["entry"] == "Operates from the shadows of the capital."


def test_parse_block_deceased_keyword_flag():
    block = "**Old Tomas** — _Innkeeper, deceased_\n\nRan the Gilded Flagon."
    ent = kanka_push.parse_entity_block(block)
    assert ent["name"] == "Old Tomas"
    assert ent["type"] == "Innkeeper"
    assert ent["is_dead"] is True
    # keyword flags must not leak into the free-text type
    assert "deceased" not in ent["type"]


def test_parse_block_gm_private_and_destroyed_flags():
    block = "**Sunken Keep** — _Ruin, destroyed, GM-private_\n\nUnder the lake."
    ent = kanka_push.parse_entity_block(block)
    assert ent["type"] == "Ruin"
    assert ent["is_destroyed"] is True
    assert ent["is_private"] is True


def test_parse_block_event_in_world_date():
    block = (
        "**The Sundering** — _Cataclysm_\n"
        "- In-world date: 1242-03-15\n"
        "\n"
        "The day the realm shattered."
    )
    ent = kanka_push.parse_entity_block(block)
    assert ent["date"] == "1242-03-15"
    assert ent["entry"] == "The day the realm shattered."
    # the date line must not be mistaken for a title
    assert "title" not in ent


def test_parse_block_no_flags_no_body():
    ent = kanka_push.parse_entity_block("**Lonely Name**")
    assert ent["name"] == "Lonely Name"
    assert ent["entry"] == ""
    assert "type" not in ent


def test_parse_block_multiparagraph_body_with_bullets():
    block = (
        "**The Archive** — _Library_\n"
        "\n"
        "A vast repository.\n"
        "\n"
        "- forbidden wing\n"
        "- sealed vault"
    )
    ent = kanka_push.parse_entity_block(block)
    # blank line ends the metadata zone; bullets here are body, not metadata
    assert "A vast repository." in ent["entry"]
    assert "- forbidden wing" in ent["entry"]
    assert "title" not in ent


# ── round-trip against kanka_sync.entity_block ─────────────────────────────────

def test_roundtrip_through_kanka_sync_entity_block():
    source = {
        "name": "Gareth",
        "type": "Knight",
        "entry": "<p>A <strong>brave</strong> knight of the realm.</p>",
        "is_private": False,
    }
    block = kanka_sync.entity_block(source, "characters")
    ent = kanka_push.parse_entity_block(block)
    assert ent["name"] == "Gareth"
    assert ent["type"] == "Knight"
    assert ent["entry"] == "A brave knight of the realm."


# ── parse_world_state ──────────────────────────────────────────────────────────

SAMPLE = """\
# World State — The Shattered Realm

> Generated from Kanka CE.

## NPCs

**Sera Voss** — _Spymaster_

Operates from the shadows.

**Old Tomas** — _Innkeeper, deceased_

Ran the Gilded Flagon.

## Factions

**The Fourth Circle** — _Secret Society_

An intelligence network.

## World Events

**The Sundering** — _Cataclysm_
- In-world date: 1242-03-15

The realm shattered.
"""


def test_parse_world_state_groups_by_entity_type():
    parsed = kanka_push.parse_world_state(SAMPLE)
    assert [e["name"] for e in parsed["characters"]] == ["Sera Voss", "Old Tomas"]
    assert [e["name"] for e in parsed["organisations"]] == ["The Fourth Circle"]
    assert [e["name"] for e in parsed["events"]] == ["The Sundering"]


def test_parse_world_state_threads_heading_variant_maps_to_notes():
    md = "## Threads\n\n**Loose End** — _Mystery_\n\nWho poisoned the duke?"
    parsed = kanka_push.parse_world_state(md)
    assert parsed["notes"][0]["name"] == "Loose End"


def test_parse_world_state_ignores_unknown_headings():
    md = "## Random Heading\n\n**Not An Entity**\n\nbody"
    parsed = kanka_push.parse_world_state(md)
    assert all(not v for v in parsed.values())


def test_parse_world_state_body_line_starting_with_bold_not_split():
    # A body line that opens with markdown bold (e.g. from synthesise_world_state)
    # must not be mistaken for a new entity header — only full **Name** headers split.
    md = (
        "## NPCs\n\n"
        "**Gareth** — _Knight_\n\n"
        "**Beware:** he wields a cursed blade.\n"
    )
    parsed = kanka_push.parse_world_state(md)
    assert [e["name"] for e in parsed["characters"]] == ["Gareth"]
    assert "Beware" in parsed["characters"][0]["entry"]


# ── plan_changes / apply_changes ───────────────────────────────────────────────

class FakeClient:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.created = []
        self.updated = []

    def list_all(self, campaign_id, entity_type):
        return self.existing.get(entity_type, [])

    def create(self, campaign_id, entity_type, **fields):
        self.created.append((entity_type, fields))
        return {"id": 999, **fields}

    def update(self, campaign_id, entity_type, record_id, **fields):
        self.updated.append((entity_type, record_id, fields))
        return {"id": record_id, **fields}


def test_plan_creates_unmatched_entity():
    client = FakeClient(existing={"characters": []})
    parsed = {"characters": [{"name": "Sera Voss", "entry": "Spy."}]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    assert len(changes) == 1
    assert changes[0]["action"] == "create"
    assert changes[0]["entity_type"] == "characters"
    assert changes[0]["fields"]["name"] == "Sera Voss"


def test_plan_skips_unchanged_entity():
    existing = {"characters": [
        {"id": 5, "name": "Sera Voss", "type": None, "entry": "<p>Spy.</p>"},
    ]}
    client = FakeClient(existing=existing)
    parsed = {"characters": [{"name": "Sera Voss", "entry": "Spy."}]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    assert changes[0]["action"] == "skip"


def test_plan_updates_changed_entity_with_record_id():
    existing = {"characters": [
        {"id": 5, "name": "Sera Voss", "entry": "<p>Old text.</p>"},
    ]}
    client = FakeClient(existing=existing)
    parsed = {"characters": [{"name": "Sera Voss", "entry": "New text."}]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    assert changes[0]["action"] == "update"
    assert changes[0]["record_id"] == 5


def test_plan_matches_name_case_insensitively():
    existing = {"characters": [
        {"id": 5, "name": "Sera Voss", "entry": "<p>Spy.</p>"},
    ]}
    client = FakeClient(existing=existing)
    parsed = {"characters": [{"name": "sera voss", "entry": "Spy."}]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    assert changes[0]["action"] == "skip"


def test_plan_whitelists_fields_per_type():
    # a date field has no place on a character and must be dropped
    client = FakeClient(existing={"characters": []})
    parsed = {"characters": [
        {"name": "Sera Voss", "entry": "Spy.", "date": "1242", "title": "Spymaster"},
    ]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    fields = changes[0]["fields"]
    assert "date" not in fields
    assert fields["title"] == "Spymaster"


def test_apply_dry_run_makes_no_calls():
    client = FakeClient(existing={"characters": []})
    parsed = {"characters": [{"name": "New NPC", "entry": "x"}]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    counts = kanka_push.apply_changes(client, 1, changes, dry_run=True)
    assert client.created == []
    assert client.updated == []
    assert counts["create"] == 1


def test_apply_commits_creates_and_updates():
    existing = {"characters": [
        {"id": 5, "name": "Sera Voss", "entry": "<p>Old.</p>"},
    ]}
    client = FakeClient(existing=existing)
    parsed = {"characters": [
        {"name": "Sera Voss", "entry": "New."},
        {"name": "Fresh NPC", "entry": "Hi."},
    ]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    kanka_push.apply_changes(client, 1, changes, dry_run=False)
    assert len(client.created) == 1
    assert len(client.updated) == 1
    assert client.updated[0][1] == 5  # record_id


def test_apply_continues_after_one_entity_fails():
    # a mid-loop failure must not abort the rest of the batch
    class FlakyClient(FakeClient):
        def update(self, campaign_id, entity_type, record_id, **fields):
            raise RuntimeError("kanka 422")

    existing = {"characters": [
        {"id": 5, "name": "Sera Voss", "entry": "<p>Old.</p>"},
    ]}
    client = FlakyClient(existing=existing)
    parsed = {"characters": [
        {"name": "Sera Voss", "entry": "New."},
        {"name": "Fresh NPC", "entry": "Hi."},
    ]}
    changes = kanka_push.plan_changes(client, 1, parsed)
    counts = kanka_push.apply_changes(client, 1, changes, dry_run=False)
    assert len(client.created) == 1
    assert counts["failed"] == 1
