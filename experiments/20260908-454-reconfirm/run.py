"""Does the gap-marking contract still mark the accepted gaps, on THIS repo's prompt?

The 31 gaps in `experiments/20260907-phandalin-gm-gaps-confirm/` were produced by
a standalone nine-paragraph contract that exists only in that directory, and the
GM has read all 31 against their sources and accepted them. What was never
established is whether the contract survives contact with the prompt
CampaignGenerator actually ships — a prompt assembled from fragments, two of
which instructed exactly the absorption the contract forbids (#454).

Those fragments are now reconciled: the contradicting sentence is a
`{gm_attribution}` slot filled by mode. This run is the evidence for it.

ONE VARIABLE CHANGES. The user turn is the byte-identical frozen prompt from the
confirmation run — same scene material, same campaign style, same character
references, same POV plan, same prose example. Only the SYSTEM prompt differs:
`build_narrate_system(gap_marking=True)` in place of `prompts/system.md`. Model,
effort, backend and token ceiling are held at what was tested.

WHAT WOULD COUNT AS FAILING, and what would not:

- NOT failing: a different marker count, or shifted boundaries. The prompts have
  no common structure, so nothing about position transfers. The spec says so.
- Failing: a scene coming back with no markers at all while its source is full
  of GM turns; GM material silently written into a character's perception again;
  or the marking swallowing the players' dialogue.
- Reportable, individually: a gap the GM accepted that has vanished. Each is
  named rather than summarised — counts settle nothing on their own.

The bundle arm (`--bundle`) is the evidence the Q2 ruling does not have. Gap
marking was admitted to the all-scenes path on the strength of per-scene runs;
this is the only thing that can say whether marker discipline survives one
response carrying every scene.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
CONFIRM = ROOT.parent / "20260907-phandalin-gm-gaps-confirm"
SPEC = CG / "specs/028-gap-marking-contract"

sys.path.insert(0, str(CG))

MODEL = "claude-fable-5-1"
EFFORT = "medium"
EFFORT_SOURCE = "explicit"
BACKEND = "claude-code"
MAX_TOKENS = 32000
MARKER = "GM NARRATION — TO BE WRITTEN:"

ARMS = {
    "brewbarry": ("Brewbarry", "A Banker's Revelation"),
    "soma": ("Soma", "Arrival at the Spire"),
    "valphine": ("Valphine", "Bullying Through the Loan"),
    "vukradin": ("Vukradin", "The Universal Basic Treasure Proclamation"),
}


def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def json_text(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def save_new(path: Path, value) -> None:
    """Write, refusing to clobber. An attempt that already exists is evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode() if isinstance(value, str) else value
    with path.open("xb") as handle:
        handle.write(data)


def accepted() -> dict:
    return json.loads((SPEC / "accepted_gaps.json").read_text(encoding="utf-8"))


def system_prompt(arm: str) -> str:
    """The repo's own assembled prompt, with gap marking on.

    Genre and per-character examples are deliberately NOT passed here: the
    frozen user turn already carries the campaign style, the character
    references and the narrator's prose example. Passing them again would
    change two things at once and make a difference impossible to attribute.
    """
    from session_doc.narrate import build_narrate_system

    narrator, title = ARMS[arm]
    return build_narrate_system(
        examples_text=None,
        scene=title,
        prose_mode=False,
        narrator=narrator,
        gap_marking=True,
    )


def _markers(text: str) -> list[str]:
    return re.findall(r"^.*" + re.escape(MARKER) + r".*$", text, re.M)


def _classify(text: str) -> dict:
    """Marker count, and the dialogue/narration balance SC-004 asks about.

    A dialogue line CONTAINS a quotation mark — byte-for-byte the measure the
    confirmation run used (`run.py:317`), so the two are comparable. An earlier
    version required the line to *start* with one, which is stricter and made
    every ratio here read lower than the numbers it was being compared against.
    It is a balance check, not a quality one.
    """
    body_text = re.sub(r"^.*" + re.escape(MARKER) + r".*$", "", text, flags=re.M)
    body = [ln for ln in body_text.split("\n") if ln.strip() and not ln.startswith("#")]
    dialogue = sum(1 for ln in body if '"' in ln or "“" in ln)
    return {
        "words": len(text.split()),
        "marker_count": len(_markers(text)),
        "markers": _markers(text),
        "dialogue_lines": dialogue,
        "narration_lines": len(body) - dialogue,
    }


def _call(system: str, user: str) -> tuple[str, dict]:
    from campaignlib import call_api, make_client

    client = make_client(backend=BACKEND, model_override=MODEL,
                         claude_code_effort=EFFORT,
                         claude_code_effort_source=EFFORT_SOURCE)
    response = call_api(client, system, user, MODEL, max_tokens=MAX_TOKENS)
    identity = client.last_run_identity.as_dict()
    if (identity["model"] != MODEL
            or identity["claude_code_effort"] != EFFORT
            or not identity["claude_code_effort_override"]):
        raise ValueError(f"actual selection differs from what was tested: {identity}")
    return response, identity


