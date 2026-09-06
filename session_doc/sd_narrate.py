#!/usr/bin/env python3
"""Pass 5 — per-scene narration standalone CLI.

Reads plan.md (sd_plan output) + scene_extractions/ + per-character voice
files + style examples + party.md, and writes one narration file per scene
to ``--per-scene-output DIR``. Optional filters: ``--scene N [M …]`` to
re-narrate a subset, ``--narrator NAME`` to render only one character's
sections.

This is the Phase-4 split of what used to be Passes 4–5 inside session_doc.py.
See docs/design/SessionDocRefactor.md.

By default, narration remains sequential and ``--batch`` only changes provider
submission: each scene goes through ``run_single_batch`` as its own ordered
one-item batch. ``--batch-scenes`` is the separate, explicit content mode that
puts the selected scenes into one prompt and one model exchange; combining it
with provider ``--batch`` submits that single exchange as one batch item.
"""

import argparse
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_alias_normalizer,
    atomic_write_json,
    atomic_write_text,
    client_from_args,
    format_npc_roster,
    find_alias_registry,
    find_registry,
    load_alias_map,
    run_single_batch,
    stream_api,
)
from campaignlib.api.client import resolve_cli_model
from session_doc.examples import (
    examples_declaration_problems,
    get_char_examples,
    load_declared_examples,
    load_shared_examples,
    undeclared_files,
)
from session_doc.knowledge_check import find_unknown_names, format_warning
from session_doc.io import (
    extract_scene_text,
    load_scene_extractions,
    parse_plan,
    resolve_scene_extraction_file,
    scene_extraction_files,
)
from session_doc.narrate import (
    BundleSelection,
    NarrationScene,
    build_bundled_narrate_prompts,
    build_narrate_prompt,
    build_narrate_system,
    estimate_narration_tokens,
    split_bundled_narration,
)
from campaignlib.party_config import load_party_config_arg, require_from_config
from campaignlib.players_config import load_players_config_arg
from session_doc.roster import roster_from_config
from session_doc.voice import (
    extract_contrast_sample,
    get_voice_note,
    load_declared_voices,
    unknown_narrators,
    voice_declaration_problems,
)


@dataclass
class _SceneResult:
    label: str
    narration: str
    handoff: str


