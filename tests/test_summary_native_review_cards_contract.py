"""Spec 043 US4: the card contract is tested -- schemas, goldens, version refusal, plain-text carriage."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from pipelines.summary_native.review import cards
from pipelines.summary_native.review.models import canonical_bytes
from tests import _custody_fixture as custody_fx
from tests.test_summary_native_review_cards import (  # noqa: F401  (fixtures: noise_cards, campaign)
    RID, _decide_cmd, _decisions, _export, _fresh_packet, _load_packet, noise_cards)
from tests.test_summary_native_review_delegated import campaign  # noqa: F401

GOLDEN = Path(__file__).parent / "fixtures" / "review_cards"
SCHEMAS = cards.schemas_dir()


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


PACKET_SCHEMA, DECISIONS_SCHEMA = "card-packet.v1.schema.json", "card-decisions.v1.schema.json"


def _fixture_packet(tmp_path) -> dict:
    fx = custody_fx.build(tmp_path, deterministic=True)
    rc, env = _export(fx.root, fx.review_id)
    assert rc == 0, env
    return _load_packet(fx.root, fx.review_id, env["data"]["packetId"])


def test_us4_s1_goldens_validate_and_round_trip():
    for name, model, schema in (("packet.v1.json", cards.CardPacket, PACKET_SCHEMA),
                                ("decisions.v1.json", cards.CardDecisions, DECISIONS_SCHEMA)):
        raw = (GOLDEN / name).read_bytes()
        value = json.loads(raw)
        jsonschema.validate(value, _schema(schema))
        parsed = model.model_validate(value)
        assert canonical_bytes(parsed.model_dump(by_alias=True, exclude_unset=True)) == raw, name
    decisions = json.loads((GOLDEN / "decisions.v1.json").read_text(encoding="utf-8"))
    assert {v["verdict"] for v in decisions["cards"].values()} == {"approve", "reject", "discuss"}
    assert any("draftSha256" in v for v in decisions["cards"].values())  # a sign-off with its echo


def test_us4_s1_every_exported_packet_validates(tmp_path, noise_cards):
    schema = _schema(PACKET_SCHEMA)
    jsonschema.validate(_fixture_packet(tmp_path), schema)
    root, _items = noise_cards
    packet = _fresh_packet(root)
    assert {c["kind"] for c in packet["cards"]} >= {"noise_class"}
    jsonschema.validate(packet, schema)


def test_schemas_are_current():
    for name, text in cards.schema_files().items():
        assert (SCHEMAS / name).read_text(encoding="utf-8") == text, f"{name} is stale: run cards.write_schemas()"


def test_us4_s2_unknown_major_version_refused_naming_accepted(tmp_path):
    fx = custody_fx.build(tmp_path, deterministic=True)
    rc, env = _export(fx.root, fx.review_id)
    packet = _load_packet(fx.root, fx.review_id, env["data"]["packetId"])
    path = _decisions(fx.root, packet, {packet["cards"][0]["id"]: ("approve", "")}, schemaVersion=2)
    rc, out = _decide_cmd(fx.root, fx.review_id, path)
    assert rc != 0 and out["code"] == "REVIEW_CARDS_SCHEMA"
    assert "accepted: [1]" in out["message"]
    # The checked-in bad-version golden is refused the same way, and the extra-key golden is refused too.
    for name, code in (("decisions.bad-version.json", "REVIEW_CARDS_SCHEMA"),
                       ("decisions.extra-key.json", "REVIEW_CARDS_INVALID")):
        with pytest.raises(Exception) as excinfo:
            cards.parse_decisions((GOLDEN / name).read_bytes(), max_note_chars=10_000)
        assert code in str(excinfo.value)


def test_us4_s3_markup_carried_as_text(tmp_path, monkeypatch):
    original = custody_fx._draft

    def marked(subject, chapters, *, quote):
        text = original(subject, chapters, quote=quote)
        return (text.replace("A gnome who guides", "A <b>x</b> gnome <script>alert(1)</script> who guides")
                    .replace("whisper was", "<b>x</b> whisper <script>alert(1)</script> was"))

    monkeypatch.setattr(custody_fx, "_draft", marked)
    packet = _fixture_packet(tmp_path)
    by_kind = {}
    for card in packet["cards"]:
        by_kind.setdefault(card["kind"], []).append(card)
    assert any("<script>alert(1)</script>" in c["body"] and "<b>x</b>" in c["body"] for c in by_kind["signoff"])
    assert any("<script>alert(1)</script>" in c["body"] and "<b>x</b>" in c["body"] for c in by_kind["finding"])
    for card in packet["cards"]:
        assert "&lt;" not in card["body"] and "&amp;" not in card["body"]
    assert "plain text" in _schema(PACKET_SCHEMA)["$defs"]["Card"]["properties"]["body"]["description"].lower()


def test_golden_packet_matches_fresh_export(tmp_path):
    fresh = canonical_bytes(_fixture_packet(tmp_path))
    assert fresh == (GOLDEN / "packet.v1.json").read_bytes(), (
        "the golden packet no longer matches a fresh deterministic export; if the change is intended, "
        "regenerate tests/fixtures/review_cards/*.json (and cards.write_schemas())")
