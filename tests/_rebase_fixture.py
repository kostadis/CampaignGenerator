"""Synthetic git-initialised campaign for spec 040 (source-custody rebase). Not collected: no ``test_`` prefix.

Layers (each is a function so later phases extend the state instead of rebuilding it):

1. :func:`build_active_through_ch5` - a managed generation through chapter 5, published through the REAL
   delta/promotion path (the same ``publish_delta`` the spec 039 e2e test uses), with the original summaries
   committed to the campaign's own git history.
2. :func:`stage_pending_ch6` - a pending chapter-6 grounding delta plan: edits proposed and approved, the
   deterministic check passed and the candidates staged as a promotion range (``grounding preview``).
3. :func:`apply_corrections` - commits corrections to chapters 2-5 (semantic) or a chapter-1 whitespace-only
   variant, so the pins held by the active generation go stale.

:func:`build` runs all three.  NOT built here (Phase 4 work, no records are faked to cover it): NPC receipts
published for >= 2 members of the pending plan.  The grounding-only plan is what T002 needs; the NPC layer
belongs in ``stage_pending_npc`` once US2 (rebind) needs NPC bindings to preserve.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tests.support.delta_grounding_fixture import FACTORY, GENERATION_ID, add_new_chapter, make_grounding_campaign
from tests.test_delta_grounding_e2e import NEW_LINE, INHERITED_LINE, SUPPORT, prepare, publish_delta, run

CHAPTER_5 = """# Chapter 5

Date: 2026-04-09

## Scenes

### 005.01 The Far Marker

Warden Hale walked the Lantern Road past the eastern marker and found the far marker standing. The company holds four prisoners.

#### The far marker stands.

- Hale confirms the far marker stands.
- The company holds four prisoners.

## Locations

### Far Marker

A weathered stone beyond the eastern marker.

## Memorable Moments

> "It still stands."
> - Warden Hale
> *Mara smiled.*
"""
CHAPTER_6 = """# Chapter 6

Date: 2026-04-16

## Scenes

### 006.01 The Cellar

Warden Hale confirmed the four prisoners were marched to the far marker before dusk. Corporal Tamsin counted them twice, and Quartermaster Orrin signed for them.

#### The prisoners are moved.

- Hale confirms four prisoners were marched to the far marker.
- Corporal Tamsin counts the prisoners twice.
- Quartermaster Orrin signs for the prisoners.

## Memorable Moments

> "Four, and not one more."
> - Warden Hale
> *Mara counted them twice.*

## NPCs

### Corporal Tamsin

A scarred guard who marches the prisoners and counts them twice.

### Quartermaster Orrin

A tired quartermaster who signs for the prisoners at the far marker.
"""
NEW_LINE_5 = "The far marker beyond the eastern marker still stands. [ch 005 / 005.01]"
PRISONER_LINE_5 = "The company holds four prisoners. [ch 005 / 005.01]"
OLD_LINE_1 = "The brass key still opens the sealed gate. [ch 001 / 001.01]"
CH2_LINE = "The company opens the sealed gate and clears the old watch room. [ch 002 / 002.01]"
NEW_LINE_6 = "Four prisoners were marched to the far marker. [ch 006 / 006.01]"
SUPPORT_5 = "Warden Hale walked the Lantern Road past the eastern marker"
SUPPORT_6 = "Warden Hale confirmed the four prisoners were marched to the far marker"

#: chapter -> (old text, new text): each swapped phrase sits in a cited entry (the corrections quickstart lists).
SEMANTIC = {
    2: ("The company opens the sealed gate and clears the old watch room.",
        "The company opens the sealed gate for a fee of 40 gold and clears the old watch room."),
    3: ("Hale records that the Lantern Road is safe as far as the eastern marker.",
        "Hale records the Lantern Road as open as far as the eastern marker."),
    4: ("Hale confirms the road is open to the eastern marker.",
        "Hale has not yet told the company the road is open to the eastern marker."),
    5: ("The company holds four prisoners.", "The company holds three prisoners."),
}


REGISTRY = """version: 1
campaign: promotion-fixture
entities:
  - name: Corporal Tamsin
    type: npc
    aliases: [Tamsin]
  - name: Quartermaster Orrin
    type: npc
    aliases: [Orrin]
