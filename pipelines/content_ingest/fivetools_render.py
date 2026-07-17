"""
fivetools_render.py — render 5etools-shaped JSON entities into searchable
plaintext drawer content.

The 5etools schema is precise but the JSON is full of {@tag ...} DSL
tokens, nested entries blocks, and structured stat-block fields. For
MemPalace retrieval to match meaningfully on any of it the drawer needs
human-readable prose plus the structured highlights (AC, HP, CR, …).

Each ``render_<type>`` returns plain text. The text is intentionally
markdown-flavored (headers + bold) so the same content reads well in a
terminal, the web UI, and a chat client. Tags are flattened to their
display segment via ``strip_tags``; the verbatim JSON stays available
through ``source_filepath`` metadata.

This module is import-safe — no I/O, no MemPalace, no Anthropic. It is
pure presentation.
"""

from __future__ import annotations

import re
from typing import Any

# ── Tag stripping ──────────────────────────────────────────────────────────

# Matches a single {@tag content} token. Outer braces only; nested tokens
# are handled by repeated substitution (see ``strip_tags``).
_TAG_RE = re.compile(r"\{@(\w+)\s*([^{}]*?)\}")

# Tags whose entire content is the literal display.
_TAG_LITERAL = {
    "i", "italic", "b", "bold", "s", "strike", "u", "underline",
    "sup", "sub", "color", "highlight", "note",
    "h", "h1", "h2", "h3", "h4",
    "comic", "comicH1", "comicH2", "comicH3", "comicH4", "comicNote",
    "code",
}

# Tags that prefix their content with a small label.
_TAG_PREFIX = {
    "dc": "DC ",
    "skillCheck": "",
    "savingThrow": "",
    "recharge": "Recharge ",
}


def strip_tags(text: Any) -> str:
    """Flatten {@tag ...} DSL tokens to readable display text."""
    if text is None:
        return ""
    if not isinstance(text, str):
        return str(text)
    if "{@" not in text:
        return text
    prev = None
    out = text
    while prev != out:
        prev = out
        out = _TAG_RE.sub(_replace_tag, out)
    return out


def _replace_tag(match: re.Match) -> str:
    tag = match.group(1)
    content = match.group(2).strip()
    if tag in _TAG_LITERAL:
        return content
    if tag == "dc":
        return f"DC {content}"
    if tag == "hit":
        body = content.split("|", 1)[0].strip()
        return body if body.startswith(("+", "-")) else f"+{body}"
    if tag == "recharge":
        if not content:
            return "(Recharge 6)"
        return f"(Recharge {content}–6)" if content.isdigit() else f"(Recharge {content})"
    if tag == "atk":
        body = content.lower()
        # mw=melee weapon, rw=ranged weapon, ms=melee spell, rs=ranged spell.
        return {
            "mw": "Melee Weapon Attack:",
            "rw": "Ranged Weapon Attack:",
            "ms": "Melee Spell Attack:",
            "rs": "Ranged Spell Attack:",
            "mw,rw": "Melee or Ranged Weapon Attack:",
        }.get(body, "Attack:")
    if tag == "h":
        return f"*Hit:* "
    if tag in _TAG_PREFIX:
        return f"{_TAG_PREFIX[tag]}{content}"
    parts = [p.strip() for p in content.split("|")]
    # Tags whose first segment is the display value (no name|source|display).
    if tag in ("scaledamage", "scaledice", "damage", "dice", "d20", "chance"):
        return parts[0] if parts else ""
    if len(parts) >= 3 and parts[-1]:
        return parts[-1]
    return parts[0] if parts else ""


# ── Entries-block walker ───────────────────────────────────────────────────


def render_entries_block(entries: Any, depth: int = 0) -> str:
    """Walk a 5etools ``entries[]`` block and emit readable prose."""
    if not entries:
        return ""
    if not isinstance(entries, list):
        return strip_tags(entries)
    chunks: list[str] = []
    for e in entries:
        s = _render_one(e, depth)
        if s:
            chunks.append(s)
    return "\n\n".join(chunks)


