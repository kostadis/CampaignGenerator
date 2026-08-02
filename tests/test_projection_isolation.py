"""Isolation and legacy-draft-gate tests for State Projection's output
(006-state-projection-service, User Story 1).

Before this feature all three rendering services wrote the same
``docs/<doc>_draft.md`` filename (research D2): building one silently
destroyed whichever of the other two had rendered most recently.
``test_run_leaves_other_services_untouched`` is the regression test for that
defect — each service now owns its own output namespace (research D13), and
a State Projection build must never touch a byte outside
``docs/projections/``.

``test_legacy_draft_gate`` covers the one-time migration aid the move needs
(FR-007b): a pre-move draft at the old shared path is neither guessed at nor
clobbered — the build refuses until the GM clears it by hand.
"""

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CLI = REPO / "pipelines/grounding/grounding_sections.py"


def run_cli(cwd, *argv):
    return subprocess.run([sys.executable, str(CLI), *argv],
                          capture_output=True, text=True, cwd=cwd)


def _campaign(tmp_path: Path) -> Path:
    """A minimal campaign_state-buildable fixture — deterministic sections
    only (no --backend), mirroring tests/test_grounding_sections.py's
    fixture so this file exercises the same real CLI path."""
    camp = tmp_path
    (camp / "docs/ensemble").mkdir(parents=True)
    rows = [{"chapter": 40, "scene": 1, "seq": 1, "event": "Orc nine dies."}]
    (camp / "docs/ensemble/events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    (camp / "docs/thread_registry.yaml").write_text(
        yaml.safe_dump({"version": 1, "threads": []}))
    (camp / "docs/party.md").write_text("# Party\n\nVukradin and friends.\n")
    return camp


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_leaves_other_services_untouched(tmp_path):
    camp = _campaign(tmp_path)

    # Simulate the other two rendering services already having produced
    # output for this same document, plus the promoted live doc and both
    # sibling services' own config files. None of this is State Projection's
    # to read or write (FR-003, FR-006) — a build for campaign_state must
    # leave every one of these byte-identical.
    other_files = {
        camp / "docs/pertool/campaign_state_draft.md": "per-tool rendering draft\n",
        camp / "docs/ensemble/drafts/campaign_state_draft.md": "dossier synthesis draft\n",
        camp / "docs/campaign_state.md": "promoted live doc\n",
        camp / "config/grounding.yaml": "sections_dir: docs/grounding_sections\n",
        camp / "config/ensemble.yaml": "chapters_selected: []\n",
    }
    for path, body in other_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    before = {path: _sha(path) for path in other_files}

    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert r.returncode == 0, r.stderr

    for path, sha in before.items():
        assert path.exists(), f"{path} disappeared during a State Projection build"
        assert _sha(path) == sha, f"{path} was modified by a State Projection build"

    # The new output landed only under the projections namespace — never
    # back onto the pre-move shared filename the other services still use.
    draft = camp / "docs/projections/campaign_state_draft.md"
    assert draft.exists()
    assert "Orc nine dies." in draft.read_text()
    assert not (camp / "docs/campaign_state_draft.md").exists()


def test_legacy_draft_gate(tmp_path):
    camp = _campaign(tmp_path)
    legacy = camp / "docs/campaign_state_draft.md"
    legacy.write_text("pre-move draft — the GM's diff baseline\n", encoding="utf-8")
    before = _sha(legacy)

    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert r.returncode != 0
    assert "a pre-move draft still exists at docs/campaign_state_draft.md" in r.stderr
    assert "docs/projections/campaign_state_draft.md" in r.stderr
    assert "nothing will be moved for you" in r.stderr

    # Never moved or deleted, and no new draft was written either.
    assert legacy.exists()
    assert _sha(legacy) == before
    assert not (camp / "docs/projections/campaign_state_draft.md").exists()

    # Once the GM clears it by hand, the gate never fires again.
    legacy.unlink()
    r2 = run_cli(camp, "build", "--doc", "campaign_state")
    assert r2.returncode == 0, r2.stderr
    assert (camp / "docs/projections/campaign_state_draft.md").exists()


# ── cross-service config reads (User Story 2) ───────────────────────────

#: Reading either of these from pipelines/grounding/ is a cross-service
#: config read — the same defect feature 003 deleted
#: `grounding.py:_backend_flags` for (it read Dossier Synthesis's backend
#: choice from inside the Grounding engine). State Projection declares its
#: OWN input pointers in ProjectionConfig (FR-003) instead of reaching into
#: a sibling service's document.
_FORBIDDEN_CONFIG_NAMES = {"EnsembleConfig", "GroundingConfig"}


