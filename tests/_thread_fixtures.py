"""Shared fixtures for the 014 thread-registry test files.

Kept in one place so `test_thread_registry_json.py`, `_rule.py` and
`_ratify.py` build the same campaign shape. The CLI is invoked as a
subprocess with `cwd` set to a temp campaign, because config resolution
(`stores.*` from `<config>/projections.yaml`) is CWD-relative and testing it
any other way would test something the product does not do.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "pipelines/grounding/thread_registry.py"


def campaign(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/projections.yaml").write_text("{}\n")
    return tmp_path


def chapter(tmp_path: Path, ch: int, facts: list[dict]) -> None:
    d = tmp_path / "docs/ensemble/per_chapter" / f"chapter_{ch:02d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "merged.json").write_text(json.dumps(facts))


def thread_fact(title: str, text: str, quote: str | None = None) -> dict:
    fa: dict = {"type": "thread", "subject": title, "fact": text}
    if quote:
        fa["quote_verified"] = True
        fa["source_quote"] = quote
    return fa


def cli(cwd: Path, *argv: str, stdin: str | None = None):
    """Run the CLI as the product does, but resolving imports from THIS tree.

    Without the PYTHONPATH pin the subprocess imports `campaignlib` from
    whatever the editable-install `.pth` points at — `/home/kroussos/src/
    CampaignGenerator`, the MAIN checkout — so a green run here would prove
    nothing about this branch (memory:
    `reference_worktree_editable_install_shadowing`). This bit us for real:
    `stores.thread_adjudication` existed only in the worktree, and the
    subprocess could not see it.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, str(CLI), *argv],
                          capture_output=True, text=True, cwd=cwd,
                          input=stdin, env=env)


CORPUS = "docs/ensemble/per_chapter/*/merged.json"
PROPOSALS = "docs/ensemble/thread_proposals.yaml"
REGISTRY = "docs/thread_registry.yaml"
ADJUDICATION = "docs/ensemble/thread_adjudication.json"


def harvested(tmp_path: Path) -> Path:
    """A campaign with one two-chapter candidate, already harvested."""
    c = campaign(tmp_path)
    chapter(c, 30, [thread_fact("Buppido's divine plan",
                                "Buppido speaks of a god only he hears.",
                                quote="the Sparkjewel told me")])
    chapter(c, 41, [thread_fact("Buppidos divine plan",
                                "He carves a shrine in secret.")])
    r = cli(c, "propose", "--corpus", CORPUS)
    assert r.returncode == 0, r.stderr
    return c


def proposals_doc(c: Path) -> dict:
    return yaml.safe_load((c / PROPOSALS).read_text())


def registry_doc(c: Path) -> dict:
    return yaml.safe_load((c / REGISTRY).read_text())
