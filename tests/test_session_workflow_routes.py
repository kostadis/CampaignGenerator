from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.routers.session_workflow import router


def test_route_invokes_real_worktree_cli_and_refuses_escape(tmp_path):
    campaign=tmp_path/"campaign";campaign.mkdir()
    session=campaign/"session";session.mkdir()
    (campaign/"config.yaml").write_text("{}")
    app=FastAPI();app.state.config_service=SimpleNamespace(campaign_dir=campaign)
    app.include_router(router,prefix="/api/session-workflow")
    with TestClient(app) as client:
        response=client.post("/api/session-workflow/command",json={"operation":"init","session_dir":"session","config":"config.yaml"})
        assert response.status_code==200,response.text
        assert response.json()["state"]["revision"]==1
        assert (session/"session_workflow.yaml").is_file()
        status=client.post("/api/session-workflow/command",json={"operation":"status","session_dir":"session"})
        assert status.json()["state"]==response.json()["state"]
        refused=client.post("/api/session-workflow/command",json={"operation":"init","session_dir":"..","config":"config.yaml"})
        assert refused.status_code==403
