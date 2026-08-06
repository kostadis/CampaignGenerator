"""The ``provenance`` CLI — the engine (Constitution VI). The MCP server is a face.

Four subcommands, all read-only, all deterministic, none of them making an LLM
call:

    provenance search   <query> --campaign NAME [--campaign NAME …] [filters]
    provenance resolve  <surface-form> --campaign NAME
    provenance capabilities
    provenance check    [--campaign NAME …]

## Exit codes are part of the contract

    0  success
    1  REFUSED      — missing scope, unknown campaign, absent root, no horizon marker
    2  usage        — argparse
    3  LOAD ERROR   — a malformed manifest or corrections record
    70 not yet implemented (Phase 2 only; see below)

A refusal is exit ``1``, never exit ``0`` with an empty list. A scriptable caller
has to be able to tell *"I refused to answer"* from *"I looked and found
nothing"* without parsing prose, because those two answers justify opposite next
actions and the difference between them is the whole of Story 3.

## Every refusal enumerates the known campaigns

Not politeness — the manifest is the only enumeration of what exists (FR-023),
so a caller who guessed a name wrong has no other way to discover the right one.
A refusal that does not list them forces a guess, and a guess is how someone ends
up searching a campaign they did not mean to.

## Phase-2 state

``search`` and ``resolve`` implement their **refusal** paths in full (T017); the
execution paths behind them land in Phases 3–4 and currently exit ``70`` with a
notice. ``check`` (T018) is complete. ``capabilities`` reports the resolved
workspace root and the rule that resolved it; its backend roster and status table
land at T074. Nothing here returns a plausible-looking empty result in place of
work that has not been written — a stub that exits ``0`` with no hits is
indistinguishable from a real search that found nothing, which is the one failure
mode this feature exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .corrections import CorrectionsStatus, consult
from .manifest import (
    ManifestError,
    ProvenanceManifest,
    WorkspaceRoot,
    load_manifest,
    resolve_workspace_root,
)
from .scan import enumerate_files
from .tiers import TrustTier, classify, matches_any

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_LOAD_ERROR = 3
EXIT_NOT_IMPLEMENTED = 70

#: A directory is "unclassified-heavy" when this share of its searchable files
#: match no tier glob. Advisory only — the finding says "you probably meant to
#: write a glob here", it never invents one.
UNCLASSIFIED_HEAVY_RATIO = 0.5

#: …and only once the directory is big enough for the ratio to mean anything.
UNCLASSIFIED_HEAVY_MIN_FILES = 4

#: How many example paths a per-campaign aggregate finding carries.
EXAMPLES = 5


class Refusal(Exception):
    """A request the tool declines to answer. Maps to exit code 1.

    Distinct from ``ManifestError`` (exit 3): a load error means the authored
    data is broken, a refusal means the data is fine and the *request* was not
    answerable as posed.
    """


# ── refusals (T017) ──────────────────────────────────────────────────────────


def _known(manifest: ProvenanceManifest) -> str:
    return "Known campaigns: " + ", ".join(manifest.campaign_names)


def refuse_no_scope(verb: str, query: str, manifest: ProvenanceManifest) -> Refusal:
    """FR-006, SC-003. There is no implicit "all campaigns", at any layer."""
    example = manifest.campaign_names[0]
    return Refusal(
        f"no campaign scope given.\n\n"
        f"  {verb.capitalize()} requires an explicit --campaign. There is no implicit "
        f'"all campaigns".\n\n'
        f"  {_known(manifest)}\n\n"
        f'  e.g.  provenance {verb} "{query}" --campaign {example}'
    )


def refuse_unknown_campaign(
    name: str, manifest: ProvenanceManifest, workspace: WorkspaceRoot
) -> Refusal:
    """FR-009. Named-but-unenumerated is refused by name, never silently skipped.

    The on-disk branch matters: a directory sitting in the workspace that the
    manifest does not list is *invisible on purpose* (enumeration is closed,
    FR-023). Saying "unknown campaign" about a directory the caller can see with
    ``ls`` reads as a bug; saying "present but not enumerated" tells them exactly
    which file to edit.
    """
    on_disk = (workspace.path / name).is_dir()
    if on_disk:
        body = (
            f"  A directory exists at {workspace.path / name}, but "
            f"{workspace.manifest_path}\n"
            f"  does not enumerate it. The manifest is the only enumeration of which\n"
            f"  campaigns exist (FR-023) — a directory on disk is not itself a claim\n"
            f"  that its contents are searchable, or that any of it is canon.\n\n"
            f"  Add a block for {name!r} to the manifest, or search one of these:\n"
        )
    else:
        body = f"  No such campaign, and no directory of that name under {workspace.path}.\n"
    return Refusal(f"{name!r} has no manifest entry.\n\n{body}\n  {_known(manifest)}")


def refuse_missing_root(campaign, root: Path, workspace: WorkspaceRoot) -> Refusal:
    """Story 3. The manifest is portable across machines; the corpus is not."""
    return Refusal(
        f"campaign {campaign.name!r} declares root {campaign.root!r} which does not "
        f"exist on this machine.\n\n"
        f"  Looked for: {root}\n"
        f"  Workspace root: {workspace.path}  [{workspace.detail}]\n\n"
        f"  This is a machine/config problem, not an empty result. Nothing was searched."
    )


def refuse_no_horizon(campaign, manifest: ProvenanceManifest) -> Refusal:
    """FR-025. A horizon filter with no marker is refused, never served unfiltered.

    Serving the whole corpus in answer to "what was true at chapter N" would be
    the worst available failure: a confident, complete-looking answer containing
    every future spoiler the question was asked to exclude.
    """
    return Refusal(
        f"campaign {campaign.name!r} records no horizon marker; a horizon filter "
        f"cannot be applied.\n\n"
        f"  Add a `horizon:` block to this campaign in the manifest, or drop --horizon.\n"
        f"  Serving the search unfiltered instead would answer a question about the past\n"
        f"  with material from the present.\n\n"
        f"  {_known(manifest)}"
    )


# ── shared resolution ────────────────────────────────────────────────────────


def _load(args) -> tuple[WorkspaceRoot, ProvenanceManifest]:
    """Resolve the workspace root and load the manifest. Raises ``ManifestError``."""
    workspace = resolve_workspace_root(getattr(args, "campaigns_root", None))
    return workspace, load_manifest(workspace.manifest_path)


def _resolve_scope(
    names, manifest: ProvenanceManifest, workspace: WorkspaceRoot, *, verb: str, query: str
) -> list:
    """Turn ``--campaign`` values into campaigns, refusing on the first problem.

    Refuses in the order the caller wrote the names, so the same command always
    produces the same message rather than whichever failure a set iteration
    happened to surface first.
    """
    if not names:
        raise refuse_no_scope(verb, query, manifest)

    resolved = []
    for name in names:
        campaign = manifest.get(name)
        if campaign is None:
            raise refuse_unknown_campaign(name, manifest, workspace)
        root = workspace.path / campaign.root
        if not root.is_dir():
            raise refuse_missing_root(campaign, root, workspace)
        resolved.append(campaign)
    return resolved


def _not_implemented(what: str, phase: str) -> int:
    print(
        f"NOT IMPLEMENTED: {what}\n"
        f"  Every refusal check passed; the execution path lands in {phase}.\n"
        f"  Exiting {EXIT_NOT_IMPLEMENTED} rather than 0 — an empty result here would be\n"
        f"  indistinguishable from a real search that found nothing.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


# ── findings (T018) ──────────────────────────────────────────────────────────

ERROR = "error"
INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One thing for the GM to rule on. ``check`` never rules on it itself."""

    kind: str
    level: str
    campaign: str
    message: str
    detail: tuple[str, ...] = field(default=())


