#!/usr/bin/env python3
"""Generate a session's `.cleaned.vtt` from its raw tape plus a correction record.

Extraction contract #250, R4. The raw `*.transcript.vtt` is the archive and is
never written. `transcript_corrections.yaml` is the hand-authored record. The
`.cleaned.vtt` is **output**.

Deterministic and free: no model is called, no API key is read, no token is
spent. Fixing a mishearing is a text substitution at a known cue, and asking a
model to decide which mishearings deserve fixing is precisely the scope
decision this contract exists to take out of the pipeline.

Three subcommands, in the order a session needs them::

    sd_corrections import --dir summaries/20260623   # once, for a tape already edited
    sd_corrections check  --dir summaries/20260623   # always; free
    sd_corrections apply  --dir summaries/20260623   # after editing the record

``import`` reverse-engineers a record by diffing the raw tape against a
`.cleaned.vtt` somebody already hand-edited, so an unrecorded pass becomes a
reviewable list. Its entries land **unverified** — nobody reviewed them, and
that is the point.

``check`` verifies two things and writes nothing: every ``was`` still matches
the raw tape, and regenerating reproduces the `.cleaned.vtt` currently on disk
byte-for-byte. The second is the proof that the record is *complete* — if the
regenerated tape differs, something was edited that nobody wrote down.

Exit codes::

    0  ran; nothing to report
    1  ran; findings (stale entries, or a tape the record does not reproduce)
    2  could not run (no record, no transcript, unreadable or invalid input)
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from campaignlib.transcript_corrections import (
    RECORD_NAME,
    CorrectionsError,
    apply_record,
    diff_cues,
    dump_record,
    import_edits,
    load_record,
    load_transcript,
)
from campaignlib.util import atomic_write_text
from campaignlib.vtt import VttError, parse


def _raw_candidates(d: Path) -> list[Path]:
    return sorted(
        p for p in d.glob("*.vtt")
        if not p.name.endswith(".cleaned.vtt")
    )


def _resolve(args) -> tuple[Path, Path]:
    """(session directory, record path). Raises CorrectionsError."""
    d = Path(args.dir).expanduser()
    if not d.is_dir():
        raise CorrectionsError(f"--dir is not a directory: {d}")
    return d, Path(args.record).expanduser() if args.record else d / RECORD_NAME


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dir", metavar="DIR", default=".",
                   help="Session directory holding the transcripts (default: CWD).")
    p.add_argument("--record", metavar="FILE", default=None,
                   help=f"Correction record (default: <dir>/{RECORD_NAME}).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a session .cleaned.vtt from the raw tape plus a "
                    "cue-indexed correction record. Deterministic; calls no model.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="Reverse-engineer a record from an "
                                        "already-edited .cleaned.vtt.")
    _add_common(imp)
    imp.add_argument("--raw", metavar="FILE", default=None,
                     help="Raw transcript (default: the only non-.cleaned .vtt in --dir).")
    imp.add_argument("--edited", metavar="FILE", default=None,
                     help="The hand-edited .cleaned.vtt to reverse-engineer.")
    imp.add_argument("--verified", action="store_true",
                     help="Mark imported entries verified. Do not use unless you "
                          "have actually reviewed every one — they were not "
                          "reviewed when they were made, which is why this exists.")
    imp.add_argument("--force", action="store_true",
                     help="Overwrite an existing record.")

    chk = sub.add_parser("check", help="Verify the record is current and complete. "
                                       "Writes nothing.")
    _add_common(chk)

    app = sub.add_parser("apply", help="Regenerate the .cleaned.vtt from raw + record.")
    _add_common(app)
    app.add_argument("--dry-run", action="store_true",
                     help="Report what would change; write nothing.")
    return p


def _cmd_import(args) -> int:
    d, record_path = _resolve(args)
    if record_path.exists() and not args.force:
        print(f"Error: {record_path} already exists. Pass --force to overwrite, "
              f"but read it first — an import discards hand-written notes.",
              file=sys.stderr)
        return 2

    if args.raw:
        raw_path = Path(args.raw).expanduser()
    else:
        cands = _raw_candidates(d)
        if len(cands) != 1:
            print(f"Error: expected exactly one non-.cleaned .vtt in {d}, found "
                  f"{len(cands)}: {[p.name for p in cands]} — pass --raw.",
                  file=sys.stderr)
            return 2
        raw_path = cands[0]

    edited_path = (Path(args.edited).expanduser() if args.edited
                   else raw_path.with_name(raw_path.name[:-4] + ".cleaned.vtt"))
    if not edited_path.is_file():
        print(f"Error: no edited transcript at {edited_path} — nothing to import. "
              f"A session with no .cleaned.vtt needs no record until it has a "
              f"correction.", file=sys.stderr)
        return 2

    raw = load_transcript(raw_path)
    edited = load_transcript(edited_path)
    record = import_edits(
        raw, edited,
        transcript_name=raw_path.name,
        recorded=date.today(),
        verified=args.verified,
    )
    atomic_write_text(record_path, dump_record(record))

    n = len(record.corrections)
    print(f"[sd_corrections import | {raw_path.name} -> {edited_path.name}]")
    print(f"  {len(raw.cues):,} cues; {n} differ.")
    print(f"  Wrote {record_path}")
    if n:
        state = "verified" if args.verified else "UNVERIFIED"
        print(f"  All {n} entries are {state}.")
        if not args.verified:
            print("  They were never reviewed — that is why they are unverified, not "
                  "an oversight.\n"
                  "  Read them, fix or delete the wrong ones, then set verified: true.")
    return 0


def _cmd_check(args) -> int:
    d, record_path = _resolve(args)
    record = load_record(record_path)
    raw_path = d / record.transcript
    out_path = d / record.output_name()

    raw = load_transcript(raw_path)
    result = apply_record(record, raw)

    print(f"[sd_corrections check | {record.transcript} | {len(raw.cues):,} cues]")
    print("=" * 60)
    n = len(record.corrections)
    unverified = record.unverified
    print(f"  {n} correction(s) in the record, {len(result.applied)} still apply.")

    findings = 0
    if result.problems:
        findings += len(result.problems)
        print(f"\n  {len(result.problems)} stale entr(ies) — the tape no longer says "
              f"what `was` claims:")
        for p in result.problems:
            print(f"    - {p}")

    if unverified:
        print(f"\n  {len(unverified)} unreviewed entr(ies). Not an error — a backlog:")
        for c in unverified[:10]:
            print(f"    - {c.id} (cue {c.cue}): {c.was[:60]!r} -> {c.now[:60]!r}")
        if len(unverified) > 10:
            print(f"    … and {len(unverified) - 10} more.")

    if not out_path.is_file():
        print(f"\n  {out_path.name} does not exist yet — run `apply`.")
    else:
        # Two separate claims, and conflating them is useless. Cue-level
        # equality says the *record is complete* — nothing was edited that
        # nobody wrote down. Byte equality says the *file is current*. A
        # freshly imported session always fails the second and passes the
        # first, because the generated NOTE header replaces whatever prose
        # block the hand-editor left, and reporting that as "unrecorded edits"
        # would cry wolf on the one run where the record is provably right.
        current = out_path.read_text(encoding="utf-8")
        try:
            on_disk = parse(current)
            regenerated = parse(result.text)
        except VttError as exc:
            findings += 1
            print(f"\n  {out_path.name} will not parse: {exc}")
        else:
            drift = diff_cues(regenerated, on_disk)
            if drift:
                findings += 1
                print(f"\n  {len(drift)} cue(s) in {out_path.name} are NOT explained "
                      f"by the record — somebody edited the tape without writing "
                      f"it down:")
                for index, expected, actual in drift[:10]:
                    print(f"    - cue {index}\n"
                          f"        record produces: {expected[:80]!r}\n"
                          f"        file says:       {actual[:80]!r}")
                if len(drift) > 10:
                    print(f"    … and {len(drift) - 10} more.")
                print("  -> `sd_corrections import --force` to capture them.")
            else:
                print(f"\n  All {len(on_disk.cues):,} cues in {out_path.name} are "
                      f"explained by the record. The tape is reproducible.")

            if current != result.text:
                print(f"  {out_path.name} is stale in its header only — run `apply` "
                      f"to refresh it. Not a finding.")

    print("=" * 60)
    print("  Nothing was written." if findings else "  Nothing to report.")
    return 1 if findings else 0


def _cmd_apply(args) -> int:
    d, record_path = _resolve(args)
    record = load_record(record_path)
    raw_path = d / record.transcript
    out_path = d / record.output_name()

    raw = load_transcript(raw_path)
    result = apply_record(record, raw)

    print(f"[sd_corrections apply | {record.transcript} | {len(raw.cues):,} cues]")
    if not result.ok:
        # Every correction has to hold or none are written. A half-repaired
        # tape is worse than an unrepaired one, because the record then
        # describes a file that does not exist.
        print(f"\nError: {len(result.problems)} correction(s) do not fit the tape. "
              f"Nothing written.", file=sys.stderr)
        for p in result.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    unchanged = out_path.is_file() and out_path.read_text(encoding="utf-8") == result.text
    if args.dry_run:
        print(f"  would write {out_path} "
              f"({'no change' if unchanged else 'changed'}, "
              f"{len(result.applied)} correction(s))")
        return 0

    atomic_write_text(out_path, result.text)
    print(f"  {len(result.applied)} correction(s) applied.")
    if record.unverified:
        print(f"  {len(record.unverified)} of them are still unreviewed.")
    print(f"  Wrote {out_path}{' (unchanged)' if unchanged else ''}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    handler = {"import": _cmd_import, "check": _cmd_check, "apply": _cmd_apply}[args.cmd]
    try:
        return handler(args)
    except CorrectionsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
