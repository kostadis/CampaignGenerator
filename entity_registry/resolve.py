#!/usr/bin/env python3
"""resolve — read-only name resolution against a campaign's canon chain.

Every campaign's ``CLAUDE.md`` carries the same hard rule: before writing any
proper noun, resolve it against the canonical source chain, and if what you are
about to write deviates from canon, ask the GM. The chain is ordered, first hit
wins:

  1. ``config/party.yaml``                      — PC names
  2. ``notes/vtt_transcription_corrections.md`` — the spell-pass glossary;
                                                  the **bolded** right-hand
                                                  column is canon
  3. ``docs/entity_registry.yaml``              — canonical names + approved
                                                  aliases
  4. ``docs/npcs/<name>.md``                    — a dossier's own STATED ruling
  5. ``notes/vtt_known_additions.md``           — confirmed real, not yet
                                                  promoted

Until now that rule was prose a model was trusted to obey across five files in
four formats, with nothing able to tell afterwards whether the lookup happened.
``resolve_name`` is the lookup as a call. It **reads and reports; it never
writes** — it shares no code path with the five identity-mutating verbs in
``registry.py`` (add / alias / merge / mark-distinct / mark-rejected).

Three outcomes, and the two that are not ``resolved`` are the point:

  ``resolved``   one tier ruled; lower tiers agree or are silent. ``is_change``
                 is True when the canonical form differs from the surface form
                 — the machine-readable "the GM has to see this ruling" flag.
  ``ambiguous``  two tiers disagree. Every source and its spelling is returned
                 and **no ``canonical`` key is emitted at all**, so there is
                 structurally nothing for a caller to apply. Adjudication is
                 the GM's.
  ``not_canon``  absent from all five tiers. ``near_misses`` are returned as
                 candidates to ASK about, never as a resolution. Do not invent
                 a spelling, and do not promote the transcript's majority
                 spelling — a transcript is not an authority.

Identity comparison is ``campaignlib.textproc.norm_subject`` and fuzzy matching
is ``registry.NEAR_MISS_THRESHOLD``, everywhere, with no local variants: a
second normalizer would be a second opinion about identity, which is the exact
thing the registry exists to prevent.

No API calls are made anywhere in this module.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from campaignlib.party import load_pc_names
from campaignlib.registry import Registry, find_registry, load_registry
from campaignlib.textproc import norm_subject

GLOSSARY_REL = Path("notes") / "vtt_transcription_corrections.md"
KNOWN_ADDITIONS_REL = Path("notes") / "vtt_known_additions.md"
DOSSIER_REL = Path("docs") / "npcs"

# ── glossary parsing ─────────────────────────────────────────────────────────
#
# Rows look like:
#
#   | Grygum, Gergam, Graham | **Gyrgum** |
#   | Ebum Mir, Ebonir       | **Ebonmire** (Princess Ebonmire) |
#   | Zuggtomy, Zugtmoy      | **Zuggtmoy** (confirmed via 5etools: MTF + OotA) |
#
# The last two are the hazard this module refuses to solve. Identical syntax,
# different meaning: "(Princess Ebonmire)" is an alias, "(confirmed via
# 5etools...)" is a provenance note. Nothing here classifies them. The bold form
# is the canonical; the parenthetical is returned raw and UNCLASSIFIED for the
# GM to read. A classifier is a small convenience that eventually promotes
# "confirmed via 5etools" into a name, and a fabricated canonical is the most
# expensive error in this system — the whole corpus downstream trusts it.

_CANON_RE = re.compile(r"\*\*(?P<canon>[^*]+)\*\*\s*(?P<paren>\(.*\))?\s*$")

_HEADING_TYPE = {
    "pcs": "pc",
    "npcs and creatures": "npc",
    "npcs": "npc",
    "creatures": "creature",
    "locations": "location",
    "places": "location",
    "items": "item",
    "factions": "faction",
    "deities": "deity",
    "spells": "spell",
}


def _heading_type(heading: str) -> "str | None":
    return _HEADING_TYPE.get(heading.strip().lower())


def parse_glossary(path: Path) -> list[dict]:
    """Parse the spell-pass glossary into row dicts.

    Each row: ``{"wrong": [...], "canonical": str, "parenthetical": str|None,
    "entity_type": str|None, "line": int, "evidence": str}``. Header and
    separator rows are skipped; a right-hand cell with no ``**bold**`` is not a
    ruling and is skipped too.
    """
    if not path.exists():
        return []
    rows: list[dict] = []
    heading = ""
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        left, right = cells[0], cells[1]
        if set(right) <= set("-: "):          # separator row
            continue
        m = _CANON_RE.search(right)
        if not m:                             # header row, or a cell with no ruling
            continue
        rows.append({
            "wrong": [w.strip() for w in left.split(",") if w.strip()],
            "canonical": m.group("canon").strip(),
            "parenthetical": (m.group("paren") or "").strip() or None,
            "entity_type": _heading_type(heading),
            "line": lineno,
            "evidence": line,
        })
    return rows


# ── known-additions parsing ──────────────────────────────────────────────────

_BULLET_RE = re.compile(r"^-\s+\*\*(?P<name>[^*]+)\*\*\s*(?P<rest>.*)$")


def parse_known_additions(path: Path) -> list[dict]:
    """Parse ``- **Name** — note`` bullets out of the known-additions file."""
    if not path.exists():
        return []
    out: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = _BULLET_RE.match(raw.strip())
        if not m:
            continue
        # "**A** / **B** — note" records two surface forms for one entry.
        names = [n.strip() for n in re.findall(r"\*\*([^*]+)\*\*", raw)]
        out.append({
            "names": names or [m.group("name").strip()],
            "note": m.group("rest").strip(" —-"),
            "line": lineno,
            "evidence": raw.strip(),
        })
    return out


# ── dossier frontmatter ──────────────────────────────────────────────────────
#
# campaignlib.npc.parse_dossier falls back to the FILE STEM when frontmatter is
# missing, which is exactly the trap the canon rule names: `docs/party/
# sequioa.md` does not make "Sequioa" canonical. Tier 4 therefore reads the
# frontmatter itself and accepts only an explicitly declared `name:`.

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _dossier_ruling(path: Path) -> "dict | None":
    """``{"name": str, "aliases": [...]}`` if the dossier STATES a name in its
    frontmatter, else None. The filename is never evidence."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    name = meta.get("name")
    if not name:
        return None
    aliases = meta.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    return {"name": str(name), "aliases": [str(a) for a in aliases]}


