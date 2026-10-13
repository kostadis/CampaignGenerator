"""``npc_agent`` — Prototype 1: presence candidates and the knowledge horizon.

    npc_agent candidates --campaign-dir DIR (--npc NAME ... | --all) --out-dir OUT
    npc_agent review     --campaign-dir DIR (--npc NAME ... | --all) --out PAGE [--also-campaign-dir DIR ...]
    npc_agent horizon    --campaign-dir DIR --npc NAME --chapter N --rulings FILE
                         [--knowledge FILE] [--for-agent] [--out FILE]
    npc_agent leaks      --campaign-dir DIR --knowledge FILE [--out FILE]

A knowledge ruling file holds one block per campaign; the campaign is the
``--campaign-dir`` name (``--campaign`` overrides it), as the review page labels it.

``--campaign-dir`` accepts either layout: the published one
(``<dir>/summaries`` + ``<dir>/npcs``, as in ``campaigns-public/<campaign>``) or
a campaign root (``<dir>/docs/summaries`` + ``<dir>/docs/npcs``).
``--summaries-dir`` and ``--npcs-dir`` override it.

Exit codes: 0 done; 2 refused, nothing written; 3 written, but a candidate list
does not match its published dossier (see ``check_report.md``).

Writes only under ``--out-dir`` / ``--out``, never inside the summaries or the
dossiers, and never the ruling file. No model call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from campaignlib.util import atomic_write_text
from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent import dossier as dossier_mod
from pipelines.npc_agent import horizon as horizon_mod
from pipelines.npc_agent import knowledge, presence, report, review, rulings
from pipelines.summary_native import duplicates, npc_forms

CHECK_REPORT = "check_report.md"
RULING_TEMPLATE = "presence.template.yaml"


class Refusal(Exception):
    """Refused before anything is written (exit 2)."""


def _layout(args) -> tuple[Path, Path]:
    return _dirs(args.campaign_dir, args.summaries_dir, args.npcs_dir)


def _dirs(campaign_dir, summaries, npcs) -> tuple[Path, Path]:
    if campaign_dir is not None:
        c = Path(campaign_dir).expanduser()
        if (c / "summaries").is_dir() and (c / "npcs").is_dir():
            summaries, npcs = summaries or c / "summaries", npcs or c / "npcs"
        elif (c / "docs" / "summaries").is_dir() and (c / "docs" / "npcs").is_dir():
            summaries, npcs = summaries or c / "docs" / "summaries", npcs or c / "docs" / "npcs"
        else:
            raise Refusal(
                f"{c}: neither summaries/ + npcs/ nor docs/summaries/ + docs/npcs/ found; "
                "pass --summaries-dir and --npcs-dir"
            )
    if summaries is None or npcs is None:
        raise Refusal("pass --campaign-dir, or both --summaries-dir and --npcs-dir")
    for label, p in (("summaries", summaries), ("npcs", npcs)):
        if not Path(p).is_dir():
            raise Refusal(f"{label} directory not found: {p}")
    return Path(summaries).expanduser(), Path(npcs).expanduser()


def _refuse_inside(target: Path, sources: tuple[Path, ...]) -> None:
    t = target.expanduser().resolve()
    for s in sources:
        s = s.resolve()
        if t == s or s in t.parents:
            raise Refusal(f"{target} is inside {s}; npc_agent never writes into its sources")


def _load(args):
    summaries, npcs = _layout(args)
    try:
        dossiers = dossier_mod.read_dossiers(npcs)
        if getattr(args, "all", False):
            chosen = dossiers
        else:
            chosen = dossier_mod.select(dossiers, args.npc)
    except dossier_mod.DossierError as e:
        raise Refusal(str(e)) from None
    if not chosen:
        raise Refusal(f"{npcs}: no published dossiers")
    corpus = corpus_mod.load_corpus(summaries)
    if not corpus.chapters:
        raise Refusal(f"{summaries}: no summaries with a numeric chapter prefix")
    table = presence.build_form_table(dossiers, npc_forms.load_wordlist()[0], _link_rulings(args))
    args.dossiers = dossiers
    return summaries, npcs, corpus, chosen, table


def _campaign(args, summaries: Path) -> str:
    """The key of this campaign's block in a knowledge ruling file."""
    if getattr(args, "campaign", None):
        return args.campaign
    if args.campaign_dir is not None:
        return Path(args.campaign_dir).expanduser().resolve().name
    return summaries.resolve().parent.name


