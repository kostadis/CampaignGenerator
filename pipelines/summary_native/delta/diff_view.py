"""One review document for a delta (spec 039 FR-017, Principle IX).

``render`` builds a single deterministic Markdown document -- no timestamps, every list sorted -- so the
CLI (``delta review show``) and the page print the same bytes.  It shows what a reviewer needs to
decide: unified diffs for prose that already exists, the full prose of a new dossier, the evidence
spans behind a draft, the exact hashes a decision binds to, the coverage the baseline vouches for,
and the inherited and outstanding findings.  A decision that is ``discuss``, ``reject`` or not saved
is shown as BLOCKING together with the action it blocks.  Read-only; no model call.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

from . import review_binding as rb
from .errors import DeltaRefusal
from .plan import DeltaPlan, plan_digest

_HEADER_COMMENT = re.compile(r"\A<!--.*?-->[ \t]*\n", re.DOTALL)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def unified(before: str, after: str, name: str) -> str:
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                 fromfile=f"baseline/{name}", tofile=f"candidate/{name}", lineterm="\n")
    out = "".join(line if line.endswith("\n") else line + "\n" for line in lines)
    return out


def _fence(body: str, lang: str = "") -> str:
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{lang}\n{body.rstrip(chr(10))}\n{fence}\n"


# ── grounding ───────────────────────────────────────────────────────────────


def _grounding_section(root: Path, plan: DeltaPlan) -> list[str]:
    from . import grounding_publish as gp
    from .baseline import baseline_documents, bind

    out = ["## Grounding documents", ""]
    try:
        candidates, lineage, _request = gp.load_inputs(root, plan.plan_id)
    except DeltaRefusal as exc:
        return out + [f"No candidates to review: {exc.message}", ""]
    baseline_docs: dict[str, bytes] = {}
    coverage: dict = {}
    members: list = []
    try:
        baseline = bind(root)
        coverage = dict(baseline.coverage)
        members = list(baseline.members)
        baseline_docs = baseline_documents(baseline, root)
    except DeltaRefusal as exc:
        out += [f"Baseline unavailable ({exc.message}); no diff can be shown.", ""]
    for name in sorted(candidates):
        data = candidates[name]
        before = baseline_docs.get(name, baseline_docs.get(Path(name).stem))
        state = "new document" if before is None else "unchanged" if before == data else "changed"
        out += [f"### {name} ({state})", "",
                f"- candidate sha256: `{_sha(data)}`",
                f"- baseline sha256: `{_sha(before) if before is not None else 'none'}`", ""]
        if before is None:
            out += [_fence(_text(data), "markdown")]
        elif before != data:
            out += [_fence(unified(_text(before), _text(data), name), "diff")]
    out += ["### Coverage", ""]
    if coverage:
        out += [f"- {k}: {coverage[k] if coverage[k] is not None else 'unknown'}" for k in sorted(coverage)]
    else:
        out += ["- baseline coverage not available"]
    for m in members:
        d = m.model_dump(mode="json") if hasattr(m, "model_dump") else dict(m)
        out.append("- member " + ", ".join(f"{k}={d[k]}" for k in sorted(d)))
    out += ["", "### Lineage", ""]
    for lm in sorted(lineage.members, key=lambda m: m.name):
        out.append(f"- {lm.name}: {lm.mode} `{lm.sha256}`")
    out.append("")
    return out


# ── NPC ─────────────────────────────────────────────────────────────────────


def _strip_header(text: str) -> str:
    return _HEADER_COMMENT.sub("", text, count=1)


def _npc_section(root: Path, plan: DeltaPlan) -> list[str]:
    import json

    from . import npc_baseline, npc_update

    out = ["## NPC dossiers", ""]
    try:
        state = npc_update.load_state(root, plan.plan_id)
    except DeltaRefusal as exc:
        return out + [f"No NPC drafts to review: {exc.message}", ""]
    rdir = npc_baseline.npc_root_for(root) / state["range"]
    for m in sorted(state["members"], key=lambda r: r["slug"]):
        stem, slug = m["stem"], m["slug"]
        draft_p = rdir / "draft" / f"{stem}.md"
        draft = _strip_header(draft_p.read_text(encoding="utf-8")) if draft_p.is_file() else None
        out += [f"### {m['subject']} ({m['disposition']})", ""]
        for label, path in (("draft", draft_p), ("composition", rdir / "gm" / f"{stem}.md"),
                            ("evidence pack", rdir / "evidence" / f"{stem}.md")):
            out.append(f"- {label} sha256: `{_sha(path.read_bytes()) if path.is_file() else 'absent'}`")
        bl = npc_baseline.baseline_for(root, slug)
        out.append(f"- baseline horizon: {m.get('horizon') if m.get('horizon') is not None else 'none (new)'}")
        if bl is not None:
            out.append(f"- baseline status: {bl.status}")
            out += [f"- baseline warning: {w}" for w in sorted(bl.warnings)]
        out.append("")
        if draft is None:
            out += ["Draft missing.", ""]
        elif bl is None:
            out += ["Full prose (new dossier):", "", _fence(draft, "markdown")]
        else:
            try:
                prior = npc_update._read_prior(root, bl)
            except OSError:
                prior = None
            if prior is None:
                out += ["Baseline draft is unavailable; full prose:", "", _fence(draft, "markdown")]
            elif prior == draft:
                out += ["Draft is identical to the baseline.", ""]
            else:
                out += [_fence(unified(prior, draft, f"{slug}.md"), "diff")]
        spans_p = npc_update.delta_dir(root, plan.plan_id) / f"{stem}.spans.json"
        out += ["Evidence spans:", ""]
        if spans_p.is_file():
            rec = json.loads(spans_p.read_text(encoding="utf-8"))
            for s in sorted(rec.get("spans", []), key=lambda s: (s["chapter"], s["kind"], s["id"], s["origin"])):
                out.append(f"- ch {s['chapter']:03d} {s['kind']} {s['id']} ({s['origin']}) "
                           f"{s['source_path']} `{s['source_sha256'][:12]}`")
            out += [f"- missing scope: {x}" for x in sorted(rec.get("missing_scope", []))]
        else:
            out.append("- none recorded")
        out.append("")
    return out


# ── decisions and findings ──────────────────────────────────────────────────


def _decision_section(root: Path, plan: DeltaPlan, product: str, scope: str = "publication") -> list[str]:
    title = {"grounding": "Grounding", "npc": "NPC"}[product]
    out = [f"### {title} decisions ({scope} scope)", ""]
    binding = rb.load_binding(root, plan.plan_id, product, scope)
    if binding is None:
        out += ["No review binding recorded; run `delta review handoff`. Nothing is authorised yet.", ""]
        try:
            inherited, outstanding = rb.collect_findings(root, plan, product)
        except DeltaRefusal as exc:
            inherited, outstanding = [], [f"cannot collect findings: {exc.message}"]
        out += ["Inherited findings:", ""] + ([f"- {f}" for f in inherited] or ["- none"])
        out += ["", "Outstanding findings:", ""] + ([f"- {f}" for f in outstanding] or ["- none"]) + [""]
        return out
    try:
        binding = rb.sync_from_review(root, binding)
    except DeltaRefusal as exc:
        out.append(f"- review unreadable: {exc.message}")
    out += [f"- reviewer: {binding.reviewer or 'none'}", f"- decision revision: {binding.decision_revision}",
            f"- review: {binding.review_id or 'none'}"]
    out += [f"- bound {rb.HASH_LABELS[f]}: `{getattr(binding, f)}`" for f in rb.HASH_FIELDS]
    if binding.members:
        out.append("- members: " + ", ".join(binding.members))
    try:
        stale = rb.is_stale(binding, rb.current_hashes(root, plan, product, binding.members or None))
    except DeltaRefusal as exc:
        stale = [f"cannot recompute: {exc.message}"]
    out += [f"- STALE: {r}" for r in stale]
    out += ["", "Decisions:", ""]
    out += [f"- {d.id}: {d.decision}" + (f" (member {d.member})" if d.member else "") for d in binding.decisions] \
        or ["- none"]
    stops = rb.blockers(binding)
    out += ["", "Blocking:", ""] + ([f"- BLOCKING {s} -- the {product} {'apply' if product == 'grounding' else 'publish'} "
                                     "is refused until this is approved" for s in stops] or ["- none"])
    out += ["", "Inherited findings:", ""] + ([f"- {f}" for f in binding.inherited_findings] or ["- none"])
    out += ["", "Outstanding findings:", ""] + ([f"- {f}" for f in binding.outstanding_findings] or ["- none"])
    out.append("")
    return out


def render(campaign_dir: Path | str, plan: DeltaPlan) -> str:
    root = Path(campaign_dir)
    out = [f"# Delta review: {plan.plan_id}", "",
           f"- plan sha256: `{plan_digest(plan)}`", f"- products: {', '.join(plan.products)}",
           "- sources: " + ", ".join(f"ch {s.chapter:03d}" for s in sorted(plan.sources, key=lambda s: s.chapter)), ""]
    if "grounding" in plan.products:
        out += _grounding_section(root, plan)
    if "npc" in plan.products:
        out += _npc_section(root, plan)
    out += ["## Review state", ""]
    for product in plan.products:
        out += _decision_section(root, plan, product)
    return "\n".join(out).rstrip("\n") + "\n"