# ── compatibility (NOT equality) ─────────────────────────────────────────────


_LEADING_ARTICLES = {"the", "a", "an"}


def _tokens(s: str) -> list[str]:
    toks = [t for t in (norm_subject(w) for w in re.split(r"\s+", s.strip())) if t]
    # A leading article is not a spelling difference. The registry carries
    # "the Overbright" where known-additions carries "Overbright"; reporting
    # that as a disagreement fires on every article-prefixed entity in the
    # campaign and drowns the real signal. Dropped for COMPARISON only —
    # nothing here rewrites a stored name.
    if len(toks) > 1 and toks[0] in _LEADING_ARTICLES:
        toks = toks[1:]
    return toks


def compatible(a: str, b: str) -> bool:
    """True when two forms are the same name at different lengths.

    ``config/party.yaml`` carries "Thorin Giantfriend"; the glossary rules on
    "Thorin". That is not a disagreement, and reporting it as one — on every
    single PC name, every time — would train the GM to dismiss the ``ambiguous``
    status, which destroys its value on the cases that are real. One form being
    a leading-token prefix of the other is compatible; anything else is not.
    """
    if norm_subject(a) == norm_subject(b):
        return True
    ta, tb = _tokens(a), _tokens(b)
    if ta == tb:
        return True
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return long_[: len(short)] == short


# ── the five tiers ───────────────────────────────────────────────────────────
#
# Each returns a hit dict or None. ``value`` is that tier's canonical form.
#
# Matching is ``compatible``, not raw key equality, in EVERY tier. The two
# differences it forgives — a trailing surname and a leading article — are
# differences no source disagrees about, and letting one tier forgive them
# while another does not is how the same name resolves at two different tiers
# depending on which form you happened to type.


