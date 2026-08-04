"""NPC dossier parsing, alias normalization, and player/speaker mapping."""

import re
import sys
from pathlib import Path


_DOSSIER_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)


def parse_dossier(path: "Path") -> tuple[str, list[str], list[int], str]:
    """Return (canonical_name, aliases, source_extracts, body_without_frontmatter).

    `source_extracts` is the list of dossier_extract_NNN numbers already
    absorbed into this dossier (used by planning.py's sidecar dedup).
    Missing or malformed → empty list.

    Dossiers without frontmatter fall back to (filename_stem, [], [], full_text).
    """
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    m = _DOSSIER_FRONTMATTER_RE.match(text)
    if not m:
        return (path.stem, [], [], text)
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return (path.stem, [], [], text)
    name = meta.get("name") or path.stem
    aliases = meta.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    source_extracts = meta.get("source_extracts") or []
    if not isinstance(source_extracts, list):
        source_extracts = []
    source_extracts = [
        int(n) for n in source_extracts
        if isinstance(n, int) or (isinstance(n, str) and n.isdigit())
    ]
    return (str(name), [str(a) for a in aliases], source_extracts, m.group(2))


def normalize_npc_key(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for alias-key lookups.

    LLM-emitted variants like "Harbin (Townmaster)" must match flat aliases
    like "Harbin Townmaster". Without normalization the parens block lookup.

    This is a display/lookup TEXT REWRITER (keeps spaces), not an identity
    key. For entity-identity comparisons use ``campaignlib.textproc.norm_subject``.
    """
    s = re.sub(r"[\(\)\[\]\'\"`\-]", "", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Spans whose contents are a RECORD of what somebody said, not prose the
# pipeline may edit: double-quoted speech (straight or curly) and ``*...*``
# spans, which the extraction layer uses for VTT-truncated speech and stage
# directions. See ``build_alias_normalizer(preserve_quoted=True)``.
#
# A span may wrap across a single newline but never crosses a blank line, so an
# unpaired quotation mark can only fail to protect the text after it — it can
# never swallow the rest of the document and freeze normalization off.
_PROTECTED_SPAN_RE = re.compile(
    r'"(?:[^"\n]|\n(?!\s*\n))*"'
    r'|“(?:[^”\n]|\n(?!\s*\n))*”'
    r'|\*(?:[^*\n]|\n(?!\s*\n))*\*'
)


def build_alias_normalizer(
    canonical_to_aliases: dict[str, list[str]],
    *,
    preserve_quoted: bool = False,
):
    """Return (normalize(text) -> text, [(canonical, aliases), ...]).

    The returned `normalize` rewrites any alias occurrence in `text` to
    its canonical name. Whole-word, case-insensitive, longest-first
    (so "Captain Tolubb" wins over "Tolubb" when both are aliases).

    An empty map yields an identity function and an empty entries list,
    so every extractor can call this unconditionally.

    ``preserve_quoted=True`` restricts the rewrite to prose, leaving
    ``"..."`` / ``“...”`` / ``*...*`` spans byte-identical. Callers whose input
    carries VERBATIM table dialogue must set it. An alias is an identity
    assertion — "these surface forms denote one entity" — and consuming it as a
    read-time lookup is correct; consuming it as a write-time transform inside
    quotation marks destroys which surface form was actually spoken, which is
    the entire payload of a verbatim record. The damage is worst when the alias
    data is *right*: a speaker who said "Glasstaff" comes back saying "Iarno", a
    name they may not know, and no fact-check can see the edit because the
    substituted name is canon-correct. See issue #223, and the matching
    guardrail comment in ``session_doc/scene_extract.py`` (#231).

    The canonical names still reach the model — as knowledge, via
    ``format_npc_roster`` — which is the channel that cannot corrupt a quote.
    """
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in canonical_to_aliases.items():
        for alias in aliases:
            alias_to_canonical[alias.lower()] = canonical

    # Idempotency guard. When an alias also occurs *inside* its own canonical,
    # text that already carries part of that canonical gets the shared prefix
    # duplicated: "Lord Cassian" + (Cassian -> "Lord Cassian Meliamne") became
    # "Lord Lord Cassian Meliamne", and "Lord Dagult Neverember" +
    # (Neverember -> "Dagult Neverember") became "Lord Dagult Dagult Neverember".
    # Registering the canonical's prefix-through-the-alias as a key — which
    # longest-first matching prefers over the bare alias — consumes the prefix
    # already present instead of re-emitting it. Never overwrites an explicit
    # alias mapping.
    for canonical, aliases in canonical_to_aliases.items():
        for alias in aliases:
            m = re.search(
                r"\b" + re.escape(alias) + r"\b", canonical, flags=re.IGNORECASE
            )
            if m and m.start() > 0:
                prefix = canonical[: m.end()]
                alias_to_canonical.setdefault(prefix.lower(), canonical)

    if not alias_to_canonical:
        return (lambda text: text, [])

    sorted_aliases = sorted(alias_to_canonical.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(a) for a in sorted_aliases) + r")\b",
        flags=re.IGNORECASE,
    )

    def normalize(text: str) -> str:
        return pattern.sub(lambda m: alias_to_canonical[m.group(0).lower()], text)

    def normalize_prose_only(text: str) -> str:
        """`normalize`, applied only to the gaps between protected spans."""
        out: list[str] = []
        pos = 0
        for span in _PROTECTED_SPAN_RE.finditer(text):
            out.append(normalize(text[pos:span.start()]))
            out.append(span.group(0))
            pos = span.end()
        out.append(normalize(text[pos:]))
        return "".join(out)

    entries = [(c, a) for c, a in canonical_to_aliases.items() if a]
    return (normalize_prose_only if preserve_quoted else normalize, entries)


def load_alias_map(dossier_dir, registry_path=None) -> dict[str, list[str]]:
    """Return `{canonical: [aliases]}` for a campaign's entities.

    If `registry_path` is given and points at a readable
    `entity_registry.yaml`, the registry is the single authority: its
    `{canonical: [aliases]}` projection REPLACES the dossier scan entirely
    (dossier frontmatter is one of the legacy stores the registry supersedes).
    A None/missing `registry_path` falls back to scanning `dossier_dir` for
    `*.md` dossiers, so callers without a registry are unaffected.

    Returns `{}` when neither a registry nor any dossiers are available —
    makes the caller a no-op for campaigns without planning.
    """
    if registry_path is not None:
        rp = Path(registry_path).expanduser()
        if rp.is_file():
            from campaignlib.registry import load_registry
            return load_registry(rp).canonical_to_aliases()
    if dossier_dir is None:
        return {}
    d = Path(dossier_dir).expanduser()
    if not d.is_dir():
        return {}
    result: dict[str, list[str]] = {}
    for f in sorted(d.glob("*.md")):
        # Skip sidecar files — they're not canonical dossiers.
        if ".new_notes." in f.name:
            continue
        name, aliases, _, _ = parse_dossier(f)
        result[name] = aliases
    return result


def find_alias_registry(campaign_dir, *, announce=True):
    """Discover the campaign entity registry and, when found, announce that it
    supersedes dossier aliases — so a run never *silently* swaps alias source.

    Render CLIs pass the result as ``load_alias_map(..., registry_path=...)``.
    Because a registry REPLACES the ``docs/npcs/`` dossier scan, a partial
    registry (the norm during a Phase-5 incremental migration) would otherwise
    drop hand-curated dossier aliases with no visible sign; the stderr notice is
    that sign. Returns the registry Path or None. Server routes that must stay
    quiet should call ``find_registry`` directly instead of this helper.
    """
    from campaignlib.registry import find_registry

    p = find_registry(campaign_dir)
    if p is not None and announce:
        print(
            f"Entity registry: {p}\n"
            f"  -> aliases come from the registry; docs/npcs/ dossier frontmatter "
            f"is superseded (remove the registry to use dossiers instead).",
            file=sys.stderr,
        )
    return p


_PLAYER_PLACEHOLDERS = {
    "", "not specified", "(not specified)", "[not specified]",
    "n/a", "na", "none", "unknown", "tbd",
}


def _is_player_placeholder(name: str) -> bool:
    return name.strip().lower().strip("()[]").strip() in _PLAYER_PLACEHOLDERS


def extract_player_character_map(party_text: str) -> dict[str, str]:
    """Parse party.md and return {player_name: character_name}.

    Supports two heading + info-line shapes:

    Old (single bold span):
        ## Soma
        **Tortle Druid 5, Player: Wade**

    New (party.py output, multiple bold spans separated by ``|``):
        ### Soma — Druid 5
        **Class/Level:** Druid 5 | **Species:** Tortle | **Player:** Wade

    When the Player slot holds multiple names separated by ``/`` or
    ``,``, both names map to the same character. Placeholder values
    like ``(Not specified)`` / ``[not specified]`` / ``N/A`` are
    treated as missing.
    """
    result: dict[str, str] = {}
    current_name: str | None = None

    def _record_players(raw: str) -> None:
        if _is_player_placeholder(raw):
            return
        for p in re.split(r'[/,]', raw):
            p = p.strip().rstrip('*').strip()
            if p and not _is_player_placeholder(p) and current_name:
                result[p] = current_name

    for line in party_text.splitlines():
        stripped = line.strip()
        m = re.match(r'^#{2,3}\s+(.+)$', stripped)
        if m:
            heading = m.group(1).strip()
            current_name = re.split(r'\s+[—–-]\s+', heading, maxsplit=1)[0].strip()
            continue
        if not current_name:
            continue
        new_pm = re.search(r'\*\*Player:\*\*\s*([^|]+?)(?:\s*\||\s*$)', stripped)
        if new_pm:
            _record_players(new_pm.group(1))
            current_name = None
            continue
        cm = re.match(r'^\*\*(.+\d+.+)\*\*$', stripped)
        if cm:
            pm = re.search(r',\s*Player:\s*(.+)', cm.group(1))
            if pm:
                _record_players(pm.group(1))
            current_name = None

    # First-name aliases: if a player's recorded name is "Joe Beda" → also map
    # "Joe" → that character. Skip when the first name is ambiguous (two
    # players share it but map to different characters) so we don't pick one
    # arbitrarily. Existing full-name keys always win.
    first_name_to_chars: dict[str, set[str]] = {}
    for player, char in result.items():
        first = player.split()[0] if player.split() else ""
        if first and first != player:
            first_name_to_chars.setdefault(first, set()).add(char)
    for first, chars in first_name_to_chars.items():
        if len(chars) == 1 and first not in result:
            result[first] = next(iter(chars))

    return result


def normalize_vtt_speakers(
    vtt_text: str,
    player_map: dict[str, str] | None = None,
    gm_player: str | None = None,
) -> str:
    """Rewrite speaker labels at the start of VTT lines.

    Maps each ``Player Name:`` prefix to the corresponding character
    name from ``player_map``. ``gm_player`` (if given) is rewritten to
    ``GM`` regardless of any party.md entry. Longer names match first
    so a player named ``Mike`` and a player named ``Mike Hall`` are
    both handled correctly.

    Body text is untouched — only labels at the start of a dialogue
    line are rewritten. This is a deterministic preprocessing step the
    LLM never sees and never has to derive itself.
    """
    if not player_map and not gm_player:
        return vtt_text
    full_map = dict(player_map or {})
    if gm_player:
        full_map[gm_player] = "GM"
    sorted_keys = sorted(full_map.keys(), key=len, reverse=True)
    out_lines: list[str] = []
    for line in vtt_text.splitlines():
        for key in sorted_keys:
            prefix = f"{key}:"
            if line.startswith(prefix):
                line = f"{full_map[key]}:" + line[len(prefix):]
                break
        out_lines.append(line)
    return "\n".join(out_lines)


def format_npc_roster(alias_map: dict[str, list[str]]) -> str:
    """Render an alias map as a 'Known NPCs' block to append to an extract prompt.

    Returns '' when the map is empty, so callers can write:
        system = BASE + ("\\n\\n" + roster if roster else "")
    """
    if not alias_map:
        return ""
    lines = [
        "Known NPCs in this campaign — use these exact canonical names when an NPC "
        "appears in the source text, even if the text uses a variant:"
    ]
    for canonical in sorted(alias_map):
        aliases = alias_map[canonical]
        if aliases:
            lines.append(f"- {canonical} (also: {', '.join(aliases)})")
        else:
            lines.append(f"- {canonical}")
    return "\n".join(lines)
