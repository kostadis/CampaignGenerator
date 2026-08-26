"""#342 — nothing may gate a run on whether a credential is *present*.

The deleted predicate was ``bool(os.environ["ANTHROPIC_API_KEY"])``, published
as ``api_key_present`` on ``GET /api/config/status`` and consumed by ten sites
in four Vue components. It could not be right, because it asked a global
question whose only true answer is per-run:

* three of the four supported backends (``dgx``, ``openrouter``,
  ``claude-code``) never read that variable;
* ``claude-code`` wants it **absent** — ``campaignlib/api/backends.py`` strips
  it from the child env so billing lands on the subscription, not the API;
* any non-empty string satisfied it, so it measured presence, not validity.

Credentials are now checked by the backend that needs one, at call time. These
tests fail the build if the pre-flight predicate returns by copy-paste.
"""

from __future__ import annotations

import ast
import re

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# The env var may still be *named* — in a comment explaining why it is stripped,
# in a backend that legitimately reads it, in a docstring. What may not come
# back is a boolean about its presence being computed for the UI to branch on.
BANNED_IDENTIFIERS = ("apiKeyPresent", "api_key_present")


def _frontend_sources() -> list[Path]:
    files = [
        p
        for ext in ("*.vue", "*.ts")
        for p in FRONTEND_SRC.rglob(ext)
        if "node_modules" not in p.parts
    ]
    assert files, f"no frontend sources found under {FRONTEND_SRC}"
    return files


def test_frontend_holds_no_credential_presence_flag() -> None:
    offenders = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in _frontend_sources()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if any(name in line for name in BANNED_IDENTIFIERS)
    ]
    assert not offenders, (
        "#342: the UI must not carry a credential-presence flag. Found: "
        + ", ".join(offenders)
        + ". A backend that needs a credential refuses at call time — see "
        "campaignlib/api/client.py and backends.py."
    )


def test_no_component_branches_on_the_env_var_name() -> None:
    """A component may not re-derive the flag under a different name either."""
    pattern = re.compile(r"""["']ANTHROPIC_API_KEY["']""")
    offenders = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in _frontend_sources()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, (
        "#342: no frontend source may test ANTHROPIC_API_KEY as a value. "
        "Found: " + ", ".join(offenders)
    )


def test_server_config_exposes_no_api_key_probe() -> None:
    tree = ast.parse((REPO_ROOT / "server" / "config.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "api_key_present" not in names, (
        "#342: server/config.py must not reintroduce api_key_present. "
        "Credential checks belong to the backend that needs them."
    )


def test_status_route_returns_no_credential_field() -> None:
    src = (REPO_ROOT / "server" / "routers" / "config_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    status = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "get_status"
        ),
        None,
    )
    assert status is not None, "get_status disappeared from config_routes.py"
    keys = {
        k.value
        for node in ast.walk(status)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "api_key_present" not in keys, (
        "#342: GET /api/config/status must not publish api_key_present — one "
        "global boolean cannot answer a per-backend, per-run question."
    )


def test_call_without_a_key_refuses_in_a_sentence(monkeypatch) -> None:
    """Deleting the UI gate is only safe because the call refuses cleanly.

    Without this the failure is an SDK authentication error raised mid-run —
    a traceback where the deleted button-disable used to be a message.
    """
    from campaignlib.api.client import _require_anthropic_credential

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class NotOneOfOurAdapters:
        """Stands in for the real anthropic.Anthropic client."""

    with pytest.raises(SystemExit) as excinfo:
        _require_anthropic_credential(NotOneOfOurAdapters())
    message = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in message
    # It must name the way out, not just the problem — that is the whole
    # difference between this and the SDK's own error.
    assert "claude-code" in message and "dgx" in message


def test_keyless_backends_are_never_refused(monkeypatch) -> None:
    """The three adapters need no Anthropic credential and must not be asked."""
    from campaignlib.api.backends import (
        _ClaudeCodeClient,
        _OpenAICompatClient,
        _OpenRouterClient,
    )
    from campaignlib.api.client import _require_anthropic_credential

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for cls in (_ClaudeCodeClient, _OpenAICompatClient, _OpenRouterClient):
        # __new__ without __init__: this asserts the *dispatch*, not the
        # constructors, which reach endpoints and registries.
        _require_anthropic_credential(object.__new__(cls))


def test_make_client_still_constructs_without_a_key(monkeypatch) -> None:
    """A client that is built and never used must not refuse (#342).

    Every ``--dump-only`` path in the grounding and ensemble CLIs constructs a
    client before it knows whether it will call one — that is the documented
    keyless subscription workflow. The check belongs at the call, not here.
    """
    from campaignlib.api.client import make_client

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DGX_ENDPOINT", raising=False)
    monkeypatch.delenv("CG_BACKEND", raising=False)
    assert make_client() is not None


def test_every_anthropic_entry_point_is_guarded() -> None:
    """All four ways to reach the metered API call the guard.

    A fifth entry point added without it would restore the old failure mode
    silently, which is exactly how the deleted predicate accumulated ten
    inconsistent copies in the first place.
    """
    guarded = {"call_api", "call_api_with_tools", "stream_api", "submit_batch"}
    found = set()
    for rel in ("campaignlib/api/client.py", "campaignlib/api/batch.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in guarded:
                continue
            calls = {
                c.func.id
                for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            }
            if "_require_anthropic_credential" in calls:
                found.add(node.name)
    assert found == guarded, f"unguarded Anthropic entry points: {guarded - found}"