def _t1_party(campaign_dir: Path, key: str, surface: str) -> "dict | None":
    for name in load_pc_names(campaign_dir):
        if norm_subject(name) == key or compatible(surface, name):
            return {
                "tier": 1,
                "source": "config/party.yaml",
                "value": name,
                "evidence": f"characters[].name: {name}",
                "entity_type": "pc",
            }
    return None


def _t2_glossary(campaign_dir: Path, key: str, surface: str) -> "dict | None":
    path = Path(campaign_dir) / GLOSSARY_REL
    for row in parse_glossary(path):
        hit = compatible(surface, row["canonical"]) or any(
            compatible(surface, w) for w in row["wrong"]
        )
        if not hit:
            continue
        return {
            "tier": 2,
            "source": f"{GLOSSARY_REL.as_posix()}:{row['line']}",
            "value": row["canonical"],
            "evidence": row["evidence"],
            "entity_type": row["entity_type"],
            "parenthetical": row["parenthetical"],
        }
    return None


def _t3_registry(campaign_dir: Path, key: str, surface: str) -> "dict | None":
    reg = _load_registry(campaign_dir)
    if reg is None:
        return None
    for e in reg.entities:
        for candidate in [e.name, *e.aliases]:
            if compatible(surface, candidate):
                return {
                    "tier": 3,
                    "source": "docs/entity_registry.yaml",
                    "value": e.name,
                    "evidence": (
                        f"{e.name}"
                        + (f" (alias: {candidate})" if candidate != e.name else "")
                    ),
                    "entity_type": e.type,
                }
    return None


def _t4_dossier(campaign_dir: Path, key: str, surface: str) -> "dict | None":
    d = Path(campaign_dir) / DOSSIER_REL
    if not d.is_dir():
        return None
    for f in sorted(d.glob("*.md")):
        if ".new_notes." in f.name:
            continue
        ruling = _dossier_ruling(f)
        if ruling is None:                     # states no name — not a ruling
            continue
        for candidate in [ruling["name"], *ruling["aliases"]]:
            if compatible(surface, candidate):
                return {
                    "tier": 4,
                    "source": f"{DOSSIER_REL.as_posix()}/{f.name}",
                    "value": ruling["name"],
                    "evidence": f"frontmatter name: {ruling['name']}",
                    "entity_type": "npc",
                }
    return None


def _t5_known_additions(campaign_dir: Path, key: str, surface: str) -> "dict | None":
    path = Path(campaign_dir) / KNOWN_ADDITIONS_REL
    for entry in parse_known_additions(path):
        for name in entry["names"]:
            if compatible(surface, name):
                return {
                    "tier": 5,
                    "source": f"{KNOWN_ADDITIONS_REL.as_posix()}:{entry['line']}",
                    "value": name,
                    "evidence": entry["evidence"],
                    "entity_type": None,
                    "promoted": False,
                }
    return None


TIERS = [_t1_party, _t2_glossary, _t3_registry, _t4_dossier, _t5_known_additions]

TIER_NAMES = {
    1: "config/party.yaml",
    2: "notes/vtt_transcription_corrections.md (spell-pass glossary)",
    3: "docs/entity_registry.yaml",
    4: "docs/npcs/<name>.md (dossier's stated ruling)",
    5: "notes/vtt_known_additions.md (confirmed, not yet promoted)",
}


def _load_registry(campaign_dir: Path) -> "Registry | None":
    path = find_registry(Path(campaign_dir))
    return load_registry(path) if path is not None else None


# ── near misses ──────────────────────────────────────────────────────────────


