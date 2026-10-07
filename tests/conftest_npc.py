"""Helpers shared by the spec 032 NPC-dossier tests (import them; this is not a conftest).

``npc_campaign`` copies the fixture and builds the 031 corpus for chapters 2-6 through
``cli.main``, so the NPC stages start from exactly what a user's ``build`` leaves.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import shutil
from pathlib import Path

from pipelines.summary_native.cli import main

NPC_FIXTURE = Path(__file__).parent / "fixtures" / "summary_native_npc"
SINCE, UNTIL = 2, 6


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run ``summary_native.cli.main`` and return ``(exit_code, stdout, stderr)``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(list(args))
    return rc, out.getvalue(), err.getvalue()


def npc_campaign(tmp_path: Path) -> Path:
    """Copy the fixture under ``tmp_path`` and build its corpus; return the campaign root."""
    root = tmp_path / "camp"
    shutil.copytree(NPC_FIXTURE, root, ignore=shutil.ignore_patterns("README.md"))
    rc, out, err = run_cli(
        [
            "build",
            "--config", str(root / "config" / "config.yaml"),
            "--summaries-dir", str(root / "docs" / "summaries"),
            "--since", str(SINCE),
            "--until", str(UNTIL),
        ]
    )
    assert rc == 0, f"fixture build failed ({rc}):\n{out}\n{err}"
    return root


def sha_tree(directory: Path) -> dict[str, str]:
    """``{relative path: sha256}`` for every file under ``directory``, for byte-identity checks."""
    directory = Path(directory)
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


# ── A stub model for chunked drafting (T060) ─────────────────────────────────

import re  # noqa: E402

REDUCE_BODY = (
    "## Identity\n\nA deep gnome guide. [ch 002 / entry]\n\n"
    "## Personality and Motivations\n\nCautious and watchful. [ch 003 / 003.01]\n\n"
    "## Last Observed State\n\nAs of chapter 006 he kept the first watch. [ch 006 / 006.02]\n\n"
    "## Relationships\n\n- Travels with Eldeth. [ch 002 / 002.01]\n"
)


def kind_of(system: str) -> str:
    """``map`` | ``reduce`` | ``one-shot``, from the system prompt's opening line."""
    if "PROSE PART" in system:
        return "reduce"
    if "PART of a DRAFT" in system:
        return "map"
    return "one-shot"


def map_output(user: str) -> str:
    """A well-formed map reply built from the chunk's own evidence: one History bullet per scene,
    every moment blockquote as a quote cited to its chapter's moment."""
    hist, quotes = [], []
    for part in re.split(r"(?m)^(?=## Chapter \d+)", user):
        m = re.match(r"## Chapter (\d+)", part)
        if not m:
            continue
        ch = m.group(1)
        for sid in re.findall(r"(?m)^### Scene (\d{3}\.\d{2})", part):
            hist.append(f"- Something happened. [ch {ch} / {sid}]")
        for q in re.findall(r'(?m)^> ("[^"]+")$', part):
            quotes.append(f"> {q}\n— Speaker Name [ch {ch} / moment]")
    return (
        "## History with the Party\n" + "\n".join(hist) + "\n\n## Notable Quotes\n" + "\n\n".join(quotes)
        + "\n\n## Arc-Score Candidates\n" + (hist[0].replace("Something happened.", "Candidate: the party escapes.") if hist else "") + "\n"
    )
