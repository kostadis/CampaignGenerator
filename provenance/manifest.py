"""The provenance manifest: models, strict loader, and workspace-root resolution.

``~/src/campaigns/provenance.yaml`` is the machine-readable transcription of a
trust hierarchy that until now existed only as prose in that workspace's
``CLAUDE.md``. It is **hand-authored** (FR-029) and it is the **only**
enumeration of which campaigns exist (FR-023).

Three properties are deliberate and each has cost the project something to
learn:

**Enumeration is closed.** Nothing discovers a campaign by scanning for
``config/config.yaml``. A directory present on disk but absent here is invisible
to search, and naming it is refused *by name* (FR-009). Discovery-by-scan would
have to serve a defaulted tier for the campaign it just found — and "a generated
file was read as canon" is the exact failure this feature exists to prevent.

**Loading is all-or-nothing.** One bad campaign block fails the whole load
(FR-030). There is no skip-the-broken-entry-and-carry-on, because a partial
manifest is precisely how a defaulted tier gets served to someone who has no way
to know they got one.

**Strict means strict.** Every model sets ``extra="forbid"``, and the YAML
loader additionally rejects duplicate mapping keys, which ``yaml.safe_load``
would otherwise resolve last-wins in silence. A typo'd key is a load error, not
a line nobody notices.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .tiers import AUTHORABLE_TIERS

#: The manifest's filename at the workspace root.
MANIFEST_FILENAME = "provenance.yaml"


class ManifestError(Exception):
    """A manifest could not be loaded. Maps to CLI exit code 3."""


# ── YAML loading that fails loudly ───────────────────────────────────────────


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys.

    ``yaml.safe_load`` silently keeps the last of a duplicated key. In a
    hand-authored manifest that means a campaign block, or a whole tier's globs,
    can be shadowed by a copy-paste and never noticed — the search just quietly
    covers different files than the author believes. FR-030 says fail loudly;
    this is where the loudness starts.
    """


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r} — the later value would silently win",
                key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


# ── models ───────────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    """Base for every manifest model: unknown keys are load errors."""

    model_config = ConfigDict(extra="forbid")


class TierGlobs(_Strict):
    """One glob list per authorable tier. All four keys required; empty is legal.

    Required rather than defaulted because an omitted tier and an empty tier are
    different statements, and only one of them is something a GM meant to say.
    """

    authoritative: list[str]
    search_accelerator: list[str]
    working_reference: list[str]
    staging: list[str]


class GeneratedDecl(_Strict):
    """Declares that files are pipeline output.

    A non-null ``generated_by`` on an envelope means *"will be clobbered on
    regeneration, may be stale."* That is the whole contract — it is a warning,
    not a provenance credit line (FR-003).
    """

    paths: list[str]
    by: str
    note: str | None = None

    @field_validator("paths")
    @classmethod
    def _paths_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("generated[].paths must be non-empty")
        return v

    @field_validator("by")
    @classmethod
    def _by_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("generated[].by must name the generating stage")
        return v


class Horizon(_Strict):
    """Chapter horizon marker. Chapter-only, deliberately.

    An earlier draft carried a ``kind: "chapter" | "date"`` discriminator. It is
    gone: all six campaigns are chapter-based, no date pattern field ever existed
    to drive the other branch, and a declared-but-unimplemented branch is a
    promise the schema cannot keep. If a date-horizoned campaign ever appears the
    discriminator comes back *with* its pattern field and a test — not before
    (data-model.md section 7).

    ``path_pattern`` runs over the repo-relative **path**. A regex over the file
    *body* would be inference and would violate FR-029. The boundary is the
    file, and it is not negotiable (research D14).
    """

    latest: int
    path_pattern: str

    @field_validator("latest", mode="before")
    @classmethod
    def _latest_is_int(cls, v: Any) -> Any:
        # MUST be mode="before". In the default "after" mode pydantic has already
        # coerced "46" -> 46 and True -> 1, so the isinstance check below sees an
        # int and the validator is inert. A string here means the author was
        # thinking of dates, and horizon is chapter-only.
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(
                f"horizon.latest must be an integer chapter number, got {v!r}"
            )
        return v

    @field_validator("path_pattern")
    @classmethod
    def _pattern_has_one_group(cls, v: str) -> str:
        try:
            compiled = re.compile(v)
        except re.error as exc:
            raise ValueError(f"horizon.path_pattern is not a valid regex: {exc}") from exc
        if compiled.groups != 1:
            raise ValueError(
                f"horizon.path_pattern must have exactly one capture group "
                f"(the chapter number); this one has {compiled.groups}"
            )
        return v

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.path_pattern)


