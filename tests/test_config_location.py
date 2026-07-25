"""Config-location guard — one place for config files, in ``config/``.

Track 0 of ``docs/config/grounding-isolation.md``, per the GM directive of
2026-07-24. Single user, no installed base, so fallback probes for legacy
layouts buy nothing — and they cost correctness.

What they cost, concretely. Four code paths probed for ``party.yaml`` and
disagreed on both the candidate set and the precedence:

===========================================  ==========================
``campaignlib/party.py``                     ``docs/`` → ``config/``
``platform_config_service.py``               ``config/`` → root
``ensemble.py`` (party)                      ``config/`` → root
``ensemble.py`` (planning)                   ``config/`` → root
===========================================  ==========================

``docs/party.yaml`` appeared in exactly one of them, so the obelisk campaign
(whose roster lives there) had PC-name filtering find a roster while the Party
page and ensemble PC-exclusion found nothing — simultaneously, with no error
anywhere. A campaign holding both copies would have had two subsystems reading
two different files.

This test fails if a fifth probe shows up.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEARCH_DIRS = ("campaignlib", "pipelines", "server", "session_doc", "entity_registry")

#: Config documents that have exactly one declared location. A tuple/list
#: literal mentioning one of these twice is a probe.
CONFIG_FILENAMES = (
    "config.yaml",
    "ui_state.yaml",
    "platform.yaml",
    "planning.yaml",
    "party.yaml",
    "ensemble.yaml",
    "session_doc.yaml",
    "refs.yaml",
    "refs.local.yaml",
    "ingest_manifest.yaml",
)

#: ``docs/entity_registry.yaml`` is deliberately absent from the list above —
#: it is campaign DATA, not config (D7). ``config/`` holds how a pipeline runs;
#: ``docs/`` holds what the pipelines operate on.
NOT_CONFIG = "entity_registry.yaml"


def _source_files() -> list[Path]:
    files: list[Path] = []
    for d in SEARCH_DIRS:
        p = REPO_ROOT / d
        if p.is_dir():
            files.extend(f for f in p.rglob("*.py") if "__pycache__" not in f.parts)
    return sorted(files)


def _probe_literals(tree: ast.AST) -> list[str]:
    """Find tuple/list literals that list the same config file twice.

    ``("config/party.yaml", "party.yaml")`` is the exact shape all four deleted
    probes used: iterate candidate relative paths, take the first that exists.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List)):
            continue
        strings = [
            e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(strings) < 2:
            continue
        for name in CONFIG_FILENAMES:
            hits = [s for s in strings if s == name or s.endswith("/" + name)]
            if len(hits) > 1:
                found.append(f"{name}: {hits}")
    return found


def test_no_multi_location_config_probes():
    """No module may iterate over two candidate locations for one config file."""
    offenders: dict[str, list[str]] = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if probes := _probe_literals(tree):
            offenders[str(path.relative_to(REPO_ROOT))] = probes

    assert not offenders, (
        "config files have ONE declared location (campaignlib.constants."
        "config_path); a candidate list is a probe and reintroduces the "
        "Split-Brain Track 0 removed:\n"
        + "\n".join(f"  {f}: {'; '.join(v)}" for f, v in sorted(offenders.items()))
    )


def test_guard_detects_a_probe():
    """The guard is only meaningful if it can fail."""
    assert _probe_literals(ast.parse('for rel in ("config/party.yaml", "party.yaml"): pass'))
    assert _probe_literals(ast.parse('X = ["docs/party.yaml", "config/party.yaml"]'))
    # A list of DIFFERENT config files is not a probe — that is just a set of
    # things to migrate or check, which is legitimate.
    assert not _probe_literals(ast.parse('NAMES = ("config.yaml", "party.yaml")'))
    assert not _probe_literals(ast.parse('p = config_path(cd, "party.yaml")'))


def test_entity_registry_is_not_treated_as_config():
    """D7: the registry stays in docs/. Guard against a well-meaning move.

    If someone relocates it to ``config/``, this fails and they have to change
    the decision deliberately rather than by drive-by consistency.
    """
    hits = [
        str(p.relative_to(REPO_ROOT))
        for p in _source_files()
        if re.search(r'["\']config/entity_registry\.yaml["\']', p.read_text(encoding="utf-8"))
    ]
    assert not hits, (
        f"{NOT_CONFIG} is campaign data and lives in docs/, not config/ "
        f"(docs/config/grounding-isolation.md D7): {hits}"
    )


def test_config_dir_helper_is_the_single_definition():
    """``CONFIG_DIR_NAME``/``config_path`` are defined once, in
    ``campaignlib/constants.py``, and nowhere else in the tree.

    Deliberately read off disk under ``REPO_ROOT`` rather than imported. The
    editable install (``_editable_impl_campaigngenerator.pth``) puts the MAIN
    checkout on ``sys.path``, so in a git worktree ``import campaignlib`` can
    resolve to the other tree depending on import order — a guard that imported
    would be asserting against whichever copy won the race.
    """
    src = (REPO_ROOT / "campaignlib" / "constants.py").read_text(encoding="utf-8")
    assert "CONFIG_DIR_NAME" in src
    assert "def config_path(" in src

    definers = [
        str(p.relative_to(REPO_ROOT))
        for p in _source_files()
        if re.search(r"^CONFIG_DIR_NAME\s*=", p.read_text(encoding="utf-8"), re.M)
    ]
    assert definers == ["campaignlib/constants.py"], (
        f"CONFIG_DIR_NAME must be defined exactly once; found in {definers}"
    )
