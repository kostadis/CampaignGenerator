"""DeltaPlan: the immutable, explicit selection of what a delta run covers (spec 039).

A plan is never rewritten.  A revision is a NEW file ``<plan_id>-r<revision>.json``
under ``<campaign>/docs/summaries/delta/plans/`` (``DELTA_ROOT_REL``).  Sources are
always an explicit list; an empty list refuses with exit code 2 (Principle X).
No model call is made here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from .errors import EXIT_USAGE, DeltaRefusal

SCHEMA_VERSION = 1
OPERATION_VERSION = "039.1"
DELTA_ROOT_REL = "docs/summaries/delta"
EMPTY_SELECTION_MESSAGE = "no sources selected; the delta does not default to all chapters."
_SHA = re.compile(r"^[0-9a-f]{64}$")


class StoppingPoint(str, Enum):
    plan = "plan"
    prepare = "prepare"
    propose = "propose"
    verify = "verify"
    review = "review"
    preview = "preview"
    apply = "apply"


PRODUCTS = ("grounding", "npc")


class PlanSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: str
    chapter: int = Field(ge=0)
    kind: str = "new"

    @field_validator("sha256")
    @classmethod
    def _sha(cls, v: str) -> str:
        if not _SHA.fullmatch(v):
            raise ValueError("must be a lowercase SHA-256")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v != "new":
            raise ValueError("plan sources are always kind 'new'")
        return v


class ModelChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    backend: str
    model: str
    effort: str | None = None


class PlanModels(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    generation: ModelChoice
    consistency: ModelChoice


class DeltaPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = SCHEMA_VERSION
    plan_id: str
    operation_version: str = OPERATION_VERSION
    campaign_identity: str
    products: tuple[str, ...]
    stopping_point: StoppingPoint
    sources: tuple[PlanSource, ...]
    models: PlanModels
    grounding_baseline_ref: str | None = None
    npc_baselines: dict[str, str] = Field(default_factory=dict)
    census: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    revision: int = Field(default=1, ge=1)
    #: Spec 040: ``"rebase"`` for a source-custody rebase plan.  Both fields below are OMITTED from every
    #: serialisation (hence every digest and the file on disk) while they hold their defaults, so a plan built
    #: before spec 040 keeps its exact digest (research R10; pinned by tests/test_rebase_digest_stability.py).
    kind: Literal["delta", "rebase"] = "delta"
    rebase_id: str | None = None
    #: In-memory only (never serialised): the campaign root the source paths were resolved against.
    #: On disk a plan stores campaign-root-relative paths, so a moved campaign copy still resolves.
    campaign_root: str | None = Field(default=None, exclude=True)

    @model_serializer(mode="wrap")
    def _omit_defaults(self, handler):
        data = handler(self)
        if data.get("kind") == "delta":
            data.pop("kind")
        if data.get("rebase_id") is None:
            data.pop("rebase_id", None)
        return data

    @field_validator("products")
    @classmethod
    def _products(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("products must be non-empty")
        if len(set(v)) != len(v) or any(p not in PRODUCTS for p in v):
            raise ValueError(f"products must be distinct members of {PRODUCTS}")
        return v

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: tuple[PlanSource, ...]) -> tuple[PlanSource, ...]:
        if not v:
            raise DeltaRefusal(EMPTY_SELECTION_MESSAGE, EXIT_USAGE)
        return v


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chapter_of(path: str | Path, explicit: int | None = None) -> int:
    """Explicit chapter, else the leading digits of the file name; never guessed further."""
    if explicit is not None:
        return explicit
    match = re.match(r"(\d+)", Path(path).name)
    if not match:
        raise DeltaRefusal(
            f"cannot determine a chapter number for {path}; name it with leading digits "
            "or give the chapter explicitly.", EXIT_USAGE)
    return int(match.group(1))


def _relative(path: str, root: str | None) -> str:
    """``path`` relative to ``root`` (posix) when it is under it; unchanged otherwise."""
    if root and Path(path).is_absolute():
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            return path
    return path


def _source_dumps(sources, root: str | None) -> list[dict]:
    return [{**s.model_dump(), "path": _relative(s.path, root)} for s in sources]


def _derive_plan_id(identity: str, products, stop, sources, root: str | None = None) -> str:
    body = _canonical({"campaign_identity": identity, "products": sorted(products),
                       "stopping_point": stop, "sources": _source_dumps(sources, root)})
    return "plan-" + _sha256_bytes(body.encode("utf-8"))[:16]


def _under_root(path: Path, root: Path) -> Path:
    """The campaign-root-relative form of ``path``; a source outside the root is a usage error (exit 2)."""
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise DeltaRefusal(
            f"source is outside the campaign root: {path} (root {root}); a plan records "
            "campaign-relative paths, so copy or link the file into the campaign first.", EXIT_USAGE) from exc


def create_plan(*, campaign_identity: str, products, stopping_point, source_paths,
                models: PlanModels | dict, chapters: dict[str, int] | None = None,
                grounding_baseline_ref: str | None = None,
                npc_baselines: dict[str, str] | None = None,
                census: dict[str, Any] | None = None,
                created_at: str | None = None,
                campaign_root: Path | str | None = None) -> DeltaPlan:
    """Build a plan from explicit source paths, hashing each file's exact bytes.

    With ``campaign_root`` every source must lie under it (exit 2 otherwise); the plan then stores and
    derives its id from campaign-relative paths.
    """
    paths = [Path(p) for p in (source_paths or ())]
    if not paths:
        raise DeltaRefusal(EMPTY_SELECTION_MESSAGE, EXIT_USAGE)
    root = Path(campaign_root).absolute() if campaign_root is not None else None
    if root is not None:
        paths = [root / _under_root(p, root) if p.is_file() else p for p in paths]
    chapters = chapters or {}
    sources = []
    for path in paths:
        if not path.is_file():
            raise DeltaRefusal(f"source not found: {path}", EXIT_USAGE)
        sources.append(PlanSource(
            path=str(path), sha256=_sha256_bytes(path.read_bytes()),
            chapter=chapter_of(path, chapters.get(str(path))), kind="new"))
    sources.sort(key=lambda s: (s.chapter, s.path))
    stop = StoppingPoint(stopping_point)
    prods = tuple(products)
    return DeltaPlan(
        plan_id=_derive_plan_id(campaign_identity, prods, stop.value, sources, str(root) if root else None),
        campaign_identity=campaign_identity, products=prods, stopping_point=stop,
        sources=tuple(sources),
        models=models if isinstance(models, PlanModels) else PlanModels(**models),
        grounding_baseline_ref=grounding_baseline_ref, npc_baselines=npc_baselines or {},
        census=census or {},
        created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        campaign_root=str(root) if root else None)


def revise(plan: DeltaPlan, **changes: Any) -> DeltaPlan:
    """A new plan with revision + 1; the original object is unchanged."""
    data = plan.model_dump()
    data["campaign_root"] = plan.campaign_root
    data.update(changes)
    data["revision"] = plan.revision + 1
    data["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return DeltaPlan.model_validate(data)


def plan_digest(plan: DeltaPlan) -> str:
    """sha256 of canonical JSON excluding created_at (binds reviews to a plan).

    A source is identified by its file name, chapter and content digest, never by the directory it was
    found in, so the digest survives a moved campaign copy.
    """
    data = plan.model_dump(mode="json")
    data.pop("created_at", None)
    data["sources"] = [{**src, "path": Path(src["path"]).name} for src in data["sources"]]
    return _sha256_bytes(_canonical(data).encode("utf-8"))


def plans_dir(campaign_dir: Path | str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / "plans"


def _root_of(directory: Path | str) -> Path | None:
    """The campaign root a ``plans_dir`` belongs to (``<root>/docs/summaries/delta/plans``), else None."""
    d = Path(directory).absolute()
    tail = tuple(Path(DELTA_ROOT_REL).parts) + ("plans",)
    return d.parents[len(tail) - 1] if d.parts[-len(tail):] == tail else None


def _plan_file(directory: Path, plan_id: str, revision: int) -> Path:
    return directory / f"{plan_id}-r{revision}.json"


def save_plan(plan: DeltaPlan, directory: Path | str) -> Path:
    """Write ``<plan_id>-r<revision>.json``; refuses to overwrite a different plan."""
    directory = Path(directory)
    target = _plan_file(directory, plan.plan_id, plan.revision)
    root = plan.campaign_root or (str(_root_of(directory)) if _root_of(directory) else None)
    data = plan.model_dump(mode="json")
    data["sources"] = _source_dumps(plan.sources, root)
    text = json.dumps(data, sort_keys=True, indent=2) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") == text:
            return target
        raise DeltaRefusal(f"plan revision already exists and differs: {target.name}")
    directory.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target


def load_plan(directory: Path | str, plan_id: str, revision: int | None = None) -> DeltaPlan:
    """Load a revision, or the highest one when ``revision`` is None."""
    directory = Path(directory)
    if revision is None:
        found = []
        for p in directory.glob(f"{plan_id}-r*.json"):
            m = re.fullmatch(re.escape(plan_id) + r"-r(\d+)\.json", p.name)
            if m:
                found.append(int(m.group(1)))
        if not found:
            raise DeltaRefusal(f"no plan {plan_id} in {directory}")
        revision = max(found)
    path = _plan_file(directory, plan_id, revision)
    if not path.is_file():
        raise DeltaRefusal(f"no plan {plan_id} revision {revision} in {directory}")
    data = json.loads(path.read_text(encoding="utf-8"))
    root = _root_of(directory)
    if root is not None:
        for src in data.get("sources", []):
            if not Path(src["path"]).is_absolute():
                src["path"] = str(root / src["path"])
        data["campaign_root"] = str(root)
    return DeltaPlan.model_validate(data)