def render(arm: str) -> None:
    target = ROOT / "per-scene" / arm
    if (target / "response.md").exists():
        raise ValueError(f"{arm}: an attempt already exists; preserve it")
    user = (CONFIRM / f"prompts/{arm}_user.md").read_text(encoding="utf-8")
    system = system_prompt(arm)
    started = datetime.now(timezone.utc)
    run = {
        "status": "running", "arm": arm, "mode": "per-scene",
        "started_at": started.isoformat(),
        "backend": BACKEND, "requested_model": MODEL,
        "requested_claude_code_effort": EFFORT,
        "system_prompt_source": "session_doc.narrate.build_narrate_system(gap_marking=True)",
        "system_prompt_sha256": sha(system),
        "user_prompt_sha256": sha(user),
        "user_prompt_from": str((CONFIRM / f"prompts/{arm}_user.md").relative_to(CG)),
        "generator_commit": subprocess.check_output(
            ["git", "-C", str(CG), "rev-parse", "HEAD"], text=True).strip(),
    }
    save_new(target / "system.md", system)
    try:
        response, identity = _call(system, user)
    except Exception as exc:
        run.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        (target / "run.json").write_text(json_text(run), encoding="utf-8")
        raise
    save_new(target / "response.md", response)
    run.update(status="rendered", actual_identity=identity,
               seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
               response_sha256=sha(response), **_classify(response))
    was = accepted()["arms"][arm]["count"]
    run["accepted_marker_count"] = was
    run["marker_delta"] = run["marker_count"] - was
    (target / "run.json").write_text(json_text(run), encoding="utf-8")
    print(json_text({k: run[k] for k in
                     ("arm", "status", "words", "marker_count",
                      "accepted_marker_count", "marker_delta",
                      "dialogue_lines", "narration_lines", "seconds")}))


def bundle() -> None:
    """All four scenes in one exchange — SC-009, the Q2 ruling's missing evidence."""
    from session_doc.narrate import NarrationScene, build_bundled_narrate_prompts

    target = ROOT / "bundle"
    if (target / "response.md").exists():
        raise ValueError("a bundle attempt already exists; preserve it")
    scenes = []
    for i, arm in enumerate(sorted(ARMS), start=1):
        narrator, title = ARMS[arm]
        scenes.append(NarrationScene(
            index=i, scene_name=title, narrator=narrator,
            focus=f"{narrator}'s scene.",
            moments=(CONFIRM / f"inputs/{arm}_source.md").read_text(encoding="utf-8"),
            source_path=CONFIRM / f"inputs/{arm}_source.md",
            source_kind="base", scene_events="", voice_note=None,
            character_examples=None, previous_narrator=None,
            previous_voice_sample=None, estimated_output_tokens=8000,
            output_path=target / f"{i:02d}.md", output_existed=False,
        ))
    system, user = build_bundled_narrate_prompts(scenes, gap_marking=True)
    started = datetime.now(timezone.utc)
    run = {"status": "running", "mode": "bundle", "scenes": sorted(ARMS),
           "started_at": started.isoformat(), "backend": BACKEND,
           "requested_model": MODEL, "requested_claude_code_effort": EFFORT,
           "system_prompt_sha256": sha(system), "user_prompt_sha256": sha(user)}
    save_new(target / "system.md", system)
    save_new(target / "user.md", user)
    try:
        response, identity = _call(system, user)
    except Exception as exc:
        run.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        (target / "run.json").write_text(json_text(run), encoding="utf-8")
        raise
    save_new(target / "response.md", response)
    run.update(status="rendered", actual_identity=identity,
               seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
               response_sha256=sha(response), **_classify(response))
    run["accepted_marker_count_total"] = accepted()["total"]
    (target / "run.json").write_text(json_text(run), encoding="utf-8")
    print(json_text({k: run[k] for k in
                     ("status", "words", "marker_count",
                      "accepted_marker_count_total", "dialogue_lines",
                      "narration_lines", "seconds")}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", choices=sorted(ARMS))
    ap.add_argument("--all", action="store_true", help="every per-scene arm, in order")
    ap.add_argument("--bundle", action="store_true")
    args = ap.parse_args()
    if args.bundle:
        bundle()
    elif args.all:
        for arm in sorted(ARMS):
            print(f"── {arm} ──", flush=True)
            render(arm)
    elif args.arm:
        render(args.arm)
    else:
        ap.error("choose --arm, --all or --bundle")


if __name__ == "__main__":
    main()
