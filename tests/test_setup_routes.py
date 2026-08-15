"""What ``/api/setup/run/dnd-sheet`` puts on the command line (feature 008).

The router is a forwarder: it must pass ``--party-config`` through and, more
importantly, must **not** invent an output location. Under FR-017 an explicit
output path suppresses roster naming and archival, so a synthesised default
would leave the whole feature unreachable from the browser while looking like
it worked (D11). That is the single highest-risk line in the change, and it is
a negative property no manual click-through reliably catches.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

client = TestClient(app)

SETUP_ROUTER = Path(__file__).resolve().parent.parent / "server" / "routers" / "setup.py"


@pytest.fixture
def captured_cmd(monkeypatch):
    """The argv the router built, without running anything."""
    box = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        box["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr("server.routers.setup.stream_subprocess", fake_stream_subprocess)
    return box


def _run(params: dict) -> list[str]:
    r = client.get("/api/setup/run/dnd-sheet", params=params)
    assert r.status_code == 200, r.text
    _ = r.text  # drain the stream so the generator actually runs
    return r


def test_party_config_is_forwarded(captured_cmd):
    _run({"pdfs": ["Soma.pdf"], "party_config": "config/party.yaml"})
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--party-config") + 1] == "config/party.yaml"


def test_no_output_location_is_sent_when_the_operator_set_none(captured_cmd):
    """The whole feature hinges on this: roster mode is only reachable when the
    router stays silent about where the file goes."""
    _run({"pdfs": ["Soma.pdf"], "party_config": "config/party.yaml"})
    cmd = captured_cmd["cmd"]
    assert "--output" not in cmd
    assert "--output-dir" not in cmd


def test_blank_output_fields_are_not_forwarded(captured_cmd):
    """An untouched form field arrives as an empty string, not as absent."""
    _run({"pdfs": ["Soma.pdf"], "party_config": "config/party.yaml",
          "output": "", "output_dir": "   "})
    cmd = captured_cmd["cmd"]
    assert "--output" not in cmd
    assert "--output-dir" not in cmd


def test_an_explicit_output_is_still_forwarded(captured_cmd):
    """FR-017 remains reachable — the operator can still override."""
    _run({"pdfs": ["Soma.pdf"], "output": "/tmp/soma.md"})
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--output") + 1] == "/tmp/soma.md"


def test_output_dir_is_forwarded_for_multiple_pdfs(captured_cmd):
    _run({"pdfs": ["A.pdf", "B.pdf"], "output_dir": "/tmp/out"})
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--output-dir") + 1] == "/tmp/out"
    assert "--output" not in cmd


def test_omitting_party_config_leaves_the_flag_off(captured_cmd):
    _run({"pdfs": ["Soma.pdf"], "output_dir": "/tmp/out"})
    assert "--party-config" not in captured_cmd["cmd"]


def test_the_router_contains_no_path_literals():
    """FR-020/Constitution VI: the router forwards flags. A default sheet
    directory here would be a second place the naming rule lives."""
    tree = ast.parse(SETUP_ROUTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "run_dnd_sheet"):
            literals = [
                n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
            for lit in literals:
                assert not lit.endswith(".md"), f"path literal in the router: {lit!r}"
                assert "docs/" not in lit, f"path literal in the router: {lit!r}"
                assert lit != "doc", "the CLI owns the legacy output-dir default"
            break
    else:  # pragma: no cover
        pytest.fail("run_dnd_sheet not found in server/routers/setup.py")