def canonical_catalog(campaign_dir: Path) -> list[tuple[str, int, str]]:
    """Every CANONICAL form the chain declares, as (form, tier, source).

    Canonical forms only — the glossary's left-hand column is a list of known
    garblings, and offering one of those as a near miss would be offering a
    misspelling as a candidate answer.
    """
    campaign_dir = Path(campaign_dir)
    out: list[tuple[str, int, str]] = []
    for name in load_pc_names(campaign_dir):
        out.append((name, 1, "config/party.yaml"))
    for row in parse_glossary(campaign_dir / GLOSSARY_REL):
        out.append((row["canonical"], 2, f"{GLOSSARY_REL.as_posix()}:{row['line']}"))
    reg = _load_registry(campaign_dir)
    if reg is not None:
        for e in reg.entities:
            out.append((e.name, 3, "docs/entity_registry.yaml"))
    d = campaign_dir / DOSSIER_REL
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            if ".new_notes." in f.name:
                continue
            ruling = _dossier_ruling(f)
            if ruling is not None:
                out.append((ruling["name"], 4, f"{DOSSIER_REL.as_posix()}/{f.name}"))
    for entry in parse_known_additions(campaign_dir / KNOWN_ADDITIONS_REL):
        for name in entry["names"]:
            out.append((name, 5, f"{KNOWN_ADDITIONS_REL.as_posix()}:{entry['line']}"))
    return out


def higher_authority_drift(campaign_dir: Path, ruling: dict,
                           threshold: float) -> list[dict]:
    """Near-identical but INCOMPATIBLE canonical forms held by a tier that
    outranks the one that ruled.

    This catches the case exact-key matching structurally cannot. Resolving
    "Sequioa" hits a dossier that states "Sequioa" and stops — tier 1 holds
    "Sequoia", but that never matches the surface key, so a chain built only on
    exact lookup would answer "resolved, no change" and wave through precisely
    the transposed-letter pair the canon rule exists to catch.

    Restricted to tiers that OUTRANK the ruling tier, deliberately. Comparing
    every tier against every other would fire on any two similarly-named
    distinct entities and bury the real signal; a lower-trust source disagreeing
    with a higher-trust one is the case that is always worth stopping for.
    """
    ruled_key = norm_subject(ruling["value"])
    out: list[dict] = []
    for form, tier, source in canonical_catalog(campaign_dir):
        if tier >= ruling["tier"]:
            continue
        if compatible(form, ruling["value"]):
            continue
        if SequenceMatcher(None, ruled_key, norm_subject(form)).ratio() >= threshold:
            out.append({"value": form, "tier": tier, "source": source,
                        "evidence": f"{source} → {form}"})
    return out


def near_misses(campaign_dir: Path, surface: str, threshold: float) -> list[dict]:
    """Close-but-not-matching forms from every tier, best first.

    These are CANDIDATES TO ASK THE GM ABOUT. They are never a resolution, and
    a caller that treats the top one as an answer has reintroduced exactly the
    silent-guess failure this module exists to remove.
    """
    key = norm_subject(surface)
    catalog = canonical_catalog(campaign_dir)
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for form, tier, source in catalog:
        cand_key = norm_subject(form)
        if cand_key == key or (form, tier) in seen:
            continue
        seen.add((form, tier))
        ratio = SequenceMatcher(None, key, cand_key).ratio()
        if ratio >= threshold:
            out.append({"candidate": form, "tier": tier, "source": source,
                        "ratio": round(ratio, 3)})
    out.sort(key=lambda d: (-d["ratio"], d["tier"]))
    return out


# ── the entry point ──────────────────────────────────────────────────────────


