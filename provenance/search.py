"""Search orchestration: scope -> scan -> classify -> annotate -> rank -> truncate.

This is where the feature's one recurring rule is enforced: **nothing is removed
without being counted.** Three filters can shrink a result set — the manifest's
``exclude`` globs, a chapter horizon, and a tier filter — and every one of them
reports what it took. A response of ``hits: []`` with ``suppressed_by_tier:
{working_reference: 12}`` is a different answer from ``hits: []`` alone, and the
caller's next action differs accordingly (FR-011, FR-012, SC-005).

``suppressed_by_exclude`` is the least obvious of the three and the most
important to keep. Research D17 made the manifest's ``exclude`` list the *single*
authority on what is not searched, which is right — and it concentrates the risk:
one glob added by a GM would otherwise narrow every future search with nothing in
any response to show for it.

Scope arrives already validated when the CLI calls in, but this module refuses on
its own account too. It is reachable from the MCP seam and from tests, and a
scope check that lives only in the argument parser is a scope check one caller
can walk around.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .backends import Backend, roster
from .corrections import consult
from .envelope import (
    INCLUDED,
    UNATTRIBUTABLE,
    ProvenanceEnvelope,
    build_envelope,
    chapter_for,
    rank,
    relevance_for,
)
from .identity import expansion_forms
from .scan import (
    decode_line,
    extract_excerpt,
    match_counts,
    read_lines,
    scan,
    select_scanner,
)
from .tiers import TrustTier, classify


class ScopeError(Exception):
    """A campaign was named that the manifest does not enumerate.

    The CLI turns this into its own richer refusal (which enumerates the known
    campaigns); this exists so a direct caller cannot get an unscoped search by
    bypassing the parser.
    """


@dataclass(frozen=True)
class SearchRequest:
    """``campaigns`` has no default. Not here, not in argparse, not in the MCP tool."""

    query: str
    campaigns: Sequence[str]
    tiers: Sequence[TrustTier] | None = None
    horizon: int | None = None
    expand_aliases: bool = False
    regex: bool = False
    case_sensitive: bool = False
    limit: int = 50
    context_lines: int = 2
    scanner: str | None = None


@dataclass(frozen=True)
class SearchResponse:
    hits: list[ProvenanceEnvelope]
    total_matched: int
    suppressed_by_tier: dict[str, int]
    suppressed_by_horizon: int
    suppressed_by_exclude: int
    truncated_by_limit: int
    backends_consulted: tuple[Backend, ...]
    campaigns_searched: list[str]
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)
    excluded_by_glob: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "hits": [h.as_dict() for h in self.hits],
            "total_matched": self.total_matched,
            "suppressed_by_tier": dict(self.suppressed_by_tier),
            "suppressed_by_horizon": self.suppressed_by_horizon,
            "suppressed_by_exclude": self.suppressed_by_exclude,
            "excluded_by_glob": dict(self.excluded_by_glob),
            "truncated_by_limit": self.truncated_by_limit,
            "backends_consulted": [b.as_dict() for b in self.backends_consulted],
            "campaigns_searched": list(self.campaigns_searched),
            "elapsed_ms": self.elapsed_ms,
            "warnings": list(self.warnings),
        }


def _root_of(workspace) -> Path:
    """Accept a ``WorkspaceRoot`` or a bare path — the callers legitimately differ."""
    return Path(getattr(workspace, "path", workspace))


def run_search(request: SearchRequest, manifest, workspace) -> SearchResponse:
    """Run one search across the explicitly named campaigns.

    Campaigns are iterated in the order the caller wrote them and their result
    sets stay separate through ranking; two campaigns holding an entity with the
    same name keep them apart, and nothing is merged or de-duplicated across
    games (FR-008).
    """
    started = time.perf_counter()
    root = _root_of(workspace)

    if not request.campaigns:
        raise ScopeError("no campaign scope given; there is no implicit 'all campaigns'")

    campaigns = []
    for name in request.campaigns:
        campaign = manifest.get(name)
        if campaign is None:
            raise ScopeError(f"{name!r} has no manifest entry")
        campaigns.append(campaign)

    impl = select_scanner(request.scanner)
    tier_filter = {TrustTier(t) for t in request.tiers} if request.tiers else None

    candidates: list[_Candidate] = []
    warnings: list[str] = []
    excluded_by_glob: dict[str, int] = {}
    suppressed_by_exclude = 0
    context: dict[str, _CampaignContext] = {}

    for campaign in campaigns:
        campaign_root = root / campaign.root
        lookup = consult(campaign, campaign_root)
        context[campaign.name] = _CampaignContext(campaign, campaign_root, lookup, {})
        if lookup.reason:
            warnings.append(f"{campaign.name}: corrections not consulted — {lookup.reason}")

        forms = (
            expansion_forms(campaign, campaign_root, request.query)
            if request.expand_aliases
            else (request.query,)
        )

        per_campaign: list[_Candidate] = []
        counted_exclusions = False

        for form in forms:
            result = scan(
                campaign,
                campaign_root,
                form,
                regex=request.regex,
                case_sensitive=request.case_sensitive,
                impl=impl,
            )
            if not counted_exclusions:
                # Once per campaign, not once per alias form: the exclude count
                # is a property of the corpus, not of how many times it was read.
                suppressed_by_exclude += result.files.excluded_total
                for glob, count in result.files.excluded.items():
                    excluded_by_glob[f"{campaign.name}:{glob}"] = count
                counted_exclusions = True

            if result.out_of_scope:
                warnings.append(
                    f"{campaign.name}: {len(result.out_of_scope)} file(s) matched by "
                    f"{impl.name} were not in the manifest's enumerated scope and were "
                    f"dropped — the two disagree about a glob: "
                    f"{', '.join(result.out_of_scope[:3])}"
                )
            if result.files.unreadable:
                warnings.append(
                    f"{campaign.name}: {len(result.files.unreadable)} directory/ies "
                    f"could not be read; the corpus searched here is incomplete"
                )

            counts = match_counts(result.matches)
            per_campaign += _score(request, context[campaign.name], result, form, counts)

        if len(forms) > 1:
            per_campaign = _dedupe_candidates(per_campaign)
            warnings.append(
                f"{campaign.name}: alias expansion searched "
                f"{len(forms)} surface forms ({', '.join(forms)})"
            )
        candidates.extend(per_campaign)

    total_matched = len(candidates)

    # ── horizon (FR-024, FR-012) ─────────────────────────────────────────────
    suppressed_by_horizon = 0
    if request.horizon is not None:
        kept: list[_Candidate] = []
        for candidate in candidates:
            if candidate.chapter is not None and candidate.chapter > request.horizon:
                suppressed_by_horizon += 1
            else:
                # An unattributable file is kept and labeled. The caller asked a
                # question about the past; this file cannot answer it either way,
                # and dropping it would present a narrowed corpus as a complete one.
                kept.append(candidate)
        candidates = kept
        unattributable = sum(1 for c in candidates if c.disposition == UNATTRIBUTABLE)
        if unattributable:
            warnings.append(
                f"{unattributable} hit(s) are in files the horizon pattern cannot "
                f"attribute; they are returned labeled `unattributable` rather than "
                f"guessed either way"
            )

    # ── tier (FR-011) ────────────────────────────────────────────────────────
    suppressed_by_tier: dict[str, int] = {}
    if tier_filter is not None:
        kept = []
        for candidate in candidates:
            if candidate.classification.tier in tier_filter:
                kept.append(candidate)
            else:
                key = candidate.classification.tier.value
                suppressed_by_tier[key] = suppressed_by_tier.get(key, 0) + 1
        candidates = kept

    # Ranked and truncated BEFORE the expensive part. Building an envelope reads
    # context lines and matches every correction; doing that for a query like
    # "the" — 500k+ matching lines in one campaign — costs seconds and produces
    # 499,950 envelopes nobody will ever see. Only the survivors are assembled.
    candidates.sort(key=lambda c: c.sort_key)
    truncated_by_limit = 0
    if request.limit and request.limit > 0 and len(candidates) > request.limit:
        truncated_by_limit = len(candidates) - request.limit
        candidates = candidates[: request.limit]

    envelopes = [_assemble(request, context[c.campaign], c) for c in candidates]

    ambiguous = sum(1 for e in envelopes if e.tier_ambiguous)
    if ambiguous:
        warnings.append(
            f"{ambiguous} shown hit(s) matched more than one tier's globs; the winner "
            f"is by fixed precedence and every other match is on the hit as "
            f"`tier_ambiguous`. `provenance check` lists them all for review."
        )
    unsettled = sum(
        1 for e in envelopes for c in (e.corrections or ()) if not c.verified
    )
    if unsettled:
        warnings.append(
            f"{unsettled} attached correction(s) ship `verified: false` — they assert "
            f"something that could not be reproduced on disk and are unsettled, not fact"
        )

    hits = rank(envelopes)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return SearchResponse(
        hits=hits,
        total_matched=total_matched,
        suppressed_by_tier=suppressed_by_tier,
        suppressed_by_horizon=suppressed_by_horizon,
        suppressed_by_exclude=suppressed_by_exclude,
        truncated_by_limit=truncated_by_limit,
        backends_consulted=roster(impl),
        campaigns_searched=[c.name for c in campaigns],
        elapsed_ms=elapsed_ms,
        warnings=warnings,
        excluded_by_glob=excluded_by_glob,
    )


# ── the cheap pass ───────────────────────────────────────────────────────────
#
# Scoring, filtering and ranking all run on a lightweight candidate; only the
# hits that survive truncation are assembled into envelopes. The split exists
# because the two halves differ in cost by orders of magnitude: scoring touches
# one line, assembly reads context lines and tests every correction — and a
# broad query in this corpus produces hundreds of thousands of matches, almost
# all of which the caller will never see.
#
# Both halves read the same cached file bytes, so the split changes what gets
# built, never what gets found. Every count reported to the caller is taken
# from the candidate list, before truncation.


@dataclass(frozen=True)
class _CampaignContext:
    campaign: object
    root: Path
    lookup: object
    line_cache: dict


@dataclass(frozen=True)
class _Candidate:
    campaign: str
    path: str
    line: int
    classification: object
    chapter: int | None
    disposition: str | None
    relevance: float
    surface_form: str

    @property
    def sort_key(self) -> tuple:
        return (
            -self.relevance,
            self.classification.tier.ordinal,
            self.campaign,
            self.path,
            self.line,
        )

    @property
    def dedup_key(self) -> tuple[str, str, int]:
        return (self.campaign, self.path, self.line)


def _score(request: SearchRequest, ctx: _CampaignContext, result, form: str, counts):
    """One candidate per match, without touching context lines or corrections.

    Work that is per-*file* — classification, chapter attribution, reading the
    bytes — is done once per file rather than once per match. ``scan`` returns
    matches sorted by ``(path, line)``, so a single rolling entry is enough.
    """
    per_path: dict[str, tuple] = {}
    out: list[_Candidate] = []
    current_path: str | None = None
    lines: list[bytes] = []

    for match in result.matches:
        cached = per_path.get(match.path)
        if cached is None:
            cached = (
                classify(match.path, ctx.campaign.tiers),
                chapter_for(ctx.campaign, match.path),
            )
            per_path[match.path] = cached
        classification, chapter = cached

        if match.path != current_path:
            current_path = match.path
            lines = read_lines(ctx.root / match.path, ctx.line_cache)
        line_text = decode_line(lines, match.line)[0]
        out.append(
            _Candidate(
                campaign=ctx.campaign.name,
                path=match.path,
                line=match.line,
                classification=classification,
                chapter=chapter,
                disposition=_disposition(request.horizon, chapter),
                relevance=relevance_for(
                    form,
                    match.path,
                    line_text,
                    counts.get(match.path, 1),
                    regex=request.regex,
                ),
                surface_form=form,
            )
        )
    return out


def _dedupe_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Collapse alias-expanded duplicates, keeping the longest matched form."""
    best: dict[tuple[str, str, int], _Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.dedup_key)
        if current is None or len(candidate.surface_form) > len(current.surface_form):
            best[candidate.dedup_key] = candidate
    return list(best.values())


def _assemble(
    request: SearchRequest, ctx: _CampaignContext, candidate: _Candidate
) -> ProvenanceEnvelope:
    excerpt = extract_excerpt(
        ctx.root / candidate.path, candidate.line, request.context_lines, ctx.line_cache
    )
    return build_envelope(
        ctx.campaign,
        candidate.path,
        candidate.line,
        excerpt,
        query=candidate.surface_form,
        matched_surface_form=candidate.surface_form,
        match_count=0,  # unused: the score is carried over from the cheap pass
        lookup=ctx.lookup,
        regex=request.regex,
        horizon_disposition=candidate.disposition,
        relevance=candidate.relevance,
    )


def _disposition(horizon: int | None, chapter: int | None) -> str | None:
    """``None`` means no horizon was requested.

    That is a third state, distinct from ``included``: "nobody asked" and "asked,
    and this hit qualifies" are different facts, and a caller reading the field
    should be able to tell which one it is looking at.
    """
    if horizon is None:
        return None
    return INCLUDED if chapter is not None else UNATTRIBUTABLE
