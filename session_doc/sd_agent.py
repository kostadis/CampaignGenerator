#!/usr/bin/env python3
"""Stage-scoped orchestrator: generate, then check, then stop.

One action per stage instead of three invocations and the arguments each one
needs::

    sd_agent --stage summary   ->  enhance_summary -> sd_verify_quotes -> sd_consistency -> STOP
    sd_agent --stage scenes    ->  scene_extract   -> sd_verify_quotes                   -> STOP

**It stops at the stage boundary on purpose.** The post-session flow has a
human review point between Stage 1 and Stage 2 (`docs/cli/session_doc_pipeline.md`),
and an orchestrator that ran straight through would delete it — precisely the
"LLM output feeds the next LLM call with no human gate" shape Constitution
Principle II forbids. So this runs *one* stage's generation plus the checks that
apply to that stage's output, and hands back.

Nothing here is pipeline logic: every step is a subprocess of an existing CLI
(Principle VI). This module makes no `stream_api`/`call_api` call at all.

Flag forwarding is **enumerated, not passed through**. `ensemble_batch` grew
implicit forwarding and silently dropped `--similarity` for a month
(EnsembleGroundingInvestigation #197); the fix there was to make the hop
visible, so this starts visible — every resolved command is printed before it
runs, secret-free.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from campaignlib import add_backend_args

STAGES = ("summary", "scenes")


class Step:
    """One subprocess in a stage, with how its exit code should be read."""

    def __init__(self, key: str, label: str, cmd: list[str], *,
                 findings_exit: int | None = None):
        self.key = key
        self.label = label
        self.cmd = cmd
        # Exit code that means "ran fine, found things" rather than "broke".
        self.findings_exit = findings_exit
        self.rc: int | None = None

    @property
    def ran(self) -> bool:
        return self.rc is not None

    @property
    def found_things(self) -> bool:
        return self.findings_exit is not None and self.rc == self.findings_exit

    @property
    def broke(self) -> bool:
        return self.rc is not None and self.rc != 0 and not self.found_things


def _console(name: str) -> list[str]:
    """Invoke an installed console script, else fall back to `-m`.

    The console scripts only exist after `uv pip install -e .` into the venv
    that is running this. Falling back to `python -m` keeps the agent usable
    from a source checkout that has not been installed — which is the normal
    state of a fresh worktree.
    """
    found = shutil.which(name)
    if found:
        return [found]
    return [sys.executable, "-m", f"session_doc.{name}"]


def _registry_visible() -> bool:
    """Would scene_extract auto-discover an entity registry from here?

    It resolves `find_alias_registry(Path.cwd())` itself, and a registry
    REPLACES the dossier scan, so the answer decides whether an absent
    --dossier-dir is a real gap or a non-issue. Same CWD, since the child is
    spawned from ours.
    """
    try:
        from campaignlib.npc import find_alias_registry
        return find_alias_registry(Path.cwd()) is not None
    except Exception:
        # Never let a grounding *note* break the run it is annotating.
        return False


def _selection_args(args) -> list[str]:
    """Backend selection, forwarded to the GENERATION step only.

    Verification never gets these: it calls no model, and passing it a
    `--model` would imply a cost it cannot incur.
    """
    out: list[str] = []
    if args.backend:
        out += ["--backend", args.backend]
    if args.endpoint:
        out += ["--endpoint", args.endpoint]
    if args.model:
        out += ["--model", args.model]
    if args.fast:
        out += ["--fast"]
    if args.batch:
        out += ["--batch"]
    return out


def _verify_args(args, *, summary: Path | None, scenes: Path | None,
                 vtt: Path, out: Path) -> list[str]:
    cmd = _console("sd_verify_quotes") + ["--vtt", str(vtt)]
    if summary:
        cmd += ["--summary", str(summary)]
    if scenes:
        cmd += ["--scene-extractions", str(scenes)]
    cmd += ["--out", str(out), "--threshold", str(args.threshold)]
    if args.report_only:
        cmd += ["--report-only"]
    return cmd


def resolve_vtt(args) -> Path | None:
    """The transcript, resolved ONCE and shared by generation and verification.

    They must not disagree: verifying against a different .vtt than the one
    generation read reports edits that were never made. A session can carry
    both `*.transcript.vtt` and `*.cleaned.vtt`, and where they differ it is on
    proper nouns — exactly where spurious findings would cluster.
    """
    if args.vtt:
        return Path(args.vtt).expanduser()
    sd = Path(args.session_dir).expanduser()
    vtts = sorted(sd.glob("*.vtt"))
    return vtts[0] if vtts else None


def build_steps(args) -> tuple[list[Step], list[str]]:
    """Return (steps, notes). `notes` are things the human should be told."""
    sd = Path(args.session_dir).expanduser()
    notes: list[str] = []

    vtt = resolve_vtt(args)
    if vtt is None:
        raise ValueError(f"no .vtt found in {sd} — pass --vtt explicitly")
    if not vtt.exists():
        raise ValueError(f"transcript not found: {vtt}")

    if not args.vtt:
        candidates = sorted(sd.glob("*.vtt"))
        if len(candidates) > 1:
            # A session commonly carries both `*.transcript.vtt` and the
            # spell-passed `*.cleaned.vtt`, and alphabetical order picks
            # `cleaned` — a real choice, made silently. Where the two differ is
            # on proper nouns, which is exactly where a wrong pick would
            # manufacture findings, so say which one won.
            others = ", ".join(c.name for c in candidates if c != vtt)
            notes.append(
                f"{len(candidates)} .vtt files in the session dir; using "
                f"{vtt.name} (first alphabetically). Not used: {others}. "
                f"Pass --vtt to choose deliberately — it must be the transcript "
                f"the artifact was generated from."
            )

    summary = Path(args.summary).expanduser() if args.summary else sd / "session-summary.md"
    scenes = (Path(args.scene_extractions).expanduser() if args.scene_extractions
              else sd / "scene_extractions_new")
    narration = Path(args.narration_dir).expanduser() if args.narration_dir else sd / "narration"
    steps: list[Step] = []

    if args.stage == "summary":
        gm = Path(args.gmassist).expanduser() if args.gmassist else sd / "gm-assist.md"
        if not args.skip_generate:
            if not gm.exists():
                raise ValueError(f"gm-assist not found: {gm}")
            steps.append(Step(
                "generate", "generate      ",
                _console("enhance_summary") + [
                    str(vtt), "--gmassist", str(gm), "--output", str(summary),
                ] + _selection_args(args),
            ))
        steps.append(Step(
            "verify", "verify quotes ",
            _verify_args(args, summary=summary, scenes=None, vtt=vtt,
                         out=narration / "quote_report.md"),
            findings_exit=1,
        ))
        if args.context:
            steps.append(Step(
                "consistency", "consistency   ",
                _console("sd_consistency") + [str(summary)]
                + ["--context", *args.context]
                + ["--out", str(narration / "consistency_report.md")]
                + _selection_args(args),
            ))
        else:
            notes.append(
                "consistency check SKIPPED — no --context given. The grounding "
                "docs (campaign_state.md, world_state.md, party.md) are what it "
                "compares against, so without them there is nothing to check."
            )

    else:  # scenes
        if not args.skip_generate:
            if not summary.exists():
                raise ValueError(
                    f"session-summary not found: {summary} — run --stage summary first"
                )
            grounding: list[str] = []
            if args.dossier_dir:
                grounding += ["--dossier-dir", str(Path(args.dossier_dir).expanduser())]
            elif _registry_visible():
                # `docs/entity_registry.yaml` is auto-discovered from the CWD by
                # scene_extract and REPLACES the dossier scan outright, so the
                # roster already reaches the model. Saying "pass --dossier-dir"
                # here would be advice to add a flag the registry supersedes.
                notes.append(
                    "no --dossier-dir, but an entity registry is discoverable "
                    "from the CWD — scene_extract will use it, and it supersedes "
                    "a dossier scan. The roster reaches the model."
                )
            else:
                # No registry AND no dossiers. Post-D13 the roster reaches the
                # model ONLY through the system prompt — the VTT is never
                # rewritten any more — so this run has no way to learn that
                # "Blueberry" and "Brewbarry" are one NPC. Mis-set names then
                # surface as verification findings that look like fabrication
                # but are really missing grounding. Silent; say so.
                notes.append(
                    "no --dossier-dir and NO entity registry found from the CWD: "
                    "the canonical NPC roster will not reach the model. Since "
                    "6e00f54 the roster is the only channel for canonical "
                    "spellings (the VTT is deliberately never rewritten), so "
                    "expect name-shaped quote findings. Run from the campaign "
                    "root, or pass --dossier-dir."
                )
            if args.party:
                grounding += ["--party", str(Path(args.party).expanduser())]
            if args.gm_player:
                grounding += ["--gm-player", args.gm_player]
            steps.append(Step(
                "generate", "generate      ",
                _console("scene_extract") + [
                    str(vtt), "--summary", str(summary), "--output-dir", str(scenes),
                ] + grounding + _selection_args(args),
            ))
        steps.append(Step(
            "verify", "verify quotes ",
            _verify_args(args, summary=None, scenes=scenes, vtt=vtt,
                         out=narration / "quote_report_scenes.md"),
            findings_exit=1,
        ))
        # sd_consistency compares a *recap* against campaign grounding docs;
        # per-scene extraction files are not a recap, so it does not apply here.

    return steps, notes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run one extraction stage and its checks, then stop at the "
                    "stage boundary (the human review point).",
    )
    p.add_argument("--stage", choices=STAGES, required=True,
                   help="Which stage to run. 'summary' = enhance_summary; "
                        "'scenes' = scene_extract. Never both — the boundary "
                        "between them is a human checkpoint.")
    p.add_argument("--session-dir", required=True, metavar="DIR",
                   help="Session workspace; inputs and outputs resolve beneath it.")
    p.add_argument("--vtt", metavar="FILE",
                   help="Transcript (default: first *.vtt in the session dir). "
                        "Passed to BOTH generation and verification so they "
                        "cannot disagree about the source of truth.")
    p.add_argument("--gmassist", metavar="FILE", help="Stage 1 input (default: gm-assist.md).")
    p.add_argument("--summary", metavar="FILE", help="Default: <session-dir>/session-summary.md")
    p.add_argument("--scene-extractions", metavar="DIR",
                   help="Default: <session-dir>/scene_extractions_new")
    p.add_argument("--narration-dir", metavar="DIR",
                   help="Where reports are written (default: <session-dir>/narration).")
    p.add_argument("--dossier-dir", metavar="DIR",
                   help="NPC dossiers, forwarded to scene_extract (--stage scenes). "
                        "The canonical roster goes into the system prompt; since "
                        "6e00f54 that is the ONLY way the model learns canonical "
                        "spellings, so omitting it degrades extraction silently.")
    p.add_argument("--party", metavar="FILE",
                   help="party.md, forwarded to scene_extract (--stage scenes) for "
                        "player -> character speaker mapping.")
    p.add_argument("--gm-player", metavar="NAME",
                   help="GM's display name in the VTT, forwarded to scene_extract "
                        "(--stage scenes).")
    p.add_argument("--context", nargs="+", metavar="FILE",
                   help="Grounding docs for the consistency check. Omitted ⇒ "
                        "that step is skipped and the run says so.")
    p.add_argument("--threshold", type=float, default=0.85,
                   help="Forwarded to sd_verify_quotes (default: 0.85).")
    p.add_argument("--report-only", action="store_true",
                   help="Forwarded to sd_verify_quotes: report without annotating.")
    p.add_argument("--skip-generate", action="store_true",
                   help="Check an artifact that already exists — re-verify "
                        "without re-spending tokens.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the commands and exit. Nothing runs, nothing is spent.")
    p.add_argument("--model", default=None, help="Forwarded to the generation step only.")
    p.add_argument("--fast", action="store_true", help="Forwarded to the generation step only.")
    add_backend_args(p)
    return p


def main() -> int:
    args = build_parser().parse_args()

    try:
        steps, notes = build_steps(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(f"[sd_agent | stage: {args.stage} | {len(steps)} step(s)]")
    print("─" * 60)
    for i, s in enumerate(steps, 1):
        print(f"{'①②③④'[i - 1]} {s.label} {' '.join(s.cmd)}")
    print("─" * 60)
    for n in notes:
        print(f"  note: {n}")

    if args.dry_run:
        print("\nDry run — nothing executed, nothing spent.")
        return 0

    degraded: list[str] = []
    for i, s in enumerate(steps, 1):
        print(f"\n{'①②③④'[i - 1]} {s.label.strip()}")
        print("─" * 60)
        s.rc = subprocess.run(s.cmd).returncode

        if s.key == "generate" and s.rc != 0:
            # Checking an artifact that was never produced reports nonsense.
            print(f"\nError: generation failed (exit {s.rc}). Stopping — there "
                  f"is nothing to check.", file=sys.stderr)
            return 2
        if s.broke:
            # A check that could not run is not a check that passed.
            degraded.append(s.key)
            print(f"  warning: {s.key} could not run (exit {s.rc}) — continuing, "
                  f"but this run did NOT verify that.", file=sys.stderr)

    print("\n" + "─" * 60)
    for i, s in enumerate(steps, 1):
        if s.key == "generate":
            state = "ok" if s.rc == 0 else f"exit {s.rc}"
        elif s.found_things:
            state = "findings — see the report"
        elif s.rc == 0:
            state = "clean"
        else:
            state = f"COULD NOT RUN (exit {s.rc})"
        print(f"{'①②③④'[i - 1]} {s.label} {state}")

    for n in notes:
        print(f"\nnote: {n}")

    print("\nNothing was auto-corrected. Review the report(s), then apply fixes "
          "yourself.")
    if args.stage == "summary":
        print("This run STOPPED at the stage boundary — scene extraction is a "
              "separate step, gated on your review of the summary.")
    else:
        print("This run STOPPED at the stage boundary — narration is a separate "
              "step, gated on your review of the extractions.")

    if degraded:
        return 2
    return 1 if any(s.found_things for s in steps) else 0


if __name__ == "__main__":
    sys.exit(main())
