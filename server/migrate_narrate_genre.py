"""One-shot migration CLI — #276 fix 2, the genre rulebook becomes a file.

``narrate.genre`` in ``<campaign>/<config-dir>/session_doc.yaml`` used to hold
the *text* of the campaign's genre rulebook — a paste of ``voice/_genre.md``.
Two copies, no sync, no divergence check. The consequences were live:

* out-of-the-abyss' paste had lost **every newline** on the way into YAML
  (16,303 characters on one line), so the campaign with the largest rulebook
  got it delivered as a one-line ``GENRE:`` label (#276 fix 1, #249).
* Its paste had also drifted to 0.999 similarity against the file it came
  from — the same document, no longer the same bytes.
* The value is duplicated a *third* time into ``profiles[].knobs
  .narration_genre``, synced one way only (#220), so activating a profile
  could silently replace a hand-edit with a stale copy.

This CLI relocates the rulebook to ``paths.genre_file`` — a path, resolved the
same way ``voice_dir`` and ``party`` are — and deletes the pastes.

Usage::

    python -m server.migrate_narrate_genre --campaign-dir DIR [--config-dir config]
        [--genre-file voice/_genre.md] [--prefer-file | --prefer-yaml]
        [--drop-profile-genre]

``session_doc.yaml`` is read RAW via ``yaml.safe_load`` to recover the paste:
``NarrateKnobs`` no longer declares ``genre`` and strips it on typed load,
which is exactly the data this CLI exists to rescue. Mirrors
``server/migrate_ensemble_config.py``.

**Where it refuses.** When both copies exist and disagree, choosing which one
is canonical is a scope decision about campaign content, not a mechanical
merge — so the CLI stops and reports rather than picking. Pass ``--prefer-file``
(keep ``voice/_genre.md``, discard the paste) or ``--prefer-yaml`` (overwrite
the file with the paste) once you have looked at the difference. Same for a
profile whose genre text differs from the canonical rulebook: that profile
wanted a *different* rulebook and now needs its own file, which this CLI cannot
invent.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any

import yaml

from server.session_editor_config_service import SESSION_DOC_FILENAME
from server.session_editor_config_shared import (
    load_session_editor_config,
    save_session_editor_config,
)

DEFAULT_GENRE_FILE = "voice/_genre.md"

PROFILE_GENRE_KNOB = "narration_genre"
PROFILE_GENRE_FILE_KNOB = "narration_genre_file"


def _normalize(text: str) -> str:
    """Collapse whitespace so a flattened paste compares equal to its file.

    A paste that lost its newlines is the *same rulebook*, differently mangled
    — it must not be reported as a content conflict, or every flattened
    campaign would need a manual ruling it does not deserve.
    """
    return " ".join(text.split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _word_differences(file_text: str, paste: str, limit: int = 5) -> list[str]:
    """Report the differences as *word* runs, not lines.

    A line diff is useless here: the paste is typically flattened, so every
    line differs and the diff degenerates into "the whole document". What the
    GM actually needs is "these words are in one copy and not the other" —
    which is how you tell a dropped title (fine, keep the file) from a dropped
    rule (not fine, decide deliberately). Real case: out-of-the-abyss'
    0.9989 similarity was entirely the file's ``# ...`` H1 title.
    """
    a = _normalize(file_text).split(" ")
    b = _normalize(paste).split(" ")
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        if len(out) >= limit:
            out.append("  … (more differences not shown)")
            break
        only_file = " ".join(a[i1:i2])
        only_paste = " ".join(b[j1:j2])
        context = " ".join(a[max(0, i1 - 5):i1]) or " ".join(b[max(0, j1 - 5):j1])
        out.append(f"  after “…{context}”:")
        if only_file:
            out.append(f"    only in the file:  “{only_file[:200]}”")
        if only_paste:
            out.append(f"    only in the paste: “{only_paste[:200]}”")
    return out


def _load_raw(path: Path) -> dict[str, Any]:
    """Load ``session_doc.yaml`` as a plain dict, so ``narrate.genre`` survives."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _paste_from_raw(raw: dict[str, Any]) -> str:
    narrate = raw.get("narrate")
    if not isinstance(narrate, dict):
        return ""
    value = narrate.get("genre")
    return value.strip() if isinstance(value, str) else ""


