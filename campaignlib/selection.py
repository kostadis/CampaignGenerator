"""Model/backend selection vocabulary — feature 003.

Lives in ``campaignlib`` rather than ``server`` because this is the layer that
actually talks to the backends: ``campaignlib/api/client.py`` already declares
the same canonical names as its ``--backend`` choices, and ``campaignlib.constants``
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

Backend = Literal["anthropic", "dgx", "openrouter", "claude-code", "codex-cli"]
CodexReasoningEffort = Literal[
    "minimal", "low", "medium", "high", "xhigh", "max"
]
# Deliberately NOT the same set as CodexReasoningEffort: `claude --effort`
# accepts five levels and has no "minimal". Sharing one vocabulary between the
# two subscription backends would put a value in `--help` that fails at the
# call, which is the dialect Principle XII forbids — see
# specs/021-claude-code-effort/research.md R1.
ClaudeCodeEffort = Literal["low", "medium", "high", "xhigh", "max"]

BACKENDS: tuple[str, ...] = (
    "anthropic", "dgx", "openrouter", "claude-code", "codex-cli"
)
CODEX_REASONING_EFFORTS: tuple[CodexReasoningEffort, ...] = (
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
CLAUDE_CODE_EFFORTS: tuple[ClaudeCodeEffort, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
# The two levels `claude -p` refuses when extended thinking is disabled. Kept
# beside the vocabulary rather than inline at the check so the rule has one
# home; campaignlib.api.backends reads it.
CLAUDE_CODE_THINKING_ONLY_EFFORTS: tuple[ClaudeCodeEffort, ...] = ("xhigh", "max")


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

    ``batch`` (feature 005-ui-batch-selection) is a *third*, independently
    optional field, resolved by ``server.platform_config_service.
    resolve_selection`` with the same request -> service -> platform
    precedence as ``model``/``backend`` but NOT subject to their pairing rule
    (a service that sets only ``batch`` does not thereby inherit that tier's
    model or backend — research D2 of that spec). ``None`` means "defer to
    the tier above"; ``False`` is a genuine, sticky "explicitly off for this
    service" that does not follow an app-wide change — the two must stay
    distinguishable, so this is ``bool | None`` rather than a bare ``bool``
    with a ``False`` default (see ``specs/005-ui-batch-selection/data-model.md``'s
    "Batch selection, by tier" table). An unsatisfiable ``batch: true`` is
    storable-not-rejected for the same reason an incompatible model/backend
    pair is, above.

    ``claude_code_effort`` (feature 021) is the ``claude-code`` twin of
    ``codex_reasoning_effort`` and behaves exactly like it: independently
    optional, ``None`` means "defer to the tier above", and an effort stored
    against a different active backend is storable-not-runnable. The two are
    deliberately separate fields rather than one shared "effort" — the
    vocabularies differ (``minimal`` is Codex-only) and omission means
    different things on each backend, so one field would carry two meanings.
    Both may be set at once; each lies dormant while the other backend is
    active.

    ``claude_code_thinking`` (issue #365) is ``bool | None`` for the same
    reason ``batch`` is, and the distinction is load-bearing here: ``None``
    defers to ``CG_CLAUDE_CODE_THINKING``, while ``False`` is a sticky
    "explicitly off" that beats the environment. Collapsing the two would make
    an operator's deliberate "off" indistinguishable from silence, and an
    exported variable would then quietly override them.
    """

    model_config = ConfigDict(extra="forbid")

    backend: Backend | None = None
    model: _OptStr = None
    batch: bool | None = None
    codex_reasoning_effort: CodexReasoningEffort | None = None
    claude_code_effort: ClaudeCodeEffort | None = None
    claude_code_thinking: bool | None = None

    def is_empty(self) -> bool:
        """True when this selection defers entirely to the tier above.

        An empty selection MUST be indistinguishable from an absent one, so
        consumers test this rather than ``is None``. ``batch`` participates
        here too (005): a selection carrying only ``batch=True`` (or
        ``False``) is NOT empty — it has something to say — even though
        ``backend``/``model`` are unset. Without this, ``_selection_for``-style
        callers across grounding/party/planning/editor would treat a
        batch-only override as "no override at all" and the stored intent
        would never reach ``resolve_selection``, nor survive a save that
        gates on emptiness (``save_party_config``/``save_planning_config``).
        """
        return (
            not self.backend
            and not self.model
            and self.batch is None
            and self.codex_reasoning_effort is None
            and self.claude_code_effort is None
            and self.claude_code_thinking is None
        )


def compatible(model: str | None, backend: str | None) -> bool:
    """Can ``backend`` serve ``model``?

    Existing backend checks use a ``claude-`` prefix rather than membership of
    ``server.config.MODELS`` on purpose. MODELS is a hand-maintained snapshot;
    testing against it would silently reject a legitimate Claude id that simply
    hadn't been added yet — quietly refusing a model the caller is entitled to
    run. The prefix only rejects ids that *cannot* be Anthropic API ids
    (``Qwen/…``, ``openai/…``, and OpenRouter's own ``anthropic/claude-…``
    form), and never second-guesses one that could.

    (Carried forward verbatim from the inline guard that used to live in
    ``server/routers/ensemble.py::_backend_args``. The *rule* survives here;
    the silent substitution that accompanied it did not.)

    Codex uses that same prefix check case-insensitively and rejects Claude
    model ids; all other backend checks retain their historical case-sensitive
    behavior. An absent model is vacuously compatible: it means "nothing
    chosen", which resolution handles by falling back, not by refusing.
    """
    if model is None or (isinstance(model, str) and not model.strip()):
        return True
    is_claude = model.startswith("claude-")
    # Codex model ids must not be Claude ids. Unlike the historical backend
    # checks below, this is deliberately case-insensitive: an explicitly
    # supplied ``CLAUDE-*`` value must not evade the Codex guard.
    if backend == "codex-cli":
        return not model.lower().startswith("claude-")
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