def _horizon_dir(path_pattern: str) -> str | None:
    """The directory a horizon pattern addresses, from its literal prefix.

    ``docs/chapters/chapter_(\\d+)_`` -> ``docs/chapters``. Returns ``None`` when
    the pattern has no literal directory component, in which case every file in
    the campaign would be a candidate and the finding would be noise rather than
    signal.
    """
    meta = set(".^$*+?{}[]\\|()")
    literal = ""
    for ch in path_pattern:
        if ch in meta:
            break
        literal += ch
    if "/" not in literal:
        return None
    return literal.rsplit("/", 1)[0]


def _ancestors(rel_path: str) -> list[str]:
    """Every directory containing ``rel_path``, shallowest first. Excludes the root.

    The campaign root itself is excluded: "72% of this campaign is unclassified"
    is true, unactionable, and would swallow the directory-level signal that
    tells the GM *where* to write the glob.
    """
    parts = rel_path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _heaviest_roots(subtree: dict[str, list[int]]) -> list[tuple[str, int, int]]:
    """The shallowest heavy directories, with heavy descendants folded into them.

    One missing glob over ``docs/ensemble/per_chapter/**`` is one authoring
    decision. Reporting each of its 100 leaf directories separately reads as 100
    problems and buries the four that are not this one.
    """
    reported: list[tuple[str, int, int]] = []
    for directory in sorted(subtree, key=lambda d: (d.count("/"), d)):
        total, unclassified = subtree[directory]
        if total < UNCLASSIFIED_HEAVY_MIN_FILES:
            continue
        if unclassified / total <= UNCLASSIFIED_HEAVY_RATIO:
            continue
        if any(directory.startswith(f"{seen}/") for seen, _, _ in reported):
            continue
        reported.append((directory, total, unclassified))
    return reported


