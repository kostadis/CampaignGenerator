"""``npc_agent`` — Prototype 1: presence candidates and the knowledge horizon.

    npc_agent candidates --campaign-dir DIR (--npc NAME ... | --all) --out-dir OUT
    npc_agent review     --campaign-dir DIR (--npc NAME ... | --all) --out PAGE [--also-campaign-dir DIR ...]
    npc_agent horizon    --campaign-dir DIR --npc NAME --chapter N --rulings FILE
                         [--knowledge FILE] [--for-agent] [--out FILE]
    npc_agent leaks      --campaign-dir DIR [--knowledge FILE] [--out FILE]
    npc_agent persona    --campaign-dir DIR --npc NAME --chapter N [--out FILE] [--report FILE]
    npc_agent leakcheck  --campaign-dir DIR --npc NAME --chapter N --answer FILE --given FILE
                         [--knowledge FILE] [--target-scene NNN.SS] [--out FILE]
    npc_agent backtest   --campaign-dir DIR --npc NAME --rulings FILE --target NNN.SS [--target ...]
                         --out-dir OUT [--knowledge FILE] [--dry-run] [--force] [--model M] [--backend B]
    npc_agent prep       --campaign-dir DIR --npc NAME --target NNN.SS --prep FILE [--section TEXT]
                         [--target ... --prep ... --section ...] --out PAGE
    npc_agent prep-sheet --campaign-dir DIR --npc NAME --target NNN.SS --prep FILE [--section TEXT]
                         --rulings prep.json [--out FILE]
    npc_agent replay     --campaign-dir DIR --npc NAME --rulings FILE --target NNN.SS --prep FILE [--section TEXT]
                         --prep-rulings prep.json [--target ... --prep ... --section ...] --out-dir OUT
                         [--knowledge FILE] [--turns-only] [--free] [--dry-run] [--force] [--model M] [--backend B]
    npc_agent forward    --campaign-dir DIR --npc NAME --rulings FILE --chapter N --next NNN.SS
                         --prep FILE [--section TEXT] --prep-rulings prep.json --prep-target NNN.SS
                         [--plan FILE [--plan-section TEXT]] --out-dir OUT [--knowledge FILE] [--dry-run] [--force]

``replay`` splits a scene into turns (:mod:`turns`), asks the agent each one with the real scene so far
(earlier turns' real answers included, never later ones), and writes ``OUT/replay.html``. ``forward``
asks once what she does between sessions; the GM's plan reaches the page, never a prompt.

``replay --free`` runs free: each earlier turn's real answer in "So far in this scene" is replaced by the
agent's own answer for that turn (the party's lines stay real), so turns run in order and a changed
earlier answer changes every later prompt's sha. It writes to ``OUT/<target>/free/`` and the page shows it as
its own section beside the teacher-forced one, which is left untouched.

A beat whose sentence states what someone does not know is always left out of
their horizon (:mod:`knowledge`); ``--knowledge`` adds the GM's ``who`` where
the sentence gives a description, not a name. It holds one block per campaign;
the campaign is the ``--campaign-dir`` name (``--campaign`` overrides it), as
the review page labels it.

``--campaign-dir`` accepts either layout: the published one
(``<dir>/summaries`` + ``<dir>/npcs``, as in ``campaigns-public/<campaign>``) or
a campaign root (``<dir>/docs/summaries`` + ``<dir>/docs/npcs``).
``--summaries-dir`` and ``--npcs-dir`` override it.

``persona`` keeps only the sentences of the NPC's own entries that are about her
(:mod:`persona`) and reports every dropped one; ``leakcheck`` flags, for the GM
to confirm, sentences of an agent's answer that state a hidden beat or name
something the agent was not given (:mod:`leakcheck`). Flags are not failures.

``backtest`` freezes the NPC at the chapter before each target scene she attended,
asks the model (:mod:`agent`, the only model step) what she does there, then
leak-checks the answer and writes a scoring page for the GM. The scene's own
text is written beside it as the answer key and is never in the prompt.

``prep`` cuts the GM's prep files into passages (:mod:`prep`) and writes a page where the
GM marks each one hers (she knows it) or gm (only the GM does); ``prep-sheet`` renders the
hers passages, with no line numbers or file names, once every passage is ruled.

Exit codes: 0 done; 2 refused, nothing written; 3 written, but a candidate list
does not match its published dossier (see ``check_report.md``).

Writes only under ``--out-dir`` / ``--out``, never inside the summaries or the
dossiers, and never the ruling file. No model call here: ``backtest`` reaches the
model only through :func:`agent.play`.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from campaignlib.util import atomic_write_text
from pipelines.npc_agent import agent as agent_mod
from pipelines.npc_agent import backtest_page
from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent import dossier as dossier_mod
from pipelines.npc_agent import horizon as horizon_mod
from pipelines.npc_agent import (forward, knowledge, leakcheck, persona, prep, prep_page, presence, replay_page, report,
                                 review, rulings, turns)
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


def _knowledge(args, summaries: Path, corpus) -> list[knowledge.Resolved]:
    if args.knowledge is None:
        return knowledge.resolve(corpus)
    try:
        return knowledge.resolve(corpus, knowledge.load_knowledge(args.knowledge, _campaign(args, summaries), corpus))
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


def _ruled(args, corpus, d, cands):
    """The GM's presence rulings for ``d``: ``(NpcRulings, effective)``."""
    cand_ids = {c.item.item_id for c in cands}
    try:
        ruled = rulings.load_rulings(args.rulings, {d.subject: cand_ids}, corpus)
    except rulings.RulingError as e:
        raise Refusal(str(e)) from None
    npc = ruled.get(d.subject, rulings.NpcRulings())
    return npc, rulings.effective(npc, corpus, cand_ids)


