"""Spec 041 T036: read-only replay of the real stormgiants NPC review against the GM's rulings.

Skipped unless ``STORMGIANTS`` points at a checkout containing ``docs/reviews/npc-review-6ee694eebf5b``.
Every file is opened read-only. Item replay is exact (the item's own line against its bound evidence);
the full current-draft replay is approximate for the 16 drafts edited after the review was created.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
from collections import Counter
from pathlib import Path

import pytest

from pipelines.summary_native import noise, npc_check, schema
from pipelines.summary_native.npc_verify import LAST_STATE, _strip_frontmatter

REVIEW_ID = "npc-review-6ee694eebf5b"
_ROOT = os.environ.get("STORMGIANTS")
_ROOT_PATH = Path(_ROOT).expanduser() if _ROOT else None
_REVIEW = _ROOT_PATH / "docs" / "reviews" / REVIEW_ID if _ROOT_PATH else None

pytestmark = pytest.mark.skipif(
    _REVIEW is None or not _REVIEW.is_dir(),
    reason="STORMGIANTS must point at a checkout containing docs/reviews/" + REVIEW_ID)

NUMBER_CODES = ("number-inconsistency", "ordinal-inconsistency")
STATUS_CODE = "status-claim-unsupported"
SUMMARY: dict = {}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_index(text: str) -> npc_check.EvidenceIndex:
    return npc_check.EvidenceIndex.of(npc_check.split_chapters(_strip_frontmatter(text)))


def _oracle(pattern: str) -> set[str]:
    ids: set[str] = set()
    for f in (_REVIEW / "requests").glob(pattern):
        for ev in json.loads(f.read_text())["result"]["events"]:
            ids.add(ev["item_id"])
    return ids


def _items() -> list[dict]:
    out = []
    for d in sorted((_REVIEW / "items").iterdir()):
        revs = sorted(d.glob("*.json"), key=lambda p: int(p.stem))
        if revs:
            out.append(json.loads(revs[-1].read_text()))
    return out


def _code(item: dict) -> str:
    return item["diagnostics"][0]["legacy_code"]


def _bound(item: dict):
    """(evidence Path, evidence still matches its custody hash)."""
    b = next(x for x in item["input_bindings"] if "/evidence/" in x["path"])
    p = _ROOT_PATH / b["path"]
    return p, p.is_file() and _sha(p) == b["custody_sha256"]


def _absent_from_every_cited_scene(line: str, ev: npc_check.EvidenceIndex) -> list[str]:
    """SC-004's own definition (spec 041, from the #617 analysis): a token absent from EVERY scene the
    line cites, compared by value ("1,800" == "1800", "five" == "5"). Labels are not story facts (#617
    excluded them too). Curated idioms and draft-side bare "one" are excluded: the old checker never
    examined "one", and #617 counted idioms as noise. Returns [] when no cited scene resolves."""
    keys: set = set()
    resolved = False
    for _bracket, (chapter, scene) in npc_check.citation_parts(line):
        occ = ev.items_at(chapter, scene)
        if len(occ) == 1:
            resolved = True
            keys |= {noise.token_key(t) for t in noise.tokens(occ[0].text) if not t.label}
    if not resolved:
        return []
    claim = npc_check.BRACKET_RE.sub("", line)
    return [t.surface for t in noise.tokens(claim)
            if not t.label and not t.idiom and not noise.is_bare_one(t) and noise.token_key(t) not in keys]