def _render_one(e: Any, depth: int) -> str:
    if isinstance(e, str):
        return strip_tags(e)
    if not isinstance(e, dict):
        return ""
    t = e.get("type")
    name = e.get("name")

    if t in (None, "entries", "section", "variantInner", "variantBlock"):
        body = render_entries_block(e.get("entries") or [], depth + 1)
        if name:
            header = f"## {strip_tags(name)}" if depth == 0 else f"**{strip_tags(name)}.**"
            return f"{header}\n\n{body}".strip()
        return body
    if t in ("inset", "insetReadaloud"):
        body = render_entries_block(e.get("entries") or [], depth + 1)
        title = f"_{strip_tags(name)}_" if name else ""
        return f"{title}\n{body}".strip() if title else body
    if t in ("p", "paragraph"):
        return strip_tags(e.get("entry") or e.get("entries") or "")
    if t == "quote":
        body = render_entries_block(e.get("entries") or [], depth + 1)
        by = strip_tags(e.get("by") or "")
        out = "\n".join(f"> {ln}" for ln in body.splitlines())
        return f"{out}\n— {by}" if by else out
    if t == "list":
        items = e.get("items") or []
        return "\n".join(f"- {_render_list_item(it, depth + 1)}" for it in items if it)
    if t == "item":
        return _render_list_item(e, depth)
    if t in ("table", "tableGroup"):
        return _render_table(e)
    if t == "image":
        return ""
    if t == "spellcasting":
        return _render_spellcasting_block(e)
    if t == "abilityDc":
        attr = ", ".join(str(x) for x in (e.get("attributes") or []))
        return f"Spell save DC = 8 + {attr or 'Ability'} mod + proficiency bonus."
    if t == "abilityAttackMod":
        attr = ", ".join(str(x) for x in (e.get("attributes") or []))
        return f"Spell attack bonus = {attr or 'Ability'} mod + proficiency bonus."
    if t in ("refClassFeature", "refSubclassFeature", "refOptionalfeature"):
        ref = e.get("classFeature") or e.get("subclassFeature") or e.get("optionalfeature") or ""
        if isinstance(ref, str):
            return f"({strip_tags(ref.split('|', 1)[0])})"
        return ""
    # Generic fallback: name + nested entries.
    body = render_entries_block(e.get("entries") or [], depth + 1)
    if name:
        return f"**{strip_tags(name)}.** {body}".strip()
    return body


def _render_list_item(it: Any, depth: int) -> str:
    if isinstance(it, str):
        return strip_tags(it)
    if not isinstance(it, dict):
        return ""
    name = it.get("name")
    body = ""
    if isinstance(it.get("entry"), str):
        body = strip_tags(it["entry"])
    elif it.get("entries"):
        body = render_entries_block(it["entries"], depth + 1)
    if name:
        return f"**{strip_tags(name)}.** {body}".strip()
    return body


def _render_table(t: dict) -> str:
    caption = strip_tags(t.get("caption") or t.get("name") or "")
    labels = [strip_tags(str(x)) for x in (t.get("colLabels") or [])]
    rows = t.get("rows") or []
    parts: list[str] = []
    if caption:
        parts.append(f"### {caption}")
    if labels:
        parts.append("| " + " | ".join(labels) + " |")
        parts.append("|" + "|".join(["---"] * len(labels)) + "|")
    for row in rows:
        if isinstance(row, dict) and row.get("type") == "row":
            row = row.get("row") or []
        if not isinstance(row, list):
            continue
        cells = []
        for c in row:
            if isinstance(c, str):
                cells.append(strip_tags(c))
            elif isinstance(c, dict):
                if isinstance(c.get("roll"), dict):
                    rr = c["roll"]
                    if "exact" in rr:
                        cells.append(str(rr["exact"]))
                    elif "min" in rr and "max" in rr:
                        cells.append(f"{rr['min']}-{rr['max']}")
                    else:
                        cells.append(strip_tags(str(rr)))
                else:
                    cells.append(_render_one(c, 0).replace("\n", " "))
            else:
                cells.append(str(c))
        if labels and len(cells) < len(labels):
            cells.extend([""] * (len(labels) - len(cells)))
        parts.append("| " + " | ".join(cells) + " |")
    return "\n".join(parts)


