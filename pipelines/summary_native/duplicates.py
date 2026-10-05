"""Fix-at-source duplicate detection (spec 031 US3, FR-013 – FR-016).

The GM fixes a misspelled or duplicated heading IN THE SUMMARY FILES. This
module never merges, renames or aliases one. It does three small things:

* ``make_grouper`` — the only grouping the corpus applies: identical heading
  text within a category, or an EXACT registry name/alias whose entity type
  matches the category. Spells and abilities never touch the registry, and the
  registry's first-token inference is never used (research R7).
* ``find_possible_duplicates`` — LISTS likely duplicates as non-blocking
  findings with every ``file:line`` of each spelling.
* ``load_rulings`` / ``stale_rulings`` — read ``canon.yaml``, hand-authored and
  read-only here; its only key is ``not_duplicates``.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import yaml

from pipelines.summary_native import schema
from pipelines.summary_native.validate import Finding

CATEGORIES: tuple[str, ...] = tuple(schema.ENTITY_CATEGORIES.values())
RULINGS_MESSAGE = "canon.yaml records not-a-duplicate rulings only; fix duplicates in the summary files"
CANON_FILE = "canon.yaml"
_QUALIFIER_RE = re.compile(r"\s*\([^()]*\)\s*$")


class RulingsError(Exception):
    """canon.yaml is not a pure ``not_duplicates`` record (CLI exit 2)."""


# ── Rulings ────────────────────────────────────────────────────────────────


def _pair_key(category: str, a: str, b: str) -> tuple[str, frozenset[str]]:
    return category, frozenset({a.strip().casefold(), b.strip().casefold()})


@dataclass(frozen=True)
class Rulings:
    """Parsed ``not_duplicates`` rulings, in file order."""

    entries: tuple[tuple[str, str, str], ...] = ()  # (category, a, b) as written
    pairs: frozenset = field(default_factory=frozenset)

    def rules_out(self, category: str, names_a: set[str], names_b: set[str]) -> bool:
        """True if some ruling names one spelling from each side."""
        for cat, a, b in self.entries:
            if cat != category:
                continue
            ka, kb = a.strip().casefold(), b.strip().casefold()
            if (ka in names_a and kb in names_b) or (kb in names_a and ka in names_b):
                return True
        return False


def load_rulings(path: Path | None) -> Rulings:
    """Read ``canon.yaml`` strictly. An absent file is an empty record."""
    if path is None or not Path(path).is_file():
        return Rulings()
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise RulingsError(f"{path}: cannot read canon.yaml ({e})") from e
    if data is None:
        return Rulings()
    if not isinstance(data, dict):
        raise RulingsError(f"{path}: {RULINGS_MESSAGE}")
    if set(data) - {"not_duplicates"}:
        raise RulingsError(RULINGS_MESSAGE)
    raw = data.get("not_duplicates") or []
    if not isinstance(raw, list):
        raise RulingsError(f"{path}: not_duplicates must be a list of {{category, a, b}}")
    entries: list[tuple[str, str, str]] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or set(item) != {"category", "a", "b"}:
            raise RulingsError(f"{path}: not_duplicates entry {i} must be exactly {{category, a, b}}")
        cat, a, b = item["category"], item["a"], item["b"]
        if cat not in CATEGORIES:
            raise RulingsError(
                f"{path}: not_duplicates entry {i}: category {cat!r} is not one of {', '.join(CATEGORIES)}"
            )
        if not (isinstance(a, str) and isinstance(b, str) and a.strip() and b.strip()):
            raise RulingsError(f"{path}: not_duplicates entry {i}: a and b must be non-empty strings")
        entries.append((cat, a, b))
    return Rulings(
        entries=tuple(entries),
        pairs=frozenset(_pair_key(c, a, b) for c, a, b in entries),
    )


# ── Grouping ───────────────────────────────────────────────────────────────

Grouper = Callable[[str, str], "tuple[str, list[str]]"]


def make_grouper(registry) -> Grouper:
    """``grouper(category, heading) -> (canonical, grouped_by)``.

    Identical text (after strip) always groups. A registry changes the subject
    only for an exact, case-insensitive name/alias of an entity whose type is
    the category's registry type. ``grouped_by`` is ``["registry"]`` exactly
    when that happened.
    """
    tables = registry.explicit_aliases_by_type() if registry is not None else {}

    def grouper(category: str, heading: str) -> tuple[str, list[str]]:
        text = heading.strip()
        rtype = schema.CATEGORY_REGISTRY_TYPE.get(category)
        if rtype is not None:
            canonical = tables.get(rtype, {}).get(text.casefold())
            if canonical is not None and canonical != text:
                return canonical, ["registry"]
        return text, []

    return grouper


# ── Detection ──────────────────────────────────────────────────────────────


def _strip_qualifier(s: str) -> str:
    return _QUALIFIER_RE.sub("", s).strip()


def _registry_apart(registry) -> list[set[str]]:
    """Casefolded member sets of the registry's ``distinct`` / ``rejected_aliases``
    groups, each member widened to its canonical name so an alias of a listed
    entity counts too."""
    if registry is None:
        return []
    explicit: dict[str, str] = {}
    for table in registry.explicit_aliases_by_type().values():
        for k, v in table.items():
            explicit.setdefault(k, v)
    groups = []
    for group in [*registry.distinct, *registry.rejected_aliases]:
        members = [{m.strip().casefold(), explicit.get(m.strip().casefold(), m).strip().casefold()} for m in group]
        groups.append(members)
    return groups  # type: ignore[return-value]


def _held_apart(names_a: set[str], names_b: set[str], groups) -> bool:
    for members in groups:
        hit_a = [i for i, m in enumerate(members) if m & names_a]
        hit_b = [i for i, m in enumerate(members) if m & names_b]
        if any(i != j for i in hit_a for j in hit_b):
            return True
    return False


def _locations(obs) -> list[str]:
    return sorted({f"{o.source_file}:{o.line}" for o in obs}, key=_loc_key)


def _loc_key(loc: str) -> tuple:
    f, _, n = loc.rpartition(":")
    return f, int(n) if n.isdigit() else 0


def find_possible_duplicates(observations, registry, rulings: Rulings, threshold: float) -> list[Finding]:
    """List likely duplicate subjects per category. Never crosses categories."""
    groups = _registry_apart(registry)
    out: list[Finding] = []
    for category in CATEGORIES:
        by_subject: dict[str, list] = {}
        for o in observations:
            if o.category == category:
                by_subject.setdefault(o.canonical, []).append(o)
        subjects = sorted(by_subject)
        names = {
            s: {s.casefold(), *(o.heading.strip().casefold() for o in by_subject[s])} for s in subjects
        }
        found: dict[tuple[str, str], tuple[str, float]] = {}

        by_base: dict[str, list[str]] = {}
        for s in subjects:
            by_base.setdefault(_strip_qualifier(s).casefold(), []).append(s)
        for members in by_base.values():
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    if _strip_qualifier(a) == a and _strip_qualifier(b) == b:
                        continue  # case-only difference: the similarity pass lists it
                    found[(a, b)] = ("qualifier", SequenceMatcher(None, a.casefold(), b.casefold()).ratio())

        folded = [s.casefold() for s in subjects]
        sm = SequenceMatcher(autojunk=False)
        for j, b in enumerate(subjects):
            sm.set_seq2(folded[j])
            for i in range(j):
                if (subjects[i], b) in found:
                    continue
                sm.set_seq1(folded[i])
                if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
                    continue
                ratio = sm.ratio()
                if ratio >= threshold:
                    found[(subjects[i], b)] = ("similarity", ratio)

        for (a, b), (reason, ratio) in sorted(found.items()):
            if rulings.rules_out(category, names[a], names[b]):
                continue
            if _held_apart(names[a], names[b], groups):
                continue
            loc_a, loc_b = _locations(by_subject[a]), _locations(by_subject[b])
            first = min(loc_a + loc_b, key=_loc_key)
            f, _, n = first.rpartition(":")
            detail = f"similarity {ratio:.2f}" if reason == "similarity" else f"qualifier; ratio {ratio:.2f}"
            out.append(
                Finding(
                    file=f,
                    line=int(n),
                    code=schema.POSSIBLE_DUPLICATE,
                    message=f"{category}: '{a}' ~ '{b}' ({detail}); fix the summaries or rule it in canon.yaml",
                    expected=None,
                    found=None,
                    blocking=False,
                    in_range=True,
                    locations={a: loc_a, b: loc_b},
                )
            )
    return out


def headings_by_category(observations) -> dict[str, set[str]]:
    """Casefolded headings (as written) and canonical subjects per category."""
    out: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    for o in observations:
        out[o.category].update({o.heading.strip().casefold(), o.canonical.casefold()})
    return out


def headings_of_files(files, grouper) -> dict[str, set[str]]:
    """Like ``headings_by_category`` but over every parsed file, in range or not."""
    out: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    for pf in files:
        for e in pf.entities:
            canonical, _ = grouper(e.category, e.heading)
            out[e.category].update({e.heading.strip().casefold(), canonical.casefold()})
    return out


def stale_rulings(rulings: Rulings, headings: dict[str, set[str]]) -> list[Finding]:
    """A ruling whose heading occurs in no readable summary (any range) is stale (non-blocking)."""
    out: list[Finding] = []
    for category, a, b in rulings.entries:
        present = headings.get(category, set())
        gone = [x for x in (a, b) if x.strip().casefold() not in present]
        if not gone:
            continue
        out.append(
            Finding(
                file=CANON_FILE,
                line=None,
                code=schema.STALE_RULING,
                message=(
                    f"{category}: ruling '{a}' / '{b}' is stale; "
                    f"{', '.join(repr(g) for g in gone)} no longer occurs in any summary"
                ),
                expected=None,
                found=None,
                blocking=False,
                in_range=True,
            )
        )
    return out
