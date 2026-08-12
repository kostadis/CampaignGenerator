"""Party roster configuration — models and YAML I/O for ``<config>/party.yaml``.

Phase 1 of ``docs/config/grounding-isolation.md``. This module is the **one**
implementation of the party roster's shape. Before it there were two: a
validating dataclass loader in ``server/party_config_shared.py`` and a raw-YAML
re-implementation of the same three-state ``arc_score`` encoding inside
``server/routers/config_routes.py``'s ``party-yaml`` routes, which validated
nothing and wrote non-atomically.

It lives in ``campaignlib`` rather than ``server`` so the dependency arrow
points one way: ``server/`` and ``pipelines/`` both import ``campaignlib``, and
neither imports the other. ``pipelines/grounding/party.py`` previously did
``from server.party_config_shared import …`` — the CLI engine importing the web
app.

**Authored vs resolved.** The models below hold paths exactly as the GM wrote
them, relative to a base directory that is *not* stored here. Resolution to
absolute paths is a separate, explicit step (:func:`resolve_party_config`).
That split exists because the obvious alternative — resolving during load, the
way the old loader did — makes a load/save round-trip silently rewrite every
relative path in the file as an absolute one. ``save_planning_config`` has that
exact bug today (it writes ``str(entry.dossier)`` where ``dossier`` is a
resolved absolute ``Path``), so a roster edited in the UI comes back
machine-specific and unportable.

**Strict vs lenient.** Shape errors always raise. File-existence is the
caller's choice, because the two callers legitimately differ: the CLI must
refuse to render a document from a roster pointing at files that are not there,
while the API must let the GM name a sheet they are about to write. See
:func:`resolve_party_config`'s ``require_files`` and :func:`missing_files`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import yaml
from campaignlib.selection import ModelSelection
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from campaignlib.util import atomic_write_text

PARTY_CONFIG_FILENAME = "party.yaml"


def _as_authored(v: Any) -> Any:
    """Accept a ``Path`` at the boundary, store the string.

    Callers that already hold a ``Path`` (the CLI, tests) shouldn't have to
    stringify it, but there is exactly one internal representation so a
    load/save round-trip cannot rewrite what the GM authored.
    """
    return str(v) if isinstance(v, Path) else v


AuthoredPath = Annotated[str | None, BeforeValidator(_as_authored)]

#: Per-character path fields, in the order they are rendered and reported.
#: ``sheet`` is required; the rest are optional.
PATH_FIELDS: tuple[str, ...] = ("sheet", "backstory", "dossier", "arc_score")


class PartyCharacter(BaseModel):
    """One PC, with paths exactly as authored.

    ``arc_score`` + ``trackless`` encode the three states the YAML
    distinguishes:

    ==================  ==================  =========================
    On disk             ``arc_score``       ``trackless``
    ==================  ==================  =========================
    key absent          ``None``            ``False``
    ``arc_score: null`` ``None``            ``True``   (trackless by design)
    ``arc_score: path`` the path            ``False``
    ==================  ==================  =========================

    ``dossier`` is the PC's ensemble-built current-state dossier (from
    ``facts_to_state``'s ``merged_dossiers/``) — narrative facts from actual
    play that the static sheet and backstory don't carry. Which dossier belongs
    to which PC is a campaign-specific attribution decision, so it is always an
    explicit human-authored mapping, never inferred by name-matching.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    sheet: Annotated[str, BeforeValidator(_as_authored)]
    backstory: AuthoredPath = None
    dossier: AuthoredPath = None
    arc_score: AuthoredPath = None
    trackless: bool = False


class PartyConfig(BaseModel):
    """Root model — the ``<config>/party.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    characters: list[PartyCharacter] = Field(default_factory=list)

    #: Feature 003 — this service's own model/backend override. Empty means
    #: "defer to the platform selection", which is the default and the common
    #: case. Set it to run this document's generation on a different model or
    #: backend from the rest of the app, affecting only this service's runs.
    selection: ModelSelection = Field(default_factory=ModelSelection)


class ResolvedCharacter(BaseModel):
    """A :class:`PartyCharacter` with its paths resolved against a base dir.

    Never persisted — this is what the render pipelines consume, so they can
    read the referenced files. Producing it is always explicit, so a save path
    can never accidentally serialize absolute paths back into the roster.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    sheet: Path
    backstory: Path | None = None
    dossier: Path | None = None
    arc_score: Path | None = None
    trackless: bool = False


