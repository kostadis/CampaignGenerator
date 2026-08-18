"""Tests for CampaignGenerator#326: consistency-check tools auto-load the
campaign's entity_registry.yaml as an AUTHORITATIVE CANON prompt section,
and --context accumulates across repeats instead of overwriting.

Regression anchor for the Obelisk "Foreput"/"Dawnforge" incident (#117) and
the concrete defect test_provenance_incidents.py::
test_incident_4_the_glossary_is_searchable_at_all documents: "check_consistency
never loads the glossary." This test proves it now does — without anyone
having to remember to pass --context docs/entity_registry.yaml by hand.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_doc import check_consistency, sd_consistency  # noqa: E402

_REGISTRY_YAML = """\
version: 1
campaign: fixture
entities:
  - name: Kalan Strongbranch
    type: npc
    aliases: [Strongbranch, Kalan]
    note: Gatewarden; archmage
distinct:
  - [Ilvara, Sylvira]
"""


def _make_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "campaign"
    (campaign_dir / "docs").mkdir(parents=True)
    (campaign_dir / "docs" / "entity_registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
    (campaign_dir / "config.yaml").write_text("documents: []\n", encoding="utf-8")
    return campaign_dir


def test_check_consistency_auto_loads_registry_as_canon(tmp_path, monkeypatch):
    campaign_dir = _make_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Kalan Stormbranch showed up.", encoding="utf-8")

    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append({"system": system, "user": user})
        return "No issues found."

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream_api)
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config.yaml"),
    ])

    check_consistency.main()

    assert len(calls) == 1
    user_prompt = calls[0]["user"]
    assert "AUTHORITATIVE CANON" in user_prompt
    assert "Kalan Strongbranch" in user_prompt
    assert "Ilvara" in user_prompt and "Sylvira" in user_prompt  # distinct pair rendered

    system_prompt = calls[0]["system"]
    assert "canon wins" in system_prompt.lower()


def test_check_consistency_context_accumulates_across_repeats(tmp_path, monkeypatch):
    """The #117 companion bug: repeated --context flags must not overwrite."""
    campaign_dir = _make_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    ctx_a = tmp_path / "a.md"
    ctx_a.write_text("Context A content.", encoding="utf-8")
    ctx_b = tmp_path / "b.md"
    ctx_b.write_text("Context B content.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config.yaml"),
        "--context", str(ctx_a),
        "--context", str(ctx_b),
    ])

    check_consistency.main()

    assert "Context A content." in calls[0]
    assert "Context B content." in calls[0]


def test_check_consistency_no_registry_omits_canon_section(tmp_path, monkeypatch):
    campaign_dir = tmp_path / "campaign_no_registry"
    campaign_dir.mkdir()
    (campaign_dir / "config.yaml").write_text("documents: []\n", encoding="utf-8")
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    ctx = tmp_path / "party.md"
    ctx.write_text("Party roster.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config.yaml"),
        "--context", str(ctx),
    ])

    check_consistency.main()

    assert "AUTHORITATIVE CANON" not in calls[0]


def test_sd_consistency_auto_loads_registry_as_canon(tmp_path, monkeypatch):
    campaign_dir = _make_campaign(tmp_path)
    recap_path = campaign_dir / "session-summary.md"
    recap_path.write_text("Kalan Stormbranch showed up.", encoding="utf-8")
    ctx = campaign_dir / "docs" / "campaign_state.md"
    ctx.write_text("Campaign state.", encoding="utf-8")
    out_path = campaign_dir / "consistency_report.md"

    calls = []
    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        sd_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.chdir(campaign_dir)
    monkeypatch.setattr(sys, "argv", [
        "sd_consistency", str(recap_path),
        "--context", str(ctx),
        "--out", str(out_path),
    ])

    sd_consistency.main()

    assert len(calls) == 1
    assert "AUTHORITATIVE CANON" in calls[0]
    assert "Kalan Strongbranch" in calls[0]
