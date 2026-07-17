"""
proposal_loader.py — shared dossier_proposal.md loading for render pipelines.

Phase 3 of the RLM integration plan wires one invariant into ``prep.py``,
``session_doc.py`` and ``planning.py``:

    render pipelines consume a human-approved `docs/dossier_proposal.md`
    rather than raw rpg_retriever output.

This module provides the small helpers those scripts need to enforce it:

* :func:`load_proposal` — idempotent read of ``<campaign-dir>/docs/dossier_proposal.md``.
* :func:`require_approved_proposal` — strict check used by render-gated modes.
* :func:`attach_proposal_to_documents` — inject the proposal into the
  config's documents list at runtime so ``campaignlib.assemble_docs``
  picks it up with no config file edits.

Keeping this tiny and library-only means there's exactly one code path
that knows how to find and validate the proposal file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .dossier_proposer import is_approved

logger = logging.getLogger(__name__)


DOSSIER_PROPOSAL_REL_PATH = Path("docs/dossier_proposal.md")
DOSSIER_PROPOSAL_LABEL = "dossier_proposal"


# ── Exceptions ───────────────────────────────────────────────────────────


class ProposalRequired(RuntimeError):
    """Raised when a render pipeline demands a proposal and none is present."""


class ProposalNotApproved(RuntimeError):
    """Raised when a proposal file exists but still carries the default
    ``candidates only`` status banner (i.e. no human has reviewed it)."""


# ── Resolution ───────────────────────────────────────────────────────────


@dataclass
class LoadedProposal:
    path: Path
    text: str
    approved: bool


def _proposal_path(campaign_dir: Path | str | None) -> Path:
    """Return the canonical proposal path inside ``campaign_dir``. Does
    not touch the filesystem.
    """
    if campaign_dir is None:
        return Path.cwd() / DOSSIER_PROPOSAL_REL_PATH
    return Path(campaign_dir).expanduser().resolve() / DOSSIER_PROPOSAL_REL_PATH


def load_proposal(campaign_dir: Path | str | None = None) -> LoadedProposal | None:
    """Load ``<campaign-dir>/docs/dossier_proposal.md`` if it exists.

    Returns ``None`` when the file is missing — callers treat that as
    "no proposal yet" (fine for non-gated modes).
    """
    path = _proposal_path(campaign_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("proposal_loader: could not read %s: %s", path, exc)
        return None
    return LoadedProposal(path=path, text=text, approved=is_approved(text))


def require_approved_proposal(campaign_dir: Path | str | None = None) -> LoadedProposal:
    """Strict read — used by render-gated workflow modes.

    Raises :class:`ProposalRequired` when the file is missing, or
    :class:`ProposalNotApproved` when it exists but the status banner
    still says ``candidates only``.
    """
    loaded = load_proposal(campaign_dir)
    if loaded is None:
        raise ProposalRequired(
            f"dossier proposal not found at {_proposal_path(campaign_dir)}. "
            "Run `dossier_proposer '<query>'` to generate one, "
            "review + edit it, then change the status banner to "
            "`> **Status:** approved by <name> on <date>.` before re-running."
        )
    if not loaded.approved:
        raise ProposalNotApproved(
            f"proposal at {loaded.path} has not been approved — edit the "
            "`> **Status:**` header line away from `candidates only` "
            "after review."
        )
    return loaded


# ── Config integration ───────────────────────────────────────────────────


def attach_proposal_to_documents(
    config: dict,
    campaign_dir: Path | str | None = None,
    *,
    label: str = DOSSIER_PROPOSAL_LABEL,
    prepend: bool = False,
) -> bool:
    """Append a synthetic ``documents`` entry so ``assemble_docs`` picks
    the proposal up with no config-file edits.

    Idempotent — returns ``True`` on first attach and ``False`` if the
    config already has a document with the given ``label``. Does nothing
    when the proposal file is absent.
    """
    loaded = load_proposal(campaign_dir)
    if loaded is None:
        return False

    docs = config.setdefault("documents", [])
    for entry in docs:
        if isinstance(entry, dict) and entry.get("label") == label:
            return False

    record = {"label": label, "path": str(loaded.path)}
    if prepend:
        docs.insert(0, record)
    else:
        docs.append(record)
    return True


__all__ = [
    "DOSSIER_PROPOSAL_LABEL",
    "DOSSIER_PROPOSAL_REL_PATH",
    "LoadedProposal",
    "ProposalNotApproved",
    "ProposalRequired",
    "attach_proposal_to_documents",
    "load_proposal",
    "require_approved_proposal",
]
