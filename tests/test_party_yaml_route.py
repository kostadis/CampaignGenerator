"""API tests for GET/PUT /api/config/party-yaml — specifically the optional
`dossier` field (this PC's ensemble-built merged_dossiers/npc_*.md), which
round-trips the same way `backstory` does."""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_get_party_yaml_returns_dossier_field(tmp_path):
    cfg = tmp_path / "party.yaml"
    cfg.write_text("""
characters:
  - name: Zephyr
    sheet: zephyr.md
    dossier: docs/ensemble/merged_dossiers/npc_zephyr.md
""", encoding="utf-8")

    r = client.get("/api/config/party-yaml", params={"path": str(cfg)})
    assert r.status_code == 200
    chars = r.json()["characters"]
    assert chars[0]["dossier"] == "docs/ensemble/merged_dossiers/npc_zephyr.md"


def test_get_party_yaml_dossier_absent_is_empty_string(tmp_path):
    cfg = tmp_path / "party.yaml"
    cfg.write_text("characters:\n  - name: Soma\n    sheet: soma.md\n", encoding="utf-8")

    r = client.get("/api/config/party-yaml", params={"path": str(cfg)})
    assert r.status_code == 200
    assert r.json()["characters"][0]["dossier"] == ""


def test_put_party_yaml_writes_dossier(tmp_path):
    cfg = tmp_path / "party.yaml"

    r = client.put("/api/config/party-yaml", json={
        "path": str(cfg),
        "characters": [{
            "name": "Zephyr",
            "sheet": "zephyr.md",
            "dossier": "docs/ensemble/merged_dossiers/npc_zephyr.md",
        }],
    })
    assert r.status_code == 200
    assert "dossier: docs/ensemble/merged_dossiers/npc_zephyr.md" in cfg.read_text(encoding="utf-8")


def test_put_party_yaml_omits_blank_dossier(tmp_path):
    cfg = tmp_path / "party.yaml"

    r = client.put("/api/config/party-yaml", json={
        "path": str(cfg),
        "characters": [{"name": "Soma", "sheet": "soma.md", "dossier": ""}],
    })
    assert r.status_code == 200
    assert "dossier" not in cfg.read_text(encoding="utf-8")
