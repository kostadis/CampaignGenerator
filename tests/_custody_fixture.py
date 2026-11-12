"""Shared fixture for spec 042 (per-item custody): a REAL multi-NPC verified review.

Not a conftest -- import ``build``.  Everything is made through the public CLI
(``review init`` / ``review create --kind npc_verification`` with a ``dossiers``
selection), the same route ``test_summary_native_npc_publish::_create_real_review``
takes, so the items, bindings and custody are exactly what production writes.

Layout (``RANGE = ch001-003``)::

    docs/summaries/001-a.md  002-b.md  003-c.md
    docs/npcs/summary_native/ch001-003/{draft,evidence,gm}/npc_<slug>.md

NPCs (every dossier entry is handed all three summaries, as the full-range build does):

* ``a``  evidence names only 001; advisory finding (typography) -> claim item(s)
* ``b``  evidence names only 002; advisory finding
* ``c``  evidence names 001 and 003; NO finding -> a sign-off item only (R6 layout path)
* ``d``  evidence uses ``- Source: selected evidence`` (the delta form) -> R5 fallback

Every NPC passes mechanical verification, so ``sign(npc)`` works for all of them.
``build(tmp_path, extra_npcs=N)`` adds ``N`` more finding-free NPCs (``n00``..) that
all cite 001 only, for the SC-001-shaped "other NPCs unaffected" test.

API used by the tests::

    fx = build(tmp_path)
    fx.root, fx.review_id, fx.generation, fx.rd          # Path, str, int, Path (range dir)
    fx.items                                              # {npc: [ReviewItem, ...]}  (all kinds)
    fx.signoff(npc) / fx.findings(npc)                    # the sign-off item / the finding items
    fx.draft(npc) / fx.evidence(npc) / fx.gm(npc)         # absolute Paths
    fx.summary(1|2|3)                                     # absolute Path
    fx.rel(path)                                          # campaign-relative posix string
    fx.touch(path)  fx.restore(path)  fx.delete(path)     # change / put back / remove a source
    fx.decide(items, verdict="approve", **kw)             # -> (exit_code, envelope dict)
    fx.sign(npc)                                          # -> (exit_code, envelope dict)
    fx.cli(*args)                                         # -> (exit_code, envelope dict), --json
    fx.snapshot()                                         # (manifest, custody, items) via read_snapshot
    fx.review_tree_sha()                                  # {relpath: sha256} of the review dir
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipelines.summary_native import npc_compose
from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review.store import read_snapshot
from tests.conftest_npc import run_cli, sha_tree

RANGE = "ch001-003"
SUMMARY_FILES = {1: "001-a.md", 2: "002-b.md", 3: "003-c.md"}


def _summary(ch: int, title: str) -> str:
    return (
        f"# Chapter {ch}\n\nDate: 2026-02-0{ch}\n\n## Scenes\n\n"
        f"### {ch:03d}.01 {title}\n\nThe party met Quill and Pip in {title}. Quill whispered a warning.\n\n"
        f"#### The meeting.\n\n- Quill warns them.\n\n"
        f"## NPCs\n\n### Quill\n\nA deep gnome.\n"
    )


def _evidence(subject: str, chapters: list[int], *, delta: bool = False) -> str:
    fm = yaml.safe_dump({"subject": subject, "global": False, "chapters": chapters}, sort_keys=False)
    parts = [f"---\n{fm}---\n\n# NPC — {subject}\n"]
    for ch in chapters:
        src = "selected evidence" if delta else f"docs/summaries/{SUMMARY_FILES[ch]} (line 7)"
        parts.append(
            f"\n## Chapter {ch:03d}\n\n### Scene {ch:03d}.01 — Meeting (mentioned)\n"
            f"- Source: {src}\n- Mention lines: 9\n\n{subject} spoke to the party. “Quill’s whisper was a warning.”\n"
        )
    return "".join(parts)


def _draft(subject: str, chapters: list[int], *, quote: bool) -> str:
    cites = "; ".join(f"ch {ch:03d} / {ch:03d}.01" for ch in chapters)
    body = (
        f"---\nsubject: {subject}\n---\n\n## Identity\n\nA gnome who guides the party. [{cites}]\n\n"
        f"## History with the Party\n\n- Spoke to the party. [{cites}]\n"
    )
    if quote:
        # A straight apostrophe where the evidence has a curly one -> a typography advisory, never a failure.
        # (A placeholder speaker used to be the advisory here; since #634 it fails verification.)
        ch = chapters[0]
        body += f"\n## Notable Quotes\n\n> \"Quill's whisper was a warning.\"\n> — Quill [ch {ch:03d} / {ch:03d}.01]\n"
    return (
        f"<!-- summary_native npc draft | npc: {subject} | range: {RANGE} | run: 20261112T101500Z "
        f"| draft_key: k | manual sha256: m | model: x | backend: y -->\n" + body
    )


@dataclass
class CustodyFixture:
    root: Path
    review_id: str
    generation: int
    rd: Path
    items: dict[str, list] = field(default_factory=dict)
    originals: dict[Path, bytes] = field(default_factory=dict)

    # ── lookups ─────────────────────────────────────────────────────────
    def draft(self, npc: str) -> Path:
        return self.rd / "draft" / f"npc_{npc}.md"

    def evidence(self, npc: str) -> Path:
        return self.rd / "evidence" / f"npc_{npc}.md"

    def gm(self, npc: str) -> Path:
        return self.rd / "gm" / f"npc_{npc}.md"

    def summary(self, n: int) -> Path:
        return self.root / "docs/summaries" / SUMMARY_FILES[n]

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def signoff(self, npc: str):
        return next(i for i in self.items[npc] if i.proposed_action.action == "signoff_npc_draft")

    def findings(self, npc: str) -> list:
        return [i for i in self.items[npc] if i.proposed_action.action != "signoff_npc_draft"]

    # ── source mutation (the tests' "edit a file" vocabulary) ───────────
    def _remember(self, path: Path) -> None:
        self.originals.setdefault(Path(path), Path(path).read_bytes())

    def touch(self, path: Path) -> None:
        """Change the file's bytes (append a line). ``restore`` puts the original back."""
        path = Path(path)
        self._remember(path)
        path.write_bytes(path.read_bytes() + b"\nedited.\n")

    def restore(self, path: Path) -> None:
        path = Path(path)
        path.write_bytes(self.originals[path])

    def delete(self, path: Path) -> None:
        path = Path(path)
        self._remember(path)
        path.unlink()

    # ── CLI ─────────────────────────────────────────────────────────────
    def cli(self, *args: str):
        rc, out, _err = run_cli([*args, "--campaign-dir", str(self.root), "--json"])
        try:
            return rc, json.loads(out)
        except json.JSONDecodeError:
            return rc, {"ok": False, "raw": out}

    def decide(self, items, verdict: str = "approve", *, disposition: str | None = None,
               reviewer: str = "GM", note: str = "ok", request_id: str | None = None,
               expected_decision_revision: int = 0):
        """``review decide --json`` for ``items`` (ReviewItems, or item ids) in ONE batch."""
        by_id = {i.item_id: i for npc in self.items.values() for i in npc}
        chosen = [by_id[i] if isinstance(i, str) else i for i in items]
        decisions = []
        for item in chosen:
            disp = disposition or (
                "document_signoff" if item.proposed_action.action == "signoff_npc_draft" else "accept_no_change"
            )
            decisions.append({
                "item_id": item.item_id, "item_revision": item.revision, "review_digest": item.review_digest,
                "expected_decision_revision": expected_decision_revision,
                "verdict": verdict, "disposition": disp, "note": note,
            })
        ids = "-".join(i.item_id[-6:] for i in chosen)
        batch = {
            "version": 1, "request_id": request_id or f"fx-{ids}-{verdict}-{len(list(self.root.glob('fx-*.json')))}",
            "review_generation": self.generation, "reviewer": reviewer, "decisions": decisions,
        }
        path = self.root / f"fx-decisions-{len(list(self.root.glob('fx-decisions-*.json')))}.json"
        path.write_text(json.dumps(batch), encoding="utf-8")
        return self.cli("review", "decide", self.review_id, "--decisions", str(path))

    def sign(self, npc: str, *, reviewer: str = "GM", expected_decision_revision: int = 0):
        """``review npc sign --json`` for one NPC's exact current draft bytes."""
        import hashlib

        item = self.signoff(npc)
        digest = hashlib.sha256(self.draft(npc).read_bytes()).hexdigest()
        return self.cli(
            "review", "npc", "sign", self.review_id, "--item", item.item_id, "--draft-sha256", digest,
            "--expected-decision-revision", str(expected_decision_revision), "--reviewer", reviewer,
        )

    # ── read-only views ─────────────────────────────────────────────────
    def snapshot(self):
        return read_snapshot(self.root, self.review_id)

    def review_tree_sha(self) -> dict[str, str]:
        return sha_tree(self.root / "docs" / "reviews" / self.review_id)