def _horizon(args, summaries, corpus, d, ms, npc, eff, chapter, for_agent):
    """The horizon at ``chapter``; with ``for_agent`` it refuses what an agent must never be given."""
    items = {it.item_id: it for it in corpus.items()}
    resolved = _knowledge(args, summaries, corpus)
    unresolved = frozenset(r.candidate.beat_id for r in resolved if r.unresolved)
    h = horizon_mod.build_horizon(d, presence.events(ms), eff, chapter, items, presence.snapshots(ms),
                                  npc.not_perceived, knowledge.hidden_from(resolved, d), unresolved)
    if for_agent and h.unresolved:
        raise Refusal(
            f"{', '.join(sorted(h.unresolved))}: in an event {d.subject} attended, the summary says someone "
            "doesn't know something without naming who; an agent is never given a beat that may be hidden "
            "from it. Rule who in --knowledge."
        )
    if for_agent and h.unruled:
        raise Refusal(
            f"{len(h.unruled)} event(s) naming {d.subject} up to chapter {chapter} are unanswered; "
            "an agent is never given an incomplete horizon. Answer them, or run without --for-agent."
        )
    return h


def cmd_horizon(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    if args.out is not None:
        _refuse_inside(Path(args.out), (summaries, npcs))
    d = chosen[0]
    ms = presence.mentions(corpus, d, table)
    npc, eff = _ruled(args, corpus, d, presence.events(ms))
    h = _horizon(args, summaries, corpus, d, ms, npc, eff, args.chapter, args.for_agent)
    text = horizon_mod.render_horizon(h, for_agent=args.for_agent, compact=args.compact_horizon)
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
        hides = [k for k in c["cards"] if k["o"] == knowledge.HIDES]
        open_ = [k for k in hides if not k["wh"] and not k["pa"]]
        print(f"knowledge notes, {c['campaign']}: {len(c['cards'])} beat(s), {len(hides)} hidden from someone, "
              f"{len(open_)} need a name")
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
    resolved = _knowledge(args, summaries, corpus)
    cases = knowledge.leak_cases(resolved, dossiers)
    text = knowledge.leak_cases_yaml(_campaign(args, summaries), cases)
    if args.out is None:
        sys.stdout.write(text)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.out), text)
        print(f"wrote {args.out}: {len(cases)} leak case(s)")
    hides = [r for r in resolved if r.outcome == knowledge.HIDES]
    print(f"{len(resolved)} beat(s) say someone doesn't know: {len(hides)} state what, "
          f"{len(resolved) - len(hides)} do not", file=sys.stderr)
    for c in cases:
        if c.subject is None:
            print(f"{c.beat_id}: {c.who} has no published dossier; kept as a leak case", file=sys.stderr)
    for r in hides:
        if r.party:
            print(f"{r.candidate.beat_id}: hidden from the party; no NPC case", file=sys.stderr)
        elif r.nobody:
            print(f"{r.candidate.beat_id}: about people no NPC agent plays; no NPC case", file=sys.stderr)
        elif r.unresolved:
            print(f"{r.candidate.beat_id}: hidden from someone the sentence does not name "
                  f"({r.candidate.before.strip()[-40:]!r}); rule who in --knowledge", file=sys.stderr)
    return 0


def _write(text: str, out: Path | None, sources: tuple[Path, ...]) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    _refuse_inside(out, sources)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, text)
    print(f"wrote {out}", file=sys.stderr)