def resolve_name(campaign_dir: "Path | str", surface: str,
                 threshold: "float | None" = None) -> dict:
    """Walk the canon chain for ``surface`` and report the ruling.

    Read-only. Returns one of three shapes — see the module docstring. The
    ``ambiguous`` shape deliberately carries no ``canonical`` key.
    """
    from .registry import NEAR_MISS_THRESHOLD           # lazy: registry imports us

    campaign_dir = Path(campaign_dir)
    threshold = NEAR_MISS_THRESHOLD if threshold is None else threshold
    key = norm_subject(surface)

    if not key:
        return {"surface_form": surface, "status": "not_canon",
                "reason": "empty after normalization", "near_misses": []}

    hits = [h for h in (t(campaign_dir, key, surface) for t in TIERS) if h]

    if not hits:
        return {
            "surface_form": surface,
            "status": "not_canon",
            "tiers_checked": sorted(TIER_NAMES),
            "near_misses": near_misses(campaign_dir, surface, threshold),
            "guidance": (
                "Absent from all five tiers — NOT canon. Do not invent a spelling "
                "and do not carry the transcript's spelling forward. Surface it to "
                "the GM as a new-name candidate and wait. Any near_misses above are "
                "questions, not answers."
            ),
        }

    ruling, *lower = hits
    conflicts = [
        {"value": h["value"], "tier": h["tier"], "source": h["source"],
         "evidence": h["evidence"]}
        for h in lower if not compatible(h["value"], ruling["value"])
    ]
    conflicts += higher_authority_drift(campaign_dir, ruling, threshold)
    conflicts.sort(key=lambda c: c["tier"])

    if conflicts:
        ruling_as_conflict = {
            "value": ruling["value"], "tier": ruling["tier"],
            "source": ruling["source"], "evidence": ruling["evidence"],
        }
        ranked = sorted([ruling_as_conflict, *conflicts], key=lambda c: c["tier"])
        favoured, others = ranked[0], ranked[1:]
        return {
            "surface_form": surface,
            "status": "ambiguous",
            # No "canonical" key, by design: there is nothing to apply.
            "favoured": favoured,
            "why_favoured": (
                f"tier {favoured['tier']} ({TIER_NAMES[favoured['tier']]}) is the "
                f"highest-authority source that carries a form of this name"
            ),
            "conflicts": others,
            "guidance": (
                "Sources disagree. Do not adjudicate: show the GM each source and "
                "its spelling, say which the chain favours and why, and wait for "
                "the ruling."
            ),
        }

    out = {
        "surface_form": surface,
        "status": "resolved",
        "canonical": ruling["value"],
        "tier": ruling["tier"],
        "authority": ruling["source"],
        "evidence": ruling["evidence"],
        "is_change": not compatible(surface, ruling["value"]),
        "entity_type": ruling.get("entity_type"),
        "parenthetical": ruling.get("parenthetical"),
        "also_found_in": [
            {"tier": h["tier"], "source": h["source"], "value": h["value"]}
            for h in lower
        ],
        "conflicts": [],
        "near_misses": [],
    }
    if ruling["tier"] == 5:
        out["promoted"] = False
    if out["is_change"]:
        out["guidance"] = (
            "This is a name CHANGE. Correct direction, but still a ruling: show it "
            "to the GM with the citing source before or as it lands. A bulk rename "
            "is one ruling to show, not N edits to bury."
        )
    return out


# ── rendering ────────────────────────────────────────────────────────────────


def format_result(r: dict) -> str:
    """Human-readable rendering of a resolve_name result."""
    lines = [f"{r['surface_form']!r} → {r['status'].upper()}"]
    if r["status"] == "resolved":
        lines.append(f"  canonical : {r['canonical']}")
        lines.append(f"  tier      : {r['tier']} — {TIER_NAMES[r['tier']]}")
        lines.append(f"  authority : {r['authority']}")
        lines.append(f"  evidence  : {r['evidence']}")
        lines.append(f"  is_change : {r['is_change']}")
        if r.get("parenthetical"):
            lines.append(
                f"  parenthetical (UNCLASSIFIED — alias or provenance note, "
                f"the GM reads it): {r['parenthetical']}"
            )
        if r.get("promoted") is False:
            lines.append("  promoted  : False — real, but not yet promoted to canon")
        for a in r["also_found_in"]:
            lines.append(f"  also      : tier {a['tier']} {a['source']} → {a['value']}")
    elif r["status"] == "ambiguous":
        f = r["favoured"]
        lines.append("  NO canonical returned — the GM rules on this one.")
        lines.append(f"  favoured  : {f['value']}  (tier {f['tier']}, {f['source']})")
        lines.append(f"  because   : {r['why_favoured']}")
        for c in r["conflicts"]:
            lines.append(f"  conflict  : {c['value']}  (tier {c['tier']}, {c['source']})")
    else:
        for nm in r.get("near_misses", []):
            lines.append(
                f"  near miss : {nm['candidate']}  (tier {nm['tier']}, "
                f"{nm['ratio']}, {nm['source']})"
            )
        if not r.get("near_misses"):
            lines.append("  near miss : none")
    if r.get("guidance"):
        lines.append(f"  → {r['guidance']}")
    return "\n".join(lines)