def _render_spellcasting_block(sc: dict) -> str:
    """Render a single ``spellcasting`` entry (nested under a creature's
    ``trait``/``spellcasting`` array)."""
    name = strip_tags(sc.get("name") or "Spellcasting")
    parts: list[str] = [f"**{name}.**"]
    for h in sc.get("headerEntries") or []:
        if isinstance(h, str):
            parts.append(strip_tags(h))
    spells = sc.get("spells") or {}
    for level in sorted(spells.keys(), key=_spell_level_sort_key):
        info = spells[level] or {}
        slot = info.get("slots")
        spell_list = ", ".join(strip_tags(s) for s in info.get("spells") or [])
        if not spell_list:
            continue
        if str(level) == "0":
            parts.append(f"Cantrips (at will): {spell_list}")
        else:
            slot_str = f" ({slot} slots)" if slot is not None else ""
            parts.append(f"{_ordinal(int(level))} level{slot_str}: {spell_list}")
    will = sc.get("will") or []
    if will:
        parts.append(f"At will: {', '.join(strip_tags(s) for s in will)}")
    daily = sc.get("daily") or {}
    for k in sorted(daily.keys()):
        v = daily[k] or []
        suffix = "/day each" if k.endswith("e") else "/day"
        n = re.match(r"(\d+)", k)
        n_str = n.group(1) if n else k
        parts.append(f"{n_str}{suffix}: {', '.join(strip_tags(s) for s in v)}")
    rest = sc.get("rest") or {}
    for k in sorted(rest.keys()):
        v = rest[k] or []
        n = re.match(r"(\d+)", k)
        n_str = n.group(1) if n else k
        parts.append(f"{n_str}/rest: {', '.join(strip_tags(s) for s in v)}")
    footer = sc.get("footerEntries") or []
    for h in footer:
        if isinstance(h, str):
            parts.append(strip_tags(h))
    return " ".join(parts)


def _spell_level_sort_key(level: Any) -> int:
    try:
        return int(level)
    except (TypeError, ValueError):
        return 99


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ── Monster (statblock) ────────────────────────────────────────────────────


_SIZE_FULL = {
    "T": "Tiny", "S": "Small", "M": "Medium",
    "L": "Large", "H": "Huge", "G": "Gargantuan",
}
_ALIGN_FULL = {
    "L": "lawful", "N": "neutral", "C": "chaotic",
    "G": "good", "E": "evil", "U": "unaligned",
    "A": "any alignment",
    "NX": "neutral", "NY": "neutral",
}