def _profile_pastes(raw: dict[str, Any]) -> dict[str, str]:
    """profile name -> its ``narration_genre`` paste (only non-empty ones)."""
    out: dict[str, str] = {}
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        return out
    for entry in profiles:
        if not isinstance(entry, dict):
            continue
        knobs = entry.get("knobs")
        if not isinstance(knobs, dict):
            continue
        value = knobs.get(PROFILE_GENRE_KNOB)
        if isinstance(value, str) and value.strip():
            out[str(entry.get("name") or "<unnamed>")] = value.strip()
    return out


def _describe(text: str) -> str:
    return f"{len(text)} chars / {text.count(chr(10)) + 1 if text else 0} lines"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot migration: relocate the genre rulebook from "
            "narrate.genre (a pasted string) to paths.genre_file (a path)."
        )
    )
    parser.add_argument(
        "--campaign-dir", required=True, metavar="DIR",
        help="Campaign root directory (contains <config-dir>/session_doc.yaml)",
    )
    parser.add_argument(
        "--config-dir", default="config", metavar="DIR",
        help="Configuration subdirectory within campaign (default: 'config')",
    )
    parser.add_argument(
        "--genre-file", default=DEFAULT_GENRE_FILE, metavar="PATH",
        help=f"Rulebook path, relative to the campaign dir "
             f"(default: {DEFAULT_GENRE_FILE})",
    )
    parser.add_argument(
        "--prefer-file", action="store_true",
        help="On a content conflict, keep the file and discard the YAML paste.",
    )
    parser.add_argument(
        "--prefer-yaml", action="store_true",
        help="On a content conflict, overwrite the file with the YAML paste.",
    )
    parser.add_argument(
        "--drop-profile-genre", action="store_true",
        help="Discard a profile's divergent genre text instead of refusing. "
             "The profile then inherits the campaign rulebook.",
    )
    args = parser.parse_args(argv)

    if args.prefer_file and args.prefer_yaml:
        print("--prefer-file and --prefer-yaml are mutually exclusive.",
              file=sys.stderr)
        return 2

    campaign_dir = Path(args.campaign_dir).expanduser().resolve()
    config_dir_path = campaign_dir / args.config_dir
    session_doc_path = config_dir_path / SESSION_DOC_FILENAME
    genre_rel = args.genre_file
    genre_path = campaign_dir / genre_rel

    raw = _load_raw(session_doc_path)
    paste = _paste_from_raw(raw)
    profile_pastes = _profile_pastes(raw)
    file_text = (
        genre_path.read_text(encoding="utf-8").strip()
        if genre_path.is_file() else ""
    )
    already_pointed = ((raw.get("paths") or {}).get("genre_file")
                       if isinstance(raw.get("paths"), dict) else None)

    # ── Nothing pasted anywhere ──────────────────────────────────────────
    if not paste and not profile_pastes:
        if already_pointed:
            print(f"nothing to migrate — paths.genre_file is already set to "
                  f"{already_pointed}")
            return 0
        if not file_text:
            print(f"nothing to migrate — no narrate.genre in {session_doc_path}, "
                  f"and no rulebook at {genre_path}")
            return 0
        # The obviously-correct case: a rulebook exists but nothing points at it.
        cfg = load_session_editor_config(session_doc_path)
        cfg = cfg.model_copy(
            update={"paths": cfg.paths.model_copy(update={"genre_file": genre_rel})}
        )
        save_session_editor_config(session_doc_path, cfg)
        print("\n".join([
            "pointed the editor at the existing rulebook",
            f"  session_doc.yaml:  {session_doc_path}",
            f"  paths.genre_file:  {genre_rel}  ({_describe(file_text)})",
        ]))
        return 0

    # ── Decide which copy is canonical ───────────────────────────────────
    canonical: str
    write_file = False
    if paste and file_text:
        if _normalize(paste) == _normalize(file_text):
            canonical, source = file_text, "file (identical to the paste)"
        elif args.prefer_file:
            canonical, source = file_text, "file (--prefer-file)"
        elif args.prefer_yaml:
            canonical, source, write_file = paste, "YAML paste (--prefer-yaml)", True
        else:
            sim = _similarity(paste, file_text)
            print("\n".join([
                f"REFUSING to guess: narrate.genre and {genre_rel} disagree.",
                f"  narrate.genre:  {_describe(paste)}",
                f"  {genre_rel}:  {_describe(file_text)}",
                f"  similarity (whitespace-normalised): {sim:.4f}",
                "",
                "Which copy is the real rulebook is a content decision, not a merge.",
                "Look at the difference, then re-run with one of:",
                "  --prefer-file   keep the file, discard the YAML paste",
                "  --prefer-yaml   overwrite the file with the YAML paste",
                "",
                "What differs (words, not lines — the paste has no line structure):",
                *_word_differences(file_text, paste),
            ]), file=sys.stderr)
            return 1
    elif paste:
        canonical, source, write_file = paste, "YAML paste (no file existed)", True
    else:
        canonical, source = file_text, "file (only profiles carried a paste)"
        if not canonical:
            print(f"REFUSING: profiles carry genre text but there is no rulebook at "
                  f"{genre_path} and no narrate.genre to seed it from.",
                  file=sys.stderr)
            return 1

    # ── Profile divergence is its own ruling ─────────────────────────────
    divergent = {
        name: text for name, text in profile_pastes.items()
        if _normalize(text) != _normalize(canonical)
    }
    if divergent and not args.drop_profile_genre:
        print("\n".join([
            "REFUSING to guess: these profiles carry genre text that differs from "
            "the canonical rulebook.",
            *[f"  profile '{name}': {_describe(text)} "
              f"(similarity {_similarity(text, canonical):.4f})"
              for name, text in sorted(divergent.items())],
            "",
            "A profile holds a rulebook *path* now, so a profile that wanted a "
            "different rulebook needs its own file — which this CLI cannot write "
            "for you. Either:",
            f"  1. write it (e.g. voice/_genre_<profile>.md), re-run, then set that "
            f"profile's {PROFILE_GENRE_FILE_KNOB} knob by hand; or",
            "  2. re-run with --drop-profile-genre to discard the divergent text "
            "and let the profile inherit the campaign rulebook.",
        ]), file=sys.stderr)
        return 1

    # ── Write ────────────────────────────────────────────────────────────
    if write_file:
        if not canonical.count("\n") and len(canonical) > 200:
            print(f"  WARNING: the paste has no newlines and is {len(canonical)} "
                  f"characters — it was flattened before it reached YAML (#249). "
                  f"{genre_rel} will be written as one long line.\n"
                  f"    -> re-add the line structure by hand; the render is correct "
                  f"either way since #276 fix 1, but the file is meant to be read.",
                  file=sys.stderr)
        genre_path.parent.mkdir(parents=True, exist_ok=True)
        genre_path.write_text(canonical + "\n", encoding="utf-8")

    cfg = load_session_editor_config(session_doc_path)  # strips narrate.genre
    new_profiles = []
    for profile in cfg.profiles:
        knobs = dict(profile.knobs)
        if knobs.pop(PROFILE_GENRE_KNOB, None) is not None:
            knobs[PROFILE_GENRE_FILE_KNOB] = genre_rel
        new_profiles.append(profile.model_copy(update={"knobs": knobs}))
    cfg = cfg.model_copy(update={
        "paths": cfg.paths.model_copy(update={"genre_file": genre_rel}),
        "profiles": new_profiles,
    })
    save_session_editor_config(session_doc_path, cfg)

    lines = [
        "migrated the genre rulebook to a file",
        f"  session_doc.yaml:  {session_doc_path}",
        f"  canonical copy:    {source}",
        f"  rulebook:          {genre_path}  ({_describe(canonical)})"
        + ("  [written]" if write_file else "  [unchanged]"),
        f"  paths.genre_file:  {genre_rel}",
        f"  narrate.genre:     deleted ({_describe(paste)})" if paste
        else "  narrate.genre:     absent",
    ]
    if profile_pastes:
        lines.append(
            f"  profiles rewritten: {len(profile_pastes)} "
            f"({PROFILE_GENRE_KNOB} -> {PROFILE_GENRE_FILE_KNOB})"
        )
    if divergent:
        lines.append(
            f"  DISCARDED divergent profile genre text (--drop-profile-genre): "
            f"{', '.join(sorted(divergent))}"
        )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
