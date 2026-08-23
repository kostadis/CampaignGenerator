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


def _blank_is_absent(v: Any) -> Any:
    """An all-whitespace alias means "no alias", not "match the empty string".

    The YAML loader refuses a blank ``sheet_name`` outright — a human who typed
    the key meant something by it. This is the API's path, where the roster
    editor sends every field it renders and an untouched text input arrives as
    ``""``; that is an absent declaration, not a mistake to report.
    """
    return None if isinstance(v, str) and not v.strip() else v


DeclaredName = Annotated[str | None, BeforeValidator(_blank_is_absent)]

#: Per-character path fields, in the order they are rendered and reported.
#: ``sheet`` is required; the rest are optional.
#:
#: ``voice`` and ``examples`` joined this tuple in feature 009 and that is the
#: entire mechanism behind "a character's voice and examples arrive because it
#: named them". They used to be found by matching a file name against the
#: character's first name, which is a similarity-based identity assertion and
#: the last one left in this codebase. A path is checked by
#: :func:`missing_files`, reported by the API, rendered by the Party page and
#: refused by the CLI — it fails loudly, and the prefix rule failed silently.
PATH_FIELDS: tuple[str, ...] = (
    "sheet", "backstory", "dossier", "arc_score", "voice", "examples",
)


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

    ``voice`` and ``examples`` name this character's voice specification and
    its style-examples file (feature 009). Both are **declarations**: a render
    follows the path, and an absent file is reported before the first API call
    rather than discovered as a narrator that quietly had no register rules.
    They replaced a rule that matched a file name against the character's first
    name, which resolved ``Gyrgum`` to nothing after a rename and told nobody
    (campaigns#175). Optional — a character that declares neither has neither,
    stated rather than inferred.

    ``sheet_name`` is the character name as the *downloaded PDF prints it*, and
    exists only for the case where that spelling is wrong and the download
    cannot be corrected — a typo the player typed into D&D Beyond. Declaring it
    lets ``dnd_sheet`` attribute the sheet without the roster having to adopt
    the typo as the character's name: ``name`` still owns the output filename,
    the ``players.yaml`` join and the ``party.md`` heading. It is an explicit
    human-authored mapping in the same sense as ``dossier`` — the exact-match
    ruling in :mod:`campaignlib.sheet_naming` bans *inferring* that two
    spellings are one character, not *stating* it. When the sheet's spelling is
    the correct one and the world merely calls the character something else,
    this is the wrong field: make ``name`` the sheet's spelling and put the
    other name in the character's prose, where narrators read it.

    There is deliberately **no ``player`` field**. It lived here between
    features 008 and 009 and had exactly one production reader; who plays a
    character is now recorded in ``players.yaml``, which
    :mod:`campaignlib.players_config` owns. A document still carrying it is
    refused by name — see :func:`load_party_config`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    sheet: Annotated[str, BeforeValidator(_as_authored)]
    sheet_name: DeclaredName = None
    backstory: AuthoredPath = None
    dossier: AuthoredPath = None
    arc_score: AuthoredPath = None
    voice: AuthoredPath = None
    examples: AuthoredPath = None
    trackless: bool = False


class PartyConfig(BaseModel):
    """Root model — the ``<config>/party.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    characters: list[PartyCharacter] = Field(default_factory=list)

    #: Feature 009 — example files that belong to the whole campaign rather
    #: than to one character, and therefore reach EVERY narrator. toee's
    #: ``combat_and_consequences.md`` and obelisk's ``house_style.md`` are the
    #: real cases; today they reach every narrator only by *falling through*
    #: the per-character routing, which is the same fall-through that sends one
    #: character's style to everybody after a rename (#301). Declaring them
    #: makes "shared" a written statement instead of the absence of a match: a
    #: file that nothing declares is **unused**, not shared, and
    #: ``players check`` names it.
    shared_examples: list[str] = Field(default_factory=list)

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
    sheet_name: str | None = None
    backstory: Path | None = None
    dossier: Path | None = None
    arc_score: Path | None = None
    voice: Path | None = None
    examples: Path | None = None
    trackless: bool = False


class ResolvedPartyConfig(BaseModel):
    """A :class:`PartyConfig` with every path resolved. Never persisted.

    Mirrors :class:`PartyConfig`'s single ``characters`` attribute so the
    render pipelines can take either shape without caring which they were
    handed.
    """

    model_config = ConfigDict(extra="forbid")

    characters: list[ResolvedCharacter] = Field(default_factory=list)
    shared_examples: list[Path] = Field(default_factory=list)


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
        # `player` was retired in feature 009. Refuse rather than ignore: a
        # location that still parses is a split brain waiting to happen, and a
        # value silently dropped here is a person the GM thinks is recorded.
        if "player" in entry:
            raise ValueError(
                f"{path}: character {name!r} still carries the retired 'player' "
                f"field. Who plays a character is recorded in players.yaml now.\n"
                f"  Fix: python -m server.migrate_players_config "
                f"--campaign-dir <campaign>"
            )
        # The three-state read: presence of the key is as meaningful as its
        # value, so this cannot be expressed as a plain model field default.
        if "arc_score" in entry:
            trackless = entry["arc_score"] is None
            arc_score = None if trackless else str(entry["arc_score"])
        else:
            trackless = False
            arc_score = None
        # A blank declaration would make the entry match nothing at all, which
        # is worse than not declaring one — refuse rather than quietly orphan it.
        sheet_name = entry.get("sheet_name")
        if sheet_name is not None and not str(sheet_name).strip():
            raise ValueError(
                f"{path}: character {name!r} has an empty 'sheet_name'. Give it "
                f"the spelling the downloaded PDF prints, or remove the key."
            )
        characters.append(
            PartyCharacter(
                name=str(name),
                sheet=str(sheet),
                sheet_name=str(sheet_name) if sheet_name else None,
                backstory=str(entry["backstory"]) if entry.get("backstory") else None,
                dossier=str(entry["dossier"]) if entry.get("dossier") else None,
                arc_score=arc_score,
                voice=str(entry["voice"]) if entry.get("voice") else None,
                examples=str(entry["examples"]) if entry.get("examples") else None,
                trackless=trackless,
            )
        )
    shared_raw = raw.get("shared_examples") or []
    if not isinstance(shared_raw, list):
        raise ValueError(f"{path}: 'shared_examples' must be a list")
    # See load_planning_config: loader and saver both hand-build, so a new
    # field must be named in both or it round-trips to nothing.
    return PartyConfig(
        characters=characters,
        shared_examples=[str(s) for s in shared_raw if s],
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
        if pc.sheet_name:
            entry["sheet_name"] = pc.sheet_name
        if pc.backstory:
            entry["backstory"] = pc.backstory
        if pc.dossier:
            entry["dossier"] = pc.dossier
        if pc.voice:
            entry["voice"] = pc.voice
        if pc.examples:
            entry["examples"] = pc.examples
        if pc.trackless:
            entry["arc_score"] = None
        elif pc.arc_score:
            entry["arc_score"] = pc.arc_score
        entries.append(entry)
    # `selection` and `shared_examples` are written only when set. These savers
    # hand-build the YAML dict rather than dumping the model, so a new field is
    # silently dropped unless added here — which is exactly what happened when
    # feature 003 first added `selection`, and the write appeared to succeed
    # while persisting nothing.
    doc: dict[str, Any] = {"characters": entries}
    if cfg.shared_examples:
        doc["shared_examples"] = list(cfg.shared_examples)
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
                # Not a path — carried through verbatim so a resolved roster is
                # still attributable (dnd_sheet reads the authored copy today,
                # but a resolved config that silently lost the alias would
                # attribute sheets differently from the one on disk).
                sheet_name=pc.sheet_name,
                backstory=_resolve(pc.backstory, "backstory", pc.name),
                dossier=_resolve(pc.dossier, "dossier", pc.name),
                arc_score=_resolve(pc.arc_score, "arc_score", pc.name),
                voice=_resolve(pc.voice, "voice", pc.name),
                examples=_resolve(pc.examples, "examples", pc.name),
                trackless=pc.trackless,
            )
            for pc in cfg.characters
        ],
        # The resolver hand-builds too, and it is what the render pipelines
        # actually consume — a field missing here is a field the renderer never
        # sees, however faithfully the loader read it.
        shared_examples=[
            p for p in (
                _resolve(s, "shared_examples", "<campaign>")
                for s in cfg.shared_examples
            ) if p is not None
        ],
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

    The cwd default is now correct for every campaign. It used to be
    campaign-dependent — out-of-the-abyss resolved from the campaign root
    while Phandalin, stormgiants and toee resolved from ``party.yaml``'s own
    directory, so no single default was right for all of them. #291 rewrote
    those three campaign-root-relative, so the ambiguity is gone from the
    data rather than papered over here.
    """
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    if not path.exists():
        print(
            f"Error: --party-config not found: {path}",
            file=sys.stderr,
        )
        return None
    try:
        cfg = load_party_config(path)
    except ValueError as e:
        print(
            f"Warning: --party-config unreadable ({e})", file=sys.stderr,
        )
        return None
    return resolve_party_config(cfg, base or Path.cwd(), require_files=False)


def require_from_config(value, *, what: str, party_config_arg: str | None):
    """Return ``value``, or exit(1) — the roster has no ``party.md`` fallback.

    #265 shipped the sheet-frontmatter roster with a fallback to parsing
    ``party.md``; that fallback is deleted. It was silent by construction: a
    campaign whose sheets lacked frontmatter kept rendering, from a *generated*
    document, and nothing said so. ``docs/cli/provenance_search.md``'s rule
    applies — ``party.md`` is `generated_by` output with a countdown on it, and
    reading a roster back out of it is exactly the "treat generated output as
    canon" incident that machinery exists to prevent.

    ``value is None`` (not falsiness) is the failure signal, so an empty
    player map — every character's ``player`` field a placeholder, as in
    Hillsfar — stays legitimate rather than being mistaken for a broken config.

    The callers that produce ``value`` (``roster_from_config``,
    ``player_map_from_config``, :func:`load_party_config_arg`) have already
    printed *which* character failed and why; this only adds what to do about
    it, so the two messages compose instead of repeating.
    """
    if value is not None:
        return value
    if not party_config_arg:
        detail = (
            "  No --party-config was given. The roster now comes only from each\n"
            "  character's sheet frontmatter, so this flag is required."
        )
    else:
        detail = (
            f"  --party-config was {party_config_arg}, but it did not yield a usable\n"
            "  roster for every character (see the per-character reasons above)."
        )
    print(
        f"Error: cannot build the {what} from the party config.\n"
        f"{detail}\n"
        "  Fix: point --party-config at the campaign's config/party.yaml, then give\n"
        "  every referenced sheet YAML frontmatter:\n"
        "      sheet_frontmatter --apply <sheet>.md [...]\n"
        "  party.md is NOT consulted — it is generated output, and reading a roster\n"
        "  back out of it is how a stale roster becomes invisible (#265).",
        file=sys.stderr,
    )
    sys.exit(1)
