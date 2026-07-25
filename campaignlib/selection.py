"""Model/backend selection vocabulary — feature 003.

Lives in ``campaignlib`` rather than ``server`` because this is the layer that
actually talks to the backends: ``campaignlib/api/client.py`` already declares
the same four names as its ``--backend`` choices, and ``campaignlib.constants``
already owns ``DEFAULT_MODEL``. Principle V — one seam per boundary — argues
for the vocabulary living with the boundary it describes.

The practical forcing function: ``PartyConfig`` and ``PlanningConfig`` are
campaignlib models (``campaignlib/party_config.py``,
``campaignlib/planning_config.py``), and a service document that carries a
``selection`` field cannot import one from ``server`` without inverting the
layering. ``server.platform_config_shared`` re-exports these names, so existing
imports keep working.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict

Backend = Literal["anthropic", "dgx", "openrouter", "claude-code"]

BACKENDS: tuple[str, ...] = ("anthropic", "dgx", "openrouter", "claude-code")


def _empty_to_none(v: Any) -> Any:
    """Treat empty/whitespace strings as 'unset' so defaults take over."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


_OptStr = Annotated[str | None, BeforeValidator(_empty_to_none)]


class ModelSelection(BaseModel):
    """A chosen model and the backend that serves it. Both optional; both
    absent means "no selection here — defer to the tier above".

    This is the *common core* of the two selection shapes that predate feature
    003 — ``server.ensemble_config_shared.EnsembleBackend`` (which adds
    ``endpoints``, plural, for the extract stage's two-Spark fan-out) and
    ``server.session_editor_config_shared.BackendProfile`` (which adds
    ``endpoint``, singular). That plural/singular split is load-bearing and
    deliberately NOT unified; see
    ``specs/003-model-selection-resolution/data-model.md``.

    An incompatible pair (a DGX model id with an Anthropic backend, say) is
    *storable* but not *runnable*: the write is allowed so the operator can
    switch the platform backend and come back to fix the override later, while
    resolution refuses the run and says why. Rejecting the write instead would
    make the refusal message unreachable.
    """

    model_config = ConfigDict(extra="forbid")

    backend: Backend | None = None
    model: _OptStr = None

    def is_empty(self) -> bool:
        """True when this selection defers entirely to the tier above.

        An empty selection MUST be indistinguishable from an absent one, so
        consumers test this rather than ``is None``.
        """
        return not self.backend and not self.model


def compatible(model: str | None, backend: str | None) -> bool:
    """Can ``backend`` serve ``model``?

    The check is a ``claude-`` prefix rather than membership of
    ``server.config.MODELS`` on purpose. MODELS is a hand-maintained snapshot;
    testing against it would silently reject a legitimate Claude id that simply
    hadn't been added yet — quietly refusing a model the caller is entitled to
    run. The prefix only rejects ids that *cannot* be Anthropic API ids
    (``Qwen/…``, ``openai/…``, and OpenRouter's own ``anthropic/claude-…``
    form), and never second-guesses one that could.

    (Carried forward verbatim from the inline guard that used to live in
    ``server/routers/ensemble.py::_backend_args``. The *rule* survives here;
    the silent substitution that accompanied it did not.)

    An absent model is vacuously compatible: it means "nothing chosen", which
    resolution handles by falling back, not by refusing.
    """
    if not model:
        return True
    is_claude = model.startswith("claude-")
    if backend in ("anthropic", "claude-code", None, ""):
        return is_claude
    if backend == "dgx":
        return not is_claude
    if backend == "openrouter":
        # OpenRouter ids are vendor-namespaced ("anthropic/claude-sonnet-4.6",
        # "qwen/qwen3-next-80b"). A bare "claude-…" is an Anthropic API id and
        # would 404 there.
        return "/" in model
    return True
