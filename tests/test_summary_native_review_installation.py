"""Installed-wheel contract for the summary-native review surface."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers.installed_distribution import InstalledDistribution, build_installed_distribution


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("viewer.html", "viewer.js", "viewer.css")


def test_viewer_renders_and_saves_exact_claim_actions() -> None:
    root = Path(__file__).resolve().parents[1] / "pipelines/summary_native/review/web"
    html = (root / "viewer.html").read_text(encoding="utf-8")
    script = (root / "viewer.js").read_text(encoding="utf-8")
    assert 'id="claim-fields"' in html
    for field in ("subject_id", "predicate", "normalized_value", "certainty", "audience"):
        assert field in script
    for action in ("confirm_claim_mapping", "dismiss_claim_finding", "accept_claim_uncertainty", "signoff_document"):
        assert action in script
    assert "Prepare an exact finding disposition before approval" in script


def _viewer_functions() -> str:
    script = (REPO_ROOT / "pipelines/summary_native/review/web/viewer.js").read_text(encoding="utf-8")
    def between(start: str, end: str) -> str:
        begin = script.index(start)
        return script[begin:script.index(end, begin)]
    return (
        between("function approvalDisposition(item)", "\nasync function openItem")
        + "\n"
        + between("function request(){", "\nasync function advanceNext")
    )


def _run_viewer(scenario: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute the viewer's decision functions")
    program = (
        "const $=id=>({value:'note'});\n"
        + _viewer_functions()
        + "\n"
        + scenario
    )
    result = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_viewer_approval_dispositions_are_ones_the_server_accepts() -> None:
    """The browser and the decision validator must agree on what Approve means."""
    from types import SimpleNamespace

    from pipelines.summary_native.review.store import _validate_action_decision

    actions = ["confirm_claim_mapping", "dismiss_claim_finding", "accept_claim_uncertainty", "signoff_document"]
    dispositions = _run_viewer(
        "const state={review:{kind:'grounding_documents'}};"
        f"console.log(JSON.stringify({json.dumps(actions)}.map(action=>approvalDisposition({{proposed_action:{{action}}}}))))"
    )
    for action, disposition in zip(actions, dispositions):
        item = SimpleNamespace(proposed_action=SimpleNamespace(
            action=action, details={"evidence_digest": "e", "rationale_digest": "r"},
        ))
        _validate_action_decision(item, verdict="approve", disposition=disposition)


def test_viewer_saves_only_the_item_on_screen_unless_it_is_in_the_ticked_batch() -> None:
    """Ticking A and B then reading C must not record a decision on A and B."""
    scenario = (
        "const items=['a','b','c'].map(id=>({item_id:id,revision:1,review_digest:'d',decision_revision:0}));"
        "const state={review:{kind:'npc_verification',generation:1},items,selected:new Set(['a','b']),"
        "verdict:'approve',proposal:null,identityDisposition:null,current:{item_id:'c'}};"
        "const onScreen=request().decisions.map(d=>d.item_id);"
        "state.current={item_id:'a'};"
        "const batch=request().decisions.map(d=>d.item_id);"
        "console.log(JSON.stringify({onScreen,batch}))"
    )
    assert _run_viewer(scenario) == {"onScreen": ["c"], "batch": ["a", "b"]}


@pytest.fixture(scope="module")
def installed_review(tmp_path_factory: pytest.TempPathFactory) -> InstalledDistribution:
    return build_installed_distribution(tmp_path_factory.mktemp("installed-review-wheel"))


def _installed_web_dir(installed: InstalledDistribution) -> Path:
    result = installed.run(
        str(installed.python),
        "-c",
        (
            "from pathlib import Path; "
            "import pipelines.summary_native.review.web as package; "
            "print(Path(package.__file__).resolve().parent)"
        ),
    )
    directory = Path(result.stdout.strip())
    assert directory.is_dir()
    assert not directory.is_relative_to(REPO_ROOT)
    assert directory.is_relative_to(installed.wheel.parent.parent)
    return directory


def test_review_viewer_assets_are_readable_from_the_installed_wheel(
    installed_review: InstalledDistribution,
) -> None:
    members = installed_review.members()
    expected = {
        f"pipelines/summary_native/review/web/{asset}" for asset in ASSETS
    }
    assert expected <= members

    probe = (
        "import json; from importlib.resources import files; "
        "root=files('pipelines.summary_native.review.web'); "
        f"names={ASSETS!r}; "
        "print(json.dumps({name: len(root.joinpath(name).read_bytes()) for name in names}, sort_keys=True))"
    )
    result = installed_review.run(str(installed_review.python), "-c", probe)
    sizes = json.loads(result.stdout)
    assert set(sizes) == set(ASSETS)
    assert all(size > 0 for size in sizes.values())


def test_installed_summary_native_runs_the_shared_review_cli_away_from_checkout(
    installed_review: InstalledDistribution,
) -> None:
    campaign = installed_review.away / "campaign"
    campaign.mkdir()
    authority = installed_review.run(
        str(installed_review.scripts / "summary_native"),
        "authority",
        "init",
        "--campaign-dir",
        str(campaign),
        "--campaign",
        "installed-wheel-test",
        "--json",
    )
    assert json.loads(authority.stdout)["ok"] is True
    result = installed_review.run(
        str(installed_review.scripts / "summary_native"),
        "review",
        "init",
        "--campaign-dir",
        str(campaign),
        "--json",
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["code"] == "REVIEW_INITIALIZED"
    assert payload["data"]["campaign_root"] == str(campaign.resolve())
    assert (campaign / "docs" / "reviews" / "campaign.json").is_file()

    provenance = installed_review.run(
        str(installed_review.python),
        "-c",
        "import pipelines.summary_native.cli as module; print(module.__file__)",
    )
    cli_path = Path(provenance.stdout.strip()).resolve()
    assert not cli_path.is_relative_to(REPO_ROOT)
    assert cli_path.is_relative_to(installed_review.wheel.parent.parent)


@pytest.mark.parametrize(
    ("asset", "route"),
    (
        ("viewer.html", "/r/capability/"),
        ("viewer.js", "/r/capability/assets/viewer.js"),
        ("viewer.css", "/r/capability/assets/viewer.css"),
    ),
)
def test_installed_service_fails_safely_when_a_required_asset_is_absent(
    installed_review: InstalledDistribution,
    asset: str,
    route: str,
) -> None:
    web_dir = _installed_web_dir(installed_review)
    packaged_asset = web_dir / asset
    hidden_asset = web_dir / f".{asset}.missing"
    packaged_asset.replace(hidden_asset)
    try:
        probe = (
            "import json; from pathlib import Path; from types import SimpleNamespace; "
            "from fastapi.testclient import TestClient; "
            "from campaignlib.review_config import ReviewConfig; "
            "import pipelines.summary_native.review.web.app as web; "
            "web.authenticate_token=lambda *_args, **_kwargs: SimpleNamespace(grant_id='grant'); "
            "app=web.create_review_app(Path.cwd(), 'review-1', "
            "ReviewConfig(bind_host='127.0.0.1', port=8766, origin='http://127.0.0.1:8766')); "
            f"response=TestClient(app, raise_server_exceptions=False).get({route!r}, "
            "headers={'Host':'127.0.0.1:8766'}); "
            "print(json.dumps({'status':response.status_code,'payload':response.json()}, sort_keys=True))"
        )
        result = installed_review.run(str(installed_review.python), "-c", probe)
    finally:
        hidden_asset.replace(packaged_asset)

    response = json.loads(result.stdout)
    assert response == {
        "status": 503,
        "payload": {
            "ok": False,
            "code": "REVIEW_SERVICE_ERROR",
            "message": "Review service failed safely.",
        },
    }
    assert str(packaged_asset) not in result.stdout
    assert str(packaged_asset) not in result.stderr
