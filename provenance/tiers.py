"""Trust tiers, and the glob -> tier classification that assigns them.

The tier is the single most load-bearing label on a hit. It is what lets a
reader tell "the GM wrote this at the table" from "a pipeline generated this and
will overwrite it next Tuesday" without opening the file. FR-002 requires it on
every hit; FR-010 makes it the ranking tiebreak.

Two decisions here are worth understanding before editing:

**Precedence is fixed and first-match-wins, but ambiguity is reported.**
A pure first-match-wins rule would be the tool quietly making a scope decision
the GM never signed off on. So the classifier keeps testing after it has an
answer, and every *additional* tier whose globs also matched is recorded on the
hit as ``tier_ambiguous`` and surfaced by ``provenance check``. One deterministic
answer per query, with the disagreement visible (research D8, Constitution II).

**No match is an answer, not a failure.** A file matching no glob comes back
labeled ``unclassified`` and is still returned (FR-013). Dropping it would be
the silent narrowing this whole feature exists to prevent; ``unclassified`` is
therefore a real tier at query time, and deliberately *not* authorable in a
manifest — nobody writes "this is unclassified", it is what the absence of a
declaration looks like.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache


class TrustTier(str, Enum):
    """The five tiers, ordered by how much a reader should trust the content.

    ``str`` mixin so a tier serialises to its own name in JSON without a custom
    encoder — the CLI's ``--json`` output and the MCP tool return the same
    strings the manifest is authored in.
    """

    AUTHORITATIVE = "authoritative"
    SEARCH_ACCELERATOR = "search_accelerator"
    WORKING_REFERENCE = "working_reference"
    STAGING = "staging"
    UNCLASSIFIED = "unclassified"

    @property
    def ordinal(self) -> int:
        """Rank for the FR-010 tiebreak. Lower sorts first (more trusted)."""
        return _ORDINALS[self]


_ORDINALS = {
    TrustTier.AUTHORITATIVE: 0,
    TrustTier.SEARCH_ACCELERATOR: 1,
    TrustTier.WORKING_REFERENCE: 2,
    TrustTier.STAGING: 3,
    TrustTier.UNCLASSIFIED: 4,
}

#: The four tiers a GM may declare globs for, in classification order.
#: ``UNCLASSIFIED`` is absent on purpose — it is assigned at query time only.
AUTHORABLE_TIERS: tuple[TrustTier, ...] = (
    TrustTier.AUTHORITATIVE,
    TrustTier.SEARCH_ACCELERATOR,
    TrustTier.WORKING_REFERENCE,
    TrustTier.STAGING,
)


# ── glob matching ────────────────────────────────────────────────────────────
#
# Hand-rolled rather than fnmatch or PurePath.match, for two reasons that both
# bite in practice:
#
#   - fnmatch's `*` happily crosses `/`, so `docs/*.md` would match
#     `docs/npcs/keeper.md` and mis-tier every dossier in the corpus.
#   - PurePath.full_match() understands `**` correctly but only landed in
#     Python 3.13, and this package declares >=3.9.
#
# The semantics implemented are rg's / gitignore's, which is what the manifest
# author will expect since the same globs drive rg's `-g` flags:
#   `*`   any run of characters within one path segment
#   `?`   exactly one character, not `/`
#   `**/` zero or more whole path segments
#   `**`  at the end: everything below this point
#   `[…]` a character class, `!` or `^` negates


@lru_cache(maxsize=2048)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate one glob into an anchored regex over a POSIX relative path."""
    out: list[str] = []
    i, n = 0, len(pattern)

    while i < n:
        c = pattern[i]

        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            doubled = (j - i) >= 2
            # `**` only means "cross directories" when it is a whole segment;
            # `foo**bar` is just a wildcard within one segment.
            whole_segment = (i == 0 or pattern[i - 1] == "/") and (
                j >= n or pattern[j] == "/"
            )
            if doubled and whole_segment:
                if j >= n:
                    out.append(".*")           # trailing `**`
                else:
                    out.append("(?:.*/)?")     # `**/` — zero or more segments
                    j += 1                     # consume the separator
            else:
                out.append("[^/]*")
            i = j
            continue

        if c == "?":
            out.append("[^/]")
            i += 1
            continue

        if c == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":     # a literal ] as the first member
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:                          # unterminated — a literal bracket
                out.append(re.escape("["))
                i += 1
                continue
            body = pattern[i + 1 : j]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body + "]")
            i = j + 1
            continue

        out.append(re.escape(c))
        i += 1

    return re.compile("^" + "".join(out) + r"\Z")


def matches_any(rel_path: str, patterns) -> bool:
    """True if ``rel_path`` (POSIX, campaign-relative) matches any glob."""
    return any(compile_glob(p).search(rel_path) for p in patterns)


# ── classification ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    """One deterministic tier, plus every other tier that also claimed the path."""

    tier: TrustTier
    ambiguous: tuple[TrustTier, ...] = field(default=())

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous)


def classify(rel_path: str, tier_globs) -> Classification:
    """Classify one campaign-relative path against a campaign's ``TierGlobs``.

    ``tier_globs`` is anything exposing ``.authoritative`` / ``.search_accelerator``
    / ``.working_reference`` / ``.staging`` glob lists — in practice the
    manifest's ``TierGlobs`` model, but the classifier does not import it, so
    the tests can pass a stub and so ``tiers.py`` stays free of a manifest
    dependency it does not need.

    Returns the winning tier and, separately, every *other* tier that matched.
    The caller decides what to do with the ambiguity; this function never
    resolves it silently and never drops a path (FR-013).
    """
    matched: list[TrustTier] = []
    for tier in AUTHORABLE_TIERS:
        if matches_any(rel_path, getattr(tier_globs, tier.value, ()) or ()):
            matched.append(tier)

    if not matched:
        return Classification(TrustTier.UNCLASSIFIED)

    # matched is already in ordinal order because AUTHORABLE_TIERS is.
    return Classification(tier=matched[0], ambiguous=tuple(matched[1:]))