def render_monster(m: dict) -> str:
    """Render a 5etools monster entity to a full statblock string."""
    if not isinstance(m, dict):
        return ""
    parts: list[str] = []
    parts.append(f"# {strip_tags(m.get('name') or 'Unnamed creature')}")

    type_line = _format_type_line(m)
    if type_line:
        parts.append(f"*{type_line}*")

    src = m.get("source")
    page = m.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")

    ac = _format_ac(m.get("ac"))
    if ac:
        parts.append(f"**Armor Class** {ac}")
    hp = _format_hp(m.get("hp"))
    if hp:
        parts.append(f"**Hit Points** {hp}")
    sp = _format_speed(m.get("speed"))
    if sp:
        parts.append(f"**Speed** {sp}")

    abil = _format_abilities(m)
    if abil:
        parts.append(abil)

    if m.get("save"):
        parts.append(f"**Saving Throws** {_format_kv_signed(m['save'])}")
    if m.get("skill"):
        parts.append(f"**Skills** {_format_kv_signed(m['skill'])}")
    if m.get("vulnerable"):
        parts.append(f"**Damage Vulnerabilities** {_format_dmg_list(m['vulnerable'], 'vulnerable')}")
    if m.get("resist"):
        parts.append(f"**Damage Resistances** {_format_dmg_list(m['resist'], 'resist')}")
    if m.get("immune"):
        parts.append(f"**Damage Immunities** {_format_dmg_list(m['immune'], 'immune')}")
    if m.get("conditionImmune"):
        parts.append(f"**Condition Immunities** {_format_dmg_list(m['conditionImmune'], 'conditionImmune')}")

    senses = [strip_tags(s) for s in (m.get("senses") or []) if s]
    pp = m.get("passive")
    if pp is not None:
        senses.append(f"passive Perception {pp}")
    if senses:
        parts.append(f"**Senses** {', '.join(senses)}")

    if m.get("languages"):
        parts.append(f"**Languages** {', '.join(strip_tags(l) for l in m['languages'])}")

    cr = _format_cr(m.get("cr"))
    if cr:
        parts.append(f"**Challenge** {cr}")
    if m.get("pbNote"):
        parts.append(f"**Proficiency Bonus** {strip_tags(m['pbNote'])}")

    if m.get("trait"):
        parts.append(_render_block_section("Traits", m["trait"]))
    if m.get("spellcasting"):
        parts.append(_render_block_section("Spellcasting", m["spellcasting"]))
    if m.get("action"):
        parts.append(_render_block_section("Actions", m["action"], header_text=m.get("actionHeader")))
    if m.get("bonus"):
        parts.append(_render_block_section("Bonus Actions", m["bonus"], header_text=m.get("bonusHeader")))
    if m.get("reaction"):
        parts.append(_render_block_section("Reactions", m["reaction"], header_text=m.get("reactionHeader")))
    if m.get("legendary"):
        parts.append(_render_block_section("Legendary Actions", m["legendary"], header_text=m.get("legendaryHeader")))
    if m.get("mythic"):
        parts.append(_render_block_section("Mythic Actions", m["mythic"], header_text=m.get("mythicHeader")))

    return "\n\n".join(p for p in parts if p)


def _format_type_line(m: dict) -> str:
    sizes = m.get("size") or []
    size_str = " or ".join(_SIZE_FULL.get(s, s) for s in sizes) if sizes else ""
    typ = _format_creature_type(m.get("type"))
    align = _format_alignment(m.get("alignment"))
    head = f"{size_str} {typ}".strip() if typ else size_str
    return ", ".join([s for s in (head, align) if s])


def _format_creature_type(t: Any) -> str:
    if t is None:
        return ""
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        base = t.get("type") or ""
        if isinstance(base, dict):  # nested choice
            base = base.get("choose", [None])[0] or ""
        tags = []
        for tg in t.get("tags") or []:
            if isinstance(tg, str):
                tags.append(tg)
            elif isinstance(tg, dict):
                pre = tg.get("prefix") or ""
                tag_name = tg.get("tag") or ""
                tags.append(f"{pre} {tag_name}".strip())
        if tags:
            return f"{base} ({', '.join(tags)})"
        return str(base)
    return str(t)


def _format_alignment(a: Any) -> str:
    if not a:
        return ""
    if isinstance(a, str):
        return _ALIGN_FULL.get(a, a)
    if isinstance(a, list):
        if all(isinstance(x, str) for x in a):
            return " ".join(_ALIGN_FULL.get(x, x) for x in a)
        if all(isinstance(x, dict) for x in a):
            chunks = []
            for d in a:
                aln = d.get("alignment") or []
                if isinstance(aln, str):
                    aln = [aln]
                txt = " ".join(_ALIGN_FULL.get(y, y) for y in aln)
                if d.get("chance"):
                    txt += f" ({d['chance']}%)"
                chunks.append(txt)
            return " or ".join(chunks)
    return str(a)


