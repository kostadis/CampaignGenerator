"""Scoped name associations (spec 039 T049, FR-013, N4, research R3).

A model *proposes* that an unresolved or short name in a selected source refers to a registry
entity, for one exact scope ("faction offer", never "deployed"). Nothing here is applied: the GM
decides each proposal with ``decide`` (revisioned), and only ``approved`` ones are ever returned
to drafting by ``approved_associations``. This module never reads the registry for writing and
never adds an alias, global or otherwise (test: registry bytes unchanged).

Record: ``<campaign>/docs/summaries/delta/associations/<plan_id>.json``.
Model call: ``propose`` only, via ``campaignlib`` (``caller`` is the test seam).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

import campaignlib
from types import SimpleNamespace

from campaignlib.api.client import client_from_args
from campaignlib.registry import find_registry, load_registry

from .census import read_pinned_source
from .errors import EXIT_REFUSAL, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL, DeltaPlan, PlanSource
from .records_io import read_json, write_json

ASSOC_REL = f"{DELTA_ROOT_REL}/associations"
DECISIONS = {"approve": "approved", "reject": "rejected", "discuss": "discuss"}
_STATES = ("approved", "rejected", "discuss", "unresolved")


class AssocSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    revision: str  # sha256 of the source file the quote was checked against
    scene: str
    span: str


class Association(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str  # the name as written in the source (never becomes an alias)
    canonical_id: str
    source: AssocSource
    relationship_support: str
    rationale: str = ""
    scope: str
    audience: str = "gm"
    decision: str = "unresolved"
    reviewer: str | None = None
    decision_revision: int = 0
    history: list[dict] = Field(default_factory=list)


class AssocStore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    associations: list[Association] = Field(default_factory=list)
    dropped: list[dict] = Field(default_factory=list)


def store_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / ASSOC_REL / f"{plan_id}.json"


def load_store(campaign_dir: Path | str, plan_id: str) -> AssocStore:
    p = store_path(campaign_dir, plan_id)
    if not p.is_file():
        return AssocStore(plan_id=plan_id)
    return AssocStore.model_validate(read_json(p))


def save_store(campaign_dir: Path | str, store: AssocStore) -> Path:
    return write_json(store_path(campaign_dir, store.plan_id), store.model_dump(mode="json"))


def association_id(plan_id: str, canonical_id: str, revision: str, scene: str, support: str) -> str:
    h = hashlib.sha256("\x1f".join([plan_id, canonical_id, revision, scene, support]).encode()).hexdigest()
    return "assoc-" + h[:12]


def _parse_json_list(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict)]


def _scene_has(root: Path, path: str, scene: str, support: str) -> bool:
    """The named scene (or moment / NPC entry) of this source itself contains the quoted support."""
    from pipelines.summary_native import npc_link, parse

    scene = scene.strip()
    if not scene:
        return False
    pf = parse.parse_file(Path(path), root)
    for it in npc_link.iter_items(pf):
        if it.kind == "scene" and it.scene_id == scene and support in it.text:
            return True
        if it.kind == "moment" and scene in ("moment", "moments") and support in it.text:
            return True
    return any(ee.category == "npc" and scene in ("entry", f"npcs/{ee.heading}") and support in ee.body
               for ee in pf.entities)


def propose(campaign_dir: Path | str, plan: DeltaPlan, names: list[dict], *, backend: str | None = None,
            model: str | None = None, client=None, caller=None, now: str | None = None) -> AssocStore:
    """Ask a model for scoped association proposals; verify them mechanically; store as unresolved.

    ``names`` is ``[{"name": str, "evidence": [{"path"?, "scene", "text"}]}]`` (typically the census'
    unresolved entries). A proposal is kept only if its ``canonical_id`` is an exact registry
    canonical name and its quoted support appears verbatim in a selected source; the rest are
    recorded under ``dropped``. Existing decisions are preserved (same id keeps its history).
    """
    root = Path(campaign_dir)
    rpath = find_registry(root)
    if rpath is None:
        raise DeltaRefusal("no entity registry found; associations resolve to registry canonical names",
                           EXIT_USAGE)
    canon = sorted(e.name for e in load_registry(rpath).entities)
    texts = {s.path: (read_pinned_source(s), s.sha256) for s in plan.sources}  # exit 3 if a source moved
    if caller is None:
        client = client or client_from_args(SimpleNamespace(backend=backend, model=None, endpoint=None))
        caller = campaignlib.call_api
    prompt = (
        "Registry canonical names (use these exactly):\n" + "\n".join(f"- {c}" for c in canon)
        + "\n\nNames to associate:\n" + json.dumps(names, ensure_ascii=False, indent=1)
        + '\n\nReturn a JSON list. Each item: {"name","canonical_id","scene","relationship_support" '
          '(a VERBATIM quote from the source),"rationale","scope" (the exact relationship, narrow)}. '
          'Omit anything you cannot support with a verbatim quote.')
    raw = caller(client, "You propose scoped name associations for a game master to review. "
                 "You never decide; every item is reviewed.", prompt, model)
    store = load_store(root, plan.plan_id)
    have = {a.id: a for a in store.associations}
    for item in _parse_json_list(str(raw)):
        cid, support = str(item.get("canonical_id", "")), str(item.get("relationship_support", ""))
        scene = str(item.get("scene", ""))
        if cid not in canon:
            store.dropped.append({"item": item, "reason": "canonical_id_not_in_registry"})
            continue
        hit = next(((p, sha) for p, (t, sha) in texts.items() if support and support in t), None)
        if hit is None:
            store.dropped.append({"item": item, "reason": "support_not_verbatim_in_selected_source"})
            continue
        if not _scene_has(root, hit[0], scene, support):
            store.dropped.append({"item": item, "reason": "scene_does_not_contain_support"})
            continue
        if not str(item.get("scope", "")).strip():
            store.dropped.append({"item": item, "reason": "scope_missing"})
            continue
        aid = association_id(plan.plan_id, cid, hit[1], scene, support)
        if aid in have:
            continue
        a = Association(id=aid, name=str(item.get("name", "")), canonical_id=cid,
                        source=AssocSource(path=hit[0], revision=hit[1], scene=scene, span=support),
                        relationship_support=support, rationale=str(item.get("rationale", "")),
                        scope=str(item["scope"]).strip(),
                        audience="gm")  # a model never chooses an audience; association evidence is GM-only (FR-012)
        store.associations.append(a)
        have[aid] = a
    save_store(root, store)
    return store


def decide(campaign_dir: Path | str, plan_id: str, assoc_id: str, decision: str, reviewer: str,
           reason: str | None = None, now: str | None = None) -> Association:
    """Record a revisioned decision (approve|reject|discuss). Never touches the registry."""
    if decision not in DECISIONS:
        raise DeltaRefusal(f"decision must be one of {sorted(DECISIONS)}; got {decision!r}", EXIT_USAGE)
    if not (reviewer or "").strip():
        raise DeltaRefusal("a reviewer is required to record an association decision", EXIT_USAGE)
    store = load_store(campaign_dir, plan_id)
    a = next((x for x in store.associations if x.id == assoc_id), None)
    if a is None:
        raise DeltaRefusal(f"no association {assoc_id} in plan {plan_id}", EXIT_USAGE)
    a.decision_revision += 1
    a.decision, a.reviewer = DECISIONS[decision], reviewer.strip()
    a.history.append({"revision": a.decision_revision, "decision": a.decision, "reviewer": a.reviewer,
                      "reason": reason, "at": now or datetime.now(timezone.utc).isoformat(timespec="seconds")})
    save_store(campaign_dir, store)
    return a


def approved_associations(campaign_dir: Path | str, plan_id: str, *, canonical_id: str | None = None,
                          audience: str | None = None) -> list[Association]:
    """The only associations drafting may use: ``decision == approved`` (optionally filtered)."""
    out = [a for a in load_store(campaign_dir, plan_id).associations if a.decision == "approved"]
    if canonical_id is not None:
        out = [a for a in out if a.canonical_id == canonical_id]
    if audience is not None:
        out = [a for a in out if a.audience == audience]
    return out


def require_approved(campaign_dir: Path | str, plan_id: str, assoc_id: str) -> Association:
    """Return the association if approved; otherwise refuse (it cannot be drafting evidence)."""
    a = next((x for x in load_store(campaign_dir, plan_id).associations if x.id == assoc_id), None)
    if a is None or a.decision != "approved":
        state = a.decision if a else "unknown"
        raise DeltaRefusal(f"association {assoc_id} is {state}, not approved; only an approved "
                           "association can be drafting evidence", EXIT_REFUSAL)
    return a


def selected_approved(campaign_dir: Path | str, plan: DeltaPlan) -> list[tuple[Association, PlanSource]]:
    """Approved, still-pinned support in this plan only; never expand a scoped quote to its scene."""
    selected = {str(Path(s.path).resolve()): s for s in plan.sources}
    out = []
    for a in approved_associations(campaign_dir, plan.plan_id, audience="gm"):
        src = selected.get(str(Path(a.source.path).resolve()))
        if src is None or a.source.revision != src.sha256:
            raise DeltaRefusal(f"association {a.id}: support is outside the pinned selection")
        text = read_pinned_source(src)
        if (not a.relationship_support or a.source.span != a.relationship_support
                or a.relationship_support not in text
                or not _scene_has(Path(campaign_dir), src.path, a.source.scene, a.relationship_support)):
            raise DeltaRefusal(f"association {a.id}: support no longer resolves in its exact scope")
        out.append((a, src))
    return out
