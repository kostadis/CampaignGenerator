#!/usr/bin/env python3
"""Aggregate exhaustive atomic facts into per-entity current-state dossiers.

The ensemble (`ensemble_extract.py`) produces tens of thousands of atomic
facts — far too many to feed `synthesise_world_state.py` directly. This script
is the missing COMPRESSION layer: it bundles every fact about one entity and
asks a local model to collapse them into a single current-state dossier
(`distill_extractions` density), with an explicit Uncertainty block so a human
can correct scope/ordering/attribution before the dossiers feed synthesis.

Two stages:

  1. BUNDLE (deterministic, no LLM): group facts by (type, canonical subject),
     ordered by CHAPTER index (not in-world date), keeping only "stateful"
     entity types above a fact-count floor. `--list` stops here so you can see
     exactly what will be aggregated — the human checkpoint on scope.

  2. AGGREGATE (local model): per entity, feed its facts in chapter order to the
     `state_aggregate` prompt -> one dossier .md per entity in --out-dir.

Examples:
  # See the bundles (no model call) — sorted by fact count
  python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' --list

  # Prototype: aggregate one dense entity on the local Spark
  python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' \
      --only Daz --out-dir scratch_output/state-proto \
      --backend dgx --endpoints http://192.168.1.147:8001/v1 \
      --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8

  # Top 10 densest entities
  python facts_to_state.py --corpus '...' --top 10 --out-dir scratch_output/state-proto \
      --backend dgx --endpoints http://192.168.1.147:8001/v1 --model Qwen/...
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import warnings
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from campaignlib import (
    DEFAULT_MODEL,
    atomic_write_text,
    build_batch_request,
    client_from_args,
    load_agent_prompt,
    load_pc_names,
    run_batch,
    stream_api,
)
from campaignlib.api.client import resolve_cli_model
from campaignlib.selection import BACKENDS
from campaignlib.registry import Registry, load_registry, resolve_registry_arg
from .ensemble_merge import _norm_subject
from .synthesise_world_state import (
    expand_globs,
    load_aliases,
    session_index,
    session_label,
)

AGGREGATE_SYSTEM = load_agent_prompt("state_aggregate")

# Entity types worth aggregating into a state model. event/date/thread are
# cross-cutting (history / temporal anchors / mysteries) and handled on a
# separate track, not per-entity.
STATEFUL_TYPES = ["npc", "faction", "location", "object", "monster"]

# Types tracked per-occurrence rather than as one campaign-wide "current
# state." An object ("Spores") or a generic creature ("gray ooze") recurs
# across many separate encounters that each deserve their own bundle; unlike an
# npc/faction/location, there's no single current-state to collapse them into.
# These bypass the --known-only filter so every distinct anonymous
# (location-scoped) encounter still gets aggregated (subject to --min-facts).
OCCURRENCE_SCOPED_TYPES = {"object", "monster"}

_INT_RE = re.compile(r"\d+")


def chapter_num(path: Path) -> int:
    """Integer chapter index from a merged.json's label (gen-ch03 -> 3)."""
    nums = _INT_RE.findall(session_label(path))
    return int(nums[0]) if nums else 0


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "entity"


def _narrative_key(item: tuple[int, dict, str | None]) -> tuple[int, int, int]:
    """Sort key putting a bundle's facts in the order they were narrated.

    Chapter first, then ``quote_offset`` — the character position of the fact's
    source quote inside that chapter, stamped by ``ensemble_merge`` (issue
    #195). Before it existed, facts within a chapter came out in whatever order
    the merge's alphabetical (type, subject, fact) sort left them, so a dossier
    could report an entity's death before its arrival.

    Facts with no offset sort **last** within their chapter, not first: a
    missing offset means the quote could not be located in the source, which is
    the same signal ``quote_verified`` carries — usually a fabricated or
    ``...``-stitched quote. Leading with the least trustworthy facts would be
    the wrong default. Corpora merged before #195 have no offsets at all, so
    they degrade to the previous chapter-only ordering rather than breaking.
    """
    chapter, fact, _location = item
    offset = fact.get("quote_offset")
    return (chapter, 1, 0) if offset is None else (chapter, 0, offset)


class Bundle:
    """All facts about one (type, canonical-subject), in narrative order.

    Each ``fact`` dict is stored and handed back exactly as loaded from
    ``merged.json`` — nothing here rebuilds it from a field whitelist, so any
    key ``ensemble_merge`` stamps (``quote_offset``, and since issue #202
    ``scene_index``, the fact's chunk index — the join key for a future
    scene-narrative pass) survives untouched, including its absence on a
    corpus merged before that stamping existed (``fact.get(...)`` upstream,
    never ``fact["..."]``).
    """

    def __init__(self, type_: str, key: str):
        self.type = type_
        self.key = key
        # Internally a 3-tuple: (chapter, fact, location_or_None).
        # The location is the dominant location of the chapter the fact came
        # from — used only by split_bundle_by_location; ignored elsewhere.
        self.facts: list[tuple[int, dict, str | None]] = []
        self._names: Counter = Counter()

    def add(self, chapter: int, fact: dict, display: str,
            location: str | None = None) -> None:
        self.facts.append((chapter, fact, location))
        self._names[display] += 1

    @property
    def display(self) -> str:
        return self._names.most_common(1)[0][0]

    @property
    def chapters(self) -> tuple[int, int]:
        chs = [c for c, _, _l in self.facts]
        return (min(chs), max(chs))

    def ordered(self) -> list[tuple[int, dict]]:
        """Narrative-ordered (chapter, fact) pairs — backward-compatible API."""
        return [(ch, f) for ch, f, _ in sorted(self.facts, key=_narrative_key)]

    def ordered_with_location(self) -> list[tuple[int, dict, str | None]]:
        """Narrative-ordered (chapter, fact, location) triples."""
        return sorted(self.facts, key=_narrative_key)


def split_bundle_by_gap(b: Bundle, max_gap: int) -> list["Bundle"]:
    """Split b into sub-bundles wherever consecutive chapter numbers gap > max_gap.

    Named individuals typically appear across chapters with small gaps — the
    split leaves them intact. Generic labels ("orc", "guard") appear in
    encounter clusters separated by large gaps; each cluster becomes its own
    dossier so the LLM isn't asked to synthesize a single "state" for multiple
    unrelated individuals. Sub-bundles get a chapter-start suffix in both their
    key and display name so filenames are unique:
      npc_orc.md  →  npc_orc_ch01.md, npc_orc_ch23.md
    """
    ordered = b.ordered()
    if len(ordered) < 2:
        return [b]

    groups: list[list[tuple[int, dict]]] = []
    current: list[tuple[int, dict]] = [ordered[0]]
    for ch, f in ordered[1:]:
        if ch - current[-1][0] > max_gap:
            groups.append(current)
            current = [(ch, f)]
        else:
            current.append((ch, f))
    groups.append(current)

    if len(groups) == 1:
        return [b]

    result = []
    for group in groups:
        start_ch = group[0][0]
        suffix = f" ch{start_ch:02d}"
        new_b = Bundle(b.type, f"{b.key}ch{start_ch:02d}")
        for ch, f in group:
            new_b.add(ch, f, b.display + suffix)
        result.append(new_b)
    return result


