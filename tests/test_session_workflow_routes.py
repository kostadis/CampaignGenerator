from server.main import app
from server.platform_config_service import PlatformConfigService
from fastapi.testclient import TestClient


def test_route_invokes_real_worktree_cli_and_refuses_escape(tmp_path, monkeypatch):
    campaign=tmp_path/"campaign";campaign.mkdir()
    session=campaign/"session";session.mkdir()
    (campaign/"config.yaml").write_text("{}")
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(campaign, config_dir="."), raising=False)
    with TestClient(app) as client:
        response=client.post("/api/session-workflow/command",json={"operation":"init","session_dir":"session","config":"config.yaml"})
        assert response.status_code==200,response.text
        assert response.json()["state"]["revision"]==1
        assert (session/"session_workflow.yaml").is_file()
        status=client.post("/api/session-workflow/command",json={"operation":"status","session_dir":"session"})
        assert status.json()["state"]==response.json()["state"]
        refused=client.post("/api/session-workflow/command",json={"operation":"init","session_dir":"..","config":"config.yaml"})
        assert refused.status_code==403


def test_saved_review_history_can_exceed_default_one_mib(tmp_path, monkeypatch):
    from session_doc.workflow.engine import Engine

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    session = campaign / "session"
    session.mkdir()
    (campaign / "config.yaml").write_text("{}")
    engine = Engine(session, campaign)
    engine.initialize(str(campaign / "config.yaml"))
    state = engine.store.load()
    history = "Preserved review discussion. " * 40000
    assert len(history.encode()) > 1048576
    state.events.append({"operation": "review-history", "discussion": history})
    engine.store.save(state, expected_revision=state.revision)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(campaign, config_dir="."), raising=False)
    with TestClient(app) as client:
        response = client.post("/api/session-workflow/command", json={"operation": "resume", "session_dir": "session"})
        assert response.status_code == 200, response.text[:200]
        assert response.json()["state"]["events"][-1]["discussion"] == history