def cmd_persona(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    for o in (args.out, args.report):
        if o is not None:
            _refuse_inside(Path(o), (summaries, npcs))
    d = chosen[0]
    entries = [c.item for c in presence.snapshots(presence.mentions(corpus, d, table))]
    sentences = persona.persona(entries, d, args.chapter)
    _write(persona.render_persona(sentences, d.subject, args.chapter), args.out, (summaries, npcs))
    if args.report is not None:
        _write(persona.render_persona_report(sentences, d.subject, args.chapter), args.report, (summaries, npcs))
    return 0


def cmd_leakcheck(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    if args.out is not None:
        _refuse_inside(Path(args.out), (summaries, npcs))
    d = chosen[0]
    texts = {}
    for label, path in (("answer", args.answer), ("given", args.given)):
        try:
            texts[label] = Path(path).read_text(encoding="utf-8")
        except OSError as e:
            raise Refusal(f"--{label} {path}: cannot read ({e.strerror})") from None
    if args.target_scene is not None and not re.fullmatch(r"\d{3}\.\d{2}", args.target_scene):
        raise Refusal(f"--target-scene {args.target_scene}: expected NNN.SS")
    cases = [c for c in knowledge.leak_cases(_knowledge(args, summaries, corpus), args.dossiers)
             if knowledge.names_dossier(c.who, d)]
    flags = leakcheck.check(texts["answer"], given=texts["given"], cases=cases, corpus=corpus,
                            chapter=args.chapter, target_scene=args.target_scene,
                            secret_terms=args.secret_term)
    _write(leakcheck.render_flags(flags), args.out, (summaries, npcs))
    return 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n\0\n" + user).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclasses.dataclass
class _Target:
    """Everything one target needs, built (and every refusal raised) before anything is written."""

    target: str
    freeze: int
    scene: corpus_mod.Item
    persona_md: str
    persona_report: str
    horizon_md: str
    situation_md: str
    system: str
    user: str
    sha: str
    empty_horizon: bool
    persona_sentences: int


def _prepare_target(args, summaries, corpus, d, ms, npc, eff, target: str) -> _Target:
    if not re.fullmatch(r"\d{3}\.\d{2}", target):
        raise Refusal(f"--target {target}: expected NNN.SS")
    scene = next((it for it in corpus.items() if it.item_id == target and it.kind == corpus_mod.SCENE), None)
    if scene is None:
        raise Refusal(f"--target {target}: not a scene in the summaries")
    answer = eff.get(target)
    if answer is None or answer[0] != rulings.PRESENT:
        raise Refusal(
            f"--target {target}: the presence rulings do not answer 'present' for {d.subject} here "
            f"(effective: {answer[0] if answer else 'unanswered'}); a backtest predicts what she does at "
            "an event she attended."
        )
    freeze = scene.chapter - 1
    h = _horizon(args, summaries, corpus, d, ms, npc, eff, freeze, for_agent=True)
    horizon_md = horizon_mod.render_horizon(h, for_agent=True, compact=args.compact_horizon)
    entries = [c.item for c in presence.snapshots(ms)]
    sentences = persona.persona(entries, d, freeze)
    persona_md = persona.render_persona(sentences, d.subject, freeze)
    situation_md = agent_mod.situation(corpus, target)
    system, user = agent_mod.build_prompt(d.subject, persona_md, horizon_md, situation_md)
    return _Target(target, freeze, scene, persona_md, persona.render_persona_report(sentences, d.subject, freeze),
                   horizon_md, situation_md, system, user, _sha(system, user),
                   not h.witnessed and h.snapshot is None, sum(1 for s in sentences if s.kept and s.chapter <= freeze))


def cmd_backtest(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    out_dir = Path(args.out_dir)
    _refuse_inside(out_dir, (summaries, npcs))
    d = chosen[0]
    ms = presence.mentions(corpus, d, table)
    npc, eff = _ruled(args, corpus, d, presence.events(ms))
    targets = list(dict.fromkeys(args.target))
    prepared = [_prepare_target(args, summaries, corpus, d, ms, npc, eff, t) for t in targets]
    resolved = _knowledge(args, summaries, corpus)
    cases = [c for c in knowledge.leak_cases(resolved, args.dossiers) if knowledge.names_dossier(c.who, d)]
    backend = agent_mod.backend_name(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_targets, answered_at = [], []
    for t in prepared:
        tdir = out_dir / t.target
        tdir.mkdir(parents=True, exist_ok=True)
        for name, text in (("persona.md", t.persona_md), ("persona.report.md", t.persona_report),
                           ("horizon.md", t.horizon_md), ("situation.md", t.situation_md),
                           ("prompt.system.md", t.system), ("prompt.user.md", t.user),
                           ("actual.md", t.scene.text + "\n")):
            atomic_write_text(tdir / name, text)
        prev = _read_json(tdir / "run.json")
        run = {"npc": d.subject, "target": t.target, "freeze_chapter": t.freeze, "model": args.model,
               "backend": backend, "prompt_sha256": t.sha, "dry_run": bool(args.dry_run), "written_at": _now(),
               "answer_prompt_sha256": prev.get("answer_prompt_sha256"), "answer_model": prev.get("answer_model"),
               "answer_backend": prev.get("answer_backend"), "answer_at": prev.get("answer_at"),
               "compact_horizon": bool(args.compact_horizon), "secret_terms": list(args.secret_term)}
        ans_path = tdir / "answer.md"
        reuse = (not args.force and ans_path.is_file() and run["answer_prompt_sha256"] == t.sha
                 and run["answer_model"] == args.model and run["answer_backend"] == backend)
        status = "dry run"
        if not args.dry_run:
            if reuse:
                status = "answer reused"
            else:
                atomic_write_text(ans_path, agent_mod.play(args, t.system, t.user).strip() + "\n")
                run.update(answer_prompt_sha256=t.sha, answer_model=args.model, answer_backend=backend, answer_at=_now())
                status = "answered"
        atomic_write_text(tdir / "run.json", json.dumps(run, indent=2) + "\n")
        if args.dry_run or not ans_path.is_file():
            print(f"{t.target}: {status}; persona {t.persona_sentences} sentence(s), "
                  f"horizon {'empty' if t.empty_horizon else 'not empty'}")
            continue
        answer = ans_path.read_text(encoding="utf-8")
        given = "\n\n".join((t.persona_md, t.horizon_md, t.situation_md))
        flags = leakcheck.check(answer, given=given, cases=cases, corpus=corpus, chapter=t.freeze, target_scene=t.target,
                                secret_terms=args.secret_term)
        atomic_write_text(tdir / "flags.md", leakcheck.render_flags(flags))
        atomic_write_text(tdir / "flags.json", json.dumps([dataclasses.asdict(f) for f in flags], indent=2) + "\n")
        answered_at.append(run["answer_at"] or run["written_at"])
        bundle_targets.append({
            "target": t.target, "freeze": t.freeze, "scene_title": t.scene.title or t.target,
            "situation": t.situation_md, "persona": t.persona_md, "horizon": t.horizon_md, "answer": answer,
            "flags": [{"kind": f.kind, "sentence": f.sentence, "detail": f.detail, "beat_id": f.beat_id,
                       "name": f.name, "future": f.future} for f in flags],
            "actual_beats": [[b.beat_id, b.text] for b in corpus_mod.beats(t.scene)],
        })
        print(f"{t.target}: {status}; persona {t.persona_sentences} sentence(s), "
              f"horizon {'empty' if t.empty_horizon else 'not empty'}; {len(flags)} flag(s)")
    if bundle_targets:
        run_id = max(answered_at).replace("-", "").replace(":", "")
        page = backtest_page.render({"version": backtest_page.BUNDLE_VERSION, "npc": d.subject, "run_id": run_id,
                                     "model": args.model, "targets": bundle_targets})
        atomic_write_text(out_dir / "backtest.html", page)
        print(f"wrote {out_dir / 'backtest.html'}")
    else:
        print("dry run: prompts written, no answers and no page")
    return 0


def _npc_forms(args) -> tuple[str, tuple[str, ...]]:
    summaries, npcs = _layout(args)
    try:
        d = dossier_mod.select(dossier_mod.read_dossiers(npcs), args.npc)[0]
    except dossier_mod.DossierError as e:
        raise Refusal(str(e)) from None
    return d.subject, tuple(dict.fromkeys((d.subject, *d.forms)))


def _passages(path: Path, forms, section: str | None) -> list[prep.Passage]:
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise Refusal(f"--prep {path}: cannot read ({e.strerror})") from None
    try:
        return prep.extract(text, forms, section or None, file=str(path))
    except prep.PrepError as e:
        raise Refusal(str(e)) from None


def _scene_titles(summaries: Path) -> dict[str, str]:
    c = corpus_mod.load_corpus(summaries)
    return {it.item_id: it.title for it in c.items() if it.kind == corpus_mod.SCENE and it.title}


def cmd_prep(args) -> int:
    summaries, npcs = _layout(args)
    subject, forms = _npc_forms(args)
    targets = list(args.target)
    if len(set(targets)) != len(targets):
        raise Refusal("--target given twice")
    if len(args.prep) != len(targets):
        raise Refusal(f"{len(targets)} --target but {len(args.prep)} --prep; give one --prep per --target")
    sections = list(args.section or [])
    if sections and len(sections) != len(targets):
        raise Refusal(f"{len(targets)} --target but {len(sections)} --section; give one per --target "
                      "(an empty \"\" for a target with none)")
    sections = sections or [""] * len(targets)
    out = Path(args.out)
    _refuse_inside(out, (summaries, npcs, *(Path(p).expanduser().resolve().parent for p in args.prep)))
    titles = _scene_titles(summaries)
    bundle_targets = []
    for t, pf, sec in zip(targets, args.prep, sections):
        ps = _passages(pf, forms, sec)
        bundle_targets.append({
            "target": t, "scene_title": titles.get(t, t), "source": Path(pf).name, "section": sec,
            "passages": [{"pid": p.pid, "line": p.line, "heading": list(p.heading), "text": p.text} for p in ps],
        })
        how = f"section {sec!r}" if sec else f"passages naming {subject}"
        print(f"{t}: {len(ps)} passage(s) ({how}) from {Path(pf).name}")
    page = prep_page.render({"version": prep_page.BUNDLE_VERSION, "npc": subject, "targets": bundle_targets})
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, page)
    print(f"wrote {out} ({len(page.encode('utf-8')) // 1024} KiB)")
    return 0


def cmd_prep_sheet(args) -> int:
    summaries, npcs = _layout(args)
    subject, forms = _npc_forms(args)
    target = args.target
    ps = _passages(args.prep, forms, args.section)
    try:
        ruled = prep.load_rulings(args.rulings, subject, target, ps)
        text = prep.sheet(ps, ruled)
    except prep.PrepError as e:
        raise Refusal(str(e)) from None
    _write(text, args.out, (summaries, npcs, Path(args.prep).expanduser().resolve().parent))
    return 0


# ── replay (Prototype 4) and forward (Prototype 5) ──────────────────────────

_ANSWER_KEYS = ("answer_prompt_sha256", "answer_model", "answer_backend", "answer_at")


def _flag_dicts(flags) -> list[dict]:
    return [{"kind": f.kind, "sentence": f.sentence, "detail": f.detail, "beat_id": f.beat_id,
             "name": f.name, "future": f.future} for f in flags]


def _answered(args, ans_path: Path, prev: dict, sha: str, backend: str, system: str, user: str) -> tuple[str, dict]:
    """Answer one prompt, or reuse the answer for the same prompt, model and backend.

    Returns ``(status, entry)``; ``entry`` holds the ``answer_*`` fields for ``run.json``.
    """
    entry = {k: prev.get(k) for k in _ANSWER_KEYS}
    reuse = (not args.force and ans_path.is_file() and entry["answer_prompt_sha256"] == sha
             and entry["answer_model"] == args.model and entry["answer_backend"] == backend)
    if args.dry_run:
        return "dry run", entry
    if reuse:
        return "answer reused", entry
    atomic_write_text(ans_path, agent_mod.play(args, system, user).strip() + "\n")
    entry.update(answer_prompt_sha256=sha, answer_model=args.model, answer_backend=backend, answer_at=_now())
    return "answered", entry


def _prep_sheet(prep_file, section, prep_rulings, target, subject, forms) -> str:
    """The passages ruled hers for ``target``; refuses while any is unruled."""
    ps = _passages(prep_file, forms, section)
    try:
        ruled = prep.load_rulings(prep_rulings, subject, target, ps)
        return prep.sheet(ps, ruled)
    except prep.PrepError as e:
        raise Refusal(str(e)) from None


def _write_replay_page(out_dir: Path, npc: str, model: str) -> bool:
    """Rebuild ``replay.html`` from every ``bundle.json`` under ``out_dir``; False when there is nothing to show."""
    replay_b, forward_b, stamps = [], [], []
    for f in sorted([*out_dir.glob("*/bundle.json"), *out_dir.glob("*/free/bundle.json")]):
        b = _read_json(f)
        if b.get("kind") == "replay":
            replay_b.append(b)
        elif b.get("kind") == "forward":
            forward_b.append(b)
        else:
            continue
        stamps.append(b.get("answer_at") or "")
    if not stamps:
        return False
    for b in forward_b:
        b["doc_prefix"] = "" if len(forward_b) == 1 else f"{b['freeze']}-"
    run_id = max(stamps).replace("-", "").replace(":", "")
    page = replay_page.render({"version": replay_page.BUNDLE_VERSION, "npc": npc, "run_id": run_id, "model": model,
                               "replay": [{k: v for k, v in b.items() if k not in ("kind", "answer_at")} for b in replay_b],
                               "forward": [{k: v for k, v in b.items() if k not in ("kind", "answer_at")} for b in forward_b]})
    atomic_write_text(out_dir / "replay.html", page)
    print(f"wrote {out_dir / 'replay.html'}")
    return True


def _so_far(subject: str, done: list[turns.Turn], answers: list[str] | None = None) -> str:
    """The scene so far; ``answers`` (free mode) replaces each turn's real answer with the agent's."""
    if not done:
        return "(Nothing yet: this is the start of the scene.)"
    parts = []
    for i, t in enumerate(done):
        if t.prompt:
            parts.append(t.prompt)
        parts.append(f"{subject}: {t.actual if answers is None else answers[i]}")
    return "\n\n".join(parts)


def _print_split(target: str, ts: list[turns.Turn]) -> None:
    print(f"{target}: {len(ts)} turn(s)")
    for k, t in enumerate(ts, 1):
        p = t.prompt.replace("\n", " ")
        print(f"  {k:02d} prompt: {(p[:97] + '...') if len(p) > 100 else p or '(she acts first)'}")
        print(f"     actual beats: {', '.join(b.rsplit('.', 1)[-1] for b in t.beat_ids)}")


def cmd_replay(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    d = chosen[0]
    targets = list(dict.fromkeys(args.target))
    for t in targets:
        if not re.fullmatch(r"\d{3}\.\d{2}", t):
            raise Refusal(f"--target {t}: expected NNN.SS")
    scenes = {}
    for t in targets:
        scenes[t] = next((it for it in corpus.items() if it.item_id == t and it.kind == corpus_mod.SCENE), None)
        if scenes[t] is None:
            raise Refusal(f"--target {t}: not a scene in the summaries")
    splits = {t: turns.split_turns(scenes[t], d) for t in targets}
    for t in targets:
        if not splits[t]:
            raise Refusal(f"--target {t}: no sentence of the scene has {d.subject} as its subject; nothing to replay")
    if args.turns_only:
        for t in targets:
            _print_split(t, splits[t])
        return 0
    if args.rulings is None:
        raise Refusal("--rulings is required (only --turns-only runs without it)")
    if not args.out_dir:
        raise Refusal("--out-dir is required")
    sources = [summaries, npcs] + [Path(p).expanduser().resolve().parent for p in args.prep]
    out_dir = Path(args.out_dir)
    _refuse_inside(out_dir, tuple(sources))
    if len(args.prep) != len(targets):
        raise Refusal(f"{len(targets)} --target but {len(args.prep)} --prep; give one --prep per --target")
    sections = list(args.section or [])
    if sections and len(sections) != len(targets):
        raise Refusal(f"{len(targets)} --target but {len(sections)} --section; give one per --target "
                      "(an empty \"\" for a target with none)")
    sections = sections or [""] * len(targets)
    pr = list(args.prep_rulings or [])
    if len(pr) == 1:
        pr = pr * len(targets)
    if len(pr) != len(targets):
        raise Refusal("give --prep-rulings once, or once per --target")
    ms = presence.mentions(corpus, d, table)
    npc, eff = _ruled(args, corpus, d, presence.events(ms))
    subject, forms = d.subject, tuple(dict.fromkeys((d.subject, *d.forms)))
    prepared = []
    for t, pf, sec, pj in zip(targets, args.prep, sections, pr):
        answer = eff.get(t)
        if answer is None or answer[0] != rulings.PRESENT:
            raise Refusal(
                f"--target {t}: the presence rulings do not answer 'present' for {subject} here "
                f"(effective: {answer[0] if answer else 'unanswered'}); a replay predicts what she does at "
                "an event she attended."
            )
        scene = scenes[t]
        freeze = scene.chapter - 1
        h = _horizon(args, summaries, corpus, d, ms, npc, eff, freeze, for_agent=True)
        horizon_md = horizon_mod.render_horizon(h, for_agent=True, compact=args.compact_horizon)
        sentences = persona.persona([c.item for c in presence.snapshots(ms)], d, freeze)
        persona_md = persona.render_persona(sentences, subject, freeze)
        situation_md = agent_mod.situation(corpus, t)
        sheet_md = _prep_sheet(pf, sec, pj, t, subject, forms)
        def build(k, answers=None, *, t=t, persona_md=persona_md, horizon_md=horizon_md, sheet_md=sheet_md,
                  situation_md=situation_md):
            turn = splits[t][k]
            system, user = agent_mod.build_turn_prompt(
                subject, persona_md, horizon_md, sheet_md, situation_md,
                _so_far(subject, splits[t][:k], answers), turn.prompt or "(Nothing is put to you: the moment is yours.)")
            return turn, system, user, _sha(system, user)
        prepared.append((t, scene, freeze, situation_md, build))
    resolved = _knowledge(args, summaries, corpus)
    cases = [c for c in knowledge.leak_cases(resolved, args.dossiers) if knowledge.names_dossier(c.who, d)]
    backend = agent_mod.backend_name(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    any_answer = False
    mode = "free" if args.free else "teacher_forced"
    for t, scene, freeze, situation_md, build in prepared:
        tdir = out_dir / t / "free" if args.free else out_dir / t
        (tdir / "turns").mkdir(parents=True, exist_ok=True)
        n_turns = len(splits[t])
        fixed = None if args.free else [build(k) for k in range(n_turns)]
        atomic_write_text(tdir / "prompt.system.md", (fixed[0] if fixed else build(0))[1])
        prev_turns = _read_json(tdir / "run.json").get("turns") or {}
        run = {"npc": subject, "target": t, "mode": mode, "freeze_chapter": freeze, "model": args.model,
               "backend": backend, "dry_run": bool(args.dry_run), "written_at": _now(),
               "compact_horizon": bool(args.compact_horizon), "secret_terms": list(args.secret_term), "turns": {}}
        page_turns, stamps, own = [], [], []
        for n in range(1, n_turns + 1):
            if fixed:
                turn, system, user, sha = fixed[n - 1]
            else:  # free: she sees her own earlier answers; before one exists (dry run) the slot says so
                turn, system, user, sha = build(n - 1, own)
            nn = f"{n:02d}"
            ndir = tdir / "turns" / nn
            ndir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(ndir / "prompt.user.md", user)
            atomic_write_text(ndir / "actual.md", turn.actual + "\n")
            status, entry = _answered(args, ndir / "answer.md", prev_turns.get(nn) or {}, sha, backend, system, user)
            run["turns"][nn] = {"prompt_sha256": sha, "beat_ids": list(turn.beat_ids), **entry}
            if args.dry_run or not (ndir / "answer.md").is_file():
                print(f"{t} turn {nn}: {status}")
                if args.free:
                    own.append(((ndir / "answer.md").read_text(encoding="utf-8").strip() if (ndir / "answer.md").is_file()
                                else "(not yet answered: dry run)"))
                continue
            answer = (ndir / "answer.md").read_text(encoding="utf-8")
            own.append(answer.strip())
            flags = leakcheck.check(answer, given=user, cases=cases, corpus=corpus, chapter=freeze, target_scene=t,
                                   secret_terms=args.secret_term)
            atomic_write_text(ndir / "flags.json", json.dumps(_flag_dicts(flags), indent=2) + "\n")
            stamps.append(entry["answer_at"] or run["written_at"])
            page_turns.append({"n": n, "prompt": turn.prompt, "actual": turn.actual, "answer": answer, "sha": sha,
                               "beat_ids": list(turn.beat_ids), "flags": _flag_dicts(flags)})
            print(f"{t} turn {nn}: {status}; {len(flags)} flag(s)")
        atomic_write_text(tdir / "run.json", json.dumps(run, indent=2) + "\n")
        if page_turns and len(page_turns) == n_turns:
            any_answer = True
            atomic_write_text(tdir / "bundle.json", json.dumps({
                "kind": "replay", "mode": mode, "target": t, "freeze": freeze, "scene_title": scene.title or t, "situation": situation_md,
                "turns": page_turns, "answer_at": max(stamps)}, ensure_ascii=False) + "\n")
    if any_answer:
        _write_replay_page(out_dir, subject, args.model)
    else:
        print("dry run: prompts written, no answers and no page")
    return 0


def cmd_forward(args) -> int:
    summaries, npcs, corpus, chosen, table = _load(args)
    d = chosen[0]
    subject, forms = d.subject, tuple(dict.fromkeys((d.subject, *d.forms)))
    n = args.chapter
    if not re.fullmatch(r"\d{3}\.\d{2}", args.next):
        raise Refusal(f"--next {args.next}: expected NNN.SS")
    if not re.fullmatch(r"\d{3}\.\d{2}", args.prep_target):
        raise Refusal(f"--prep-target {args.prep_target}: expected NNN.SS")
    nxt = next((it for it in corpus.items() if it.item_id == args.next and it.kind == corpus_mod.SCENE), None)
    if nxt is None:
        raise Refusal(f"--next {args.next}: not a scene in the summaries")
    if nxt.chapter <= n:
        raise Refusal(f"--next {args.next}: is not after the freeze chapter {n}")
    sources = [summaries, npcs] + [Path(p).expanduser().resolve().parent for p in (args.prep, args.plan) if p]
    out_dir = Path(args.out_dir)
    _refuse_inside(out_dir, tuple(sources))
    ms = presence.mentions(corpus, d, table)
    npc, eff = _ruled(args, corpus, d, presence.events(ms))
    answer = eff.get(args.next)
    if answer is None or answer[0] != rulings.PRESENT:
        raise Refusal(f"--next {args.next}: the presence rulings do not answer 'present' for {subject} here "
                      f"(effective: {answer[0] if answer else 'unanswered'}); the comparison is a scene she attended.")
    h = _horizon(args, summaries, corpus, d, ms, npc, eff, n, for_agent=True)
    horizon_md = horizon_mod.render_horizon(h, for_agent=True, compact=args.compact_horizon)
    sentences = persona.persona([c.item for c in presence.snapshots(ms)], d, n)
    persona_md = persona.render_persona(sentences, subject, n)
    sheet_md = _prep_sheet(args.prep, args.section, args.prep_rulings, args.prep_target, subject, forms)
    attended = any(it.kind == corpus_mod.SCENE and it.chapter == n and (eff.get(it.item_id) or ("",))[0] == rulings.PRESENT
                   for it in corpus.items())
    standing_md = forward.standing(corpus, n, attended)
    system, user = agent_mod.build_forward_prompt(subject, persona_md, horizon_md, sheet_md, standing_md)
    sha = _sha(system, user)
    plan_md = ""
    if args.plan:
        ps = _passages(args.plan, forms, args.plan_section)
        body = prep.sheet(ps, {p.pid: prep.HERS for p in ps}, require_complete=False)
        plan_md = "# The GM's plan\n\n" + (body or "(No passages.)\n")
    resolved = _knowledge(args, summaries, corpus)
    cases = [c for c in knowledge.leak_cases(resolved, args.dossiers) if knowledge.names_dossier(c.who, d)]
    backend = agent_mod.backend_name(args)
    fdir = out_dir / f"forward-{n}"
    fdir.mkdir(parents=True, exist_ok=True)
    for name, text in (("prompt.system.md", system), ("prompt.user.md", user), ("actual.md", nxt.text + "\n")):
        atomic_write_text(fdir / name, text)
    if plan_md:
        atomic_write_text(fdir / "plan.md", plan_md)
    prev = _read_json(fdir / "run.json")
    run = {"npc": subject, "freeze_chapter": n, "next": args.next, "model": args.model, "backend": backend,
           "prompt_sha256": sha, "dry_run": bool(args.dry_run), "written_at": _now(),
           "compact_horizon": bool(args.compact_horizon), "secret_terms": list(args.secret_term)}
    raw_path = fdir / "answer.raw.md"
    status, entry = _answered(args, raw_path, prev, sha, backend, system, user)
    run.update(entry)
    if args.dry_run or not raw_path.is_file():
        atomic_write_text(fdir / "run.json", json.dumps(run, indent=2) + "\n")
        print(f"forward-{n}: {status}; prompts written, no answer and no page")
        return 0
    moves, parsed = forward.parse_moves(raw_path.read_text(encoding="utf-8"))
    run["parsed"] = parsed
    atomic_write_text(fdir / "run.json", json.dumps(run, indent=2) + "\n")
    atomic_write_text(fdir / "answer.json", json.dumps([dataclasses.asdict(m) for m in moves], indent=2, ensure_ascii=False) + "\n")
    page_moves, flag_rows = [], []
    for i, m in enumerate(moves):
        flags = _flag_dicts(leakcheck.check(f"{m.move} {m.why}".strip(), given=user, cases=cases, corpus=corpus, chapter=n,
                                                   secret_terms=args.secret_term))
        flag_rows.append({"index": i, "flags": flags})
        page_moves.append({"move": m.move, "why": m.why, "flags": flags})
    atomic_write_text(fdir / "flags.json", json.dumps(flag_rows, indent=2) + "\n")
    atomic_write_text(fdir / "bundle.json", json.dumps({
        "kind": "forward", "freeze": n, "next": args.next, "next_title": nxt.title or args.next, "actual": nxt.text,
        "plan": plan_md, "sha": sha, "parsed": parsed, "moves": page_moves,
        "answer_at": run["answer_at"] or run["written_at"]}, ensure_ascii=False) + "\n")
    print(f"forward-{n}: {status}; {len(moves)} move(s){'' if parsed else ' (reply was not JSON; kept raw)'}; "
          f"{sum(len(r['flags']) for r in flag_rows)} flag(s)")
    _write_replay_page(out_dir, subject, args.model)
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
                   help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    h.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    h.add_argument("--compact-horizon", action="store_true",
                    help="give a scene that does not name the NPC as a one-line recap, not in full")
    h.set_defaults(func=cmd_horizon)

    k = sub.add_parser("leaks", help="leak cases from the GM's knowledge rulings: who must not know what")
    _common(k)
    k.add_argument("--knowledge", type=Path, default=None,
                   help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    k.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    k.add_argument("--out", type=Path, default=None, help="default: stdout")
    k.set_defaults(func=cmd_leaks)

    pe = sub.add_parser("persona", help="who an NPC is as of a chapter: her own entries, cut to sentences about her")
    _common(pe)
    pe.add_argument("--npc", action="append", required=True)
    pe.add_argument("--chapter", type=int, required=True)
    pe.add_argument("--out", type=Path, default=None, help="default: stdout")
    pe.add_argument("--report", type=Path, default=None, help="every sentence, kept and dropped with its reason")
    pe.set_defaults(func=cmd_persona)

    lc = sub.add_parser("leakcheck", help="flag sentences of an agent's answer for the GM to confirm")
    _common(lc)
    lc.add_argument("--npc", action="append", required=True)
    lc.add_argument("--chapter", type=int, required=True)
    lc.add_argument("--answer", type=Path, required=True, help="the agent's answer")
    lc.add_argument("--given", type=Path, required=True, help="the exact text the agent was given")
    lc.add_argument("--knowledge", type=Path, default=None,
                    help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    lc.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    lc.add_argument("--target-scene", default=None, help="NNN.SS: cases up to and including this scene (default: the chapter)")
    lc.add_argument("--out", type=Path, default=None, help="default: stdout")
    lc.add_argument("--secret-term", action="append", default=[], metavar="TERM",
                    help="flag an answer sentence that gives away this term of the NPC's own secret (repeatable)")
    lc.set_defaults(func=cmd_leakcheck)
    bt = sub.add_parser("backtest", help="replay an NPC at scenes she attended, from the chapter before, and score it")
    _common(bt)
    bt.add_argument("--npc", action="append", required=True)
    bt.add_argument("--rulings", type=Path, required=True, help="the GM's presence ruling file")
    bt.add_argument("--knowledge", type=Path, default=None,
                    help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    bt.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    bt.add_argument("--target", action="append", required=True, help="NNN.SS, a scene she attended (repeatable)")
    bt.add_argument("--out-dir", type=Path, required=True)
    bt.add_argument("--dry-run", action="store_true", help="write the prompts and answer key; call no model")
    bt.add_argument("--force", action="store_true", help="ask the model again even if an answer for this prompt exists")
    agent_mod.add_model_args(bt)
    bt.add_argument("--compact-horizon", action="store_true",
                    help="give a scene that does not name the NPC as a one-line recap, not in full")
    bt.add_argument("--secret-term", action="append", default=[], metavar="TERM",
                    help="flag an answer sentence that gives away this term of the NPC's own secret (repeatable)")
    bt.set_defaults(func=cmd_backtest)

    pr = sub.add_parser("prep", help="write the prep sheet page: the GM marks each prep passage hers or GM only")
    _common(pr)
    pr.add_argument("--npc", action="append", required=True)
    pr.add_argument("--target", action="append", required=True, help="NNN.SS (repeatable, parallel to --prep)")
    pr.add_argument("--prep", action="append", type=Path, required=True, help="a prep markdown file, one per --target")
    pr.add_argument("--section", action="append", default=None,
                    help="heading-text prefix: every passage under it (\"\" for none: passages naming the NPC)")
    pr.add_argument("--out", type=Path, required=True, help="the HTML page to write")
    pr.set_defaults(func=cmd_prep)

    ps = sub.add_parser("prep-sheet", help="the passages ruled hers, as the agent sees them; refused while any is unruled")
    _common(ps)
    ps.add_argument("--npc", action="append", required=True)
    ps.add_argument("--target", required=True)
    ps.add_argument("--prep", type=Path, required=True)
    ps.add_argument("--section", default="")
    ps.add_argument("--rulings", type=Path, required=True, help="prep.json saved from the page")
    ps.add_argument("--out", type=Path, default=None, help="default: stdout")
    ps.set_defaults(func=cmd_prep_sheet)

    rp = sub.add_parser("replay", help="replay an NPC turn by turn at scenes she attended, with the real scene so far, and score it")
    _common(rp)
    rp.add_argument("--npc", action="append", required=True)
    rp.add_argument("--rulings", type=Path, default=None, help="the GM's presence ruling file (not needed with --turns-only)")
    rp.add_argument("--knowledge", type=Path, default=None,
                    help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    rp.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    rp.add_argument("--target", action="append", required=True, help="NNN.SS, a scene she attended (repeatable)")
    rp.add_argument("--prep", action="append", type=Path, default=[], help="a prep markdown file, one per --target")
    rp.add_argument("--section", action="append", default=None,
                    help="heading-text prefix for that --target's prep (\"\" for none: passages naming the NPC)")
    rp.add_argument("--prep-rulings", action="append", type=Path, default=None,
                    help="prep.json saved from the prep page (once, or once per --target)")
    rp.add_argument("--turns-only", action="store_true",
                    help="print each target's turn split and stop: no rulings, prep or model needed")
    rp.add_argument("--free", action="store_true",
                    help="free-running: she sees her own earlier answers, not the real ones (writes OUT/<target>/free/)")
    rp.add_argument("--out-dir", type=Path, default=None)
    rp.add_argument("--dry-run", action="store_true", help="write the prompts and answer key; call no model")
    rp.add_argument("--force", action="store_true", help="ask the model again even if an answer for this prompt exists")
    agent_mod.add_model_args(rp)
    rp.add_argument("--compact-horizon", action="store_true",
                    help="give a scene that does not name the NPC as a one-line recap, not in full")
    rp.add_argument("--secret-term", action="append", default=[], metavar="TERM",
                    help="flag an answer sentence that gives away this term of the NPC's own secret (repeatable)")
    rp.set_defaults(func=cmd_replay)

    fw = sub.add_parser("forward", help="ask what an NPC does between sessions, from the chapter she is frozen at")
    _common(fw)
    fw.add_argument("--npc", action="append", required=True)
    fw.add_argument("--rulings", type=Path, required=True, help="the GM's presence ruling file")
    fw.add_argument("--knowledge", type=Path, default=None,
                    help="the GM's who rulings, for beats whose sentence gives a description, not a name")
    fw.add_argument("--campaign", default=None, help="this campaign's name in --knowledge (default: --campaign-dir's name)")
    fw.add_argument("--chapter", type=int, required=True, help="the freeze: what she knows as of this chapter")
    fw.add_argument("--next", required=True, help="NNN.SS, her next attended scene: the comparison")
    fw.add_argument("--prep", type=Path, required=True, help="the prep file her private sheet comes from")
    fw.add_argument("--section", default="", help="heading-text prefix (\"\" for passages naming the NPC)")
    fw.add_argument("--prep-rulings", type=Path, required=True, help="prep.json saved from the prep page")
    fw.add_argument("--prep-target", required=True, help="NNN.SS: the target in prep.json the sheet is ruled under")
    fw.add_argument("--plan", type=Path, default=None, help="the GM's prep for the next session: shown on the page, never sent")
    fw.add_argument("--plan-section", default="", help="heading-text prefix for --plan (\"\" for passages naming the NPC)")
    fw.add_argument("--out-dir", type=Path, required=True)
    fw.add_argument("--dry-run", action="store_true", help="write the prompts and comparison; call no model")
    fw.add_argument("--force", action="store_true", help="ask the model again even if an answer for this prompt exists")
    agent_mod.add_model_args(fw)
    fw.add_argument("--compact-horizon", action="store_true",
                    help="give a scene that does not name the NPC as a one-line recap, not in full")
    fw.add_argument("--secret-term", action="append", default=[], metavar="TERM",
                    help="flag an answer sentence that gives away this term of the NPC's own secret (repeatable)")
    fw.set_defaults(func=cmd_forward)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("horizon", "persona", "leakcheck", "backtest", "prep", "prep-sheet", "replay", "forward") and len(args.npc) != 1:
        print(f"Error: {args.command} takes exactly one --npc", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except Refusal as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