def _forbidden_cross_service_imports(tree: ast.AST) -> list[str]:
    """Return the offending statements, rendered, or [] if clean.

    AST-based, not string matching — mirrors tests/test_layering.py, which
    this test complements: test_layering forbids `pipelines/` importing
    `server` at all; this one additionally names the two config classes
    explicitly, so the guard still fires if either were ever re-exported
    from somewhere other than `server.*`.
    """
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and (
                node.module == "server" or node.module.startswith("server.")
            ):
                names = ", ".join(a.name for a in node.names)
                bad.append(f"from {node.module} import {names}")
            for alias in node.names:
                if alias.name in _FORBIDDEN_CONFIG_NAMES:
                    bad.append(f"from {node.module} import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "server" or alias.name.startswith("server."):
                    bad.append(f"import {alias.name}")
    return bad


def test_no_cross_service_config_read():
    """No module under pipelines/grounding/ may import EnsembleConfig,
    GroundingConfig, or anything from server.* at all (FR-003).

    State Projection depends on the Extraction & State service's OUTPUT
    (the fact corpus, the dossiers) through declared pointers in its own
    ProjectionConfig — never on another rendering service's config
    document. That was exactly the shape of the bug feature 003 closed by
    deleting `grounding.py:_backend_flags`, which read Dossier Synthesis's
    backend selection straight out of `ensemble.yaml`. This is the
    regression test for that pattern recurring in this service.
    """
    grounding_dir = REPO / "pipelines" / "grounding"
    offenders: dict[str, list[str]] = {}
    for path in sorted(grounding_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if bad := _forbidden_cross_service_imports(tree):
            offenders[str(path.relative_to(REPO))] = bad

    assert not offenders, (
        "pipelines/grounding/ module(s) read another service's config "
        "directly — declare an input pointer in ProjectionConfig instead:\n"
        + "\n".join(f"  {f}: {'; '.join(v)}" for f, v in sorted(offenders.items()))
    )


def test_no_cross_service_config_read_detects_a_violation():
    """The guard above is only meaningful if it can actually fail."""
    tree = ast.parse("from server.ensemble_config_shared import EnsembleConfig")
    assert _forbidden_cross_service_imports(tree)
    tree = ast.parse("import server.grounding_config_shared")
    assert _forbidden_cross_service_imports(tree)
    # ...and does not fire on the legitimate case.
    assert not _forbidden_cross_service_imports(
        ast.parse("from campaignlib.projection_config import load_projection_config")
    )


# ── no docs/-shaped literals survive outside projections.yaml (US3) ─────

#: The State Projection engine — every one of these must resolve every
#: store/input/output path from `ProjectionConfig` rather than a Python
#: literal (research D1, FR-009, FR-014). Modelled on
#: tests/test_ensemble_config_defaults.py's TestNoDrift, one layer down.
_NO_LITERALS_FILES = [
    REPO / "pipelines/grounding/grounding_sections.py",
    REPO / "pipelines/grounding/event_spine.py",
    REPO / "pipelines/grounding/thread_registry.py",
    REPO / "pipelines/grounding/build_recent_events.py",
]

_DOCS_SHAPED = re.compile(r"^(docs/|summaries/|summaries$)")


def _docstring_constants(tree: ast.AST) -> list[ast.Constant]:
    """The bare-string-expression Constant nodes that ARE docstrings —
    module/class/function leading statements — so the scan below doesn't
    flag prose that merely mentions a path for a human reader (this very
    module's docstring included). Comments are not AST nodes at all and so
    need no handling here; the point of using AST instead of
    TestNoDrift's raw ``if lit in line`` scan is precisely to tell the two
    apart.
    """
    hosts = [tree] + [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    out: list[ast.Constant] = []
    for node in hosts:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.append(body[0].value)
    return out


def _docs_shaped_literals(path: Path) -> list[tuple[int, str]]:
    """Every non-docstring string ``Constant`` in ``path`` whose value is
    itself docs/- or summaries-shaped — catches default arguments and module
    constants (e.g. ``default=Path("docs/...")``), not merely a substring
    buried in a longer sentence (a rendered doc's own prose legitimately
    mentions ``docs/thread_registry.yaml`` for a human reader; that string
    does not itself start with ``docs/``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_constants(tree)
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if any(node is d for d in docstrings):
            continue
        if _DOCS_SHAPED.match(node.value):
            offenders.append((node.lineno, node.value))
    return offenders


def test_no_docs_literals():
    """No `docs/`-shaped or `summaries`-shaped string literal survives in
    the four State Projection engine files — every one must be declared
    exactly once, in `projections.yaml`, and resolved from the loaded
    config (the GOAL this whole story exists for). A literal surviving here
    is the same defect `ensemble-isolation.md`/`grounding-isolation.md` each
    fixed once already: a location unreachable without editing code.
    """
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _NO_LITERALS_FILES:
        found = _docs_shaped_literals(path)
        if found:
            offenders[str(path.relative_to(REPO))] = found
    assert not offenders, (
        "docs/-shaped or summaries-shaped literal(s) survive in the State "
        "Projection engine — declare them in "
        "campaignlib/projection_config.py and resolve from the loaded "
        "config instead:\n"
        + "\n".join(f"  {f}:{ln}: {v!r}"
                    for f, hits in sorted(offenders.items()) for ln, v in hits)
    )


def test_no_docs_literals_detects_a_violation():
    """The guard above is only meaningful if it can actually fail — and it
    must NOT fire on a docstring that merely mentions the same shape."""
    code_tree = ast.parse('DEFAULT_STORE = Path("docs/ensemble/events.jsonl")\n')
    assert any(
        _DOCS_SHAPED.match(n.value) for n in ast.walk(code_tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and not any(n is d for d in _docstring_constants(code_tree))
    )
    doc_tree = ast.parse('"""Reads docs/ensemble/events.jsonl for its rows."""\n')
    doc_consts = _docstring_constants(doc_tree)
    assert doc_consts and not any(
        _DOCS_SHAPED.match(n.value) for n in ast.walk(doc_tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and not any(n is d for d in doc_consts)
    )


# ── a redirected store is honoured by the freshness hash AND the read ───

def _section_state(list_stdout: str, section: str) -> str:
    m = re.search(rf"^{re.escape(section)}\s+\S+\s+(\S+)", list_stdout, re.M)
    assert m, f"section {section!r} not found in list output:\n{list_stdout}"
    return m.group(1)


def test_redirected_store_is_honoured_by_hash_and_read(tmp_path):
    """The regression test for the three-site split (research D1, FR-009):
    before US3, `docs/ensemble/events.jsonl` was a literal independently
    hardcoded at `section_inputs`' freshness hash, `render_spine`'s read and
    `render_tracking`'s read. Redirecting `stores.events` in
    `projections.yaml` must be honoured by every one of those sites
    TOGETHER — if a future edit reintroduces even one hardcoded literal
    alongside the config lookup, this test fails: either the redirected
    file's content never reaches the draft, or a stale stamp never
    invalidates when only the redirected file changes.
    """
    camp = _campaign(tmp_path)
    # The default-location store the fixture wrote — deliberately left on
    # disk and untouched from here on, so a read that silently falls back
    # to it (instead of the redirected path) is caught by its content never
    # appearing in the draft below.
    default_store = camp / "docs/ensemble/events.jsonl"
    assert "Orc nine dies." in default_store.read_text()

    redirected = camp / "alt_state" / "events.jsonl"
    redirected.parent.mkdir(parents=True)
    redirected.write_text(json.dumps(
        {"chapter": 50, "scene": 1, "seq": 1, "event": "Redirected event only here."}
    ) + "\n")
    (camp / "config").mkdir(parents=True, exist_ok=True)
    (camp / "config/projections.yaml").write_text(
        yaml.safe_dump({"stores": {"events": "alt_state/events.jsonl"}}))

    r = run_cli(camp, "build", "--doc", "campaign_state")
    assert r.returncode == 0, r.stderr
    draft = (camp / "docs/projections/campaign_state_draft.md").read_text()
    assert "Redirected event only here." in draft
    assert "Orc nine dies." not in draft   # never fell back to the default path

    # Unchanged redirected content -> fresh, nothing to re-render.
    r2 = run_cli(camp, "list", "--doc", "campaign_state")
    assert r2.returncode == 0, r2.stderr
    assert _section_state(r2.stdout, "recent_events") == "fresh"

    # Mutate ONLY the redirected file — the untouched default-location file
    # must play no part in the freshness decision.
    redirected.write_text(redirected.read_text() + json.dumps(
        {"chapter": 51, "scene": 1, "seq": 1, "event": "Second redirected event."}
    ) + "\n")
    r3 = run_cli(camp, "list", "--doc", "campaign_state")
    assert _section_state(r3.stdout, "recent_events") == "stale"

    r4 = run_cli(camp, "build", "--doc", "campaign_state")
    assert r4.returncode == 0, r4.stderr
    draft2 = (camp / "docs/projections/campaign_state_draft.md").read_text()
    assert "Second redirected event." in draft2