def _knowledge(args, summaries: Path, corpus) -> dict[str, knowledge.Note]:
    try:
        return knowledge.load_knowledge(args.knowledge, _campaign(args, summaries), corpus)
    except knowledge.KnowledgeError as e:
        raise Refusal(str(e)) from None


def _link_rulings(args) -> dict[str, str]:
    """``canon.yaml link_rulings``: which generic single-word names are safe to link.

    The published layout carries no ``canon.yaml``; without one, every generic
    form is withheld, as ``npc-link`` withholds it, and the check says so.
    """
    path = args.canon
    if path is None and args.campaign_dir is not None:
        default = Path(args.campaign_dir).expanduser() / "docs" / "summary_native" / "canon.yaml"
        if default.is_file():
            path = default
            print(f"link rulings: {path}", file=sys.stderr)
    if path is None:
        return {}
    if not Path(path).is_file():
        raise Refusal(f"--canon {path}: no such file")
    try:
        return dict(duplicates.load_rulings(Path(path)).link_rulings)
    except duplicates.RulingsError as e:
        raise Refusal(str(e)) from None


def cmd_candidates(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    out_dir = Path(args.out_dir)
    _refuse_inside(out_dir, (summaries, npcs))
    out_dir.mkdir(parents=True, exist_ok=True)
    checks, pairs = [], []
    for d in chosen:
        ms = presence.mentions(corpus, d, table)
        evs = presence.events(ms)
        check = presence.check_against_dossier(corpus, d, ms, table)
        checks.append(check)
        pairs.append((d, evs))
        atomic_write_text(out_dir / f"{d.stem}.candidates.md", report.candidates_md(d, ms, check))
        atomic_write_text(out_dir / f"{d.stem}.candidates.json", report.candidates_json(d, ms))
        print(f"{d.subject}: {len(evs)} event(s) to answer, {len(ms)} mention(s); "
              f"check {'ok' if check.ok else 'MISMATCH'}")
    atomic_write_text(out_dir / CHECK_REPORT, report.check_report_md(checks, corpus.findings))
    atomic_write_text(out_dir / RULING_TEMPLATE, presence.ruling_template(pairs))
    print(f"wrote {len(chosen) * 2 + 2} file(s) to {out_dir}")
    for f in corpus.findings:
        print(f"finding: {f}", file=sys.stderr)
    return 0 if all(c.ok for c in checks) else 3


def cmd_horizon(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    if args.out is not None:
        _refuse_inside(Path(args.out), (summaries, npcs))
    d = chosen[0]
    ms = presence.mentions(corpus, d, table)
    cands = presence.events(ms)
    items = {it.item_id: it for it in corpus.items()}
    cand_ids = {c.item.item_id for c in cands}
    try:
        ruled = rulings.load_rulings(args.rulings, {d.subject: cand_ids}, corpus)
    except rulings.RulingError as e:
        raise Refusal(str(e)) from None
    npc = ruled.get(d.subject, rulings.NpcRulings())
    eff = rulings.effective(npc, corpus, cand_ids)
    hidden = frozenset()
    if args.knowledge is not None:
        hidden = knowledge.hidden_from(_knowledge(args, summaries, corpus), d)
    h = horizon_mod.build_horizon(d, cands, eff, args.chapter, items, presence.snapshots(ms),
                                  npc.not_perceived, hidden)
    if args.for_agent and h.unruled:
        raise Refusal(
            f"{len(h.unruled)} event(s) naming {d.subject} up to chapter {args.chapter} are unanswered; "
            "an agent is never given an incomplete horizon. Answer them, or run without --for-agent."
        )
    text = horizon_mod.render_horizon(h, for_agent=args.for_agent)
    if args.out is None:
        sys.stdout.write(text)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.out), text)
        print(f"wrote {args.out}")
    return 0


def cmd_review(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    out = Path(args.out)
    _refuse_inside(out, (summaries, npcs))
    pairs = [(d, presence.mentions(corpus, d, table)) for d in chosen]
    source = args.source or _campaign(args, summaries)
    camps = [review.knowledge_campaign(_campaign(args, summaries), corpus, args.dossiers)]
    for other in args.also_campaign_dir or []:
        o_summaries, o_npcs = _dirs(other, None, None)
        try:
            o_dossiers = dossier_mod.read_dossiers(o_npcs)
        except dossier_mod.DossierError as e:
            raise Refusal(str(e)) from None
        name = Path(other).expanduser().resolve().name
        if name in {c["campaign"] for c in camps}:
            raise Refusal(f"--also-campaign-dir {other}: a campaign named {name!r} is already on the page")
        camps.append(review.knowledge_campaign(name, corpus_mod.load_corpus(o_summaries), o_dossiers))
    page = review.render_page(review.bundle(corpus, pairs, source, camps))
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, page)
    for d, ms in pairs:
        print(f"{d.subject}: {len(presence.events(ms))} event(s) to answer")
    for c in camps:
        print(f"knowledge notes, {c['campaign']}: {len(c['cards'])} beat(s) to answer")
    print(f"wrote {out} ({len(page.encode('utf-8')) // 1024} KiB)")
    return 0