_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')


def _stem_words(filename_stem: str, min_len: int = 4) -> list[str]:
    """Normalised tokens from a snake_case filename stem, filtered by min length.

    "adabra"              -> ["adabra"]
    "harbin_wester"       -> ["harbin", "wester"]
    "falcon_the_hunter"   -> ["falcon", "hunter"]   ("the" is too short)
    "alphonse_big_al_x"   -> ["alphonse"]            ("big", "al", "x" too short)
    """
    return [_norm_subject(w) for w in filename_stem.split("_") if len(w) >= min_len]


def load_known_names(sources: list[Path]) -> set[str]:
    """Build a set of normalised names from inventory .md files and .dedup_state.json.

    Inventory markdown (.md):
      - Every **bold** span (proper names and aliases).
      - First word of each multi-word bold name when it is >= 4 chars, so that
        "Adabra Gwynn" also registers "adabra" (catching short-name fact subjects).

    dedup_state.json (.json):
      - Every string in clusters_confirmed[*].aliases_recorded.
      - Each canonical filename stem, split on _ and filtered to words >= 4 chars
        (e.g. "adabra.md" → "adabra"; "harbin_wester.md" → "harbin", "wester").
      - pc_files_skipped stems by the same rule, so PCs that were filtered from
        the dedup pass are still treated as known named individuals here.
    """
    known: set[str] = set()
    for src in sources:
        path = Path(src).expanduser().resolve()
        if not path.exists():
            print(f"  warn: known-names source not found: {path}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
            for cluster in data.get("clusters_confirmed", []):
                for alias in cluster.get("aliases_recorded", []):
                    known.add(_norm_subject(alias))
                canon = cluster.get("canonical", "")
                stem = Path(canon).stem
                known.update(_stem_words(stem))
            for pc_file in data.get("pc_files_skipped", []):
                stem = Path(pc_file).stem
                known.update(_stem_words(stem))
        else:
            for m in _BOLD_RE.finditer(text):
                name = m.group(1).strip()
                if not name:
                    continue
                known.add(_norm_subject(name))
                # First word of multi-word names catches short-name fact subjects
                # (e.g. "Adabra" from "Adabra Gwynn").
                parts = name.split()
                if len(parts) > 1 and len(parts[0]) >= 4:
                    known.add(_norm_subject(parts[0]))
    return known


def _collect_monster_vocab(corpus_paths: list[Path], aliases: dict[str, str]) -> set[str]:
    """Normalised subjects of every type=="monster" fact in the corpus.

    Used to auto-exclude npc-typed subjects that are really generic creatures
    mistagged as npc (e.g. a fact framing "the ghoul" as having agency gets
    type: npc in one chapter and type: monster, correctly, in another).
    """
    # Normalise alias-map keys so a registry/aliases.json entry matches
    # regardless of the raw extracted subject's casing/punctuation (e.g.
    # registry alias "zurkwhood" must still catch extracted subject
    # "Zurkwhood") — canonicals (the dict values) stay exact-case display
    # strings; only the lookup key is normalised.
    aliases = {_norm_subject(k): v for k, v in aliases.items()}
    vocab: set[str] = set()
    for path in corpus_paths:
        try:
            facts = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for f in facts:
            if f.get("type") != "monster":
                continue
            raw = (f.get("subject") or "").strip()
            if raw:
                vocab.add(_norm_subject(aliases.get(_norm_subject(raw), raw)))
    return vocab




def load_bundles(corpus_paths: list[Path], aliases: dict[str, str],
                 types: list[str], split_gap: int | None = None,
                 known_names: set[str] | None = None,
                 exclude_names: set[str] | None = None) -> dict[str, Bundle]:
    """Group facts across all corpus files by (type, canonical subject).

    split_gap   — if set, gap-split bundles whose consecutive chapters exceed
                  this value (see split_bundle_by_gap). Still available but
                  superseded by known_names for most use cases.

    known_names — if set (built by load_known_names), entities whose normalised
                  subject is in this set get a global bundle keyed by
                  (type, subject) — normal behaviour.

    exclude_names — normalised subjects forced anonymous/location-scoped even
                  though they'd otherwise be treated as known. The override in
                  the opposite direction from known_names — for the handful of
                  generic role-phrases (e.g. "Bandit Chief", "the freed
                  prisoner") that aren't unique individuals but also aren't
                  caught by the monster-vocab check below.

    Named-vs-generic split, in order of precedence:
      1. In exclude_names -> anonymous, no matter what.
      2. In known_names -> known.
      3. type == "npc" and NOT also a type=="monster" subject somewhere in the
         corpus -> known. Unlike creatures, a campaign never gives two
         different NPCs the same name (players would confuse them) — so any
         npc-typed subject with a real name is, by construction, a unique
         individual. This makes exhaustively curating every NPC into
         known_names.md unnecessary; it only needs to hold overrides.
      4. Otherwise (non-npc types with no known_names, or explicit known_names
         miss) -> known only if known_names is None.

    Anonymous entities are location-scoped: keyed by
    (type, subject, chapter_dominant_location) instead of (type, subject), so
    e.g. "orc" becomes "Orc (Phandalin)", "Orc (Wayside Inn)" rather than one
    campaign-wide omnibus. Each bundle carries b.known = True/False so callers
    can skip synthesis for unknowns with --known-only.
    """
    bundles: dict[str, Bundle] = {}
    type_set = set(types)
    exclude_names = exclude_names or set()
    # See _collect_monster_vocab's matching comment: normalise alias-map keys
    # so casing/punctuation in the raw extracted subject can't defeat a
    # registry/aliases.json match.
    aliases = {_norm_subject(k): v for k, v in aliases.items()}
    monster_vocab = _collect_monster_vocab(corpus_paths, aliases) if "npc" in type_set else set()
    needs_location_scoping = known_names is not None or "npc" in type_set
    for path in sorted(corpus_paths, key=session_index):
        ch = chapter_num(path)
        try:
            facts = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  warn: skipping {path}: {e}", file=sys.stderr)
            continue

        # Dominant location for this chapter — used to scope anonymous entities.
        if needs_location_scoping:
            loc_counts: Counter = Counter(
                f["subject"] for f in facts if f.get("type") == "location"
            )
            if loc_counts:
                top_raw, _ = loc_counts.most_common(1)[0]
                chapter_loc_norm = _norm_subject(top_raw)
                chapter_loc_display = top_raw
            else:
                chapter_loc_norm = None
                chapter_loc_display = None
        else:
            chapter_loc_norm = None
            chapter_loc_display = None

        for f in facts:
            t = f.get("type", "")
            if t not in type_set:
                continue
            raw = (f.get("subject") or "").strip()
            if not raw:
                continue
            display = aliases.get(_norm_subject(raw), raw)
            norm = _norm_subject(display)
            if not norm:
                continue

            if norm in exclude_names:
                is_known = False
            elif known_names is not None and norm in known_names:
                is_known = True
            elif t == "npc":
                is_known = norm not in monster_vocab
            else:
                is_known = known_names is None

            if is_known:
                gkey = f"{t}\x00{norm}"
                display_for_bundle = display
            else:
                # Location-scope anonymous entities so each encounter site gets
                # its own bundle rather than one omnibus dossier for all "orc"s.
                loc_key = chapter_loc_norm or "unknown"
                gkey = f"{t}\x00{norm}\x00{loc_key}"
                loc_label = chapter_loc_display or "unknown location"
                display_for_bundle = f"{display} ({loc_label})"

            b = bundles.get(gkey)
            if b is None:
                b = bundles[gkey] = Bundle(t, norm)
                b.known = is_known  # type: ignore[attr-defined]
            b.add(ch, f, display_for_bundle, location=chapter_loc_norm)

    if split_gap is not None:
        expanded: dict[str, Bundle] = {}
        for b in bundles.values():
            for sub in split_bundle_by_gap(b, split_gap):
                sub.known = getattr(b, "known", True)  # type: ignore[attr-defined]
                expanded[f"{sub.type}\x00{sub.key}"] = sub
        return expanded

    return bundles


def select(bundles: dict[str, Bundle], min_facts: int, only: str | None,
           top: int | None, known_only: bool = False,
           known_names: set[str] | None = None) -> list[Bundle]:
    """min_facts is waived for entities in known_names (--known-names /
    --registry): once a source enumerates the known-entity universe, a real
    hit count of 1 is signal enough — the floor exists to filter noise out of
    the *unscoped* pool, not to second-guess a ground-truth roster. Bundles
    forced anonymous via --exclude-names (known=False) don't get the waiver
    even if their key happens to also appear in known_names."""
    def meets_floor(b: Bundle) -> bool:
        if known_names is not None and getattr(b, "known", True) and b.key in known_names:
            return True
        return len(b.facts) >= min_facts

    items = [b for b in bundles.values() if meets_floor(b)]
    if known_only:
        items = [b for b in items if b.type in OCCURRENCE_SCOPED_TYPES
                 or getattr(b, "known", True)]
    if only is not None:
        target = _norm_subject(only)
        items = [b for b in items if b.key == target or b.key.startswith(target + "\x00")]
    items.sort(key=lambda b: (-len(b.facts), b.type, b.display.lower()))
    if top is not None:
        items = items[:top]
    return items


def build_user_prompt(b: Bundle, with_quotes: bool) -> str:
    lo, hi = b.chapters
    span = f"chapter {lo}" if lo == hi else f"chapters {lo}-{hi}"
    head = (f"ENTITY: {b.display}   (type: {b.type})\n"
            f"{len(b.facts)} fact(s) across {span}.\n\n"
            "FACTS (chronological — earliest chapter first; later overrides "
            "earlier for current state):\n")
    lines = [head]
    for ch, f in b.ordered():
        lines.append(f"- [ch{ch:02d}] {f.get('fact', '').strip()}")
        if with_quotes:
            q = " ".join((f.get("source_quote") or "").split())
            if q:
                lines.append(f'  > "{q}"')
    return "\n".join(lines)


def dossier_path(out_dir: Path, b: Bundle) -> Path:
    return out_dir / f"{b.type}_{slugify(b.display)}.md"


def render_bundles(bundles: list[Bundle], with_quotes: bool) -> str:
    """Deterministic markdown dump of bundles, grouped by type then subject,
    facts in chapter order. Used for the cross-cutting threads/events track —
    facts that don't aggregate per-entity but feed the synthesis directly."""
    by_type: dict[str, list[Bundle]] = {}
    for b in bundles:
        by_type.setdefault(b.type, []).append(b)
    out: list[str] = []
    for t in sorted(by_type):
        out.append(f"## {t.title()}s\n")
        for b in sorted(by_type[t], key=lambda b: b.display.lower()):
            out.append(f"### {b.display}")
            for ch, f in b.ordered():
                out.append(f"- [ch{ch:02d}] {f.get('fact', '').strip()}")
                if with_quotes:
                    q = " ".join((f.get("source_quote") or "").split())
                    if q:
                        out.append(f'  > "{q}"')
            out.append("")
    return "\n".join(out)


def write_dossier(out_dir: Path, b: Bundle, body: str) -> Path:
    lo, hi = b.chapters
    fm = (f"---\nname: {b.display}\ntype: {b.type}\n"
          f"n_facts: {len(b.facts)}\nchapters: {lo}-{hi}\n---\n\n")
    dest = dossier_path(out_dir, b)
    atomic_write_text(dest, fm + body.strip() + "\n")  # FR-014: atomic publish
    return dest


def check_batch_backend(args: argparse.Namespace) -> None:
    """Fail fast (FR-003) if --batch is combined with a non-anthropic backend.

    Duplicates campaignlib.api.client.client_from_args's own anthropic-only
    check — same CG_BACKEND-aware precedence, same message — rather than
    calling client_from_args itself: client_from_args's happy path
    constructs a real client, which would force `--batch --list` (a
    deliberately network-free dry run — the human checkpoint on scope, see
    the module docstring) to require an API key just to be rejected-or-not.
    Message wording/precedence must stay byte-identical with the
    registrar's version; tests/test_facts_to_state.py checks both directly.
    """
    if not getattr(args, "batch", False):
        return
    arg_backend = getattr(args, "backend", "anthropic")
    resolved_backend = (
        arg_backend if arg_backend != "anthropic"
        else (os.environ.get("CG_BACKEND") or "anthropic")
    )
    if resolved_backend != "anthropic":
        raise SystemExit(
            "--batch requires the Claude API backend (--backend anthropic); "
            f"backend '{resolved_backend}' has no batch support"
        )


# ── Coverage report (issue #201) ─────────────────────────────────────────────
#
# Two failure modes the aggregation stage above cannot see on its own:
#
#   1. HEARSAY DOSSIERS — a known npc/monster bundle exists, but almost
#      everything known about the entity was said by *other* entities' facts,
#      not its own. Moziqodo (issue #195) is the case that drove this: the
#      one fact filed directly under his name got his fate backwards, while
#      the two correct readings landed under other entities' subjects and
#      never touched his dossier.
#   2. ZERO-FACT ENTITIES — an entity the registry knows about that never
#      once appears as a fact SUBJECT. It has no bundle, so section 1
#      (which iterates bundles) structurally cannot see it; only iterating
#      the registry finds it. Khaem is the purest case: 0 own facts, 18
#      mentions, no dossier exists.
#
# These are report-only. Per this repo's LLM Pipeline Design Rule, scope is a
# precision decision — the report flags absence, a human decides what (if
# anything) to do about it. Nothing here writes a stub dossier.


class FactRef(NamedTuple):
    """One fact, corpus-wide, independent of --types/known-name filtering.

    Mention-scanning needs every fact regardless of type — a mention of a
    hearsay npc can land inside a location, event, or thread fact just as
    easily as an npc fact — so this is built by a dedicated pass, not
    filtered from load_bundles's output.
    """

    chapter: int
    subject_norm: str
    text: str


class MentionCandidate(NamedTuple):
    """What count_mentions needs to search for one entity.

    self_key is the entity's own normalised name, used to skip counting the
    entity's own facts as "mentions of itself" — deliberately NOT type-
    qualified: an npc-typed and monster-typed bundle for the same person
    share one self_key, so a monster-typed fact about Moziqodo doesn't count
    as someone else talking about him.
    """

    self_key: str
    variants: list[str]


_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def load_all_facts(corpus_paths: list[Path], aliases: dict[str, str]) -> list[FactRef]:
    """Every fact in the corpus, canonical-subject-tagged and chapter-stamped.

    Unlike load_bundles, nothing is filtered by --types or known/anonymous
    status — mention-scanning needs the full corpus, since a hearsay entity's
    name can appear in a fact of any type. Subject canonicalisation mirrors
    load_bundles's own two-liner exactly (same aliases input) so "mentioned
    under a different entity" means the same thing in both places.
    """
    aliases_by_norm = {_norm_subject(k): v for k, v in aliases.items()}
    out: list[FactRef] = []
    for path in sorted(corpus_paths, key=session_index):
        ch = chapter_num(path)
        try:
            facts = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  warn: skipping {path}: {e}", file=sys.stderr)
            continue
        for f in facts:
            text = (f.get("fact") or "").strip()
            if not text:
                continue
            raw = (f.get("subject") or "").strip()
            display = aliases_by_norm.get(_norm_subject(raw), raw) if raw else ""
            out.append(FactRef(ch, _norm_subject(display), text))
    return out


def build_alias_variants(aliases: dict[str, str]) -> dict[str, list[str]]:
    """Invert the resolved variant->canonical alias map: {canonical: [variants]}.

    Excludes the self-mapped canonical entry. Lets mention-search widen past a
    bundle's single display name to every surface form the alias map (registry
    or legacy) already knows about, per "use the alias map already resolved in
    facts_to_state" (issue #201).
    """
    variants: dict[str, list[str]] = {}
    for variant, canonical in aliases.items():
        if variant == canonical:
            continue
        variants.setdefault(canonical, []).append(variant)
    return variants


def _build_token_index(facts: list[FactRef]) -> dict[str, list[int]]:
    """word -> [fact indices whose text contains it], for O(1) candidate shortlisting.

    A naive per-candidate substring/regex scan of the whole corpus is
    O(candidates x facts); with hundreds of candidates and tens of thousands
    of facts that's slow enough to matter. This index lets count_mentions
    shortlist, per name variant, only the facts that could possibly match
    before running the precise word-boundary regex.
    """
    index: dict[str, list[int]] = {}
    for i, f in enumerate(facts):
        for tok in _tokenize(f.text):
            index.setdefault(tok, []).append(i)
    return index


def count_mentions(
    facts: list[FactRef],
    candidates: dict[str, MentionCandidate],
    token_index: dict[str, list[int]] | None = None,
) -> dict[str, tuple[int, int | None]]:
    """For each candidate key, (mention_count, last_mention_chapter).

    A mention is a fact whose (canonicalised) subject differs from the
    candidate's own name, and whose text contains one of the candidate's name
    variants as a whole word (case-insensitive). Counted per FACT, not per
    occurrence — a name appearing twice in one fact's text is one mention.
    last_mention_chapter is None when the candidate has zero mentions.
    """
    if token_index is None:
        token_index = _build_token_index(facts)

    results: dict[str, tuple[int, int | None]] = {}
    for key, cand in candidates.items():
        seen: set[int] = set()
        last_chapter: int | None = None
        for variant in cand.variants:
            variant = variant.strip()
            words = _WORD_RE.findall(variant.lower())
            if not words:
                continue
            shortlist: set[int] | None = None
            for w in words:
                idxs = token_index.get(w)
                if not idxs:
                    shortlist = set()
                    break
                s = set(idxs)
                shortlist = s if shortlist is None else (shortlist & s)
                if not shortlist:
                    break
            if not shortlist:
                continue
            pattern = re.compile(r"\b" + re.escape(variant) + r"\b", re.IGNORECASE)
            for i in shortlist:
                if i in seen:
                    continue
                f = facts[i]
                if f.subject_norm == cand.self_key:
                    continue  # own fact under another type tag, not a mention
                if pattern.search(f.text):
                    seen.add(i)
                    if last_chapter is None or f.chapter > last_chapter:
                        last_chapter = f.chapter
        results[key] = (len(seen), last_chapter)
    return results


class CoverageEntry(NamedTuple):
    type: str  # "npc", "monster", or "npc+monster" when collapsed across both
    key: str
    display: str
    own_facts: int
    mentions: int
    last_chapter: int | None  # max(own last chapter, last mention chapter)


class HearsayCoverage(NamedTuple):
    """compute_hearsay_coverage's result, plus the visibility count Fix 1
    (peer review of this branch) asked for: filtering silently is how #194's
    dossier floor shipped a hidden-loss bug in the first place, so the count
    of candidates a gate removed travels with the result rather than
    vanishing into it."""

    entries: list[CoverageEntry]
    n_dropped_unregistered: int


def compute_hearsay_coverage(
    bundles: dict[str, "Bundle"],
    all_facts: list[FactRef],
    alias_variants: dict[str, list[str]],
    min_mentions: int = 3,
    max_own_facts: int = 2,
    token_index: dict[str, list[int]] | None = None,
    registry: Registry | None = None,
    require_registered: bool = True,
) -> HearsayCoverage:
    """Section 1 — thin-but-present npc/monster entities (issue #201).

    ``bundles`` MUST already be scoped to types=["npc", "monster"] (the
    caller's job, typically via a dedicated load_bundles(...,
    types=["npc","monster"]) call independent of whatever --types the main
    aggregation run used) — a raw own-vs-mentioned ratio over every type does
    NOT work: the top hits are concepts like "Madness" (0 own / 259
    mentions) that are *supposed* to be heavily referred to. Type-scoping the
    candidates, not the mention text, is what makes the signal usable.

    Anonymous/location-scoped bundles (b.known is False) are never
    candidates — "Orc (Phandalin)" isn't a mis-attributed individual, it's
    already correctly generic.

    Type-scoping the bundle isn't quite enough on a real corpus: extraction
    occasionally mistags a single fact under type npc/monster for something
    that is unambiguously NOT an individual elsewhere in the record — e.g.
    "Underdark" (a registered *location*, well-attested under that type)
    picking up one stray type=monster fact somewhere, or "Lolth"/"Tiamat"
    (registered *deities*) picking up a type=npc fact. Those aren't hearsay
    npcs, they're mistagging artifacts, and they otherwise dominate the report
    (a region or archdevil's name appears constantly). If ``registry`` is
    given, a candidate whose name IS a registered entity is dropped when the
    registry's OWN declared type for it isn't "npc" — the registry is this
    repo's single source of truth for entity identity (CLAUDE.md), so its
    type call wins over a single extraction lens's stray tag.

    ``require_registered`` (default True): when ``registry`` is given, a
    candidate must ALSO actually be a registered entity, not merely absent
    from the type-mismatch above. On a real corpus, unregistered npc/monster-
    typed subjects are dominated by extraction noise the lens mistook for a
    name — pronouns ("she"), collective/role phrases ("The Party", "Dwarf",
    "assassins") — which otherwise bury the genuine hits (Moziqodo, Whistler,
    ...) under hundreds of mentions apiece. Pass ``require_registered=False``
    (``--coverage-unregistered``) to see the raw, unfiltered set instead — a
    campaign with no registry, or a known-incomplete one, has no other way to
    surface an unregistered hearsay entity. A no-op when ``registry`` is
    None: there is nothing to require membership in.
    """
    registry_type_of: dict[str, str] = {}
    if registry is not None:
        registry_type_of = {_norm_subject(e.name): e.type for e in registry.entities}
    require_registered = require_registered and registry is not None

    # Group by the PLAIN (type-independent) key first: the same person can
    # produce separate npc- and monster-typed bundles (seen on the OOTA
    # corpus for Whistler, Malfire, Yestabrod, Araumycos) and must be
    # reported once, not twice with an identical mention count under two
    # rows — the design doc explicitly warns against double-counting an
    # entity that appears under two types.
    grouped: dict[str, dict] = {}
    n_dropped_unregistered = 0
    for b in bundles.values():
        if b.type not in ("npc", "monster"):
            continue
        if not getattr(b, "known", True):
            continue
        reg_type = registry_type_of.get(b.key)
        if reg_type is not None and reg_type != "npc":
            continue  # registered as something else -- a cross-type mistag, not hearsay
        if reg_type is None and require_registered:
            n_dropped_unregistered += 1
            continue
        g = grouped.setdefault(b.key, {"types": set(), "own": 0, "display": b.display,
                                       "bundles": []})
        g["types"].add(b.type)
        g["own"] += len(b.facts)
        g["bundles"].append(b)
        if len(b.facts) >= max((len(x.facts) for x in g["bundles"][:-1]), default=0):
            g["display"] = b.display  # denser bundle's casing wins ties too

    candidates: dict[str, MentionCandidate] = {
        key: MentionCandidate(self_key=key,
                              variants=[g["display"], *alias_variants.get(g["display"], [])])
        for key, g in grouped.items()
    }

    mentions = count_mentions(all_facts, candidates, token_index=token_index)

    out: list[CoverageEntry] = []
    for key, g in grouped.items():
        own = g["own"]
        if own > max_own_facts:
            continue
        n_mentions, last_mention_ch = mentions.get(key, (0, None))
        if n_mentions < min_mentions:
            continue
        hi = max(b.chapters[1] for b in g["bundles"])
        last_chapter = hi if last_mention_ch is None else max(hi, last_mention_ch)
        type_label = "+".join(t for t in ("npc", "monster") if t in g["types"])
        out.append(CoverageEntry(type_label, key, g["display"], own, n_mentions, last_chapter))
    out.sort(key=lambda e: (-e.mentions, e.own_facts, e.display.lower()))
    return HearsayCoverage(out, n_dropped_unregistered)


def compute_zero_fact_coverage(
    bundles: dict[str, "Bundle"],
    registry: Registry,
    all_facts: list[FactRef],
    alias_variants: dict[str, list[str]],
    min_mentions: int = 3,
    types: frozenset = frozenset({"npc"}),
    token_index: dict[str, list[int]] | None = None,
) -> list[CoverageEntry]:
    """Section 2 — registry entities that never appear as a fact subject at all
    (issue #201). They have no bundle, so section 1 (which iterates bundles)
    structurally cannot see them; this iterates the REGISTRY instead — the
    asymmetry the issue is named for.

    ``bundles`` should be the same npc/monster-scoped set section 1 uses.
    Registry entity types don't include "monster" (see
    campaignlib.registry.VALID_TYPES), so this defaults to "npc" only — the
    closest analogue to section 1's npc/monster scope.

    ``min_mentions`` still applies here: a registry entity with zero own
    facts AND zero (or few) mentions never surfaced in the corpus at all,
    which isn't the "referred-to but never grounded" condition this report
    exists to flag.
    """
    present = {b.key for b in bundles.values()}
    candidates: dict[str, MentionCandidate] = {}
    display_of: dict[str, str] = {}
    for e in registry.entities:
        if e.type not in types:
            continue
        key = _norm_subject(e.name)
        if not key or key in present:
            continue
        candidates[key] = MentionCandidate(
            self_key=key,
            variants=[e.name, *alias_variants.get(e.name, [])],
        )
        display_of[key] = e.name

    mentions = count_mentions(all_facts, candidates, token_index=token_index)

    out: list[CoverageEntry] = []
    for key in candidates:
        n_mentions, last_chapter = mentions.get(key, (0, None))
        if n_mentions < min_mentions:
            continue
        out.append(CoverageEntry("npc", key, display_of[key], 0, n_mentions, last_chapter))
    out.sort(key=lambda e: (-e.mentions, e.display.lower()))
    return out


def recency_cutoff(latest_chapter: int, recent_window: int) -> int | None:
    """First chapter counted as "recent" — mirrors
    synthesise_world_state.split_dossiers's cutoff formula (issue #194 / PR
    #196), recomputed here directly from the bundle/mention data --list
    already has rather than requiring dossiers to already be on disk.
    recent_window <= 0 means every chapter counts as recent (no cutoff)."""
    return latest_chapter - recent_window + 1 if recent_window > 0 else None


def flag_recent(entries: list[CoverageEntry], cutoff: int | None) -> list[CoverageEntry]:
    """Section 3 — entries from section 1 or 2 whose last-touched chapter falls
    inside the recency window: "check these before regenerating" (issue #201)."""
    if cutoff is None:
        return list(entries)
    return [e for e in entries if e.last_chapter is not None and e.last_chapter >= cutoff]


class CoverageResult(NamedTuple):
    hearsay: list[CoverageEntry]
    zero_fact: list[CoverageEntry]
    latest_chapter: int
    n_dropped_unregistered: int


def compute_coverage(
    corpus_paths: list[Path],
    aliases: dict[str, str],
    known_names: set[str] | None,
    registry: Registry | None,
    min_mentions: int = 3,
    max_own_facts: int = 2,
    registry_types: frozenset = frozenset({"npc"}),
    exclude_names: set[str] | None = None,
    require_registered: bool = True,
) -> CoverageResult:
    """Run both coverage sections.

    zero_fact is [] when registry is None — section 2 has no roster to
    iterate without one (--list still runs; the report says so).

    exclude_names is the SAME --exclude-names set main() already builds for
    the aggregation path (location_scoped_races.md-shaped files): a name the
    GM has already ruled "not a unique individual" (a race/collective like
    "Derro", a recurring item-species) must not become a hearsay candidate
    here either, or coverage would flag exactly the noise --exclude-names
    exists to suppress everywhere else in this file.

    require_registered is forwarded to compute_hearsay_coverage — see its
    docstring. Default True; --coverage-unregistered flips it off.
    """
    coverage_bundles = load_bundles(corpus_paths, aliases, ["npc", "monster"],
                                    known_names=known_names,
                                    exclude_names=exclude_names)
    all_facts = load_all_facts(corpus_paths, aliases)
    token_index = _build_token_index(all_facts)
    alias_variants = build_alias_variants(aliases)
    latest_chapter = max((chapter_num(p) for p in corpus_paths), default=0)

    hearsay, n_dropped_unregistered = compute_hearsay_coverage(
        coverage_bundles, all_facts, alias_variants,
        min_mentions=min_mentions, max_own_facts=max_own_facts,
        token_index=token_index, registry=registry,
        require_registered=require_registered)

    zero_fact: list[CoverageEntry] = []
    if registry is not None:
        zero_fact = compute_zero_fact_coverage(
            coverage_bundles, registry, all_facts, alias_variants,
            min_mentions=min_mentions, types=registry_types,
            token_index=token_index)

    return CoverageResult(hearsay, zero_fact, latest_chapter, n_dropped_unregistered)


def render_coverage_report(
    hearsay: list[CoverageEntry],
    zero_fact: list[CoverageEntry],
    registry_available: bool,
    latest_chapter: int,
    recent_window: int,
    min_mentions: int,
    max_own_facts: int,
    n_dropped_unregistered: int = 0,
    require_registered: bool = True,
) -> str:
    """Deterministic markdown-ish report text — no model call (issue #201 is a
    report, not a render; "LLM renders, humans decide")."""
    cutoff = recency_cutoff(latest_chapter, recent_window)
    lines = [
        "=" * 60,
        "COVERAGE REPORT (issue #201) — report only, writes nothing",
        "",
        f"Hearsay npc/monster ({len(hearsay)}) — >= {min_mentions} mention(s) in "
        f"other entities' facts, <= {max_own_facts} own:",
    ]
    if registry_available:
        if require_registered:
            lines.append(f"  (requires --registry membership; "
                         f"{n_dropped_unregistered} unregistered candidate(s) dropped -- "
                         f"pass --coverage-unregistered to include them)")
        else:
            lines.append("  (--coverage-unregistered: unregistered candidates included, "
                         "no registration filter applied)")
    if hearsay:
        for e in hearsay:
            lines.append(f"  {e.mentions:>4} mentions / {e.own_facts:>2} own   "
                        f"{e.type:11s} {e.display}  (last touched ch {e.last_chapter})")
    else:
        lines.append("  (none)")
    lines.append("")

    if registry_available:
        lines.append(f"Zero-own-fact registry entities ({len(zero_fact)}) — never a "
                     f"fact subject; no bundle, no dossier exists:")
        if zero_fact:
            for e in zero_fact:
                lines.append(f"  {e.mentions:>4} mentions /  0 own   npc       "
                            f"{e.display}  (last mentioned ch {e.last_chapter})")
        else:
            lines.append("  (none)")
    else:
        lines.append("Zero-own-fact registry entities: skipped (no --registry resolved).")
    lines.append("")

    flagged = flag_recent(hearsay + zero_fact, cutoff)
    if cutoff is None:
        lines.append(f"Recency window: --recent-window {recent_window} "
                     "(0 = every chapter counts as recent).")
    else:
        lines.append(f"Recency window: last {recent_window} chapter(s) = "
                     f"chapters {cutoff}-{latest_chapter} (latest chapter = {latest_chapter}).")
    if flagged:
        names = ", ".join(f"{e.display} (ch{e.last_chapter})" for e in flagged)
        lines.append(f"Check these before regenerating — {len(flagged)} fall inside "
                     f"the window: {names}")
    else:
        lines.append("Nothing above falls inside the window.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", required=True, nargs="+", metavar="GLOB",
                   help="merged.json glob(s) (e.g. 'scratch_output/full-oota/gen-ch*/merged.json')")
    p.add_argument("--out-dir", metavar="DIR",
                   help="Where to write per-entity dossiers (required unless --list)")
    p.add_argument("--aliases", metavar="FILE", default=None,
                   help="aliases.json ({canonical: [variants]}) for subject canonicalisation")
    p.add_argument("--registry", metavar="PATH", default=None,
                   help="Entity registry (docs/entity_registry.yaml) as the single source "
                        "for aliases + known-names. Supersedes --aliases/--known-names.")
    p.add_argument("--types", nargs="+", default=STATEFUL_TYPES, metavar="TYPE",
                   help=f"Entity types to aggregate (default: {' '.join(STATEFUL_TYPES)})")
    p.add_argument("--min-facts", type=int, default=3, metavar="N",
                   help="Only aggregate entities with at least N facts (default 3); "
                        "below this there's nothing to collapse. Waived for "
                        "entities in --known-names/--registry — a known entity "
                        "always gets a dossier, even with just 1 fact.")
    p.add_argument("--split-gap", type=int, default=None, metavar="N",
                   help="Split any bundle whose consecutive-chapter gap exceeds N "
                        "into separate sub-bundles. Heuristic fallback; prefer "
                        "--known-names for campaigns with inventory files.")
    p.add_argument("--known-names", nargs="+", action="extend", default=[], metavar="FILE",
                   help="One or more inventory .md files (bold-marked proper nouns) "
                        "and/or .dedup_state.json files. Entities whose normalised "
                        "name appears in any of these are treated as named "
                        "individuals (global bundle, full dossier). For non-npc "
                        "types, everything else is anonymous and scoped to the "
                        "chapter's dominant location (e.g. 'orc' becomes 'Orc "
                        "(Phandalin)', 'Orc (Wayside Inn)'); npc-typed subjects are "
                        "known by default regardless (see --types), so this mainly "
                        "adds locations/factions/objects and any npc overrides. Use "
                        "--known-only to skip synthesis for anonymous bundles.")
    p.add_argument("--exclude-names", nargs="+", action="extend", default=[], metavar="FILE",
                   help="Same file format as --known-names, but the inverse: forces "
                        "these normalised names to anonymous/location-scoped even "
                        "though they'd otherwise qualify as known. For npc, every "
                        "named subject is known by default (see --types), so use "
                        "this for the residual generic role-phrases that slip "
                        "through as npc facts (e.g. 'Bandit Chief', 'the freed "
                        "prisoner') and aren't already caught by the automatic "
                        "monster-vocabulary check.")
    p.add_argument("--known-only", action="store_true",
                   help="With --known-names: synthesize dossiers only for known "
                        "(named) entities; print anonymous bundles in --list but "
                        "skip them for LLM aggregation. They remain available for "
                        "a later dedup pass. Exception: object- and monster-typed "
                        "bundles are occurrence-scoped (see OCCURRENCE_SCOPED_TYPES) "
                        "and always aggregated regardless of known/anonymous status, "
                        "since every distinct object/creature encounter is tracked "
                        "separately rather than collapsed into one current-state.")
    p.add_argument("--only", metavar="NAME", default=None,
                   help="Aggregate only the entity whose normalised name matches NAME (prototype).")
    p.add_argument("--top", type=int, default=None, metavar="N",
                   help="Aggregate only the N densest entities (prototype).")
    p.add_argument("--list", action="store_true",
                   help="Stage 1 only: print the selected bundles (no model call). "
                        "The human checkpoint on what will be aggregated.")
    p.add_argument("--coverage", action="store_true",
                   help="With --list: append a coverage report (issue #201) flagging "
                        "(1) known npc/monster entities heavily referenced in OTHER "
                        "entities' facts but thin or absent in their own -- hearsay "
                        "dossiers, the Moziqodo/#195 failure mode -- and (2) --registry "
                        "entities that never appear as a fact subject at all, so no "
                        "bundle and no dossier is possible (section 2 needs --registry; "
                        "skipped with a note otherwise). Report only -- writes nothing, "
                        "decides nothing. Off by default: it's a second, heavier corpus "
                        "pass most --list invocations (tuning --min-facts/--only/--top) "
                        "don't want paying for.")
    p.add_argument("--hearsay-min-mentions", type=int, default=3, metavar="N",
                   help="--coverage: flag an entity only with >= N mentions in OTHER "
                        "entities' facts (default 3). Applies to both coverage "
                        "sections.")
    p.add_argument("--hearsay-max-own-facts", type=int, default=2, metavar="N",
                   help="--coverage: cap on a section-1 (npc/monster bundle) entity's "
                        "own fact count to still count as hearsay (default 2). Section "
                        "2 (zero-fact registry entities) always qualifies by definition.")
    p.add_argument("--coverage-unregistered", action="store_true",
                   help="--coverage: include section-1 candidates that are NOT in "
                        "--registry (default: require registry membership). On a real "
                        "corpus, unregistered npc/monster-typed subjects are dominated "
                        "by extraction noise -- pronouns, collective/role phrases like "
                        "'The Party' or 'the gate warden' -- that bury genuine hearsay "
                        "individuals under hundreds of mentions apiece. Pass this for a "
                        "campaign with no registry, or one known to be incomplete, where "
                        "an unregistered hearsay entity would otherwise never surface. "
                        "No-op without --registry (there is nothing to require "
                        "membership in either way).")
    p.add_argument("--recent-window", type=int, default=4, metavar="N",
                   help="--coverage: flag section-1/2 entities last touched or "
                        "mentioned within the last N chapters as 'check before "
                        "regenerating' (default 4, matching ensemble.yaml's "
                        "tuning.dossier_recent_window default). Same recency concept "
                        "as synthesise_world_state.py's --recent-window (issue #194 / "
                        "PR #196), computed independently here from --list's own "
                        "bundle/mention data rather than requiring dossiers already on "
                        "disk. 0 = every chapter counts as recent.")
    p.add_argument("--render-only", metavar="FILE", default=None,
                   help="Deterministic dump of the selected bundles to FILE as "
                        "grouped markdown (no model call). Used to build the "
                        "cross-cutting threads/events track for synthesis "
                        "(e.g. --types thread --min-facts 2 --render-only threads.md).")
    p.add_argument("--quotes", action=argparse.BooleanOptionalAction, default=True,
                   help="Include source_quote lines in the model input (default on).")
    # Declared directly rather than via campaignlib.api.client.add_backend_args(
    # — that helper also registers a singular --endpoint, which would collide
    # with this script's own fan-out --endpoints (plural, one client per
    # worker thread; see client_from_args(args, endpoint=...) in the worker
    # pool below).
    p.add_argument("--backend", choices=BACKENDS,
                   default="anthropic",
                   help="LLM backend (default: anthropic). Combine with --endpoints "
                        "for --backend dgx.")
    p.add_argument("--endpoints", nargs="+", default=None, metavar="URL",
                   help="Multiple OpenAI-compatible endpoints to fan out across "
                        "concurrently (one worker per endpoint, work-stealing). "
                        "All must serve --model.")
    # Wording copied verbatim from campaignlib.api.client.add_backend_args's
    # --batch (not delegated to it — see the --backend/--endpoints comment
    # above; this hand-rolled parser can't call add_backend_args without
    # colliding on --endpoint). tests/test_facts_to_state.py asserts the two
    # stay in sync.
    p.add_argument(
        "--batch", action="store_true", default=False,
        help="Process Claude API calls through the Message Batches API (50%% "
             "token cost, asynchronous; blocks and polls until complete). "
             "Anthropic backend only. Unrelated to ensemble_batch (local "
             "dispatch).")
    p.add_argument("--entity-parallel", type=int, default=None, metavar="N",
                   help="Number of entities to aggregate concurrently (default: one per endpoint). "
                        "Set higher than the endpoint count to parallelise on a single endpoint.")
    p.add_argument("--model", default=None, metavar="ID",
                   help=f"Model id (default: $DGX_MODEL on a DGX endpoint, else {DEFAULT_MODEL}).")
    p.add_argument("--max-tokens", type=int, default=8000, metavar="N",
                   help="max_tokens per aggregation call (default 8000).")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.model = resolve_cli_model(
        args, legacy_default=None
    ).effective_model

    # Fail fast (FR-003), once, before any corpus/registry loading or
    # worker-thread creation below — the worker pool's per-thread
    # client_from_args(args, endpoint=...) call would otherwise raise this
    # same rejection too, but only after N threads had already started (and,
    # in --list/--render-only mode, wouldn't run at all). No-op when --batch
    # is absent, so the DGX --endpoints fan-out is unaffected.
    check_batch_backend(args)

    if not args.list and not args.render_only and not args.out_dir:
        parser.error("--out-dir is required unless --list / --render-only")
    if args.coverage and not args.list:
        parser.error("--coverage only applies with --list (issue #201's coverage "
                     "report is a --list extension, not a standalone mode)")

    corpus = expand_globs(args.corpus)
    if not corpus:
        print("Error: no corpus files matched.", file=sys.stderr)
        sys.exit(1)
    registry_path, campaign_dir, explicit_registry = resolve_registry_arg(
        args.registry, bool(args.aliases or args.known_names), parser)

    known_names: set[str] | None
    reg: Registry | None = None
    if registry_path is not None:
        if explicit_registry and (args.aliases or args.known_names):
            parser.error("--registry is the single source; do not combine it with "
                         "--aliases/--known-names")
        reg = load_registry(registry_path)
        pc_names = load_pc_names(campaign_dir)
        aliases = reg.alias_to_canonical()
        known_names = reg.known_names(extra=pc_names)
        if explicit_registry:
            print(f"Entity registry: {registry_path}")
        else:
            print(f"Auto-discovered entity registry: {registry_path} "
                  f"(pass --aliases/--known-names to use legacy files instead)")
        if pc_names:
            print(f"  + {len(pc_names)} PC name(s) from party.yaml folded into known_names")
    else:
        if args.aliases or args.known_names:
            warnings.warn(
                "--aliases/--known-names are deprecated; migrate to --registry "
                "(docs/entity_registry.yaml). See registry (entity_registry/registry.py).",
                DeprecationWarning,
            )
        aliases = load_aliases(Path(args.aliases).expanduser()) if args.aliases else {}

        known_names = None
        if args.known_names:
            known_names = load_known_names([Path(p) for p in args.known_names])
            print(f"Known names: {len(known_names)} normalised entries from "
                  f"{len(args.known_names)} source(s)")

    exclude_names: set[str] = set()
    if args.exclude_names:
        exclude_names = load_known_names([Path(p) for p in args.exclude_names])
        print(f"Excluded names: {len(exclude_names)} normalised entries from "
              f"{len(args.exclude_names)} source(s)")

    bundles = load_bundles(corpus, aliases, args.types, split_gap=args.split_gap,
                           known_names=known_names, exclude_names=exclude_names)
    selected = select(bundles, args.min_facts, args.only, args.top,
                      known_only=args.known_only, known_names=known_names)

    scoping_active = known_names is not None or "npc" in set(args.types)
    total_entities = len(bundles)
    n_known   = sum(1 for b in bundles.values() if getattr(b, "known", True))
    n_unknown = total_entities - n_known
    scope_note = (f"  ({n_known} known / {n_unknown} location-scoped)"
                  if scoping_active else "")
    split_note = f", gap-split >{args.split_gap}" if args.split_gap else ""
    print(f"Corpus:   {len(corpus)} file(s)")
    print(f"Entities: {total_entities} of types {args.types}{split_note}{scope_note} "
          f"(>= {args.min_facts} facts: {sum(1 for b in bundles.values() if len(b.facts) >= args.min_facts)})")
    n_floor_waived = sum(1 for b in selected if len(b.facts) < args.min_facts)
    print(f"Selected: {len(selected)} for aggregation"
          + (" (known-only)" if args.known_only else "")
          + (f", {n_floor_waived} below --min-facts (included via known-names/registry)"
             if n_floor_waived else ""))
    print("=" * 60)

    if args.render_only:
        md = render_bundles(selected, args.quotes)
        dest = Path(args.render_only).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        print(f"Rendered {len(selected)} bundle(s) -> {dest} "
              f"(~{len(md)//4:,} tokens)")
        return

    if args.list or not selected:
        show_all = args.list and not args.known_only and scoping_active
        # When scoping is active, show unknown entities too so the human can
        # see what got location-scoped (even if they won't be synthesized).
        list_items = selected
        if show_all:
            unseen_keys = {id(b) for b in selected}
            extras = [b for b in bundles.values()
                      if not getattr(b, "known", True)
                      and len(b.facts) >= args.min_facts
                      and id(b) not in unseen_keys]
            extras.sort(key=lambda b: (-len(b.facts), b.type, b.display.lower()))
            list_items = selected + extras
        for b in list_items:
            lo, hi = b.chapters
            tag = "" if not scoping_active else ("[known]   " if getattr(b, "known", True) else "[location]")
            print(f"  {tag}{len(b.facts):>5}  {b.type:9s}  {b.display}  (ch {lo}-{hi})")
        if not selected:
            print("(nothing selected)")
        if args.list and args.coverage:
            require_registered = not args.coverage_unregistered
            coverage = compute_coverage(
                corpus, aliases, known_names, reg,
                min_mentions=args.hearsay_min_mentions,
                max_own_facts=args.hearsay_max_own_facts,
                exclude_names=exclude_names,
                require_registered=require_registered,
            )
            print()
            print(render_coverage_report(
                coverage.hearsay, coverage.zero_fact, reg is not None,
                coverage.latest_chapter, args.recent_window,
                args.hearsay_min_mentions, args.hearsay_max_own_facts,
                n_dropped_unregistered=coverage.n_dropped_unregistered,
                require_registered=require_registered,
            ))
        return

    model = args.model
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resumable: skip entities whose dossier already exists (survives sleeps /
    # interrupts; re-run to fill in the rest).
    todo = [b for b in selected if not dossier_path(out_dir, b).exists()]
    already = len(selected) - len(todo)

    if args.batch:
        # ── batch path (anthropic backend only) ─────────────────────────
        # Replaces the per-thread fan-out below with ONE grouped Message
        # Batch over every not-yet-aggregated entity's independent
        # aggregation call. The unit is the same Bundle the threaded path
        # aggregates one at a time; custom_id is its dossier filename stem
        # (dossier_path(out_dir, b).stem) — deterministic and, since it's
        # already the output filename, trivially collision-free with the
        # writer below. Successes are written with the same write_dossier
        # helper (atomic_write_text under the hood, FR-014) the threaded
        # path uses, so the on-disk cache-write guarantee is unchanged.
        if not todo:
            print(f"All {len(selected)} entitie(s) already aggregated "
                  f"({already} pre-existing) — nothing to submit.")
            return
        print(f"Aggregating {len(todo)} entitie(s) via the Message Batches API "
              f"(model: {model or 'default'})"
              f"{f'; {already} already done (skipped)' if already else ''}\n")

        client = client_from_args(args)
        by_id = {dossier_path(out_dir, b).stem: b for b in todo}
        requests = [
            build_batch_request(
                custom_id=dossier_path(out_dir, b).stem,
                system=AGGREGATE_SYSTEM,
                user=build_user_prompt(b, args.quotes),
                model=model,
                max_tokens=args.max_tokens,
            )
            for b in todo
        ]
        results = run_batch(client, requests, label="facts_to_state")

        done = 0
        failed: list[str] = []
        for custom_id, record in results.items():
            b = by_id.get(custom_id)
            if record["status"] != "succeeded":
                failed.append(custom_id)
                print(f"FAILED {custom_id}: {record['status']} {record.get('error')}",
                      file=sys.stderr)
                continue
            if b is not None:
                write_dossier(out_dir, b, record["text"])
                done += 1
                print(f"[{done}/{len(todo)}] {b.type}: {b.display} "
                      f"({len(b.facts)} facts) -> {dossier_path(out_dir, b).name}")

        print(f"\nWrote {done} dossier(s) to {out_dir} ({already} pre-existing)")
        if failed:
            print(f"{len(failed)} entitie(s) failed (re-run --batch to retry "
                  f"only the missing one(s)):", file=sys.stderr)
            for custom_id in failed:
                print(f"  {custom_id}", file=sys.stderr)
            sys.exit(1)
        print("REVIEW these (esp. the ## Uncertainty blocks) before synthesis.")
        return

    # [None] means "no explicit endpoint" — the worker pool still runs once,
    # resolving via client_from_args(args, endpoint=None), which falls back to
    # --backend / env resolution (anthropic by default).
    endpoints = args.endpoints or [None]
    where = ", ".join(e or "Anthropic API" for e in endpoints)
    print(f"Aggregating {len(todo)} entitie(s) on {where} (model: {model or 'default'})"
          f"{f'; {already} already done (skipped)' if already else ''}\n")

    work: queue.Queue = queue.Queue()
    for item in enumerate(todo, 1):
        work.put(item)
    lock = threading.Lock()
    done = 0
    errors: list[str] = []

    def worker(endpoint: str | None) -> None:
        nonlocal done
        client = client_from_args(args, endpoint=endpoint)
        while True:
            try:
                i, b = work.get_nowait()
            except queue.Empty:
                return
            try:
                user = build_user_prompt(b, args.quotes)
                body = stream_api(client, AGGREGATE_SYSTEM, user, model,
                                  max_tokens=args.max_tokens, silent=True)
                write_dossier(out_dir, b, body)
                with lock:
                    done += 1
                    print(f"[{done}/{len(todo)}] {b.type}: {b.display} "
                          f"({len(b.facts)} facts) -> {dossier_path(out_dir, b).name}")
            except Exception as e:  # one bad entity must not kill the batch
                with lock:
                    errors.append(f"{b.type}:{b.display}: {e!r}")
                    print(f"  ERROR {b.type}: {b.display}: {e!r}", file=sys.stderr)

    n_workers = args.entity_parallel if args.entity_parallel is not None else len(endpoints)
    threads = [threading.Thread(target=worker, args=(endpoints[i % len(endpoints)],), daemon=True)
               for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\nWrote {done} dossier(s) to {out_dir} ({already} pre-existing)")
    if errors:
        print(f"{len(errors)} entitie(s) failed (re-run to retry):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    print("REVIEW these (esp. the ## Uncertainty blocks) before synthesis.")


if __name__ == "__main__":
    main()