def _format_ac(ac: Any) -> str:
    if not ac:
        return ""
    if isinstance(ac, int):
        return str(ac)
    if not isinstance(ac, list):
        return str(ac)
    chunks = []
    for entry in ac:
        if isinstance(entry, int):
            chunks.append(str(entry))
        elif isinstance(entry, dict):
            v = entry.get("ac")
            from_list = entry.get("from") or []
            cond = entry.get("condition") or ""
            base = str(v) if v is not None else ""
            extras = []
            if from_list:
                extras.append(", ".join(strip_tags(str(f)) for f in from_list))
            if cond:
                extras.append(strip_tags(cond))
            if extras:
                chunks.append(f"{base} ({'; '.join(extras)})".strip())
            else:
                chunks.append(base)
        elif isinstance(entry, str):
            chunks.append(strip_tags(entry))
    return ", ".join(c for c in chunks if c)


def _format_hp(hp: Any) -> str:
    if hp is None:
        return ""
    if isinstance(hp, dict):
        special = hp.get("special")
        if special:
            return strip_tags(special)
        avg = hp.get("average")
        formula = hp.get("formula")
        if avg is not None and formula:
            return f"{avg} ({formula})"
        if avg is not None:
            return str(avg)
        if formula:
            return formula
        return ""
    return str(hp)


def _format_speed(speed: Any) -> str:
    if not speed:
        return ""
    if isinstance(speed, (int, str)):
        return f"{speed} ft."
    if not isinstance(speed, dict):
        return str(speed)
    chunks = []
    for k in ("walk", "fly", "swim", "climb", "burrow"):
        v = speed.get(k)
        if v is None:
            continue
        chunks.append(_format_one_speed(k, v))
    if speed.get("canHover"):
        chunks.append("(hover)")
    if speed.get("choose"):
        ch = speed["choose"]
        modes = ch.get("from") or []
        amt = ch.get("amount")
        chunks.append(
            f"{', '.join(modes)} {amt} ft. (choose)" if modes and amt else strip_tags(str(ch))
        )
    return ", ".join(c for c in chunks if c)


def _format_one_speed(mode: str, v: Any) -> str:
    if isinstance(v, bool):
        return f"{mode}" if mode != "walk" else ""
    if isinstance(v, int):
        return f"{v} ft." if mode == "walk" else f"{mode} {v} ft."
    if isinstance(v, dict):
        n = v.get("number")
        cond = v.get("condition") or ""
        base = f"{n} ft." if mode == "walk" else f"{mode} {n} ft."
        if cond:
            base += f" {strip_tags(cond)}"
        return base
    return str(v)


def _format_abilities(m: dict) -> str:
    rows = []
    for a in ("str", "dex", "con", "int", "wis", "cha"):
        v = m.get(a)
        if v is None:
            return ""
        rows.append((a.upper(), v, _modifier(v)))
    head = "| " + " | ".join(r[0] for r in rows) + " |"
    sep = "|" + "|".join(["---"] * 6) + "|"
    body = "| " + " | ".join(f"{r[1]} ({r[2]})" for r in rows) + " |"
    return "\n".join([head, sep, body])


def _modifier(score: Any) -> str:
    if not isinstance(score, int):
        return ""
    mod = (score - 10) // 2
    return f"+{mod}" if mod >= 0 else str(mod)


def _format_kv_signed(d: Any) -> str:
    if not isinstance(d, dict):
        return strip_tags(str(d)) if d else ""
    chunks = []
    for k, v in d.items():
        if k == "other":
            chunks.append(strip_tags(str(v)))
        else:
            chunks.append(f"{k.title()} {v}")
    return ", ".join(chunks)


def _format_dmg_list(lst: Any, key: str) -> str:
    if not lst:
        return ""
    if not isinstance(lst, list):
        return strip_tags(str(lst))
    parts = []
    for x in lst:
        if isinstance(x, str):
            parts.append(strip_tags(x))
        elif isinstance(x, dict):
            sub = x.get(key) or []
            if isinstance(sub, list):
                sub_str = ", ".join(strip_tags(str(s)) for s in sub)
            else:
                sub_str = strip_tags(str(sub))
            note = x.get("note") or ""
            pre = x.get("preNote") or ""
            chunk = " ".join([pre, sub_str, note]).strip()
            chunk = re.sub(r"\s+", " ", chunk)
            if chunk:
                parts.append(chunk)
    return "; ".join(parts)