def _breakdown(parent: str, subtree: dict[str, list[int]]) -> tuple[str, ...]:
    """The child subtrees carrying the parent's unclassified weight.

    Without this a finding reads "docs/ — 3064 of 3565", which is true and
    useless: the GM still has to go find out where. With it they can see that
    one ``docs/ensemble/`` glob accounts for most of it.
    """
    depth = parent.count("/") + 1
    children = [
        (directory, counts)
        for directory, counts in subtree.items()
        if directory.startswith(f"{parent}/") and directory.count("/") == depth
    ]
    children.sort(key=lambda item: (-item[1][1], item[0]))
    lines = [
        f"{directory}/ — {counts[1]}/{counts[0]}"
        for directory, counts in children[:EXAMPLES]
        if counts[1]
    ]
    if not lines:
        return ()
    remainder = sum(c[1] for _, c in children[EXAMPLES:])
    if remainder:
        lines.append(f"… and {remainder} more beneath other children")
    return ("heaviest children: " + "  ·  ".join(lines),)


def check_campaign(campaign, workspace: WorkspaceRoot) -> list[Finding]:
    """Validate one campaign's authored data against what is on disk.

    Reports; never edits, never resolves an ambiguity, never prunes a stale
    entry. Mirrors ``registry check`` deliberately — the GM rules, the tool
    surfaces (Constitution II).
    """
    name = campaign.name
    findings: list[Finding] = []
    root = workspace.path / campaign.root

    if not root.is_dir():
        return [
            Finding(
                "campaign-root-missing",
                ERROR,
                name,
                f"declared root {campaign.root!r} does not exist on this machine",
                (f"looked for: {root}",),
            )
        ]

    # ── identity ─────────────────────────────────────────────────────────────
    if not campaign.identity.has_store:
        findings.append(
            Finding(
                "no-identity-store",
                INFO,
                name,
                "no entity registry and no aliases file declared",
                ("`provenance resolve` will answer NO IDENTITY STORE, which is a real "
                 "answer and distinguishable from a miss",),
            )
        )
    else:
        for kind in ("registry", "aliases"):
            declared = getattr(campaign.identity, kind)
            if declared and not (root / declared).is_file():
                findings.append(
                    Finding(
                        "identity-store-missing",
                        ERROR,
                        name,
                        f"identity.{kind} declares {declared!r} but no such file exists",
                        (f"looked for: {root / declared}",),
                    )
                )

    # ── corrections ──────────────────────────────────────────────────────────
    lookup = consult(campaign, root)
    if lookup.status is CorrectionsStatus.NOT_CONSULTED:
        findings.append(
            Finding(
                "corrections-unreadable",
                ERROR,
                name,
                "a corrections record is declared but could not be loaded",
                tuple((lookup.reason or "").splitlines()),
            )
        )

    files = enumerate_files(campaign, root)

    if lookup.status is CorrectionsStatus.CONSULTED and lookup.record is not None:
        for correction in lookup.record.corrections:
            if not any(matches_any(p, correction.applies_to.paths) for p in files.paths):
                findings.append(
                    Finding(
                        "stale-correction-entry",
                        ERROR,
                        name,
                        f"correction {correction.id!r} matches no file on disk — prune it",
                        tuple(f"applies_to.paths: {p}" for p in correction.applies_to.paths),
                    )
                )
            if not correction.verified:
                findings.append(
                    Finding(
                        "unverified-correction",
                        INFO,
                        name,
                        f"correction {correction.id!r} ships verified: false — it asserts "
                        f"something not reproducible on disk",
                        (correction.note,) if correction.note else (),
                    )
                )

    # ── tiers ────────────────────────────────────────────────────────────────
    #
    # Aggregated by (winner, losers) rather than emitted per file: a single
    # overlapping glob pair produces hundreds of identical findings, and a
    # hundred copies of one problem reads as a hundred problems.
    ambiguous: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    subtree: dict[str, list[int]] = {}

    for rel in files.paths:
        result = classify(rel, campaign.tiers)
        unclassified = result.tier is TrustTier.UNCLASSIFIED
        # Count into every ancestor, not just the immediate parent. One missing
        # glob over a deep tree is ONE finding; reporting it per-directory
        # produced 100+ identical lines for a single cause, and a report nobody
        # reads is not a human checkpoint.
        for ancestor in _ancestors(rel):
            counts = subtree.setdefault(ancestor, [0, 0])
            counts[0] += 1
            counts[1] += unclassified
        if result.is_ambiguous:
            key = (result.tier.value, tuple(t.value for t in result.ambiguous))
            ambiguous.setdefault(key, []).append(rel)

    for (winner, losers), examples in sorted(ambiguous.items()):
        findings.append(
            Finding(
                "tier-ambiguous",
                INFO,
                name,
                f"{len(examples)} file(s) match more than one tier's globs — "
                f"{winner} wins by precedence over {', '.join(losers)}",
                tuple(examples[:EXAMPLES])
                + ((f"… and {len(examples) - EXAMPLES} more",) if len(examples) > EXAMPLES else ()),
            )
        )

    for parent, total, unclassified in _heaviest_roots(subtree):
        findings.append(
            Finding(
                "unclassified-heavy",
                INFO,
                name,
                f"{parent}/ — {unclassified} of {total} searchable files beneath it "
                f"match no tier glob",
                _breakdown(parent, subtree)
                + ("they are still searched and returned as `unclassified` (FR-013); this "
                   "is a hint that a glob is missing, not a suppression",),
            )
        )

    # ── horizon ──────────────────────────────────────────────────────────────
    if campaign.horizon is not None:
        directory = _horizon_dir(campaign.horizon.path_pattern)
        if directory:
            pattern = campaign.horizon.compiled()
            orphans = [
                rel
                for rel in files.paths
                if rel.startswith(f"{directory}/") and not pattern.search(rel)
            ]
            if orphans:
                findings.append(
                    Finding(
                        "horizon-unattributable",
                        INFO,
                        name,
                        f"{len(orphans)} file(s) under {directory}/ carry no chapter number "
                        f"the pattern can read",
                        tuple(orphans[:EXAMPLES])
                        + (
                            (f"… and {len(orphans) - EXAMPLES} more",)
                            if len(orphans) > EXAMPLES
                            else ()
                        )
                        + (f"pattern: {campaign.horizon.path_pattern}",),
                    )
                )

    if files.unreadable:
        findings.append(
            Finding(
                "unreadable-directory",
                ERROR,
                name,
                f"{len(files.unreadable)} directory/ies could not be read — the corpus "
                f"walked here is incomplete",
                tuple(files.unreadable[:EXAMPLES]),
            )
        )

    return findings