def cmd_leaks(args) -> int:
    summaries, npcs = _layout(args)
    corpus = corpus_mod.load_corpus(summaries)
    try:
        dossiers = dossier_mod.read_dossiers(npcs)
    except dossier_mod.DossierError as e:
        raise Refusal(str(e)) from None
    if args.out is not None:
        _refuse_inside(Path(args.out), (summaries, npcs))
    notes = _knowledge(args, summaries, corpus)
    cases = knowledge.leak_cases(notes, corpus, dossiers)
    text = knowledge.leak_cases_yaml(_campaign(args, summaries), cases)
    if args.out is None:
        sys.stdout.write(text)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.out), text)
        print(f"wrote {args.out}: {len(cases)} leak case(s)")
    kinds = {k: sum(1 for n in notes.values() if n.kind == k) for k in knowledge.KINDS}
    print("notes: " + ", ".join(f"{k} {v}" for k, v in kinds.items()), file=sys.stderr)
    for c in cases:
        if c.subject is None:
            print(f"{c.beat_id}: {c.who} has no published dossier; kept as a leak case", file=sys.stderr)
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--campaign-dir", type=Path, default=None,
                   help="campaigns-public/<campaign>, or a campaign root")
    p.add_argument("--summaries-dir", type=Path, default=None)
    p.add_argument("--npcs-dir", type=Path, default=None, help="published dossiers (top-level *.md)")
    p.add_argument("--canon", type=Path, default=None,
                   help="canon.yaml with link_rulings (default: <campaign-dir>/docs/summary_native/canon.yaml if present)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="npc_agent", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("candidates", help="list every item naming an NPC, with its evidence")
    _common(c)
    who = c.add_mutually_exclusive_group(required=True)
    who.add_argument("--npc", action="append", help="subject, file stem or name form (repeatable)")
    who.add_argument("--all", action="store_true", help="every NPC with a published dossier")
    c.add_argument("--out-dir", type=Path, required=True)
    c.set_defaults(func=cmd_candidates)

    r = sub.add_parser("review", help="write the presence review page for the GM")
    _common(r)
    rwho = r.add_mutually_exclusive_group(required=True)
    rwho.add_argument("--npc", action="append", help="subject, file stem or name form (repeatable)")
    rwho.add_argument("--all", action="store_true", help="every NPC with a published dossier")
    r.add_argument("--out", type=Path, required=True, help="the HTML page to write")
    r.add_argument("--source", default=None, help="label shown on the page (default: the campaign directory name)")
    r.add_argument("--also-campaign-dir", action="append", type=Path,
                   help="another campaign whose knowledge notes the page also shows (repeatable)")
    r.add_argument("--campaign", default=None, help="this campaign's name in knowledge files (default: --campaign-dir's name)")
    r.set_defaults(func=cmd_review)

    h = sub.add_parser("horizon", help="an NPC's knowledge horizon at a chapter")
    _common(h)
    h.add_argument("--npc", action="append", required=True)
    h.add_argument("--chapter", type=int, required=True)
    h.add_argument("--rulings", type=Path, required=True, help="the GM's presence ruling file")
    h.add_argument("--out", type=Path, default=None, help="default: stdout")
    h.add_argument("--for-agent", action="store_true",
                   help="only what the NPC could know; refused while any event is unanswered")
    h.add_argument("--knowledge", type=Path, default=None,
                   help="the GM's knowledge ruling file: secrets hidden from this NPC are left out")
    h.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    h.set_defaults(func=cmd_horizon)

    k = sub.add_parser("leaks", help="leak cases from the GM's knowledge rulings: who must not know what")
    _common(k)
    k.add_argument("--knowledge", type=Path, required=True, help="the GM's knowledge ruling file")
    k.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    k.add_argument("--out", type=Path, default=None, help="default: stdout")
    k.set_defaults(func=cmd_leaks)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "horizon" and len(args.npc) != 1:
        print("Error: horizon takes exactly one --npc", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except Refusal as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