def _narration_output_path(output_dir: Path, index: int,
                           scene_name: str, narrator: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", (scene_name or narrator).lower()).strip("_")
    return output_dir / f"session_doc_scene_{index:02d}_{slug}.md"


def _format_narration_output(*, index: int, scene_name: str, narrator: str,
                             session_id: str, narration: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (scene_name or narrator).lower()).strip("_")
    return (
        "---\n"
        f"scene: {index:02d}\n"
        f"slug: {slug}\n"
        f"narrator: {narrator}\n"
        f"scene_name: {scene_name}\n"
        f"session: {session_id}\n"
        "---\n\n"
        f"{narration.strip()}\n"
    )


def _write_narration_output(path: Path, *, index: int, scene_name: str,
                            narrator: str, session_id: str,
                            narration: str) -> None:
    atomic_write_text(path, _format_narration_output(
        index=index, scene_name=scene_name, narrator=narrator,
        session_id=session_id, narration=narration,
    ))


def _report_scene(scene: NarrationScene, *, include_source: bool = True) -> dict:
    result = {
        "index": scene.index,
        "scene_name": scene.scene_name,
        "narrator": scene.narrator,
        "output_path": str(scene.output_path.resolve()),
    }
    if include_source:
        result.update({
            "source_path": str(scene.source_path.resolve()),
            "source_kind": scene.source_kind,
            "output_existed": scene.output_existed,
        })
    return result


def _write_bundle_report(path: Path, *, status: str, exit_code: int,
                         backend: str, model: str | None,
                         selection: BundleSelection | None,
                         exchange_count: int,
                         written: list[NarrationScene],
                         missing: list[dict] | None = None,
                         rejected: list[dict] | None = None,
                         message: str = "",
                         provider_batch: bool = False,
                         bundle_ceiling: int = 0) -> None:
    scenes = selection.scenes if selection is not None else ()
    run_id = path.stem if path.name != "sd_narrate_bundle_latest.json" else uuid.uuid4().hex
    payload = {
        "version": 1,
        "run_id": run_id,
        "mode": "bundle",
        "status": status,
        "exit_code": exit_code,
        "backend": backend,
        "model": model,
        "provider_batch": (selection.provider_batch if selection is not None
                           else provider_batch),
        "exchange_count": exchange_count,
        "projected_output_tokens": (selection.projected_output_tokens
                                    if selection is not None else 0),
        "bundle_ceiling": (selection.bundle_ceiling if selection is not None
                           else bundle_ceiling),
        "requested": [_report_scene(s) for s in scenes],
        "replaced": [_report_scene(s) for s in scenes if s.output_existed],
        "written": [_report_scene(s, include_source=False) for s in written],
        "missing": missing or [],
        "rejected": rejected or [],
        "message": message,
        "report_path": str(path.resolve()),
    }
    atomic_write_json(path, payload)


def _load_genre_file(path: str | None) -> str | None:
    """Read the genre rulebook from disk, or warn loudly and return None.

    The file is the single source of truth (#276 fix 2): it is not mirrored
    into ``session_doc.yaml``, so a missing or empty file means Pass 5 runs
    with **no** genre directive at all. That is a big silent quality change —
    the rulebook is where the per-narrator bookkeeping caps and the banned-tic
    list live — so say so rather than proceeding quietly.
    """
    if not path:
        # The floor, restored by #303's review. Dropping the false alarm on a
        # null `narrate.genre` removed the last thing on any surface that
        # pointed at obelisk having no rulebook at all — the router omits the
        # flag when `paths.genre_file` is unset, and this function used to
        # return None in silence, so Pass 5 rendered with no register rules and
        # said nothing anywhere.
        #
        # A note, not a warning: "no rulebook configured and none on disk" is a
        # legitimate state. The louder case — configured nowhere while
        # `voice/_genre.md` sits right there — is #295's, and belongs where the
        # config can see the campaign directory.
        print("Note: no --narration-genre-file; Pass 5 will render with no "
              "genre directive (no register rules, no banned-tic list, no "
              "bookkeeping caps).", file=sys.stderr)
        return None
    p = Path(path).expanduser()
    if not p.is_file():
        print(f"Warning: --narration-genre-file {p} does not exist. Pass 5 will run "
              f"with NO genre directive — no register rules, no banned-tic list, no "
              f"bookkeeping caps.\n"
              f"  -> create the file, or drop the flag if that was intended.",
              file=sys.stderr)
        return None
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        print(f"Warning: --narration-genre-file {p} is empty. Pass 5 will run with NO "
              f"genre directive.", file=sys.stderr)
        return None
    return text


def _voice_dir_arg(path: str | None) -> Path | None:
    """Validate ``--voice-dir`` as a directory, or refuse the run.

    The directory is no longer how a narrator finds its voice spec — that is
    declared per character in ``party.yaml`` — but a **declared path that is
    not a directory is still a typo**, and a typo here used to be silent:
    ``Path.glob`` over a missing directory yields nothing rather than raising,
    so a renamed ``voice_dir`` produced exactly the same empty result as no
    flag at all (#300).

    What it is read for now is the orphan census: files sitting in the
    directory that no character declares, which is what a rename leaves behind.
    An empty directory is not fatal — ``new_workspace`` creates ``voice/``
    empty and ``PlatformConfigService.derive`` fills the setting in from its
    mere existence, so failing here would refuse Narrate on every fresh
    campaign over a path the tool chose.
    """
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_dir():
        print(f"Error: --voice-dir {p} is not a directory.\n"
              f"  -> fix the path, or drop the flag.", file=sys.stderr)
        sys.exit(1)
    return p


def _same_resolved_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _extraction_for_path(extractions: list[dict], path: Path) -> dict | None:
    for sx in extractions:
        if _same_resolved_path(sx["path"], path):
            return sx
    return None


def _die_exact_scene_file(message: str) -> None:
    print(f"Error: --scene-extraction-file {message}", file=sys.stderr)
    sys.exit(1)


def _load_exact_scene_extraction(
    raw_path: str,
    *,
    scene_index: int,
    scene_name: str,
    directory_extractions: list[dict],
) -> tuple[dict, bool]:
    """Validate and load a single-scene extraction override.

    The eligible file set and scene association stay delegated to
    ``session_doc.io``. This function only sequences the CLI refusals and
    returns the loader-parsed extraction for the exact file.
    """
    exact = Path(raw_path).expanduser()
    if not exact.exists():
        _die_exact_scene_file(f"{exact} does not exist.")
    if not exact.is_file():
        _die_exact_scene_file(f"{exact} is not a regular file.")
    try:
        exact.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _die_exact_scene_file(f"{exact} must be readable UTF-8 ({e}).")

    eligible = scene_extraction_files(exact.parent)
    if not any(_same_resolved_path(candidate, exact)
               for candidate in eligible.values()):
        _die_exact_scene_file(
            f"{exact} is not an eligible NN_*.md scene extraction under "
            "session_doc.io rules."
        )

    loaded = _extraction_for_path(directory_extractions, exact)
    loaded_from_directory = loaded is not None
    if loaded is None:
        loaded = _extraction_for_path(load_scene_extractions(exact.parent), exact)
    if loaded is None:
        _die_exact_scene_file(
            f"{exact} is not an eligible NN_*.md scene extraction under "
            "session_doc.io loader rules."
        )

    resolved = resolve_scene_extraction_file(exact.parent, scene_index, scene_name)
    if resolved is None or not _same_resolved_path(resolved, exact):
        identity = loaded.get("name") or exact.name
        _die_exact_scene_file(
            f"{exact} is not associated with selected scene {scene_index} "
            f"('{scene_name}') by exact scene identity or {scene_index:02d}_ "
            f"prefix; file identity is '{identity}'."
        )

    return loaded, loaded_from_directory


def _load_bundle_scene_overrides(
    raw_paths: list[str], selected: list[tuple[int, dict]],
) -> dict[int, dict]:
    """Resolve repeatable exact files to one selected full-plan scene each."""
    resolved: dict[int, dict] = {}
    for raw_path in raw_paths:
        exact = Path(raw_path).expanduser()
        if not exact.exists():
            raise ValueError(f"{exact} does not exist")
        if not exact.is_file():
            raise ValueError(f"{exact} is not a regular file")
        try:
            exact.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"{exact} must be readable UTF-8 ({exc})") from exc
        eligible = scene_extraction_files(exact.parent)
        if not any(_same_resolved_path(candidate, exact) for candidate in eligible.values()):
            raise ValueError(f"{exact} is not an eligible NN_*.md scene extraction")
        loaded = _extraction_for_path(load_scene_extractions(exact.parent), exact)
        if loaded is None:
            raise ValueError(f"{exact} is not loadable under session_doc.io rules")
        claims: list[int] = []
        for index, section in selected:
            candidate = resolve_scene_extraction_file(
                exact.parent, index, section.get("scene", "")
            )
            if candidate is not None and _same_resolved_path(candidate, exact):
                claims.append(index)
        if len(claims) != 1:
            raise ValueError(
                f"{exact} must reconcile to exactly one selected plan scene; "
                f"matched {claims or 'none'}"
            )
        index = claims[0]
        if index in resolved:
            raise ValueError(f"two --scene-extraction-file values claim scene {index}")
        resolved[index] = loaded
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render per-scene first-person narration from a plan + scene extractions."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Session recap (used to extract scene event text when the "
                             "scene file lacks an explicit summary).")
    parser.add_argument("--plan", required=True, metavar="FILE",
                        help="plan.md (sd_plan output).")
    parser.add_argument("--scene-extractions", required=True, metavar="DIR",
                        help="Directory of NN_*.md scene files (scene_extract output).")
    parser.add_argument("--scene-extraction-file", metavar="FILE", action="append",
                        help="Exact single-scene input override. Sequential mode accepts one "
                             "file with exactly one --scene N; bundled mode accepts "
                             "repeatable files reconciled to selected plan scenes.")
    parser.add_argument("--per-scene-output", required=True, metavar="DIR",
                        help="Where to write session_doc_scene_NN_<slug>.md files.")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — supplies the party document's narrative content "
                             "(voice cues, relationships) to the prompt. It is NOT read "
                             "for the roster (#265), so passing it without "
                             "--party-config is an error rather than a silent "
                             "party.md-sourced roster.")
    parser.add_argument("--party-config", metavar="FILE", default=None,
                        help="party.yaml (conventionally <campaign>/config/party.yaml). "
                             "REQUIRED: the roster comes from each character's D&D Beyond "
                             "sheet frontmatter (issue #265) and there is no party.md "
                             "fallback — a sheet without frontmatter is a hard error. Run "
                             "sheet_frontmatter --apply to add it.")
    parser.add_argument("--players-config", metavar="FILE", default=None,
                        help="players.yaml (conventionally "
                             "<campaign>/config/players.yaml). Supplies the "
                             "person's name for each character in the roster "
                             "block. Only players still at the table are named.")
    parser.add_argument("--voice-dir", metavar="DIR",
                        help="Directory holding the campaign's voice files. Read "
                             "ONLY to report files nothing declares — a "
                             "character's own voice file is named by its "
                             "'voice:' entry in party.yaml, never matched by "
                             "filename (feature 009).")
    parser.add_argument("--examples", metavar="DIR",
                        help="Directory holding the campaign's example files. "
                             "Read ONLY to report files nothing declares. A "
                             "character's examples come from its 'examples:' "
                             "entry and the campaign's 'shared_examples:' list, "
                             "both in party.yaml.")
    parser.add_argument("--narrator", metavar="NAME",
                        help="Render only this character's sections.")
    parser.add_argument("--scene", nargs="+", type=int, metavar="N",
                        help="Render only the listed scene number(s) (1-based).")
    parser.add_argument("--prose-mode", action="store_true",
                        help="Strip mechanical / GM framing from narration.")
    parser.add_argument("--narration-genre-file", default=None, metavar="PATH",
                        help="File holding the genre/register rulebook injected into "
                             "Pass 5 (conventionally <campaign>/voice/_genre.md). A "
                             "one-line directive or a full document both work; anything "
                             "longer than a short label is injected as its own delimited "
                             "block. Replaces --narration-genre, which took the text "
                             "inline and made session_doc.yaml a second copy of the file "
                             "(#276).")
    parser.add_argument("--reflections", action="store_true",
                        help="Inject campaign_state and world_state context into Pass 5 so "
                             "the narrator can draw on past events as memories.")
    parser.add_argument("--context", nargs="+", action="extend", metavar="FILE",
                        help="Campaign context files for --reflections.")
    parser.add_argument("--dossier-dir", default=None, metavar="DIR",
                        help="Per-NPC dossier files (planning --build-dossiers). "
                             "Aliases are normalised before Pass 5; a 'Known NPCs' roster "
                             "is seeded into the narrate prompt.")
    parser.add_argument("--alias-registry", default=None, metavar="PATH",
                        help="entity_registry.yaml, or a campaign dir holding "
                             "docs/entity_registry.yaml, to source canonical names from. "
                             "Default: auto-discover docs/entity_registry.yaml under CWD.")
    parser.add_argument("--known-lore", nargs="+", metavar="FILE",
                        help="Documents the whole party is assumed to know — normally the "
                             "campaign bible, or docs/chapters/*.md up to the chapter "
                             "BEFORE this session. Enables a post-narration warning for "
                             "names that appear neither there nor in this session's scene "
                             "extractions (#223 A.3). Warning only; nothing is rewritten.")
    parser.add_argument("--no-alias-normalize", "--no-alias-normalise",
                        dest="no_alias_normalize", action="store_true",
                        help="Do not rewrite aliases to canonical names in the source text. "
                             "The 'Known NPCs' roster still reaches the prompt, so canonical "
                             "spellings remain available to the model as knowledge.")
    parser.add_argument("--narrate-tokens", type=int, default=16000, metavar="N",
                        help="Per-scene output token cap. Override per-scene with "
                             "'tokens: N' as the first line of the scene file.")
    batch_scene_group = parser.add_mutually_exclusive_group()
    batch_scene_group.add_argument(
        "--batch-scenes", dest="batch_scenes", action="store_true",
        help="Generate the explicitly selected scenes together in one model exchange.",
    )
    batch_scene_group.add_argument(
        "--no-batch-scenes", dest="batch_scenes", action="store_false",
        help="Use the established sequential per-scene generation path.",
    )
    parser.set_defaults(batch_scenes=False)
    parser.add_argument(
        "--batch-max-tokens", type=int, default=32000, metavar="N",
        help="Total output-token ceiling for one --batch-scenes exchange.",
    )
    parser.add_argument(
        "--run-report", metavar="FILE",
        help="Bundle outcome JSON (default: OUTPUT/logs/sd_narrate_bundle_latest.json).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Build prompts but skip the API call.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--model", default=None)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku (~4x cheaper, faster).")
    args = parser.parse_args()

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"

    try:
        model_intent = resolve_cli_model(args, legacy_default=DEFAULT_MODEL)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    effective_model = model_intent.effective_model
    args.model = effective_model

    per_scene_output_dir = Path(args.per_scene_output).expanduser()
    report_path: Path | None = None
    if args.batch_scenes:
        report_path = (
            Path(args.run_report).expanduser() if args.run_report
            else per_scene_output_dir / "logs" / "sd_narrate_bundle_latest.json"
        )
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            if report_path.exists() and not report_path.is_file():
                raise OSError("destination exists and is not a regular file")
        except OSError as exc:
            print(f"Error: cannot initialize --run-report {report_path}: {exc}",
                  file=sys.stderr)
            sys.exit(1)

    def refuse_bundle(code: str, message: str) -> None:
        """Persist a zero-call bundle refusal once its report path is known."""
        print(f"Error: {message}", file=sys.stderr)
        assert report_path is not None
        _write_bundle_report(
            report_path, status="refused", exit_code=1,
            backend=model_intent.backend, model=effective_model,
            selection=None, exchange_count=0, written=[],
            rejected=[{"code": code, "message": message}], message=message,
            provider_batch=bool(args.batch),
            bundle_ceiling=max(args.batch_max_tokens, 0),
        )
        sys.exit(1)

    # ── Inputs ──
    recap_path = Path(args.recap).expanduser()
    try:
        recap = recap_path.read_text(encoding="utf-8") if recap_path.exists() else ""
    except (OSError, UnicodeError) as exc:
        if args.batch_scenes:
            refuse_bundle("RECAP_UNREADABLE", f"cannot read recap {recap_path}: {exc}")
        raise
    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        if args.batch_scenes:
            refuse_bundle("PLAN_NOT_FOUND",
                          f"--plan not found: {plan_path} (run sd_plan first)")
        print(f"Error: --plan not found: {plan_path} (run sd_plan first)",
              file=sys.stderr)
        sys.exit(1)
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        if args.batch_scenes:
            refuse_bundle("PLAN_UNREADABLE", f"cannot read --plan {plan_path}: {exc}")
        raise

    sx_dir = Path(args.scene_extractions).expanduser()
    if not sx_dir.is_dir():
        if args.batch_scenes:
            refuse_bundle("SOURCE_DIRECTORY_NOT_FOUND",
                          f"--scene-extractions not found: {sx_dir}")
        print(f"Error: --scene-extractions not found: {sx_dir}", file=sys.stderr)
        sys.exit(1)
    try:
        scene_extractions = load_scene_extractions(sx_dir)
    except (OSError, UnicodeError) as exc:
        if args.batch_scenes:
            refuse_bundle(
                "SOURCE_UNREADABLE",
                f"cannot read scene extractions from {sx_dir}: {exc}",
            )
        raise
    if not scene_extractions and not args.scene_extraction_file:
        if args.batch_scenes:
            refuse_bundle("NO_SCENE_EXTRACTIONS", f"no NN_*.md files in {sx_dir}")
        print(f"Error: no NN_*.md files in {sx_dir}", file=sys.stderr)
        sys.exit(1)

    # A voice-smoothed layer next door is easy to produce and easy to forget to
    # point at; nothing downstream reveals which layer was narrated (#223, C).
    smoothed = sx_dir.parent / f"{sx_dir.name}_smoothed"
    exact_files = list(args.scene_extraction_file or [])
    exact_parent = (Path(exact_files[0]).expanduser().parent
                    if len(exact_files) == 1 else None)
    exact_file_selects_smoothed = (
        exact_parent is not None and _same_resolved_path(exact_parent, smoothed)
    )
    if (
        smoothed.is_dir()
        and smoothed.resolve() != sx_dir.resolve()
        and not exact_file_selects_smoothed
    ):
        print(f"Warning: {smoothed.name}/ exists alongside {sx_dir.name}/, but "
              f"--scene-extractions points at {sx_dir.name}/ — the voice-smoothed "
              f"extractions will NOT reach narration.\n"
              f"  -> pass --scene-extractions {smoothed} if that was the intent.",
              file=sys.stderr)

    try:
        per_scene_output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if args.batch_scenes:
            refuse_bundle(
                "OUTPUT_UNWRITABLE",
                f"cannot create narration output directory {per_scene_output_dir}: {exc}",
            )
        raise

    try:
        party = Path(args.party).expanduser().read_text(encoding="utf-8") if args.party else None
    except (OSError, UnicodeError) as exc:
        if args.batch_scenes:
            refuse_bundle("PARTY_UNREADABLE", f"cannot read --party {args.party}: {exc}")
        raise

    # The roster comes from each character's sheet frontmatter (#265). There is
    # no party.md fallback: --party still supplies the party document's
    # narrative content to the prompt, but not the "never contradict these"
    # class block, which must come from the sheets.
    #
    # Only required when a roster was actually asked for. Running with neither
    # flag is a legitimate mode that predates #265 — the class block is simply
    # absent — so deleting the fallback must not turn "no roster wanted" into
    # an error. Passing --party alone IS an error: it used to be a roster
    # source and is not read as one any more, and failing is how you find out.
    resolved_party_config = None
    players_config = load_players_config_arg(args.players_config)
    if args.batch_scenes and args.players_config and players_config is None:
        refuse_bundle(
            "PLAYERS_CONFIG_UNREADABLE",
            f"--players-config did not yield usable configuration: {args.players_config}",
        )
    if args.party_config or args.party:
        resolved_party_config = load_party_config_arg(args.party_config)
        if args.batch_scenes and resolved_party_config is None:
            refuse_bundle(
                "PARTY_CONFIG_UNREADABLE",
                "bundled narration requires a usable --party-config when party "
                "information is requested",
            )
        try:
            roster = require_from_config(
                roster_from_config(resolved_party_config, players_config)
                if resolved_party_config else None,
                what="character roster",
                party_config_arg=args.party_config,
            )
        except SystemExit:
            if args.batch_scenes:
                refuse_bundle(
                    "ROSTER_UNAVAILABLE",
                    "cannot build the character roster from the supplied configuration",
                )
            raise
    else:
        roster = ""
    narration_genre = _load_genre_file(args.narration_genre_file)

    # Voice specs and style examples come from the roster's DECLARATIONS, not
    # from scanning a directory and matching names (feature 009). A character
    # names its own files; the campaign names the shared ones. Both are paths,
    # so both fail loudly.
    voice_files: dict[str, str] = {}
    per_char_examples: dict[str, str] = {}
    examples_text: str | None = None
    if resolved_party_config is not None:
        try:
            voice_files = load_declared_voices(resolved_party_config)
            per_char_examples = load_declared_examples(resolved_party_config)
            examples_text = load_shared_examples(resolved_party_config)
        except (OSError, UnicodeError) as exc:
            if args.batch_scenes:
                refuse_bundle(
                    "NARRATOR_GUIDANCE_UNREADABLE",
                    f"cannot read declared narrator guidance: {exc}",
                )
            raise

    # The two directories are read for ONE thing now: reporting files nothing
    # declares. A declared path that is not a directory is still a typo, and a
    # typo here used to be silent (#300).
    if args.batch_scenes and args.voice_dir and not Path(args.voice_dir).expanduser().is_dir():
        refuse_bundle("VOICE_DIRECTORY_NOT_FOUND",
                      f"--voice-dir {Path(args.voice_dir).expanduser()} is not a directory")
    voice_dir = _voice_dir_arg(args.voice_dir)
    examples_dir: Path | None = None
    if args.examples:
        examples_dir = Path(args.examples).expanduser()
        if not examples_dir.is_dir():
            if args.batch_scenes:
                refuse_bundle("EXAMPLES_DIRECTORY_NOT_FOUND",
                              f"--examples {examples_dir} is not a directory")
            print(f"Error: --examples {examples_dir} is not a directory.\n"
                  f"  -> fix the path, or drop the flag.", file=sys.stderr)
            sys.exit(1)

    context_parts: list[str] = []
    if args.context:
        for c in args.context:
            cp = Path(c).expanduser()
            if not cp.is_file():
                if args.batch_scenes:
                    refuse_bundle("CONTEXT_NOT_FOUND", f"--context file not found: {cp}")
                continue
            try:
                context_parts.append(cp.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                if args.batch_scenes:
                    refuse_bundle("CONTEXT_UNREADABLE",
                                  f"cannot read --context {cp}: {exc}")
                raise

    if args.alias_registry:
        given = Path(args.alias_registry).expanduser()
        registry_path = find_registry(given) if given.is_dir() else given
        if registry_path is None or not registry_path.is_file():
            if args.batch_scenes:
                refuse_bundle("ALIAS_REGISTRY_NOT_FOUND",
                              f"--alias-registry not found: {args.alias_registry}")
            print(f"Error: --alias-registry not found: {args.alias_registry}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Entity registry: {registry_path} (--alias-registry)", file=sys.stderr)
    else:
        registry_path = find_alias_registry(Path.cwd())

    try:
        alias_map = load_alias_map(args.dossier_dir, registry_path=registry_path)
    except (OSError, UnicodeError, ValueError) as exc:
        if args.batch_scenes:
            refuse_bundle("ALIASES_UNREADABLE", f"cannot load narrator aliases: {exc}")
        raise
    npc_roster = format_npc_roster(alias_map)

    # Snapshot the session's own source BEFORE alias normalisation. The check
    # below exists to catch names the PIPELINE introduced, so an alias the
    # normaliser just expanded must not get to vouch for itself: normalising
    # first would put "Aldus Hern" in the known set and hide the one finding
    # this is here to make (#223 A.3).
    session_source = "\n".join(
        f"{sx['moments']}\n{sx['summary']}\n{sx['body']}" for sx in scene_extractions
    )
    known_lore_texts: list[str] = []
    for k in (args.known_lore or []):
        kp = Path(k).expanduser()
        if kp.is_file():
            known_lore_texts.append(kp.read_text(encoding="utf-8"))
        else:
            print(f"Warning: --known-lore file not found: {kp}", file=sys.stderr)

    # Alias rewriting is scoped to prose: quoted and italic spans are a verbatim
    # record of what a person said at the table and are never edited here (#223).
    # The canonical names reach the model as knowledge via `npc_roster` instead —
    # the same channel scene_extract settled on in #231.
    if alias_map and not args.no_alias_normalize:
        normalize, _ = build_alias_normalizer(alias_map, preserve_quoted=True)
        recap = normalize(recap)
        for sx in scene_extractions:
            sx["moments"] = normalize(sx["moments"])
            sx["summary"] = normalize(sx["summary"])
            sx["body"]    = normalize(sx["body"])

    all_sections = parse_plan(plan_text, len(scene_extractions) or 1)
    if not all_sections:
        if args.batch_scenes:
            refuse_bundle("PLAN_EMPTY", "could not parse plan.md.")
        print("Error: could not parse plan.md.", file=sys.stderr)
        sys.exit(1)

    # plan-position lookup so single-scene re-runs still get the prev-narrator contrast
    plan_narrator_by_scene = {idx: s["narrator"] for idx, s in enumerate(all_sections, 1)}

    if args.batch_scenes:
        if args.narrator:
            refuse_bundle(
                "NARRATOR_FILTER",
                "--narrator cannot be combined with --batch-scenes; select "
                "stable full-plan indices with --scene, or omit --batch-scenes "
                "for sequential narrator filtering.",
            )
        if args.batch_max_tokens < 1:
            refuse_bundle("INVALID_CEILING", "--batch-max-tokens must be positive.")
        if args.scene and len(set(args.scene)) != len(args.scene):
            refuse_bundle("DUPLICATE_SELECTION",
                          "bundled scene selection contains duplicate indices.")
        if args.scene:
            bad = [n for n in args.scene if n < 1 or n > len(all_sections)]
            if bad:
                refuse_bundle(
                    "SELECTION_OUT_OF_RANGE",
                    f"scene number(s) out of range: {bad} "
                    f"(plan has {len(all_sections)})",
                )
            wanted_indices = set(args.scene)
        else:
            wanted_indices = set(range(1, len(all_sections) + 1))
        sections = [
            (i, section) for i, section in enumerate(all_sections, 1)
            if i in wanted_indices
        ]
        if not sections:
            refuse_bundle("EMPTY_SELECTION", "bundled narration selection is empty.")
    else:
        sections = list(all_sections)

    if args.narrator and not args.batch_scenes:
        wanted = args.narrator.strip().lower()
        sections = [s for s in sections if s["narrator"].lower() == wanted]
        if not sections:
            print(f"Error: narrator '{args.narrator}' not in plan.", file=sys.stderr)
            sys.exit(1)
    if not args.batch_scenes and len(exact_files) > 1:
        _die_exact_scene_file("may repeat only with --batch-scenes.")
    if not args.batch_scenes and exact_files and (
        not args.scene or len(args.scene) != 1 or args.scene[0] < 1
    ):
        _die_exact_scene_file(
            f"{Path(exact_files[0]).expanduser()} requires exactly "
            "one --scene N (positive, 1-based)."
        )
    if args.scene and not args.batch_scenes:
        total = len(sections)
        bad = [n for n in args.scene if n < 1 or n > total]
        if bad:
            if exact_files and not args.batch_scenes:
                _die_exact_scene_file(
                    f"{Path(exact_files[0]).expanduser()} requires "
                    f"exactly one --scene N in range; got {bad} (plan has {total})."
                )
            print(f"Error: scene number(s) out of range: {bad} (plan has {total})",
                  file=sys.stderr)
            sys.exit(1)
        sections = [(n, sections[n - 1]) for n in args.scene]
    elif not args.batch_scenes:
        sections = list(enumerate(sections, 1))

    exact_scene_input: tuple[int, dict] | None = None
    exact_scene_input_loaded_from_directory = False
    bundle_overrides: dict[int, dict] = {}
    if exact_files and not args.batch_scenes:
        selected_scene_index, selected_section = sections[0]
        exact_extraction, exact_scene_input_loaded_from_directory = (
            _load_exact_scene_extraction(
                exact_files[0],
                scene_index=selected_scene_index,
                scene_name=selected_section.get("scene", ""),
                directory_extractions=scene_extractions,
            )
        )
        exact_scene_input = (selected_scene_index, exact_extraction)

        # The source-knowledge check uses the pre-normalisation session text.
        # Directory-loaded overrides are already represented in the original
        # snapshot; exact files from another directory need to be added once.
        if not exact_scene_input_loaded_from_directory:
            session_source = "\n".join(
                part for part in [
                    session_source,
                    (
                        f"{exact_extraction['moments']}\n"
                        f"{exact_extraction['summary']}\n"
                        f"{exact_extraction['body']}"
                    ),
                ] if part
            )
            if alias_map and not args.no_alias_normalize:
                normalize, _ = build_alias_normalizer(alias_map, preserve_quoted=True)
                exact_extraction["moments"] = normalize(exact_extraction["moments"])
                exact_extraction["summary"] = normalize(exact_extraction["summary"])
                exact_extraction["body"]    = normalize(exact_extraction["body"])

    if args.batch_scenes and exact_files:
        try:
            bundle_overrides = _load_bundle_scene_overrides(exact_files, sections)
        except ValueError as exc:
            refuse_bundle("INVALID_SOURCE_OVERRIDE",
                          f"--scene-extraction-file {exc}")
        for index, override in list(bundle_overrides.items()):
            directory_copy = _extraction_for_path(scene_extractions, override["path"])
            if directory_copy is not None:
                bundle_overrides[index] = directory_copy
                continue
            session_source = "\n".join(part for part in (
                session_source,
                f"{override['moments']}\n{override['summary']}\n{override['body']}",
            ) if part)
            if alias_map and not args.no_alias_normalize:
                override["moments"] = normalize(override["moments"])
                override["summary"] = normalize(override["summary"])
                override["body"] = normalize(override["body"])

    # Pre-flight: every narrator about to be rendered must resolve to a voice
    # spec. Checked here — after --narrator/--scene filtering, before the first
    # API call — so a render either has all its specs or does not start (#300).
    # A per-narrator warning inside the loop fires once scenes 1..n-1 have
    # already been paid for and written, which makes the miss something you
    # discover in the output rather than something that stops you.
    #
    # What it checks changed with feature 009: a DECLARED path that is absent,
    # or a narrator the roster does not have. It used to check whether a name
    # matched a filename, which is how a renamed character kept resolving to
    # nothing and told nobody (campaigns#175).
    #
    # Gated on the roster declaring *something*. A campaign that declares no
    # voice or example files at all is rendering without them on purpose — the
    # mode `--voice-dir`-absent has always been — and refusing there would turn
    # "no specs wanted" into an error. The moment one character declares a
    # file, the others' silence becomes worth reporting.
    # Two independent gates, because a campaign may reasonably declare style
    # examples and no voice specs, or the reverse.
    declares_voice = resolved_party_config is not None and any(
        c.voice for c in resolved_party_config.characters
    )
    declares_examples = resolved_party_config is not None and (
        any(c.examples for c in resolved_party_config.characters)
        or bool(resolved_party_config.shared_examples)
    )
    declares_anything = declares_voice or declares_examples
    if declares_anything:
        narrators = [s["narrator"] for _i, s in sections]
        problems = unknown_narrators(resolved_party_config, narrators)
        if declares_voice:
            problems += voice_declaration_problems(resolved_party_config, narrators)
        if declares_examples:
            problems += examples_declaration_problems(resolved_party_config, narrators)
        if problems:
            print("Error: this render's narrators do not all have their "
                  "declared files:", file=sys.stderr)
            for line in problems:
                print(f"  - {line}", file=sys.stderr)
            print("  -> fix the 'voice:'/'examples:' entries in party.yaml, or "
                  "create the missing file(s).", file=sys.stderr)
            if args.batch_scenes:
                refuse_bundle(
                    "NARRATOR_GUIDANCE",
                    "this render's narrators do not all have their declared files: "
                    + "; ".join(problems),
                )
            sys.exit(1)

    # Report files nothing declares. Not fatal: an orphan reaches no narrator,
    # so it cannot corrupt a render — it is simply work that is not being used,
    # and the state a rename leaves behind. Under the rule this replaced, such
    # a file joined a GLOBAL block that went to EVERY narrator, which is the
    # #301 bleed; the detector built to catch that could not see a rename
    # (#315), and both are gone with the fall-through.
    if declares_anything:
        declared_voice = [c.voice for c in resolved_party_config.characters if c.voice]
        declared_ex = [c.examples for c in resolved_party_config.characters if c.examples]
        declared_ex += list(resolved_party_config.shared_examples)
        orphans = (undeclared_files(voice_dir, declared_voice)
                   + undeclared_files(examples_dir, declared_ex))
        if orphans:
            print("Note: these files are declared by nobody and reach no "
                  "narrator:", file=sys.stderr)
            for o in orphans:
                print(f"  - {o}", file=sys.stderr)
            print("  -> declare them in party.yaml ('voice:'/'examples:' on a "
                  "character, or 'shared_examples:'), or delete them.",
                  file=sys.stderr)

    if args.batch_scenes:
        prepared: list[NarrationScene] = []
        for i, section in sections:
            narrator = section["narrator"]
            scene_name = section.get("scene", "")
            match = bundle_overrides.get(i)
            if match is None:
                resolved_source = resolve_scene_extraction_file(sx_dir, i, scene_name)
                if resolved_source is not None:
                    match = _extraction_for_path(scene_extractions, resolved_source)
            if match is None:
                refuse_bundle(
                    "SOURCE_NOT_FOUND",
                    f"no exact scene extraction matches '{scene_name}' (scene {i}); "
                    "bundled narration made no model call.",
                )
            char_moments = match["moments"] or match["body"]
            scene_events = match["summary"] or (
                extract_scene_text(recap, scene_name) if scene_name and recap else ""
            )
            previous_narrator = plan_narrator_by_scene.get(i - 1)
            previous_voice_sample = None
            if previous_narrator and previous_narrator.lower() != narrator.lower():
                previous_examples = (
                    get_char_examples(per_char_examples, previous_narrator)
                    if per_char_examples else None
                )
                if previous_examples:
                    previous_voice_sample = extract_contrast_sample(previous_examples)
                else:
                    previous_narrator = None
            source_path = Path(match["path"])
            source_kind = "override" if i in bundle_overrides else "base"
            output_path = _narration_output_path(
                per_scene_output_dir, i, scene_name, narrator
            )
            prepared.append(NarrationScene(
                index=i,
                scene_name=scene_name,
                narrator=narrator,
                focus=section.get("focus", ""),
                source_path=source_path,
                source_kind=source_kind,
                scene_events=scene_events,
                moments=char_moments,
                voice_note=(get_voice_note(voice_files, narrator)
                            if voice_files else None),
                character_examples=(get_char_examples(per_char_examples, narrator)
                                    if per_char_examples else None),
                previous_narrator=previous_narrator,
                previous_voice_sample=previous_voice_sample,
                estimated_output_tokens=estimate_narration_tokens(char_moments),
                output_path=output_path,
                output_existed=output_path.exists(),
            ))

        selection = BundleSelection(
            scenes=tuple(prepared), bundle_ceiling=args.batch_max_tokens,
            provider_batch=bool(args.batch),
        )
        assert report_path is not None
        print(f"\n[sd_narrate | content mode: bundle | provider batch: "
              f"{'on' if args.batch else 'off'}]")
        print(f"  Requested: {len(prepared)} scenes in plan order")
        for scene in prepared:
            state = "REPLACE" if scene.output_existed else "NEW"
            print(f"  {scene.index:02d}  {scene.narrator} — {scene.scene_name}  "
                  f"{scene.source_kind}  {state}")
            print(f"      source: {scene.source_path}")
            print(f"      output: {scene.output_path}")
        print(f"  Projected output: {selection.projected_output_tokens:,} tokens / "
              f"{selection.bundle_ceiling:,} ceiling")
        print("  Model exchanges: 1")
        if selection.projected_output_tokens > selection.bundle_ceiling:
            message = (
                f"projected bundle output {selection.projected_output_tokens:,} exceeds "
                f"--batch-max-tokens {selection.bundle_ceiling:,}; raise the ceiling, "
                "select fewer --scene indices, or omit --batch-scenes for sequential narration"
            )
            print(f"Error: {message}", file=sys.stderr)
            _write_bundle_report(
                report_path, status="refused", exit_code=1,
                backend=model_intent.backend, model=effective_model,
                selection=selection, exchange_count=0, written=[],
                rejected=[{"code": "CAPACITY", "message": message}],
                message=message,
            )
            sys.exit(1)

        try:
            system_prompt, user_prompt = build_bundled_narrate_prompts(
                prepared,
                shared_examples=examples_text,
                party=party,
                roster=roster,
                npc_roster=npc_roster,
                context_docs=(context_parts
                              if args.reflections and context_parts else None),
                prose_mode=args.prose_mode,
                genre=narration_genre,
            )
        except Exception as exc:
            message = f"bundled narration prompt preflight failed: {exc}"
            _write_bundle_report(
                report_path, status="refused", exit_code=1,
                backend=model_intent.backend, model=effective_model,
                selection=selection, exchange_count=0, written=[],
                rejected=[{"code": "PROMPT", "message": message}],
                message=message,
            )
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)
        if args.dry_run:
            print("─" * 60)
            print(user_prompt[:1200] + ("...(truncated)" if len(user_prompt) > 1200 else ""))
            print("─" * 60)
            return

        try:
            client = client_from_args(args)
        except Exception as exc:
            message = f"bundled narration backend initialization failed: {exc}"
            _write_bundle_report(
                report_path, status="failed", exit_code=1,
                backend=model_intent.backend, model=effective_model,
                selection=selection, exchange_count=0, written=[],
                rejected=[{"code": "BACKEND", "message": message}],
                message=message,
            )
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)

        try:
            if args.batch:
                raw_response = run_single_batch(
                    client, system=system_prompt, user=user_prompt,
                    model=args.model, max_tokens=args.batch_max_tokens,
                )
            else:
                raw_response = stream_api(
                    client, system_prompt, user_prompt, args.model,
                    max_tokens=args.batch_max_tokens, verbose=args.verbose,
                    cache_system=True,
                )
        except Exception as exc:
            message = f"bundled narration backend failed: {exc}"
            _write_bundle_report(
                report_path, status="failed", exit_code=1,
                backend=model_intent.backend, model=effective_model,
                selection=selection, exchange_count=1, written=[],
                rejected=[{"code": "BACKEND", "message": message}],
                message=message,
            )
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)

        split = split_bundled_narration(raw_response, prepared)
        if split["failed"]:
            message = f"bundle response unreconcilable: {split['failure_reason']}: {split['failure_detail']}"
            _write_bundle_report(
                report_path, status="unreconcilable", exit_code=4,
                backend=model_intent.backend, model=effective_model,
                selection=selection, exchange_count=1, written=[],
                rejected=[{"code": split["failure_reason"],
                           "message": split["failure_detail"]}],
                message=message,
            )
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(4)

        prepared_by_index = {scene.index: scene for scene in prepared}
        written_scenes: list[NarrationScene] = []
        missing: list[dict] = []
        session_id = recap_path.parent.name
        for result in split["sections"]:
            scene = prepared_by_index[result["i"]]
            if result["status"] != "complete":
                missing.append({
                    "index": scene.index, "scene_name": scene.scene_name,
                    "narrator": scene.narrator, "reason": result["status"],
                })
                continue
            narration = result["body"].strip()
            if args.known_lore:
                warning = format_warning(
                    f"scene {scene.index} ({scene.narrator} — {scene.scene_name})",
                    find_unknown_names(narration, [*known_lore_texts, session_source]),
                )
                if warning:
                    print(warning, file=sys.stderr)
            try:
                _write_narration_output(
                    scene.output_path, index=scene.index,
                    scene_name=scene.scene_name, narrator=scene.narrator,
                    session_id=session_id, narration=narration,
                )
            except Exception as exc:
                message = f"failed writing scene {scene.index}: {exc}"
                _write_bundle_report(
                    report_path, status="failed", exit_code=1,
                    backend=model_intent.backend, model=effective_model,
                    selection=selection, exchange_count=1,
                    written=written_scenes,
                    rejected=[{"code": "WRITE", "message": message,
                               "index": scene.index, "path": str(scene.output_path)}],
                    message=message,
                )
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
            written_scenes.append(scene)
            print(f"  Wrote {scene.output_path.name}")

        partial = bool(missing)
        exit_code = 3 if partial else 0
        status = "partial" if partial else "success"
        message = f"Wrote {len(written_scenes)} of {len(prepared)} selected narration scenes."
        _write_bundle_report(
            report_path, status=status, exit_code=exit_code,
            backend=model_intent.backend, model=effective_model,
            selection=selection, exchange_count=1,
            written=written_scenes, missing=missing, message=message,
        )
        print(f"\n{message}")
        if missing:
            print("  Missing: " + ", ".join(
                f"{item['index']:02d} {item['scene_name']} ({item['reason']})"
                for item in missing
            ))
        print(f"  Run report: {report_path}")
        if partial:
            sys.exit(3)
        print("Run assemble to combine them into a single session document.")
        return

    if args.batch_max_tokens != 32000:
        print("Note: --batch-max-tokens is ignored without --batch-scenes.",
              file=sys.stderr)

    client = client_from_args(args)
    handoff = ""
    written: list[Path] = []

    for i, section in sections:
        narrator   = section["narrator"]
        focus      = section.get("focus", "")
        scene_name = section.get("scene", "")
        label      = f"{narrator} — {scene_name}" if scene_name else narrator

        # Find the matching scene file (case-insensitive name match, fallback to index).
        if exact_scene_input is not None and i == exact_scene_input[0]:
            match = exact_scene_input[1]
        else:
            match: dict | None = None
            sn = (scene_name or "").lower().strip()
            if sn:
                for sx in scene_extractions:
                    if sx["name"].lower().strip() == sn:
                        match = sx
                        break
            if match is None and 1 <= i <= len(scene_extractions):
                match = scene_extractions[i - 1]
        if match is None:
            print(f"Error: no scene extraction matches '{scene_name}' (scene {i}).",
                  file=sys.stderr)
            sys.exit(1)
        char_moments = match["moments"] or match["body"]
        scene_summary_override = match["summary"] or None

        # Voice / examples / contrast
        voice_note = get_voice_note(voice_files, narrator) if voice_files else None
        char_examples = (get_char_examples(per_char_examples, narrator)
                         if per_char_examples else None)
        prev_narrator = plan_narrator_by_scene.get(i - 1)
        prev_voice_sample = None
        if prev_narrator and prev_narrator.lower() != narrator.lower():
            prev_text = (get_char_examples(per_char_examples, prev_narrator)
                         if per_char_examples else None)
            if prev_text:
                prev_voice_sample = extract_contrast_sample(prev_text)
            else:
                prev_narrator = None

        # Scene scope text
        scene_events_str = scene_summary_override or ""
        if not scene_events_str and scene_name and recap:
            scene_events_str = extract_scene_text(recap, scene_name)
        narrate_context = (context_parts
                           if args.reflections and context_parts else None)

        # The global examples block reaches scene mode too. It used to be
        # dropped here (de12e2b, "keep the prompt lean — the style constraint
        # is already carried by voice notes and the handoff"), back when scene
        # mode capped narration at 3000 tokens. That rationale is stale: the
        # cap is 16000 now, and voice notes carry a *character's* voice, not
        # the campaign's house style. Suppressing it meant a non-character
        # example file was silently inert in the only mode the pipeline
        # actually runs — every plan section carries a `scene:` line.
        # Per-char examples and the voice spec still outrank it downstream
        # (see build_narrate_system's block order).
        narrate_system = build_narrate_system(
            examples_text,
            scene=scene_name or None,
            prose_mode=args.prose_mode,
            has_scene_events=bool(scene_events_str or narrate_context),
            scene_anchored=bool(scene_summary_override),
            narrator=narrator,
            char_examples=char_examples,
            voice_note=voice_note,
            genre=narration_genre,
        )
        narrate_prompt = build_narrate_prompt(
            narrator, focus, char_moments, party, handoff,
            roster,
            npc_roster=npc_roster,
            scene_text=scene_events_str or None,
            context_docs=narrate_context,
            prev_narrator=prev_narrator,
            prev_voice_sample=prev_voice_sample,
        )

        est = estimate_narration_tokens(char_moments)
        warn = (f"  ⚠ estimated {est} — add 'tokens: {est}' to override"
                if est > args.narrate_tokens else "")
        print(f"\n[sd_narrate scene {i}: {label}]"
              f"  ({len(char_moments):,} chars, est. ~{est}{warn})")

        if args.dry_run:
            print("─" * 60)
            print(narrate_prompt[:400] + ("...(truncated)" if len(narrate_prompt) > 400 else ""))
            print("─" * 60)
            continue

        print("─" * 60)
        if args.batch:
            # Order-dependent chain (handoff / prev_voice_sample) — never
            # grouped; one sequential one-item batch per scene (FR-006).
            try:
                narration = run_single_batch(
                    client, system=narrate_system, user=narrate_prompt,
                    model=args.model, max_tokens=args.narrate_tokens,
                )
            except RuntimeError as e:
                print(f"Error: batch item failed for scene {label}: {e}",
                      file=sys.stderr)
                sys.exit(1)
        else:
            narration = stream_api(client, narrate_system, narrate_prompt,
                                   args.model, max_tokens=args.narrate_tokens,
                                   verbose=args.verbose, cache_system=True)
        print("─" * 60)
        narration = narration.strip()
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

        if args.known_lore:
            warning = format_warning(
                f"scene {i} ({label})",
                find_unknown_names(narration, [*known_lore_texts, session_source]),
            )
            if warning:
                print(warning, file=sys.stderr)

        session_id = recap_path.parent.name
        per_scene_file = _narration_output_path(
            per_scene_output_dir, i, scene_name, narrator
        )
        _write_narration_output(
            per_scene_file, index=i, scene_name=scene_name,
            narrator=narrator, session_id=session_id, narration=narration,
        )
        written.append(per_scene_file)
        print(f"  Wrote {per_scene_file.name}")

    if not args.dry_run:
        print(f"\nWrote {len(written)} per-scene narration file(s) to {per_scene_output_dir}/")
        print("Run assemble to combine them into a single session document.")


if __name__ == "__main__":
    main()