# ── subcommands ──────────────────────────────────────────────────────────────


def cmd_search(args) -> int:
    workspace, manifest = _load(args)
    campaigns = _resolve_scope(
        args.campaign, manifest, workspace, verb="search", query=args.query
    )
    if args.horizon is not None:
        for campaign in campaigns:
            if campaign.horizon is None:
                raise refuse_no_horizon(campaign, manifest)
    return _not_implemented("provenance search", "Phase 3 (T039-T049)")


def cmd_resolve(args) -> int:
    workspace, manifest = _load(args)
    _resolve_scope(
        args.campaign, manifest, workspace, verb="resolve", query=args.surface_form
    )
    return _not_implemented("provenance resolve", "Phase 4 (T053-T058)")


def cmd_capabilities(args) -> int:
    workspace = resolve_workspace_root(getattr(args, "campaigns_root", None))
    try:
        manifest = load_manifest(workspace.manifest_path)
    except ManifestError as exc:
        if args.json:
            print(json.dumps({"workspace_root": str(workspace.path),
                              "resolved_from": workspace.rule,
                              "manifest": None,
                              "error": str(exc)}, indent=2))
            return EXIT_LOAD_ERROR
        raise

    if args.json:
        print(
            json.dumps(
                {
                    "workspace_root": str(workspace.path),
                    "resolved_from": workspace.rule,
                    "resolved_detail": workspace.detail,
                    "manifest": str(workspace.manifest_path),
                    "campaigns": manifest.campaign_names,
                    "backends": None,
                },
                indent=2,
            )
        )
        return EXIT_OK

    print(f"Workspace root: {workspace.path}")
    print(f"  resolved from: {workspace.rule} — {workspace.detail}")
    print()
    print(f"Manifest: {workspace.manifest_path}  (loaded, {len(manifest.campaigns)} campaigns)")
    for name in manifest.campaign_names:
        print(f"  {name}")
    print()
    print("Backends: not yet reported — the roster, the per-campaign status table and the")
    print("  `.gitignore` note land at T074 (Phase 6). Absence here is a missing feature,")
    print("  not a claim that no backend exists.")
    return EXIT_OK


