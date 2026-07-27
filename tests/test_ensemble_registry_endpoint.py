"""GET /api/ensemble/registry — the entity-registry status probe for the
Setup page's registry-migration UI.

Always 200, like /status: "no registry yet" and "registry is invalid" are
both states the frontend needs to *render*, not errors it needs to catch.
Mirrors tests/test_ensemble_gates.py's TestClient/monkeypatch.chdir style.
"""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _write(path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_no_registry_reports_found_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/registry")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "found": False,
        "path": None,
        "error": "no entity registry at docs/entity_registry.yaml — run `registry init .`",
    }


def test_valid_registry_reports_counts_types_and_clean_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "entity_registry.yaml", """\
version: 1
campaign: test
entities:
  - name: Grundar
    type: npc
    aliases: [Gru]
  - name: Kazryn Nyantani
    type: npc
    aliases: [Kazryn]
  - name: Velkynvelve
    type: location
""")

    r = client.get("/api/ensemble/registry")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["path"] == "docs/entity_registry.yaml"
    assert body["error"] is None
    assert body["entity_count"] == 3
    assert body["alias_count"] == 2  # Gru + Kazryn; Velkynvelve has none
    assert body["types"] == {"npc": 2, "location": 1}
    assert body["check"]["grouping"] == []
    assert body["check"]["fuzzy"] == []
    assert body["check"]["clean"] is True


def test_drift_against_legacy_store_surfaces_grouping_finding(tmp_path, monkeypatch):
    """docs/aliases.json (the legacy store cmd_check's grouping detector (a5)
    reads, per entity_registry/registry.py) grouping two names the registry
    resolves to two DIFFERENT entities — that's grouping drift, and it must
    flip `clean` to False."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "entity_registry.yaml", """\
version: 1
entities:
  - name: Grundar
    type: npc
  - name: Kazryn Nyantani
    type: npc
""")
    _write(tmp_path / "docs" / "aliases.json",
           '{"Grundar": ["Kazryn Nyantani"]}')

    r = client.get("/api/ensemble/registry")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["error"] is None
    assert body["check"]["grouping"], "expected a grouping-drift finding"
    assert body["check"]["clean"] is False


def test_invalid_registry_reports_error_with_no_counts(tmp_path, monkeypatch):
    """An identity collision (two entities claiming the same normalized name)
    fails campaignlib.registry.validate() — load_registry raises ValueError.
    The endpoint must still answer 200 and found:true (the file IS there),
    just with an error and no counts/check computed off a Registry that was
    never actually returned."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "entity_registry.yaml", """\
version: 1
entities:
  - name: Grundar
    type: npc
    aliases: [Gru]
  - name: Gru
    type: npc
""")

    r = client.get("/api/ensemble/registry")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["path"] == "docs/entity_registry.yaml"
    assert body["error"]
    assert "identity collision" in body["error"]
    assert "entity_count" not in body
    assert "check" not in body