def build(tmp_path: Path, *, extra_npcs: int = 0) -> CustodyFixture:
    root = tmp_path / "camp"
    rd = root / "docs/npcs/summary_native" / RANGE
    for sub in ("draft", "evidence", "gm"):
        (rd / sub).mkdir(parents=True)
    (root / "docs/npcs/authored").mkdir(parents=True)
    (root / "docs/summaries").mkdir(parents=True)
    for ch, name in SUMMARY_FILES.items():
        (root / "docs/summaries" / name).write_text(_summary(ch, ["Pens", "Descent", "Market"][ch - 1]), encoding="utf-8")

    #            slug, subject, evidence chapters, delta-form, quote(advisory)
    spec = [
        ("a", "Aaa", [1], False, True),
        ("b", "Bbb", [2], False, True),
        ("c", "Ccc", [1, 3], False, False),
        ("d", "Ddd", [1], True, False),
    ] + [(f"n{i:02d}", f"Nnn{i:02d}", [1], False, False) for i in range(extra_npcs)]

    for slug, subject, chapters, delta, quote in spec:
        draft = rd / "draft" / f"npc_{slug}.md"
        draft.write_text(_draft(subject, chapters, quote=quote), encoding="utf-8")
        (rd / "evidence" / f"npc_{slug}.md").write_text(_evidence(subject, chapters, delta=delta), encoding="utf-8")
        authored = root / "docs/npcs/authored" / f"{slug}.authored.yaml"
        authored.write_text(yaml.safe_dump({"subject": subject, "manual": [], "secrets": "gm-only\n"}), encoding="utf-8")
        npc_compose.compose_gm(draft, authored, rd / "gm" / f"npc_{slug}.md", subject, f"npc_{slug}")

    initialize_ledger(root, AuthorityLedger(version=2, campaign="custody-fx", revision=1), actor="test")
    rc, out, err = run_cli(["review", "init", "--campaign-dir", str(root), "--json"])
    assert rc == 0, out + err
    all_summaries = [f"docs/summaries/{n}" for n in SUMMARY_FILES.values()]
    selection = root / "npc-selection.json"
    selection.write_text(json.dumps({"dossiers": [{
        "id": slug, "npc": subject,
        "draft_path": f"docs/npcs/summary_native/{RANGE}/draft/npc_{slug}.md",
        "evidence_path": f"docs/npcs/summary_native/{RANGE}/evidence/npc_{slug}.md",
        "summary_paths": all_summaries,
        "manual": [],
    } for slug, subject, *_ in spec]}), encoding="utf-8")
    rc, out, err = run_cli([
        "review", "create", "--kind", "npc_verification", "--selection", str(selection),
        "--campaign-dir", str(root), "--json",
    ])
    assert rc == 0, out + err
    review_id = json.loads(out)["data"]["review_id"]

    manifest, _custody, items = read_snapshot(root, review_id)
    fx = CustodyFixture(root=root, review_id=review_id, generation=manifest.generation, rd=rd)
    for slug, *_ in spec:
        draft_rel = f"docs/npcs/summary_native/{RANGE}/draft/npc_{slug}.md"
        fx.items[slug] = [
            i for i in items
            if i.locator.source_path == draft_rel
            or any(b.path == draft_rel for b in i.input_bindings)
        ]
    return fx


def cleanup(fx: CustodyFixture) -> None:  # pragma: no cover - convenience
    shutil.rmtree(fx.root, ignore_errors=True)