def _format_cr(cr: Any) -> str:
    if cr is None or cr == "":
        return ""
    if isinstance(cr, (str, int, float)):
        return str(cr)
    if isinstance(cr, dict):
        base = cr.get("cr", "")
        lair = cr.get("lair")
        coven = cr.get("coven")
        extras = []
        if lair is not None:
            extras.append(f"{lair} in lair")
        if coven is not None:
            extras.append(f"{coven} in coven")
        if extras:
            return f"{base} ({'; '.join(extras)})"
        return str(base)
    return str(cr)


def _render_block_section(label: str, items: Any, *, header_text: Any = None) -> str:
    if not items:
        return ""
    if not isinstance(items, list):
        items = [items]
    out = [f"## {label}"]
    if header_text:
        for h in (header_text if isinstance(header_text, list) else [header_text]):
            if isinstance(h, str):
                out.append(strip_tags(h))
            elif isinstance(h, dict):
                rendered = _render_one(h, 1)
                if rendered:
                    out.append(rendered)
    for it in items:
        if not isinstance(it, dict):
            if isinstance(it, str) and it.strip():
                out.append(strip_tags(it))
            continue
        if it.get("type") == "spellcasting":
            out.append(_render_spellcasting_block(it))
            continue
        name = it.get("name")
        body = render_entries_block(it.get("entries") or [], 1)
        if name and body:
            out.append(f"**{strip_tags(name)}.** {body}")
        elif name:
            out.append(f"**{strip_tags(name)}.**")
        elif body:
            out.append(body)
    return "\n\n".join(out)


# ── Spell ──────────────────────────────────────────────────────────────────

_SCHOOL_FULL = {
    "A": "Abjuration", "C": "Conjuration", "D": "Divination", "E": "Enchantment",
    "V": "Evocation", "I": "Illusion", "N": "Necromancy", "T": "Transmutation",
    "P": "Psionic",
}


def render_spell(s: dict) -> str:
    if not isinstance(s, dict):
        return ""
    parts: list[str] = []
    parts.append(f"# {strip_tags(s.get('name') or 'Unnamed spell')}")

    level = s.get("level")
    school = _SCHOOL_FULL.get(s.get("school"), s.get("school", ""))
    ritual = (s.get("meta") or {}).get("ritual")
    if level == 0:
        meta_line = f"{school} cantrip"
    else:
        meta_line = f"{_ordinal(level) if isinstance(level, int) else level}-level {school}"
    if ritual:
        meta_line += " (ritual)"
    parts.append(f"*{meta_line.strip()}*")

    src = s.get("source")
    page = s.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")

    parts.append(f"**Casting Time:** {_format_spell_time(s.get('time'))}")
    parts.append(f"**Range:** {_format_spell_range(s.get('range'))}")
    parts.append(f"**Components:** {_format_spell_components(s.get('components'))}")
    parts.append(f"**Duration:** {_format_spell_duration(s.get('duration'))}")

    body = render_entries_block(s.get("entries") or [], 1)
    if body:
        parts.append(body)

    higher = s.get("entriesHigherLevel") or []
    if higher:
        parts.append(render_entries_block(higher, 1))

    classes = (s.get("classes") or {}).get("fromClassList") or []
    if classes:
        names = ", ".join(c.get("name", "") for c in classes if isinstance(c, dict))
        if names:
            parts.append(f"_Classes: {names}_")
    return "\n\n".join(p for p in parts if p)


def _format_spell_time(time: Any) -> str:
    if not time:
        return ""
    if isinstance(time, list):
        return ", or ".join(_format_one_spell_time(t) for t in time)
    return _format_one_spell_time(time)


def _format_one_spell_time(t: Any) -> str:
    if isinstance(t, dict):
        n = t.get("number")
        u = t.get("unit") or ""
        cond = t.get("condition") or ""
        base = f"{n} {u}" + ("s" if isinstance(n, int) and n > 1 and not u.endswith("s") else "")
        return f"{base} ({strip_tags(cond)})" if cond else base
    return strip_tags(str(t))