"""

TAMSIN_MODEL = """## Identity

A scarred guard of the far marker. [ch 006 / entry]

## Personality and Motivations

She counts the prisoners twice. [ch 006 / 006.01]

## History with the Party

- Marches the prisoners to the far marker. [ch 006 / 006.01]

## Last Observed State

As of chapter 006 she has marched the prisoners to the far marker. [ch 006 / 006.01]

## Relationships

- Hands the prisoners to Quartermaster Orrin. [ch 006 / 006.01]

## Notable Quotes

None in the evidence.

## Arc-Score Candidates

- Marches the prisoners. [ch 006 / 006.01]
"""

ORRIN_MODEL = """## Identity

A tired quartermaster at the far marker. [ch 006 / entry]

## Personality and Motivations

He signs for what he is handed. [ch 006 / 006.01]

## History with the Party

- Signs for the prisoners at the far marker. [ch 006 / 006.01]

## Last Observed State

As of chapter 006 he holds the signed prisoner ledger. [ch 006 / 006.01]

## Relationships

- Receives the prisoners from Corporal Tamsin. [ch 006 / 006.01]

## Notable Quotes

None in the evidence.

## Arc-Score Candidates

- Signs for the prisoners. [ch 006 / 006.01]
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def git_show_bytes(root: Path, rev: str, rel: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, check=True).stdout


@dataclass
class RebaseFixture:
    root: Path
    generation_id: str = ""
    paths: dict[int, Path] = field(default_factory=dict)
    old_sha: dict[int, str] = field(default_factory=dict)
    new_sha: dict[int, str] = field(default_factory=dict)
    pending_plan_id: str | None = None
    staged: dict | None = None
    npc_members: list[str] = field(default_factory=list)
    npc_slugs: list[str] = field(default_factory=list)
    #: git commit holding the original (pre-correction) summaries
    original_commit: str = ""

    @property
    def corrected(self) -> list[int]:
        return sorted(c for c in self.new_sha if self.new_sha[c] != self.old_sha[c])


def _summary_paths(root: Path) -> dict[int, Path]:
    out = {}
    for p in (root / "docs/summaries").glob("*.md"):
        head = p.name.split("-", 1)[0]
        if head.isdigit():
            out[int(head)] = p
    return out


