"""US3 sentinels: audience filtering happens before deterministic renderers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from campaignlib.planning_config import PlanningNoteSelector
from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, AudienceGrant, Classification, DOCUMENT_ANCHOR, EffectiveInterval, NoteRecord, Projection, RulingRecord, SubjectRef, write_ledger
from pipelines.summary_native.authority_inputs import filtered_evidence, resolve_selection
from pipelines.summary_native import notes
from pipelines.summary_native import state_sections
from pipelines.summary_native import context
from pipelines.summary_native import key_npcs
from pipelines.summary_native.freshness import audience_state_dir
from tests import conftest_state as cs


def _record(ident: str, anchor: str, grants: set[str], content: bytes, source: str = "notes/mixed.md") -> NoteRecord:
    return NoteRecord(
        id=ident, kind="note", revision=1, classification=Classification.CANON,
        subject=SubjectRef(kind="topic", id=ident), effective=EffectiveInterval(from_chapter=1),
        audience=AudienceGrant(grants=grants), projections={Projection.WORLD_STATE}, status="active",
        recorded_at="2026-10-09T00:00:00Z", recorded_by="GM",
        source={"path": source, "anchor": anchor}, content_digest=hashlib.sha256(content).hexdigest(),
        selection_label=ident,
    )


def test_adjacent_mixed_audience_sections_are_materialized_without_the_neighbour(tmp_path: Path):
    source = tmp_path / "notes" / "mixed.md"; source.parent.mkdir()
    players = b"<!-- anchor: players -->\n- [NPC] **Subject:** Mara sees the bridge. [ch 001 / npcs]\n"
    secret = b"<!-- anchor: gm -->\n- [NPC] **Subject:** SECRET_SENTINEL vault route. [ch 001 / npcs]\n"
    source.write_bytes(players + b"### Split\n" + secret)
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[
        _record("players-bridge", "players", {"players"}, players),
        _record("gm-vault", "gm", {"gm"}, secret),
    ])
    write_ledger(tmp_path, ledger)
    evidence = filtered_evidence(tmp_path, ledger, audience="players")
    assert b"SECRET_SENTINEL" not in evidence.text
    # Extract builds prompt chapters from these bytes, then its normal
    # citation checker verifies every kept output against the same bytes.
    assert b"Mara sees the bridge" in evidence.text


def test_historical_effective_ranges_filter_extraction_and_planning_views(tmp_path: Path):
    source = tmp_path / "notes" / "history.md"; source.parent.mkdir()
    in_scope = b"<!-- anchor: in-scope -->\nVisible in chapter three.\n"
    out_of_scope = b"## Chapter ten\n<!-- anchor: out-of-scope -->\nGM_SECRET_SENTINEL from chapter ten.\n"
    source.write_bytes(in_scope + out_of_scope)
    inside = _record("inside", "in-scope", {"players"}, in_scope, "notes/history.md").model_copy(
        update={"effective": EffectiveInterval(from_chapter=2, through_chapter=5), "projections": {Projection.PLANNING}},
    )
    outside = _record("outside", "out-of-scope", {"players"}, out_of_scope, "notes/history.md").model_copy(
        update={"effective": EffectiveInterval(from_chapter=10, through_chapter=10), "projections": {Projection.PLANNING}},
    )
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[inside, outside])
    write_ledger(tmp_path, ledger)
    evidence = filtered_evidence(tmp_path, ledger, audience="players", since=2, until=5)
    assert evidence.text == in_scope and b"GM_SECRET_SENTINEL" not in evidence.text
    selection = resolve_selection(tmp_path, [PlanningNoteSelector(id="history", path="notes/history.md")])
    from pipelines.summary_native.authority_inputs import selected_planning_records
    assert [record.id for record in selected_planning_records(tmp_path, ledger, selection, audience="players", since=2, until=5)] == ["inside"]


def test_filtered_snapshot_accepts_an_applied_ruling_without_note_content_digest(tmp_path: Path):
    source = tmp_path / "notes" / "mixed.md"; source.parent.mkdir()
    content = b"<!-- anchor: public -->\nPlayer-visible correction.\n"
    source.write_bytes(content)
    ruling = RulingRecord(
        id="public-ruling", kind="ruling", revision=1, classification=Classification.RULED,
        subject=SubjectRef(kind="topic", id="public"), effective=EffectiveInterval(from_chapter=1),
        audience=AudienceGrant(grants={"players"}), projections={Projection.WORLD_STATE}, status="applied",
        recorded_at="2026-10-09T00:00:00Z", recorded_by="GM",
        source={"path": "notes/mixed.md", "anchor": "public"}, rejected_claim="old", replacement_fact="new",
        proposal_id="proposal-1", applied_receipt="receipt-1",
    )
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[ruling])
    write_ledger(tmp_path, ledger)
    assert filtered_evidence(tmp_path, ledger, audience="players").text == content


def test_structured_summary_anchor_preserves_citeable_section_for_player_extract(tmp_path: Path):
    source = tmp_path / "notes" / "001-summary.md"; source.parent.mkdir()
    public = b"<!-- anchor: public-npcs -->\n## NPCs\n- Mara keeps watch.\n## Items\n- SECRET_SENTINEL key.\n"
    source.write_bytes(public)
    record = _record("public-npcs", "public-npcs", {"players"}, b"<!-- anchor: public-npcs -->\n## NPCs\n- Mara keeps watch.\n", "notes/001-summary.md")
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[record])
    evidence = filtered_evidence(tmp_path, ledger, audience="players")
    # Only the anchored H2 block survives, and the normal citation resolver
    # can validate an extracted `[ch 001 / npcs]` note against it.
    text = evidence.text.decode()
    assert "SECRET_SENTINEL" not in text
    chapter = notes.Chapter(1, source, text, set())
    assert notes.target_text(chapter, "npcs") == "## NPCs\n- Mara keeps watch."


def test_real_filtered_extract_succeeds_for_players_and_named_character(tmp_path: Path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    chapter = next((root / "docs" / "summaries").glob("002-*.md"))
    raw = chapter.read_text(encoding="utf-8")
    raw = raw.replace("## NPCs", "<!-- anchor: public-npcs -->\n## NPCs", 1)
    raw = raw.replace("## Items", "<!-- anchor: gm-items -->\n## Items\nSECRET_SENTINEL does not belong in player prompts.\n", 1)
    chapter.write_text(raw, encoding="utf-8")
    assert cs.run_cli(["build", *cs.common(root), "--force"])[0] == 0
    data = chapter.read_bytes()
    public = data[data.index(b"<!-- anchor: public-npcs -->"):data.index(b"## Locations")]
    common = dict(source="docs/summaries/" + chapter.name)
    player = _record("player-npcs", "public-npcs", {"players"}, public, **common)
    character = _record("ara-npcs", "public-npcs", {"character:Thorin Giantfriend"}, public, **common)
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=1, records=[player, character]))
    models = cs.fake_models(monkeypatch)
    for audience in ("players", "character:Thorin Giantfriend"):
        rc, _, err = cs.run_cli([*cs.extract_args(root), "--audience", audience])
        assert rc == 0, err
        checked = next(audience_state_dir(cs.range_dir(root), audience).joinpath("notes").glob("*.checked.json"))
        checked_data = json.loads(checked.read_text())
        assert checked_data["notes"] and any("[ch 002 / npcs]" in item["text"] for item in checked_data["notes"])
        rc, _, err = cs.run_cli([
            "synth", "world_state", *cs.common(root), "--backend", "dgx", "--model", "fake-model",
            "--endpoint", "http://spark:8001/v1", "--fallback-npc-lines", "--force",
            "--audience", audience,
        ])
        assert rc == 2 and "reviewed coverage for every supporting source" in err
    assert models.extract_calls and all("SECRET_SENTINEL" not in call["user"] for call in models.extract_calls)
    assert (audience_state_dir(cs.range_dir(root), "players") / "notes" / "manifest.json").is_file()
    assert (audience_state_dir(cs.range_dir(root), "character:Thorin Giantfriend") / "notes" / "manifest.json").is_file()


def test_non_gm_extract_refuses_incomplete_authorized_coverage(tmp_path: Path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=1, records=[]))
    cs.fake_models(monkeypatch)
    rc, _, err = cs.run_cli([*cs.extract_args(root), "--audience", "players"])
    assert rc == 2 and "complete authorized support" in err


@pytest.mark.parametrize("command", ["extract", "synth"])
def test_non_gm_blocking_validation_never_renders_ungranted_summary_details(tmp_path: Path, monkeypatch, command: str):
    root = cs.state_campaign(tmp_path)
    support = (root / "config" / "players.yaml").read_bytes()
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=1, records=[
        _record("players-support", DOCUMENT_ANCHOR, {"players"}, support, source="config/players.yaml"),
    ]))
    # This duplicate in-range chapter makes validation blocking. Its filename
    # and body are both sensitive and must stay out of stdout/stderr before
    # authority filtering has a chance to establish any support view.
    (root / "docs" / "summaries" / "004-GM_SECRET_SENTINEL.md").write_text(
        "# Chapter 4\n\n## Scenes\n\n### 004.01 GM_SECRET_SENTINEL\n", encoding="utf-8",
    )
    cs.fake_models(monkeypatch)
    args = ([*cs.extract_args(root), "--audience", "players"] if command == "extract" else [
        "synth", "world_state", *cs.common(root), "--backend", "dgx", "--model", "fake-model",
        "--endpoint", "http://spark:8001/v1", "--audience", "players",
    ])
    rc, out, err = cs.run_cli(args)
    assert rc == 2
    assert "validation is unavailable for this restricted audience" in err
    assert "GM_SECRET_SENTINEL" not in out + err


def test_party_and_planning_snapshot_loaders_require_each_referenced_file(tmp_path: Path):
    root = tmp_path
    config = root / "config"; config.mkdir()
    party = config / "party.yaml"; sheet = root / "ara.txt"; backstory = root / "ara.md"; mechanic = root / "ara-arc.md"
    party.write_text("characters:\n  - name: Ara\n    sheet: ara.txt\n    backstory: ara.md\n    arc_score: ara-arc.md\n")
    planning = config / "planning.yaml"; planning.write_text("npcs:\n  - name: Mara\n    dossier: docs/npcs/mara.md\n    arc_score: ara-arc.md\n")
    values = {party: party.read_text(), planning: planning.read_text(), sheet: "SHEET_SENTINEL", backstory: "BACKSTORY_SENTINEL", mechanic: "MECHANIC_SENTINEL"}
    def reader(path):
        try:
            return values[Path(path)]
        except KeyError as exc:
            raise AuthorityError("authorized support is incomplete for this audience") from exc
    chars = context.load_party(party, root, source_text=reader)
    assert chars[0].sheet_text == "SHEET_SENTINEL" and chars[0].backstory_text == "BACKSTORY_SENTINEL"
    plan = context.load_planning(planning, root, explicit=True, source_text=reader)
    assert plan.npcs[0].arc_score == mechanic.resolve()
    del values[backstory]
    with pytest.raises(Exception, match="authorized support is incomplete"):
        context.load_party(party, root, source_text=reader)


def test_dossier_reader_uses_only_snapshot_bytes(tmp_path: Path):
    dossier = tmp_path / "mara.md"
    data = (b"<!-- published by summary_native npc-publish | source: summary_native | npc: Mara | range: ch002-005 | verify: pass -->\n"
            b"## Identity\nMara the scout. [ch 002 / npcs]\n## Last Observed State\nMara watches. [ch 002 / npcs]\nSECRET_SENTINEL\n")
    dossier.write_bytes(b"raw secret")
    view = key_npcs.published_view(dossier, reader=lambda _: data)
    assert view.name == "Mara" and "raw secret" not in view.source
    with pytest.raises(AuthorityError, match="incomplete"):
        key_npcs.published_view(dossier, reader=lambda _: (_ for _ in ()).throw(AuthorityError("authorized support is incomplete for this audience")))


def test_non_gm_extract_stages_checked_notes_until_post_model_authority_recheck(tmp_path: Path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    chapter = next((root / "docs" / "summaries").glob("002-*.md"))
    raw = chapter.read_bytes()
    chapter.write_bytes(raw.replace(b"## NPCs", b"<!-- anchor: public-npcs -->\n## NPCs", 1))
    assert cs.run_cli(["build", *cs.common(root), "--force"])[0] == 0
    data = chapter.read_bytes()
    public = data[data.index(b"<!-- anchor: public-npcs -->"):data.index(b"## Locations")]
    record = _record("player-npcs", "public-npcs", {"players"}, public,
                     source="docs/summaries/" + chapter.name)
    ledger = AuthorityLedger(version=2, campaign="state", revision=1, records=[record])
    write_ledger(root, ledger)
    models = cs.fake_models(monkeypatch)
    original = models.extract_render
    changed = False

    def mutate_after_answer(*args, **kwargs):
        nonlocal changed
        answer = original(*args, **kwargs)
        if not changed:
            changed = True
            write_ledger(root, ledger.model_copy(update={"revision": 2}))
        return answer

    monkeypatch.setattr("pipelines.summary_native.extract.render_part", mutate_after_answer)
    rc, _, err = cs.run_cli([*cs.extract_args(root), "--audience", "players"])
    assert rc == 2 and "authority inputs changed during extraction" in err
    current = cs.range_dir(root) / "state" / "audiences" / "players" / "notes"
    assert not (current / "manifest.json").exists()
    run = next((cs.range_dir(root) / "state" / "audiences" / "players" / "runs").glob("*/record.json"))
    assert json.loads(run.read_text())["authority_stale"] is True


@pytest.mark.parametrize("audience", ["players", "character:Thorin Giantfriend"])
def test_non_gm_world_synth_uses_complete_snapshot_support(tmp_path: Path, monkeypatch, audience: str):
    root = cs.state_campaign(tmp_path)
    chapter = next((root / "docs" / "summaries").glob("002-*.md"))
    source = chapter.read_bytes()
    chapter.write_bytes(source.replace(b"## NPCs", b"<!-- anchor: public-npcs -->\n## NPCs", 1))
    for path, anchor in ((root / "docs" / "entity_registry.yaml", "registry"),
                         (root / "config" / "players.yaml", "players")):
        path.write_bytes(f"# anchor: {anchor}\n".encode() + path.read_bytes())
    assert cs.run_cli(["build", *cs.common(root), "--force"])[0] == 0
    data = chapter.read_bytes()
    public = data[data.index(b"<!-- anchor: public-npcs -->"):data.index(b"## Locations")]
    grants = {audience}
    records = [
        _record("public-npcs", "public-npcs", grants, public, source="docs/summaries/" + chapter.name),
        _record("registry", "registry", grants, (root / "docs" / "entity_registry.yaml").read_bytes(), source="docs/entity_registry.yaml"),
        _record("players", "players", grants, (root / "config" / "players.yaml").read_bytes(), source="config/players.yaml"),
    ]
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=1, records=records))
    models = cs.fake_models(monkeypatch)
    rc, _, err = cs.run_cli([*cs.extract_args(root), "--audience", audience])
    assert rc == 0, err
    rc, _, err = cs.run_cli([
        "synth", "world_state", *cs.common(root), "--backend", "dgx", "--model", "fake-model",
        "--endpoint", "http://spark:8001/v1", "--fallback-npc-lines", "--force", "--audience", audience,
    ])
    assert rc == 0, err
    assert models.extract_calls and all("SECRET_SENTINEL" not in call["user"] for call in models.extract_calls)


def test_all_four_non_gm_documents_use_only_complete_classified_support(tmp_path: Path, monkeypatch):
    """Exercise the production CLI adapters for both restricted audience kinds."""
    root = cs.state_campaign(tmp_path)
    chapter = next((root / "docs" / "summaries").glob("002-*.md"))
    original = chapter.read_bytes()
    chapter.write_bytes(original.replace(
        b"## NPCs", b"<!-- anchor: public-npcs -->\n## NPCs", 1,
    ).replace(
        b"## Items", b"<!-- anchor: gm-secret -->\n## Items\nGM_SECRET_SENTINEL\n", 1))

    config = root / "config"
    (root / "docs" / "sheets").mkdir()
    (root / "notes").mkdir()
    (root / "docs" / "ensemble").mkdir()
    (config / "party.yaml").write_text(
        "characters:\n  - name: Thorin Giantfriend\n    sheet: docs/sheets/thorin.md\n    backstory: docs/sheets/thorin-backstory.md\n",
        encoding="utf-8",
    )
    (root / "docs" / "sheets" / "thorin.md").write_text("Thorin sheet\n", encoding="utf-8")
    (root / "docs" / "sheets" / "thorin-backstory.md").write_text("Thorin backstory\n", encoding="utf-8")
    (root / "notes" / "planning.md").write_bytes(b"<!-- anchor: current-plan -->\nPublic plan: hold the gate.\n")
    (config / "planning.yaml").write_text(
        "notes:\n  - id: public-plan\n    path: notes/planning.md\n",
        encoding="utf-8",
    )
    (config / "projections.yaml").write_text(
        "stores:\n  thread_registry: docs/thread_registry.yaml\n  thread_proposals: docs/ensemble/thread_proposals.yaml\n",
        encoding="utf-8",
    )
    (root / "docs" / "thread_registry.yaml").write_text("version: 1\nthreads: []\n", encoding="utf-8")
    (root / "docs" / "ensemble" / "thread_proposals.yaml").write_text("proposals: []\n", encoding="utf-8")
    assert cs.run_cli(["build", *cs.common(root), "--force"])[0] == 0

    summary_data = chapter.read_bytes()
    public = summary_data[summary_data.index(b"<!-- anchor: public-npcs -->"):summary_data.index(b"## Locations")]
    audiences = ("players", "character:Thorin Giantfriend")
    records: list[NoteRecord] = []

    def support_record(identifier: str, relative: str, audience: str) -> NoteRecord:
        data = (root / relative).read_bytes()
        return _record(identifier, DOCUMENT_ANCHOR, {audience}, data, source=relative)

    support_paths = [
        "docs/entity_registry.yaml", "config/players.yaml", "config/party.yaml",
        "docs/sheets/thorin.md", "docs/sheets/thorin-backstory.md", "config/planning.yaml",
        "config/projections.yaml", "docs/thread_registry.yaml", "docs/tracking/tracking.txt",
    ]
    for audience in audiences:
        tag = "players" if audience == "players" else "thorin"
        records.append(_record(f"summary-{tag}", "public-npcs", {audience}, public,
                               source="docs/summaries/" + chapter.name))
        plan = (root / "notes" / "planning.md").read_bytes()
        records.append(_record(f"public-plan-{tag}", "current-plan", {audience}, plan,
                               source="notes/planning.md").model_copy(update={"id": f"public-plan-{tag}", "projections": {Projection.PLANNING}}))
        records.extend(support_record(f"support-{index}-{tag}", path, audience)
                       for index, path in enumerate(support_paths, start=1))
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=1, records=records))
    models = cs.fake_models(monkeypatch)

    selection = resolve_selection(root, [PlanningNoteSelector(id="public-plan", path="notes/planning.md")])
    for audience in audiences:
        rc, _, err = cs.run_cli([*cs.extract_args(root), "--audience", audience])
        assert rc == 0, err
        for doc in ("world_state", "campaign_state", "party", "planning"):
            command = [
                "synth", doc, *cs.common(root), "--backend", "dgx", "--model", "fake-model",
                "--endpoint", "http://spark:8001/v1", "--force", "--audience", audience,
            ]
            if doc in {"world_state", "planning"}:
                command.append("--fallback-npc-lines")
            if doc == "planning":
                command += ["--authority-selection", selection.digest]
            rc, _, err = cs.run_cli(command)
            assert rc == 0, f"{audience} {doc}: {err}"

        audience_dir = audience_state_dir(cs.range_dir(root), audience)
        assert {path.name for path in (audience_dir / "drafts").glob("*.draft.md")} == {
            "world_state.draft.md", "campaign_state.draft.md", "party.draft.md", "planning.draft.md",
        }
        for path in audience_dir.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json"}:
                assert "GM_SECRET_SENTINEL" not in path.read_text(encoding="utf-8")

    assert models.extract_calls and models.prose_calls
    assert all("GM_SECRET_SENTINEL" not in call["user"] for call in [*models.extract_calls, *models.prose_calls])

    # Removing one required support grant remains a generic audience refusal
    # and must not name the missing source or surface its neighbouring bytes.
    reduced = [record for record in records if record.id != "support-4-players"]
    write_ledger(root, AuthorityLedger(version=2, campaign="state", revision=2, records=reduced))
    rc, _, err = cs.run_cli([
        "synth", "party", *cs.common(root), "--backend", "dgx", "--model", "fake-model",
        "--endpoint", "http://spark:8001/v1", "--force", "--audience", "players",
    ])
    assert rc == 2
    assert "reviewed coverage for every supporting source" in err
    assert "thorin.md" not in err and "GM_SECRET_SENTINEL" not in err