def test_item_replay_sc004():
    """SC-004: every genuinely unsupported number (absent from every scene its line cites) still reaches
    the GM. The GM's bulk noise rulings are reported alongside, not used as the true-positive oracle:
    no review in this checkout records a *reject* on a number/ordinal item (wrong claims were fixed by
    re-drafting), so "not ruled noise" is not "confirmed wrong" (validation.md, T036)."""
    items = _items()
    noise_ids = _oracle("gm-number-noise-*.json")
    num = [i for i in items if _code(i) in NUMBER_CODES]
    skipped, misses, true_positives = [], [], 0
    noise_still_flagged = noise_cleared = 0
    ev_cache: dict[Path, npc_check.EvidenceIndex] = {}
    for it in num:
        p, ok = _bound(it)
        if not ok:
            skipped.append((it["item_id"], p.name))
            continue
        ev = ev_cache.setdefault(p, _evidence_index(p.read_text()))
        line = it["claim_text"]
        findings, _recs, acct = noise.classify_numbers(line, ev)
        acct.check()
        if it["item_id"] in noise_ids:
            noise_still_flagged += bool(findings)
            noise_cleared += not findings
        absent = _absent_from_every_cited_scene(line, ev)
        if absent:
            true_positives += 1
            if not findings:
                misses.append((it["item_id"], absent, line))
    SUMMARY.update(number_items=len(num), oracle_noise=len(noise_ids), item_skipped=len(skipped),
                   true_positives=true_positives, sc004_misses=len(misses),
                   oracle_noise_cleared=noise_cleared, oracle_noise_still_flagged=noise_still_flagged)
    print(f"\n[T036 item replay] number/ordinal items={len(num)} skipped(changed evidence)={len(skipped)} "
          f"true positives (absent from every cited scene)={true_positives} misses={len(misses)}")
    print(f"[T036 item replay] GM-ruled noise={len(noise_ids)}: now cleared={noise_cleared} "
          f"still flagged={noise_still_flagged}")
    for iid, absent, line in misses:
        print(f"MISS {iid} absent={absent}\n    LINE: {line}")
    assert true_positives > 0, "replay found no true positives; the definition or the data is wrong"
    assert not misses, f"{len(misses)} genuinely unsupported numbers no longer reach the GM"


def test_status_replay_sc002():
    syn_ids = _oracle("gm-status-synonym-*.json")
    by_id = {i["item_id"]: i for i in _items()}
    findings_total, checked, skipped = 0, 0, []
    for iid in sorted(syn_ids):
        it = by_id[iid]
        p, ok = _bound(it)
        if not ok:
            skipped.append(iid)
            continue
        ev = _evidence_index(p.read_text())
        line = it["claim_text"]
        draft = f"{LAST_STATE}\n{line}\n"
        sections = npc_check.parse_sections(draft)
        assert LAST_STATE in sections
        findings, _r, acct = noise.classify_status(draft, sections, ev.text)
        acct.check()
        checked += 1
        # SC-002 is about the word the GM ruled a synonym (named in the item's own diagnostic), not
        # the whole line: a line can carry a second, separately-flagged status word (Diana's line
        # flags "alive" as its own item, npc-ceb9..., which the GM did NOT rule a synonym).
        m = re.match(r'"([^"]+)"', it["diagnostics"][0]["message"])
        assert m, f"cannot read the ruled word from {iid}"
        ruled = m.group(1).casefold()
        hit = [f for f in findings if f'draft says "{ruled}"' in f.detail.casefold()]
        findings_total += len(hit)
        for f in hit:
            print(f"STATUS FINDING {iid}: {f.detail} | {line}")
    SUMMARY.update(status_items=len(syn_ids), status_checked=checked, status_skipped=len(skipped),
                   status_findings=findings_total)
    print(f"\n[T036 status] synonym items={len(syn_ids)} checked={checked} skipped={len(skipped)} "
          f"ruled-word findings={findings_total}")
    assert findings_total == 0


def test_full_draft_replay_sc001_sc005_sc007():
    base = _ROOT_PATH / "docs" / "npcs" / "summary_native" / "ch001-086"
    changed: set[str] = set()
    for it in _items():
        for b in it["input_bindings"]:
            p = _ROOT_PATH / b["path"]
            if "/draft/" in b["path"] and (not p.is_file() or _sha(p) != b["custody_sha256"]):
                changed.add(p.name)
    total = approx = 0
    classes: Counter = Counter()
    per_draft: list[tuple[int, str]] = []
    drafts = 0
    for d in sorted((base / "draft").glob("*.md")):
        if d.name.endswith(".verify.md"):
            continue
        e = base / "evidence" / d.name
        if not e.is_file():
            continue
        drafts += 1
        findings, records, acct = noise.classify_numbers(d.read_text(), _evidence_index(e.read_text()))
        acct.check()  # SC-005
        classes.update(r.noise_class for r in records)
        total += len(findings)
        if d.name in changed:
            approx += len(findings)
        per_draft.append((len(findings), d.name))
    per_draft.sort(reverse=True)
    SUMMARY.update(drafts=drafts, sc001_findings=total, in_changed_drafts=approx,
                   changed_drafts=len(changed), classes=dict(classes))
    print(f"\n[T036 full replay] drafts={drafts} GM-facing number/ordinal findings={total} "
          f"(of which in {len(changed)} changed/approximate drafts: {approx})")
    print(f"[T036 full replay] noise classes seen={dict(classes)} top drafts={per_draft[:8]}")
    assert set(classes) <= set(noise.CLASSES)
    assert len(classes) <= 6  # SC-007
    assert total <= 100  # SC-001