def init_git(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.com")
    git(root, "config", "user.name", "fixture")
    git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def build_active_through_ch5(tmp_path: Path, capsys, monkeypatch) -> RebaseFixture:
    """Layer 1: ch1-3 legacy generation, then delta generations for ch4 and ch5 through the real publish path."""
    root = make_grounding_campaign(tmp_path)
    init_git(root)
    fx = RebaseFixture(root=root)
    publish_delta(capsys, root, add_new_chapter(root), monkeypatch, 4, "rb-r4",
                  "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE + "\n" + CH2_LINE)
    source5 = root / "docs/summaries/005-the-far-marker.md"
    source5.write_text(CHAPTER_5, encoding="utf-8")
    publish_delta(capsys, root, source5, monkeypatch, 5, "rb-r5",
                  "{line}\n" + NEW_LINE_5 + "\n" + PRISONER_LINE_5 + "\n" + OLD_LINE_1, support=SUPPORT_5)
    from pipelines.summary_native.delta import baseline as bl
    fx.generation_id = bl.bind(root).generation_id
    assert fx.generation_id != GENERATION_ID
    return fx


def stage_pending_ch6(fx: RebaseFixture, capsys, monkeypatch, *, npc: bool = False) -> RebaseFixture:
    """Layer 2: a pending ch6 plan (grounding, and NPC when ``npc``), the grounding half decided, checked and
    staged (not applied)."""
    root = fx.root
    source6 = root / "docs/summaries/006-the-cellar.md"
    source6.write_text(CHAPTER_6, encoding="utf-8")
    if npc:
        (root / "docs/entity_registry.yaml").write_text(REGISTRY, encoding="utf-8")
        # the promotion factory writes `version: 1`, which `load_players_config` (the NPC census reads it) refuses
        (root / "config/players.yaml").write_text(
            "players:\n  - id: fixture-player\n    name: Fixture Player\n    plays:\n      - Mara Vale\n", encoding="utf-8")
    pid, _line = prepare(capsys, root, source6, monkeypatch,
                         "{line}\n" + NEW_LINE_6, support=SUPPORT_6, products=("grounding", "npc") if npc else ("grounding",))
    assert run(capsys, root, "grounding", "check", "--plan", pid)["passed"] is True
    fx.staged = run(capsys, root, "grounding", "preview", "--plan", pid)["staged"]
    fx.pending_plan_id = pid
    return fx


def stage_pending_npc(fx: RebaseFixture, capsys, monkeypatch) -> RebaseFixture:
    """Layer 2b: publish TWO new NPC dossiers (Corporal Tamsin, Quartermaster Orrin) for the pending ch6 plan.

    Everything is the real path: ``delta run resume`` (census, draft with a deterministic stand-in at
    ``npc_draft.stream_api``, verify), ``delta review handoff`` (the NPC half), the exact-draft sign-off through
    ``review npc sign``, the GM's ``delta npc publish`` preview, and ``delta run resume`` again, which publishes.
    The run state, receipts and review bindings on disk are the real ones; nothing is written by hand.
    """
    from _delta_npc_support import FakeModel, handoff_and_sign, install_fake
    from pipelines.summary_native import cli as sn_cli
    from pipelines.summary_native.delta import plan as dplan

    root = fx.root
    plan = dplan.load_plan(dplan.plans_dir(root), fx.pending_plan_id)
    assert "npc" in plan.products

    def cli(*argv):
        code = sn_cli.main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    fake = install_fake(monkeypatch, FakeModel({"Corporal Tamsin": TAMSIN_MODEL, "Quartermaster Orrin": ORRIN_MODEL}))
    # the run does census, draft (the stand-in model), verify; publish waits for the GM, and so does grounding
    cli("delta", "run", "resume", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json")
    assert len(fake.prompts) == 2
    handoff_and_sign(root, capsys, plan=plan)
    code, out, err = cli("delta", "npc", "publish", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json",
                         "--member", "Corporal Tamsin", "--member", "Quartermaster Orrin")  # the GM's preview
    assert code == 0 and json.loads(out)["published"] is False, (out, err)
    cli("delta", "run", "resume", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json")
    status = json.loads(cli("delta", "run", "status", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json")[1])
    published = {m["subject"]: m for m in status["members"] if m["outcome"] == "published" and m["receipt_ref"]}
    assert sorted(published) == ["Corporal Tamsin", "Quartermaster Orrin"], status
    fx.npc_members = sorted(published)
    fx.npc_slugs = ["corporal-tamsin", "quartermaster-orrin"]
    for slug in fx.npc_slugs:
        assert (root / "docs/npcs" / f"{slug}.md").is_file()
    return fx


def snapshot_originals(fx: RebaseFixture) -> None:
    fx.paths = _summary_paths(fx.root)
    fx.old_sha = {c: sha(p.read_bytes()) for c, p in fx.paths.items()}
    fx.original_commit = commit_all(fx.root, "original summaries and published generations")


def apply_corrections(fx: RebaseFixture, *, whitespace_ch1: bool = False) -> RebaseFixture:
    """Layer 3: commit corrections.  ``whitespace_ch1`` is the separate variant: ONLY ch1, in an uncited region."""
    if whitespace_ch1:
        p = fx.paths[1]
        text = p.read_text(encoding="utf-8")
        assert "Hale keeps the gate ledger.\n" in text
        p.write_text(text.replace("Hale keeps the gate ledger.\n", "Hale keeps the gate ledger.  \n", 1), encoding="utf-8")
    else:
        for chapter, (old, new) in SEMANTIC.items():
            p = fx.paths[chapter]
            text = p.read_text(encoding="utf-8")
            assert old in text, (chapter, old)
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
    fx.new_sha = {c: sha(p.read_bytes()) for c, p in fx.paths.items()}
    commit_all(fx.root, "corrections")
    return fx


def build(tmp_path: Path, capsys, monkeypatch, *, whitespace_ch1: bool = False,
          pending_ch6: bool = True, npc: bool = False) -> RebaseFixture:
    """``npc=True`` also publishes two NPC dossiers for the pending ch6 plan (slower; the rebind tests need it)."""
    fx = build_active_through_ch5(tmp_path, capsys, monkeypatch)
    if pending_ch6:
        stage_pending_ch6(fx, capsys, monkeypatch, npc=npc)
        if npc:
            stage_pending_npc(fx, capsys, monkeypatch)
    snapshot_originals(fx)
    return apply_corrections(fx, whitespace_ch1=whitespace_ch1)


def sha_tree(root: Path, *subdirs: str) -> dict[str, str]:
    """A recursive ``relative path -> sha256`` map of every file under each ``subdirs`` (SC-004's before/after)."""
    out: dict[str, str] = {}
    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.is_symlink():
                out[p.relative_to(root).as_posix()] = sha(p.read_bytes())
    return out


def claims_and_signoffs(capsys, root: Path, plan_id: str, *, since: int, until: int, review_id: str,
                        apply: bool = True) -> dict:
    """The real claims chain and four-document signoffs for a plan's staged range, then ``grounding apply`` for real.

    The same sequence ``tests.test_delta_grounding_e2e.publish_delta`` runs after staging (claims select, claims
    review, claims check, exact signoffs of each document through ``review.documents.sign_document``, the review
    decisions, ``delta review handoff``, ``grounding apply``), over the span ``since..until``.  Nothing is mocked.
    Returns the ``grounding apply`` JSON, or (``apply=False``) the preview record after the GROUNDING half of the
    handoff only, so a caller can finish with ``delta run resume`` and leave the plan's NPC binding as it is.
    """
    from datetime import datetime, timezone

    from campaignlib.grounding_config import promotion_config_from_summary_native
    from pipelines.summary_native import cli
    from pipelines.summary_native.claims.selection import (
        confirm_selection, mandatory_source_closure, save_confirmed_selection)
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    from pipelines.summary_native.promotion.settings import load_settings
    from pipelines.summary_native.review.documents import sign_document
    from pipelines.summary_native.review.models import canonical_bytes
    from pipelines.summary_native.review.store import load_campaign_identity, read_snapshot

    staged = run(capsys, root, "grounding", "preview", "--plan", plan_id)["staged"]
    assert staged["range"] == f"ch{since:03d}-{until:03d}", staged
    config = root / "config/config.yaml"
    settings = load_settings(str(config))
    rules = promotion_config_from_summary_native(settings.summary_native).rule_versions
    campaign_id = str(load_campaign_identity(root).campaign_id)
    bundle = build_bundle_selection(root, out_root=staged["request"]["out_root"], since=since, until=until,
                                    campaign_id=campaign_id, review_id="claims-selection", rule_versions=rules,
                                    config_path=root / "config/grounding.yaml")
    selection = mandatory_source_closure(root, bundle, effective_horizon=f"through-chapter-{until}",
                                         audience="gm", rule_versions=rules)
    confirmed = confirm_selection(selection, reviewer="gm", confirmed_at=datetime(2026, 11, 6, tzinfo=timezone.utc))
    save_confirmed_selection(root, confirmed)
    selection_file = root.parent / f"selection-{plan_id}.json"
    selection_file.write_bytes(canonical_bytes(confirmed))
    assert cli.main(["claims", "review", "--config", str(config), "--selection", str(selection_file),
                     "--review", review_id, "--json"]) == 0
    capsys.readouterr()
    code = cli.main(["claims", "check", "--config", str(config), "--selection", str(selection_file),
                     "--review", review_id, "--json"])
    checked = json.loads(capsys.readouterr().out)
    assert code == 0, checked
    report = checked["data"]["paths"][0]
    _m, _c, items = read_snapshot(root, review_id)
    for item in items:
        if item.proposed_action.action == "signoff_document":
            sign_document(root, review_id, document_item_id=item.item_id,
                          item_sha256=item.proposed_action.details["document_sha256"],
                          expected_decision_revision=0, reviewer="fixture-gm")
    previewed = run(capsys, root, "grounding", "preview", "--plan", plan_id, "--review", review_id,
                    "--claims-report", report)
    manifest, _c, items = read_snapshot(root, review_id)
    others = [i for i in items if i.proposed_action.action != "signoff_document"]
    if others:
        batch = root.parent / f"decisions-{plan_id}.json"
        batch.write_text(json.dumps({"version": 1, "request_id": f"rq-{plan_id}", "review_generation": manifest.generation,
                                     "reviewer": "fixture-gm", "decisions": [
            {"item_id": i.item_id, "item_revision": i.revision, "review_digest": i.review_digest,
             "expected_decision_revision": 0, "verdict": "approve", "disposition": "accept_no_change",
             "note": "reviewed"} for i in others]}))
        assert cli.main(["review", "decide", review_id, "--decisions", str(batch),
                         "--campaign-dir", str(root), "--json"]) == 0, capsys.readouterr()
        capsys.readouterr()
    if not apply:
        from pipelines.summary_native.delta import cli_review
        from pipelines.summary_native.delta.plan import load_plan, plans_dir

        cli_review._handoff_grounding(root, load_plan(plans_dir(root), plan_id))  # the grounding binding only
        return previewed
    run(capsys, root, "review", "handoff", "--plan", plan_id)
    applied = run(capsys, root, "grounding", "apply", "--plan", plan_id, "--preview-sha", previewed["preview_sha256"])
    assert applied["applied"] is True, applied
    return applied


# --------------------------------------------------------------------------- module-scoped builds

class Capture:
    """A stand-in for ``capsys`` so a MODULE-scoped fixture can drive the CLI helpers (``capsys`` is per test).

    ``with capture.active():`` redirects stdout/stderr into it; ``readouterr()`` returns and clears what was written.
    """

    def __init__(self) -> None:
        import io

        self._out, self._err = io.StringIO(), io.StringIO()

    def active(self):
        import contextlib

        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(self._out))
        stack.enter_context(contextlib.redirect_stderr(self._err))
        return stack

    def readouterr(self):
        from collections import namedtuple

        out, err = self._out.getvalue(), self._err.getvalue()
        for buf in (self._out, self._err):
            buf.seek(0)
            buf.truncate()
        return namedtuple("CaptureResult", "out err")(out, err)


#: Everything SC-004 says a rebase must leave byte-identical once it exists.
HISTORY = ("docs/grounding/generations", "docs/grounding/activations", "docs/grounding/migrations", "docs/reviews",
           "docs/npcs")


def pending_receipts(fx: RebaseFixture) -> dict[str, str]:
    """sha256 of every NPC publication receipt the pending ch6 plan holds on disk (the run's own records)."""
    return {k: v for k, v in sha_tree(fx.root, f"docs/summaries/delta/{fx.pending_plan_id}/npc/receipts").items()
            if k.endswith(".json") and not k.endswith(".intent.json")}


class Rebased:
    """What :func:`do_rebase` leaves behind: ids, the review, and the before/after byte maps of history."""

    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


def rrun(cap, root, *argv, expect=0):
    """A ``delta rebase|rebind`` call: the ``{ok, code, message, data}`` envelope, returned as its ``data``."""
    out = run(cap, root, *argv, expect=expect)
    return out["data"] if expect == 0 else out


def do_rebase(fx: RebaseFixture, cap, *, apply: bool = True) -> Rebased:
    """The whole US1+US2 repair through the public CLI and the REAL gates, ending with the new generation active.

    prepare (with the pending plan's candidates) -> GM repairs (chapters 2, 4, 5), one hold, and the bulk hold of
    the chapter-3 entry the planning document repeats 1450 times -> approve -> decide -> ``grounding check`` ->
    ``grounding preview`` (stage) -> real claims select/review/check -> exact document signoffs ->
    ``review handoff`` -> ``grounding apply``.
    """
    root = fx.root
    before = sha_tree(root, *HISTORY)
    prep = rrun(cap, root, "rebase", "prepare", *[a for c in (2, 3, 4, 5) for a in ("--source", str(fx.paths[c]))],
               *(["--for-plan", fx.pending_plan_id] if fx.pending_plan_id else []))
    pid = prep["plan_id"]
    review = rrun(cap, root, "rebase", "show", "--plan", pid)
    from pipelines.summary_native.delta import rebase as rebase_mod, rebase_impact

    docs = rebase_mod.baseline_docs(rebase_mod.load_state(root, pid))

    def line_for(chapter: int, needle: str) -> str:
        """The affected world_state line of ``chapter`` whose text holds ``needle`` (the lines are picked by what they say)."""
        found = [l["line_id"] for l in review["affected_lines"] if l["chapter"] == chapter and l["document"] == "world_state"
                 and needle in rebase_impact.find_line(docs, l["line_id"])[2].decode("utf-8")]
        assert len(found) == 1, (chapter, needle, found)
        return found[0]

    made = {}
    for key, (chapter, needle, text) in {
            "ch2": (2, "sealed gate", "The company opens the sealed gate for a fee of 40 gold. [ch 002 / 002.01]"),
            "ch4": (4, "eastern marker", "The road is open once Hale has told the company. [ch 004 / 004.01]"),
            "ch5_count": (5, "four prisoners", "The company holds three prisoners. [ch 005 / 005.01]"),
            "ch5_held": (5, "far marker", "The far marker stands. [ch 005 / 005.01]")}.items():
        made[key] = rrun(cap, root, "rebase", "repair", "--plan", pid, "--line", line_for(chapter, needle),
                         "--text", text, "--reason", "the corrected chapter says otherwise", "--reviewer", "gm")
    for key in ("ch2", "ch4", "ch5_count"):
        run(cap, root, "grounding", "decide", made[key]["proposal_id"], "--plan", pid, "--decision", "approve",
            "--reviewer", "gm")
    run(cap, root, "grounding", "decide", made["ch5_held"]["proposal_id"], "--plan", pid, "--decision", "hold",
        "--reviewer", "gm")
    hold = rrun(cap, root, "rebase", "repair", "--plan", pid, "--hold-entry", "3/003.01", "--reviewer", "gm",
               "--reason", "the whole 003.01 entry was corrected; the repeated planning lines are held, not rewritten")
    argv = ["rebase", "decide", "--plan", pid, "--reviewer", "gm", "--reason", "read by the GM"]
    for c in (2, 3, 4, 5):
        argv += ["--source-decision", f"{c}=adopt-with-repairs"]
    for m in review["unknown_members"]:
        argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
    decided = rrun(cap, root, *argv)
    checked = run(cap, root, "grounding", "check", "--plan", pid)
    applied = claims_and_signoffs(cap, root, pid, since=2, until=5, review_id="rebase-review", apply=apply)
    from pipelines.summary_native.delta import baseline as bl
    return Rebased(plan_id=pid, rebase_id=prep["rebase_id"], prepared=prep, review=review, repairs=made, hold=hold,
                   decided=decided, checked=checked, applied=applied, history_before=before,
                   history_after=sha_tree(root, *HISTORY), new_generation=bl.bind(root).generation_id)