class ResolvedPartyConfig(BaseModel):
    """A :class:`PartyConfig` with every path resolved. Never persisted.

    Mirrors :class:`PartyConfig`'s single ``characters`` attribute so the
    render pipelines can take either shape without caring which they were
    handed.
    """

    model_config = ConfigDict(extra="forbid")

    characters: list[ResolvedCharacter] = Field(default_factory=list)


def load_party_config(path: Path) -> PartyConfig:
    """Load ``party.yaml`` and validate its *shape* only.

    Paths are returned as authored; nothing is resolved and no file is checked
    for existence — see :func:`resolve_party_config` for that.

    A missing file, or one that parses to an empty/null YAML document, returns
    an empty :class:`PartyConfig` rather than raising. An empty roster is a
    legitimate state (a campaign that has not set one up yet, or one whose last
    character was just deleted through the API), and the "emptied file reads
    back as 400" bug ``docs/config/planning-isolation.md`` had to fix twice is
    not worth re-introducing. Callers that require a non-empty roster — the
    CLI does — check for themselves.

    Raises ``ValueError`` on malformed YAML or a structurally invalid entry.
    """
    if not path.exists():
        return PartyConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return PartyConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    chars_raw = raw.get("characters") or []
    if not isinstance(chars_raw, list):
        raise ValueError(f"{path}: 'characters' must be a list")

    characters: list[PartyCharacter] = []
    for entry in chars_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"each character entry in {path} must be a mapping")
        name = entry.get("name")
        sheet = entry.get("sheet")
        if not name or not sheet:
            raise ValueError(
                f"character entry in {path} missing 'name' or 'sheet': {entry}"
            )
        # The three-state read: presence of the key is as meaningful as its
        # value, so this cannot be expressed as a plain model field default.
        if "arc_score" in entry:
            trackless = entry["arc_score"] is None
            arc_score = None if trackless else str(entry["arc_score"])
        else:
            trackless = False
            arc_score = None
        characters.append(
            PartyCharacter(
                name=str(name),
                sheet=str(sheet),
                backstory=str(entry["backstory"]) if entry.get("backstory") else None,
                dossier=str(entry["dossier"]) if entry.get("dossier") else None,
                arc_score=arc_score,
                trackless=trackless,
            )
        )
    # See load_planning_config: loader and saver both hand-build, so a new
    # field must be named in both or it round-trips to nothing.
    return PartyConfig(
        characters=characters,
        selection=ModelSelection.model_validate(raw.get("selection") or {}),
    )