def _format_spell_range(r: Any) -> str:
    if not r:
        return ""
    if isinstance(r, dict):
        rtype = r.get("type")
        dist = r.get("distance") or {}
        if rtype == "point":
            dt = dist.get("type") or ""
            amt = dist.get("amount")
            if dt == "self":
                return "Self"
            if dt == "touch":
                return "Touch"
            if dt == "sight":
                return "Sight"
            if dt == "unlimited":
                return "Unlimited"
            return f"{amt} {dt}".strip() if amt else dt
        if rtype:
            dt = dist.get("type") or ""
            amt = dist.get("amount")
            return f"Self ({amt}-{dt} {rtype})".strip() if amt else f"Self ({rtype})"
    return strip_tags(str(r))


def _format_spell_components(c: Any) -> str:
    if not c:
        return ""
    if isinstance(c, dict):
        out = []
        if c.get("v"):
            out.append("V")
        if c.get("s"):
            out.append("S")
        m = c.get("m")
        if m:
            if isinstance(m, dict):
                out.append(f"M ({strip_tags(m.get('text', ''))})")
            else:
                out.append(f"M ({strip_tags(str(m))})")
        if c.get("r"):
            out.append("R")
        return ", ".join(out)
    return strip_tags(str(c))


def _format_spell_duration(d: Any) -> str:
    if not d:
        return ""
    if isinstance(d, list):
        return "; ".join(_format_one_duration(x) for x in d)
    return _format_one_duration(d)


def _format_one_duration(d: Any) -> str:
    if not isinstance(d, dict):
        return strip_tags(str(d))
    t = d.get("type")
    if t == "instant":
        return "Instantaneous"
    if t == "permanent":
        return "Permanent"
    if t == "special":
        return "Special"
    if t == "timed":
        dur = d.get("duration") or {}
        n = dur.get("number")
        u = dur.get("type") or ""
        s = "s" if isinstance(n, int) and n > 1 and not u.endswith("s") else ""
        base = f"{n} {u}{s}".strip()
        if d.get("concentration"):
            base = f"Concentration, up to {base}"
        return base
    return strip_tags(str(d))


# ── Item ───────────────────────────────────────────────────────────────────


def render_item(it: dict) -> str:
    if not isinstance(it, dict):
        return ""
    parts = [f"# {strip_tags(it.get('name') or 'Unnamed item')}"]

    head_bits = []
    rarity = it.get("rarity")
    if rarity:
        head_bits.append(rarity)
    if it.get("reqAttune"):
        attune = it["reqAttune"]
        head_bits.append(f"requires attunement{'' if attune is True else ' ' + strip_tags(str(attune))}")
    if it.get("wondrous"):
        head_bits.append("wondrous item")
    if head_bits:
        parts.append(f"*{', '.join(head_bits)}*")

    src = it.get("source")
    page = it.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")

    body = render_entries_block(it.get("entries") or [], 1)
    if body:
        parts.append(body)

    return "\n\n".join(p for p in parts if p)


# ── Class / subclass / classFeature ────────────────────────────────────────


def render_class(c: dict) -> str:
    parts = [f"# {strip_tags(c.get('name') or 'Unnamed class')}"]
    src = c.get("source")
    page = c.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    hd = c.get("hd")
    if isinstance(hd, dict):
        parts.append(f"**Hit Die:** d{hd.get('faces')}")
    if c.get("proficiency"):
        parts.append(f"**Saving Throw Proficiencies:** {', '.join(strip_tags(p) for p in c['proficiency'])}")
    body = render_entries_block(c.get("classFeatures") or [], 1)
    if body:
        parts.append(body)
    fluff = c.get("fluff")
    if isinstance(fluff, dict):
        f_body = render_entries_block(fluff.get("entries") or [], 1)
        if f_body:
            parts.append(f_body)
    return "\n\n".join(p for p in parts if p)


