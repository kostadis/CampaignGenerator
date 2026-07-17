"""CLI-level tests that prep/session_doc/planning refuse to render
without an approved docs/dossier_proposal.md when --require-proposal
is set.

Uses subprocess so the argparse flow is exercised exactly as a user
would run it. Each script gets three scenarios: missing proposal,
unapproved proposal, approved proposal. Missing / unapproved must exit
non-zero before reaching any Claude call; approved is allowed to
proceed far enough that a subsequent failure is *not* due to the
proposal gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pipelines.rlm.proposal_loader as pl


REPO_ROOT = Path(__file__).resolve().parent.parent

# prep.py has moved into pipelines/session_prep/ and now runs as the `prep`
# console script (pyproject.toml's [project.scripts]). Resolve it next to the
# current interpreter (same venv bin/) rather than relying on $PATH, so this
# test doesn't depend on the venv being "activated" in the process running
# pytest — same rationale as server.subprocess_runner.console_script().
PREP_BIN = str(Path(sys.executable).parent / "prep")

# planning.py has moved into pipelines/grounding/ and now runs as the
# `planning` console script — same rationale as PREP_BIN above.
PLANNING_BIN = str(Path(sys.executable).parent / "planning")

# sd_plan.py has moved into session_doc/ and now runs as the `sd_plan`
# console script — same rationale as PREP_BIN above.
SD_PLAN_BIN = str(Path(sys.executable).parent / "sd_plan")


def _write_proposal(campaign_dir: Path, text: str) -> Path:
    p = campaign_dir / pl.DOSSIER_PROPOSAL_REL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _write_config(campaign_dir: Path, documents: list[dict] | None = None) -> Path:
    """Minimal config.yaml with mandatory prep.py keys stubbed."""
    system_prompt = campaign_dir / "system_prompt.md"
    system_prompt.write_text("test system prompt", encoding="utf-8")
    config_path = campaign_dir / "config.yaml"
    lines = [
        f"system_prompt: {system_prompt}",
        "log_dir: logs/",
        "documents:",
    ]
    for doc in documents or []:
        lines.append(f"  - label: {doc['label']}")
        lines.append(f"    path: {doc['path']}")
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def _run(cmd: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ── prep.py ──────────────────────────────────────────────────────────────


class TestPrepRequireProposal:
    def test_missing_proposal_refused(self, tmp_path: Path):
        config = _write_config(tmp_path)
        result = _run(
            [
                PREP_BIN,
                "--config", str(config),
                "--campaign-dir", str(tmp_path),
                "--require-proposal",
                "--beat", "anything",
            ]
        )
        assert result.returncode != 0
        assert "dossier proposal not found" in result.stderr

    def test_unapproved_proposal_refused(self, tmp_path: Path):
        config = _write_config(tmp_path)
        _write_proposal(tmp_path, "# X\n\n> **Status:** candidates only.\n")
        result = _run(
            [
                PREP_BIN,
                "--config", str(config),
                "--campaign-dir", str(tmp_path),
                "--require-proposal",
                "--beat", "anything",
            ]
        )
        assert result.returncode != 0
        assert "not been approved" in result.stderr

    def test_approved_proposal_clears_the_gate(self, tmp_path: Path):
        """When approved, the proposal check passes and --clipboard lets
        prep exit without reaching the API call.
        """
        config = _write_config(tmp_path)
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved on 2026-04-24.\n")
        result = _run(
            [
                PREP_BIN,
                "--config", str(config),
                "--campaign-dir", str(tmp_path),
                "--require-proposal",
                "--no-log",
                "--clipboard",
                "--beat", "smoke",
            ]
        )
        # Clipboard mode may fail in headless CI because pyperclip needs a
        # real clipboard provider — but the proposal check must pass
        # silently. Anything coming back from stderr should NOT be the
        # "dossier proposal" / "not been approved" strings.
        assert "dossier proposal not found" not in result.stderr
        assert "not been approved" not in result.stderr


# ── sd_plan.py ───────────────────────────────────────────────────────────
# Phase 5 of SessionDocRefactor: --require-proposal migrated from
# session_doc.py to sd_plan.py. Same semantics, same error strings, same
# proposal_loader call path.


class TestSdPlanRequireProposal:
    def test_missing_proposal_refused(self, tmp_path: Path):
        sx_dir = tmp_path / "scene_extractions"
        sx_dir.mkdir()
        result = _run(
            [
                SD_PLAN_BIN,
                "--scene-extractions", str(sx_dir),
                "--characters", "Vukradin",
                "--campaign-dir", str(tmp_path),
                "--require-proposal",
            ]
        )
        assert result.returncode != 0
        assert "dossier proposal not found" in result.stderr

    def test_unapproved_proposal_refused(self, tmp_path: Path):
        sx_dir = tmp_path / "scene_extractions"
        sx_dir.mkdir()
        _write_proposal(tmp_path, "# X\n\n> **Status:** candidates only.\n")
        result = _run(
            [
                SD_PLAN_BIN,
                "--scene-extractions", str(sx_dir),
                "--characters", "Vukradin",
                "--campaign-dir", str(tmp_path),
                "--require-proposal",
            ]
        )
        assert result.returncode != 0
        assert "not been approved" in result.stderr


# ── planning.py ──────────────────────────────────────────────────────────


class TestPlanningRequireProposal:
    def test_missing_proposal_refused(self, tmp_path: Path):
        npc = tmp_path / "npc.md"
        npc.write_text("---\nname: X\n---\n", encoding="utf-8")
        out = tmp_path / "planning.md"
        result = _run(
            [
                PLANNING_BIN,
                "--npc", str(npc),
                "--output", str(out),
                "--campaign-dir", str(tmp_path),
                "--synthesize-only",
                "--require-proposal",
            ]
        )
        assert result.returncode != 0
        assert "dossier proposal not found" in result.stderr

    def test_unapproved_proposal_refused(self, tmp_path: Path):
        npc = tmp_path / "npc.md"
        npc.write_text("---\nname: X\n---\n", encoding="utf-8")
        _write_proposal(tmp_path, "# X\n\n> **Status:** candidates only.\n")
        result = _run(
            [
                PLANNING_BIN,
                "--npc", str(npc),
                "--output", str(tmp_path / "planning.md"),
                "--campaign-dir", str(tmp_path),
                "--synthesize-only",
                "--require-proposal",
            ]
        )
        assert result.returncode != 0
        assert "not been approved" in result.stderr