class IdentityDecl(_Strict):
    """Where a campaign's identity stores live. Either key may be null."""

    registry: str | None = None
    aliases: str | None = None

    @property
    def has_store(self) -> bool:
        return bool(self.registry or self.aliases)


class ProvenanceRange(_Strict):
    """Chapter range -> authorship label (FR-026).

    out-of-the-abyss's chapters 1-15 are GM-written and 16+ are AI-assisted.
    Both are canon for plot; they are not interchangeable for voice-reference
    work, which is the entire reason the label exists.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: int
    to: int | None = None
    authorship: str
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_from_keyword(cls, data: Any) -> Any:
        # `from` is a Python keyword, so the field is `from_`; the manifest is
        # authored with the natural spelling.
        if isinstance(data, dict) and "from" in data:
            data = dict(data)
            data["from_"] = data.pop("from")
        return data

    @model_validator(mode="after")
    def _ordered(self) -> "ProvenanceRange":
        if self.to is not None and self.to < self.from_:
            raise ValueError(f"provenance range {self.from_}..{self.to} ends before it starts")
        return self

    def contains(self, chapter: int) -> bool:
        if chapter < self.from_:
            return False
        return self.to is None or chapter <= self.to


class Campaign(_Strict):
    """One game; the hard boundary of the feature.

    ``name`` is populated from the manifest key and may **not** be authored in
    the block — one name in one place. Entities are never merged across
    campaigns (FR-008).
    """

    name: str = ""
    root: str
    tiers: TierGlobs
    generated: list[GeneratedDecl] = []
    horizon: Horizon | None = None
    identity: IdentityDecl
    corrections: str | None = None
    provenance_ranges: list[ProvenanceRange] = []
    search_extensions: list[str] = [".md", ".txt", ".vtt", ".yaml", ".json"]
    exclude: list[str] = [".git/**", "**/__pycache__/**", "node_modules/**"]

    @model_validator(mode="before")
    @classmethod
    def _name_is_the_key(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data:
            raise ValueError(
                "a campaign's name is its manifest key — remove the 'name:' line "
                "rather than spelling it in two places that can disagree"
            )
        return data

    @field_validator("root")
    @classmethod
    def _root_stays_inside(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("root must be a non-empty relative path")
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError(f"root {v!r} must be relative to the workspace root")
        if ".." in p.parts:
            # An error, never a clamp. This feature reads six known directories;
            # it does not read arbitrary paths, and quietly rewriting an escape
            # into something safe would hide an authoring mistake.
            raise ValueError(f"root {v!r} escapes the workspace root with '..'")
        return v

    @model_validator(mode="after")
    def _ranges_do_not_overlap(self) -> "Campaign":
        ranges = sorted(self.provenance_ranges, key=lambda r: r.from_)
        for earlier, later in zip(ranges, ranges[1:]):
            end = earlier.to
            if end is None or end >= later.from_:
                raise ValueError(
                    f"provenance ranges overlap: {earlier.from_}..{earlier.to} "
                    f"and {later.from_}..{later.to}"
                )
        return self

    def range_for(self, chapter: int | None) -> str | None:
        """Authorship label for a chapter, or ``None`` — never a guess (FR-026)."""
        if chapter is None:
            return None
        for r in self.provenance_ranges:
            if r.contains(chapter):
                return r.authorship
        return None

    def generated_by(self, rel_path: str) -> str | None:
        """The stage that generates ``rel_path``, or ``None``."""
        from .tiers import matches_any  # local: keeps the module import graph flat

        for decl in self.generated:
            if matches_any(rel_path, decl.paths):
                return decl.by
        return None


class ProvenanceManifest(_Strict):
    """The workspace-level root document."""

    version: int
    campaigns: dict[str, Campaign]

    @field_validator("version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unknown manifest version {v!r}; this build understands version 1")
        return v

    @field_validator("campaigns")
    @classmethod
    def _non_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("campaigns must not be empty — the manifest is the only enumeration")
        return v

    @model_validator(mode="after")
    def _stamp_names(self) -> "ProvenanceManifest":
        for key, campaign in self.campaigns.items():
            campaign.name = key
        return self

    @property
    def campaign_names(self) -> list[str]:
        """Sorted, for the refusal messages that enumerate known campaigns."""
        return sorted(self.campaigns)

    def get(self, name: str) -> Campaign | None:
        return self.campaigns.get(name)


# ── workspace-root resolution (Principle VIII) ───────────────────────────────


@dataclass(frozen=True)
class WorkspaceRoot:
    """A resolved workspace root, and *which rule* resolved it.

    Reporting the rule is not decoration. The same command reads a different
    corpus depending on an environment variable a user may not remember setting,
    and "state is discoverable" means the tool says so rather than leaving it to
    be inferred from surprising results.
    """

    path: Path
    rule: str      # "flag" | "env" | "default"
    detail: str    # a sentence for `provenance capabilities`

    @property
    def manifest_path(self) -> Path:
        return self.path / MANIFEST_FILENAME


def resolve_workspace_root(explicit: str | Path | None = None) -> WorkspaceRoot:
    """``--campaigns-root`` -> ``$CAMPAIGNS_ROOT`` -> ``campaignlib.constants``."""
    if explicit:
        p = Path(explicit).expanduser()
        return WorkspaceRoot(p, "flag", "--campaigns-root was given explicitly")

    env = os.environ.get("CAMPAIGNS_ROOT")
    if env:
        return WorkspaceRoot(
            Path(env).expanduser(), "env", "$CAMPAIGNS_ROOT is set in the environment"
        )

    from campaignlib.constants import CAMPAIGNS_ROOT

    return WorkspaceRoot(
        Path(CAMPAIGNS_ROOT),
        "default",
        "built-in default (campaignlib.constants.CAMPAIGNS_ROOT); "
        "--campaigns-root not given and $CAMPAIGNS_ROOT not set",
    )


# ── the loader ───────────────────────────────────────────────────────────────


def load_manifest(path: str | Path) -> ProvenanceManifest:
    """Load and validate a manifest. Raises ``ManifestError`` on any problem.

    Every failure mode below is a *load error*, never a warning and never a
    partial result: a manifest that half-loaded would answer "which campaigns
    exist" wrongly, and every other guarantee is built on that answer.
    """
    path = Path(path)
    if not path.is_file():
        raise ManifestError(
            f"no manifest at {path}\n"
            f"  The manifest is hand-authored (FR-029) and is the only enumeration of\n"
            f"  campaigns. See specs/007-cross-campaign-search/contracts/manifest.md."
        )

    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path} is not valid YAML:\n  {exc}") from exc

    if raw is None:
        raise ManifestError(f"{path} is empty")
    if not isinstance(raw, dict):
        raise ManifestError(f"{path} must contain a mapping at the top level")

    try:
        return ProvenanceManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"{path} failed validation:\n{_render(exc)}") from exc


def _render(exc: ValidationError) -> str:
    """Render pydantic's errors with the authoring path the GM needs to fix."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "<root>"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def tier_keys() -> tuple[str, ...]:
    """The four authorable tier keys, for error messages and `check`."""
    return tuple(t.value for t in AUTHORABLE_TIERS)