def render_subclass(sc: dict) -> str:
    parts = [f"# {strip_tags(sc.get('name') or 'Unnamed subclass')}"]
    cn = sc.get("className")
    if cn:
        parts.append(f"*{cn} subclass*")
    src = sc.get("source")
    page = sc.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    body = render_entries_block(sc.get("subclassFeatures") or [], 1)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


def render_class_feature(cf: dict) -> str:
    name = cf.get("name") or "Unnamed feature"
    parts = [f"# {strip_tags(name)}"]
    cn = cf.get("className")
    lvl = cf.get("level")
    head_bits = []
    if cn:
        head_bits.append(f"{cn} feature")
    if lvl:
        head_bits.append(f"level {lvl}")
    if head_bits:
        parts.append(f"*{', '.join(head_bits)}*")
    src = cf.get("source")
    page = cf.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    body = render_entries_block(cf.get("entries") or [], 1)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


def render_subclass_feature(scf: dict) -> str:
    name = scf.get("name") or "Unnamed subclass feature"
    parts = [f"# {strip_tags(name)}"]
    cn = scf.get("className")
    sub = scf.get("subclassShortName")
    lvl = scf.get("level")
    head_bits = []
    if cn and sub:
        head_bits.append(f"{cn}: {sub} feature")
    elif cn:
        head_bits.append(f"{cn} feature")
    if lvl:
        head_bits.append(f"level {lvl}")
    if head_bits:
        parts.append(f"*{', '.join(head_bits)}*")
    src = scf.get("source")
    page = scf.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    body = render_entries_block(scf.get("entries") or [], 1)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


# ── Race / background / feat / generic name+entries ────────────────────────


def render_race(r: dict) -> str:
    parts = [f"# {strip_tags(r.get('name') or 'Unnamed race')}"]
    src = r.get("source")
    page = r.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    sz = r.get("size")
    if sz:
        parts.append(f"**Size:** {' or '.join(_SIZE_FULL.get(s, s) for s in sz)}")
    sp = _format_speed(r.get("speed"))
    if sp:
        parts.append(f"**Speed:** {sp}")
    body = render_entries_block(r.get("entries") or [], 1)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


def render_background(b: dict) -> str:
    return _render_named_with_entries(b, label="background")


def render_feat(f: dict) -> str:
    return _render_named_with_entries(f, label="feat")


def render_generic(e: dict, *, label: str = "") -> str:
    return _render_named_with_entries(e, label=label)


def _render_named_with_entries(e: dict, *, label: str) -> str:
    if not isinstance(e, dict):
        return ""
    parts = [f"# {strip_tags(e.get('name') or 'Unnamed')}"]
    if label:
        parts.append(f"*{label}*")
    src = e.get("source")
    page = e.get("page")
    if src or page:
        parts.append(f"_Source: {src or '?'}{f', p. {page}' if page else ''}_")
    body = render_entries_block(e.get("entries") or [], 1)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


def render_fluff(f: dict) -> str:
    """Render a *Fluff entry — same shape as generic name+entries."""
    return _render_named_with_entries(f, label="fluff")


# ── Public dispatch (kept here for one-stop import) ────────────────────────

def render_entity(prop: str, entity: dict) -> str:
    """Render any catalog entity to plain text by wrapper-key."""
    if prop == "monster":
        return render_monster(entity)
    if prop == "spell":
        return render_spell(entity)
    if prop in ("item", "itemGroup", "baseitem", "magicvariant", "reward"):
        return render_item(entity)
    if prop == "class":
        return render_class(entity)
    if prop == "subclass":
        return render_subclass(entity)
    if prop == "classFeature":
        return render_class_feature(entity)
    if prop == "subclassFeature":
        return render_subclass_feature(entity)
    if prop in ("race", "subrace"):
        return render_race(entity)
    if prop == "background":
        return render_background(entity)
    if prop == "feat":
        return render_feat(entity)
    if prop.endswith("Fluff"):
        return render_fluff(entity)
    return _render_named_with_entries(entity, label=prop)