def save_party_config(path: Path, cfg: PartyConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, preserving paths as authored.

    Atomic (``campaignlib.util.atomic_write_text``) so a crash mid-write leaves
    the previous roster intact rather than a truncated file the next load would
    reject. The old ``put_party_yaml`` route used a bare ``write_text``.

    The three-state ``arc_score`` is re-encoded here rather than left to
    pydantic's serializer, because "key omitted" and "key present and null"
    are different documents and only one of them can be a field default.
    """
    entries: list[dict[str, Any]] = []
    for pc in cfg.characters:
        entry: dict[str, Any] = {"name": pc.name, "sheet": pc.sheet}
        if pc.backstory:
            entry["backstory"] = pc.backstory
        if pc.dossier:
            entry["dossier"] = pc.dossier
        if pc.trackless:
            entry["arc_score"] = None
        elif pc.arc_score:
            entry["arc_score"] = pc.arc_score
        entries.append(entry)
    # `selection` is written only when set. These savers hand-build the YAML
    # dict rather than dumping the model, so a new field is silently dropped
    # unless added here — which is exactly what happened when feature 003 first
    # added it, and the write appeared to succeed while persisting nothing.
    doc: dict[str, Any] = {"characters": entries}
    if not cfg.selection.is_empty():
        doc["selection"] = cfg.selection.model_dump(exclude_none=True)
    atomic_write_text(
        path,
        yaml.safe_dump(
            doc,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
    )


def missing_files(cfg: PartyConfig, base: Path) -> dict[str, list[str]]:
    """Report referenced files that do not exist, as ``{name: [field, …]}``.

    Characters with nothing missing are omitted, so an empty dict means the
    roster is fully grounded. This is the read side of the API's lenient
    contract (D4 in ``docs/config/grounding-isolation.md``): a save naming a
    file the GM has not written yet succeeds, and the warning travels with the
    response instead of being discovered later as a CLI crash mid-run.
    """
    report: dict[str, list[str]] = {}
    for pc in cfg.characters:
        absent = [
            field
            for field in PATH_FIELDS
            if (rel := getattr(pc, field))
            and not (base / rel).expanduser().exists()
        ]
        if absent:
            report[pc.name] = absent
    return report


def resolve_party_config(
    cfg: PartyConfig, base: Path, *, require_files: bool = True
) -> ResolvedPartyConfig:
    """Resolve every character's paths against ``base``.

    ``base`` is supplied by the caller rather than derived from the config
    file's own location, so that moving ``party.yaml`` does not change what its
    contents mean — the defect ``docs/config/grounding-isolation.md`` Track A′
    exists to close (issues #145/#146).

    With ``require_files=True`` (the CLI's contract) a reference to a
    nonexistent file raises ``ValueError``. With ``False`` (the API's, and
    ensemble's PC-exclusion filter) the path is resolved regardless and the
    caller can consult :func:`missing_files`.
    """
    base = Path(base)

    def _resolve(rel: str | None, field: str, who: str) -> Path | None:
        if not rel:
            return None
        p = (base / rel).expanduser().resolve()
        if require_files and not p.exists():
            raise ValueError(
                f"party config references missing file for {who}.{field}: {p}"
            )
        return p

    return ResolvedPartyConfig(
        characters=[
            ResolvedCharacter(
                name=pc.name,
                sheet=_resolve(pc.sheet, "sheet", pc.name),
                backstory=_resolve(pc.backstory, "backstory", pc.name),
                dossier=_resolve(pc.dossier, "dossier", pc.name),
                arc_score=_resolve(pc.arc_score, "arc_score", pc.name),
                trackless=pc.trackless,
            )
            for pc in cfg.characters
        ]
    )


def load_party_config_arg(
    path_str: str | None, base: Path | None = None
) -> ResolvedPartyConfig | None:
    """CLI convenience for an optional ``--party-config PATH`` flag (issue
    #265): load + resolve it if given, else ``None`` — the "no config
    available, fall back to party.md" signal every render-CLI call site
    (``sd_narrate``, ``polish``, ``scene_extract``, ``enhance_summary``)
    needs. A missing path or malformed YAML both degrade to ``None`` with a
    stderr warning rather than raising, since this is explicitly the softer
    of two paths — the party.md fallback stays load-bearing.

    ``require_files=False``: a referenced sheet that doesn't exist yet
    doesn't abort here — ``roster_from_config``/``player_map_from_config``
    make their own per-character existence check and report it, which is
    more informative than a bare ``ValueError`` at load time.

    ``base`` defaults to the current working directory, matching this
    repo's documented CLI invariant ("run any script from a campaign
    workspace directory") and ``pipelines/grounding/party.py``'s own
    ``campaign_root or Path.cwd()`` default.

    Caution inherited, not resolved, by this helper: which base directory
    is actually correct for a given ``party.yaml``'s relative ``sheet:``
    paths is campaign-dependent — see the "Measured" table in
    ``docs/design/PartyRosterCanonicalFormat.md``. Some existing
    campaigns' sheets resolve from ``party.yaml``'s own directory, others
    from the campaign root, and no single default is right for all of
    them. Migrating those files is explicitly out of scope for issue #265.
    """
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    if not path.exists():
        print(
            f"Warning: --party-config not found: {path} — falling back to party.md",
            file=sys.stderr,
        )
        return None
    try:
        cfg = load_party_config(path)
    except ValueError as e:
        print(
            f"Warning: --party-config unreadable ({e}) — falling back to party.md",
            file=sys.stderr,
        )
        return None
    return resolve_party_config(cfg, base or Path.cwd(), require_files=False)