def cmd_check(args) -> int:
    workspace, manifest = _load(args)

    names = args.campaign or manifest.campaign_names
    for name in names:
        if manifest.get(name) is None:
            raise refuse_unknown_campaign(name, manifest, workspace)

    findings: list[Finding] = []
    for name in names:
        findings.extend(check_campaign(manifest.campaigns[name], workspace))

    errors = [f for f in findings if f.level == ERROR]

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings],
                          "errors": len(errors),
                          "campaigns": list(names)}, indent=2))
        return EXIT_REFUSED if errors else EXIT_OK

    print(f"Manifest: {workspace.manifest_path}")
    print(f"Checked: {', '.join(names)}")
    print()
    for name in names:
        mine = [f for f in findings if f.campaign == name]
        if not mine:
            print(f"{name}: no findings")
            continue
        print(f"{name}: {len(mine)} finding(s)")
        for finding in mine:
            marker = "ERROR" if finding.level == ERROR else "info "
            print(f"  [{marker}] {finding.kind}: {finding.message}")
            for line in finding.detail:
                print(f"           {line}")
        print()

    print(
        f"{len(findings)} finding(s), {len(errors)} error-level. "
        f"Nothing was edited; every finding is for GM review."
    )
    return EXIT_REFUSED if errors else EXIT_OK


# ── parser ───────────────────────────────────────────────────────────────────


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--campaigns-root",
        metavar="PATH",
        help="workspace root; overrides $CAMPAIGNS_ROOT and the built-in default",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="provenance",
        description="Read-only, provenance-aware search across campaign workspaces.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search ──
    search = sub.add_parser("search", help="search one or more named campaigns")
    search.add_argument("query")
    # NOT required=True: omitting --campaign must be a REFUSAL (exit 1) carrying
    # the campaign list, not an argparse usage error (exit 2) carrying a usage
    # string. SC-003 is asserted against that message, and a caller who gets
    # exit 2 learns nothing about which campaigns exist.
    search.add_argument(
        "--campaign",
        action="append",
        metavar="NAME",
        help="REQUIRED, repeatable. No default and no 'all' token, at any layer.",
    )
    search.add_argument("--tier", action="append", metavar="TIER",
                        choices=[t.value for t in TrustTier])
    search.add_argument("--horizon", type=int, metavar="N")
    search.add_argument("--expand-aliases", action="store_true")
    search.add_argument("--regex", action="store_true",
                        help="default: the query is escaped and matched literally")
    search.add_argument("--case-sensitive", action="store_true")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--context-lines", type=int, default=2)
    search.add_argument("--scanner", choices=("rg", "python"),
                        help="force one implementation; default = rg if discoverable")
    _add_common(search)
    search.set_defaults(func=cmd_search)

    # resolve ──
    resolve = sub.add_parser("resolve", help="resolve a surface form against a campaign")
    resolve.add_argument("surface_form", metavar="surface-form")
    resolve.add_argument("--campaign", action="append", metavar="NAME")
    _add_common(resolve)
    resolve.set_defaults(func=cmd_resolve)

    # capabilities ──
    capabilities = sub.add_parser(
        "capabilities", help="report the resolved workspace root, manifest and backends"
    )
    _add_common(capabilities)
    capabilities.set_defaults(func=cmd_capabilities)

    # check ──
    check = sub.add_parser("check", help="validate the authored data; report for GM review")
    check.add_argument("--campaign", action="append", metavar="NAME",
                       help="default: every campaign in the manifest")
    _add_common(check)
    check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ManifestError as exc:
        print(f"LOAD ERROR: {exc}", file=sys.stderr)
        return EXIT_LOAD_ERROR
    except BrokenPipeError:  # `| head`
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
