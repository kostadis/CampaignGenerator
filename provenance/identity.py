"""Read-only identity resolution over the **existing** registry loader.

This module is an adapter, not a parser. ``campaignlib/registry.py`` already
loads ``docs/entity_registry.yaml``, validates its invariants, and exposes the
projections (``alias_to_canonical``, ``canonical_to_aliases``) including the
documented first-token rule that turns ``"Kazryn"`` into ``"Kazryn Nyantani"``.
Writing a second parser here would be a Split-Brain on identity — the exact
defect the entity registry was built to end (research D10).

## Three answers, never two

``resolved`` / ``not-found`` / ``no-store``. "The store exists and this name is
not in it" and "this campaign has no store" are answers to different questions,
and collapsing them tells the reader something false: the first invites a
`registry alias` run, the second invites nothing at all (FR-017, FR-018).

## Name similarity is never evidence of identity (FR-016)

Nothing here computes a string distance in order to *assert* a match. `Vera` does
not resolve to `Veyra` because they look alike — it resolves only if a GM has
recorded the link. Near-duplicate surfacing is ``registry check``'s separate,
human-gated job and never feeds a resolution.

Case folding is not an exception to that. ``ilvara`` and ``Ilvara`` are the same
string written two ways, not two strings that resemble each other.

## The schema gap is reported, not papered over

FR-014 asks for "known-wrong variants." **The registry has no such field.** In
practice wrong variants are stored as ordinary aliases — Phandalin lists
``"Adabra Adabra Gwynn"`` and ``"king_gnercli"`` in the same ``aliases:`` list as
legitimate short forms. So the resolution says
``known_wrong_variants: not-recorded-by-schema`` rather than returning an empty
list a caller would read as "there are none." Classifying some aliases as wrong
by inspection would be precisely the name-similarity reasoning FR-016 forbids.

## The aliases projection is not a second authority

A campaign declaring only ``identity.aliases`` (a ``docs/aliases.json``
projection) answers ``no-store``, with the reason said out loud. That file is
generated *from* a registry; treating it as an identity source would reintroduce
the fragmentation the registry replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: FR-014's fourth item, and the honest answer to it.
WRONG_VARIANTS = {
    "status": "not-recorded-by-schema",
    "explanation": (
        "the entity registry has no field for wrong variants; misspellings are "
        "stored as ordinary aliases and are indistinguishable from legitimate "
        "short forms. Classifying them by inspection would be name-similarity "
        "reasoning, which FR-016 forbids."
    ),
}


class IdentityStatus(str, Enum):
    RESOLVED = "resolved"
    NOT_FOUND = "not-found"
    NO_STORE = "no-store"


class ConfusionKind(str, Enum):
    """Two real registry sections, kept apart because they mean different things."""

    DISTINCT = "distinct"              # ruled to be different entities
    REJECTED_ALIAS = "rejected-alias"  # a proposed link considered and refused


@dataclass(frozen=True)
class KnownConfusion:
    kind: ConfusionKind
    names: tuple[str, ...]

    def as_dict(self) -> dict:
        return {"kind": self.kind.value, "names": list(self.names)}


@dataclass(frozen=True)
class IdentityResolution:
    status: IdentityStatus
    surface_form: str
    canonical: str | None = None
    type: str | None = None
    aliases: tuple[str, ...] = ()
    known_confusions: tuple[KnownConfusion, ...] = ()
    note: str | None = None
    reason: str | None = None
    store: str | None = None

    @property
    def known_wrong_variants(self) -> dict:
        return dict(WRONG_VARIANTS)

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "surface_form": self.surface_form,
            "canonical": self.canonical,
            "type": self.type,
            "aliases": list(self.aliases),
            "known_confusions": [c.as_dict() for c in self.known_confusions],
            "known_wrong_variants": self.known_wrong_variants,
            "note": self.note,
            "reason": self.reason,
            "store": self.store,
        }


def _no_store(surface_form: str, reason: str) -> IdentityResolution:
    return IdentityResolution(IdentityStatus.NO_STORE, surface_form, reason=reason)


def _load(campaign, campaign_root: Path):
    """Return ``(registry, relative_path)`` or ``(None, reason)``."""
    identity = getattr(campaign, "identity", None)
    declared = getattr(identity, "registry", None) if identity else None

    if not declared:
        if identity is not None and getattr(identity, "aliases", None):
            return None, (
                f"{campaign.name} declares only an aliases projection "
                f"({identity.aliases}) and no entity registry. That file is generated "
                f"from a registry and is not an identity authority; resolving against "
                f"it would reintroduce the fragmentation the registry replaced."
            )
        return None, f"{campaign.name} declares no entity registry and no aliases file."

    path = campaign_root / declared
    if not path.is_file():
        return None, (
            f"{campaign.name} declares identity.registry {declared!r} but no such file "
            f"exists on this machine (looked for {path}). This is a machine/config "
            f"problem, not a claim that the entity is unknown."
        )

    from campaignlib.registry import load_registry

    try:
        return load_registry(path), declared
    except (ValueError, OSError) as exc:
        return None, f"{campaign.name}'s registry at {declared} could not be loaded: {exc}"


def _confusions(registry, names: set[str]) -> tuple[KnownConfusion, ...]:
    """Every recorded non-identity assertion touching one of ``names``.

    Matched case-insensitively for the same reason resolution is: a registry
    entry spelled with different casing is the same entry, not a similar one.
    """
    folded = {n.casefold() for n in names if n}
    found: list[KnownConfusion] = []
    for kind, pairs in (
        (ConfusionKind.DISTINCT, getattr(registry, "distinct", ())),
        (ConfusionKind.REJECTED_ALIAS, getattr(registry, "rejected_aliases", ())),
    ):
        for pair in pairs:
            if any(str(member).casefold() in folded for member in pair):
                found.append(KnownConfusion(kind, tuple(str(m) for m in pair)))
    return tuple(found)


def resolve(campaign, campaign_root, surface_form: str) -> IdentityResolution:
    """Resolve one surface form within one campaign. Reads; never writes (FR-032)."""
    registry, detail = _load(campaign, Path(campaign_root))
    if registry is None:
        return _no_store(surface_form, detail)

    flat = registry.alias_to_canonical()
    canonical = flat.get(surface_form)
    if canonical is None:
        folded = {k.casefold(): v for k, v in flat.items()}
        canonical = folded.get(surface_form.casefold())

    if canonical is None:
        return IdentityResolution(
            IdentityStatus.NOT_FOUND,
            surface_form,
            store=detail,
            reason=(
                f"{campaign.name} has an identity store ({detail}) and "
                f"{surface_form!r} is not in it. This is NOT a claim that no such "
                f"entity exists — only that no alias link is recorded. No canonical "
                f"form is guessed from name similarity (FR-016)."
            ),
            known_confusions=_confusions(registry, {surface_form}),
        )

    entity = next((e for e in registry.entities if e.name == canonical), None)
    return IdentityResolution(
        IdentityStatus.RESOLVED,
        surface_form,
        canonical=canonical,
        type=getattr(entity, "type", None),
        aliases=tuple(getattr(entity, "aliases", ()) or ()),
        known_confusions=_confusions(registry, {canonical, surface_form}),
        note=getattr(entity, "note", None),
        store=detail,
    )


def expansion_forms(campaign, campaign_root, surface_form: str) -> tuple[str, ...]:
    """``{canonical} ∪ {aliases}`` for ``--expand-aliases`` (FR-019).

    Falls back to the surface form alone when nothing is recorded — an
    unexpanded search is the honest answer to "there is no alias data here",
    and it is what ``matched_surface_form`` on each hit will then report.
    """
    resolution = resolve(campaign, campaign_root, surface_form)
    if resolution.status is not IdentityStatus.RESOLVED:
        return (surface_form,)
    forms = {surface_form, resolution.canonical, *resolution.aliases}
    return tuple(sorted(f for f in forms if f))
