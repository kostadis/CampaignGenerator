"""PROTOTYPE: chunked Spark drafting of world_state + campaign_state (experiment, not a pipeline).

Applies PR #504's chunked NPC pattern to the two grounding docs:

    chunk (code) -> map call per chunk -> map check (code) -> stitch + route (code)
        -> one small reduce call per prose section -> assembly (code) -> verify report (code)

One map pass feeds BOTH documents. Each map call reads whole session summaries (every scene,
moment, NPC/location/item entry) for a few chapters, not the synopsis-only chronology the
one-shot `summary_native synth` prompt carries.

Sections owned by code (no model decides them): Canon Events Timeline, Completed Encounters &
Quests, NPC Current States, Audit: Tracking Claims. The model only renders prose sections from
notes that already passed the check, and only the notes routed to that section.

Usage:
    python chunked_state.py --campaign DIR --out OUT [--since 2 --until 70] [--chunk-chars 60000]
                            [--workers 6] [--stage map|reduce|all]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from campaignlib import client_from_args, stream_api  # noqa: E402
from pipelines.summary_native import npc_check  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "qwen3.8-flash-next"
ENDPOINT = "http://192.168.1.147:8001/v1"

# ── Evidence ────────────────────────────────────────────────────────────────

SECTION_TARGETS = {
    "## Memorable Moments": "moment",
    "## NPCs": "npcs",
    "## Locations": "locations",
    "## Items": "items",
    "## Spells": "spells",
    "## Abilities": "abilities",
    "## Session-End State": "end",
}
SCENE_RE = re.compile(r"^### (\d{3}\.\d{2})\b", re.M)
CITE_BRACKET_RE = re.compile(r"\[ch [^\[\]]*\]")
CITE_PART_RE = re.compile(r"ch (\d{3}) / (\d{3}\.\d{2}|moment|npcs|locations|items|spells|abilities|end)")
CITE_FULL_RE = re.compile(
    r"\[ch \d{3} / [a-z0-9.]+(?:; ch \d{3} / [a-z0-9.]+)*\]"
)


@dataclass
class Chapter:
    number: int
    path: Path
    text: str
    targets: set[str] = field(default_factory=set)

    @property
    def block(self) -> str:
        return f"\n\n======== CHAPTER {self.number:03d} ({self.path.name}) ========\n\n{self.text.rstrip()}\n"


def load_chapters(summaries: Path, since: int, until: int) -> list[Chapter]:
    out = []
    for p in sorted(summaries.glob("*.md")):
        m = re.match(r"(\d{3})-", p.name)
        if not m or not since <= int(m.group(1)) <= until:
            continue
        text = p.read_text(encoding="utf-8")
        ch = Chapter(int(m.group(1)), p, text)
        ch.targets = set(SCENE_RE.findall(text))
        for line in text.splitlines():
            if line.rstrip() in SECTION_TARGETS:
                ch.targets.add(SECTION_TARGETS[line.rstrip()])
        out.append(ch)
    return out


def make_chunks(chapters: list[Chapter], limit: int) -> list[list[Chapter]]:
    chunks, cur, size = [], [], 0
    for ch in chapters:
        if cur and size + len(ch.text) > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(ch)
        size += len(ch.text)
    if cur:
        chunks.append(cur)
    return chunks


def rng(chunk: list[Chapter]) -> str:
    return f"{chunk[0].number:03d}-{chunk[-1].number:03d}"


def load_audit(paths: list[Path]) -> list[tuple[str, str, str]]:
    """``[(id, file, item text)]`` — every ``- `` line of every tracking file, numbered A1.."""
    items = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                items.append((f"A{len(items) + 1}", p.name, line[2:].strip()))
    return items


# ── Citations and spans ─────────────────────────────────────────────────────


#: A section cited by its own heading text ("NPCs", "Session-End State", "Memorable Moments") is the
#: same target as its key. Exact lookup over the real headings, any case; nothing else is accepted.
HEADING_KEYS = {h[3:].casefold(): t for h, t in SECTION_TARGETS.items()} | {"memorable moment": "moment", "moments": "moment"}
_HEADING_IN_CITE_RE = re.compile(r"(ch \d{3} / )([A-Za-z][A-Za-z -]*[A-Za-z])(?=[;\]])")


def _normalise_cite(bracket: str) -> str:
    return _HEADING_IN_CITE_RE.sub(lambda m: m.group(1) + HEADING_KEYS.get(m.group(2).casefold(), m.group(2)), bracket)


def cites(text: str) -> list[tuple[str, int, str]]:
    """``[(bracket, chapter, target)]``; malformed brackets yield chapter -1."""
    out = []
    for b in map(_normalise_cite, CITE_BRACKET_RE.findall(text)):
        if not CITE_FULL_RE.fullmatch(b):
            out.append((b, -1, ""))
            continue
        for c, t in CITE_PART_RE.findall(b):
            out.append((b, int(c), t))
        if not CITE_PART_RE.findall(b):
            out.append((b, -1, ""))
    return out


def cite_problem(text: str, allowed: dict[int, set[str]]) -> str | None:
    cs = cites(text)
    if not cs:
        return "uncited"
    for b, c, t in cs:
        if c < 0 or ("." in t and int(t[:3]) != c):
            return f"invalid-citation {b}"
        if c not in allowed or t not in allowed[c]:
            return f"outside-chunk {b}"
    return None


def bad_span(text: str, haystack: str) -> str | None:
    for span in npc_check.SPAN_RE.findall(text):
        inner = npc_check.strip_quote_marks(span)
        if len(inner) < 4:
            continue
        if npc_check._contains(haystack, inner) is None:
            return span
    return None


# ── Map ─────────────────────────────────────────────────────────────────────

TIMELINE_FILE = "canon_events_timeline.chunked.md"
MAP_SECTIONS = ["## Events", "## Concluded", "## Threads", "## NPC Status", "## World", "## Party", "## Audit"]
THREAD_TAGS = ("OPENED", "ADVANCED", "RESOLVED", "ABANDONED")
WORLD_TAGS = ("FACTION", "NPC", "LOCATION", "ITEM", "THREAT")
STATUSES = ("Alive", "Dead", "Missing", "Imprisoned", "Departed", "Unknown")


def map_prompt(chunk: list[Chapter], audit: list[tuple[str, str, str]]) -> tuple[str, str]:
    system = (HERE / "prompts" / "map.system.md").read_text(encoding="utf-8")
    audit_block = "\n".join(f"[{i}] ({f}) {t}" for i, f, t in audit) or "(none)"
    user = (
        f"CHAPTERS IN THIS CHUNK: {rng(chunk)}\n\n"
        "EVIDENCE (the GM-reviewed session summaries for these chapters, verbatim):\n"
        + "".join(c.block for c in chunk)
        + "\n\nAUDIT QUESTIONS — NOT EVIDENCE (tracking-file items; report only the ones THIS chunk's "
        "evidence shows happening):\n\n"
        + audit_block
        + "\n\nOUTLINE: write exactly these `##` sections, in this order, and nothing else at that level:\n\n"
        + "\n".join(MAP_SECTIONS)
        + "\n"
    )
    return system, user


@dataclass
class MapResult:
    chunk: str
    kept: dict[str, list[str]] = field(default_factory=lambda: {h: [] for h in MAP_SECTIONS})
    drops: list[tuple[str, str, str]] = field(default_factory=list)  # (section, reason, text)
    npc_rows: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)


ROW_RE = re.compile(r"^-\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|\s*([A-Za-z]+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*(\[ch .*\])\s*$")
AUDIT_RE = re.compile(r"^-\s*\[(A\d+)\]\s*\**(SHOWN|BEGUN)\**\s*[—–:-]*\s*(.*)$")


def check_map(raw: str, chunk: list[Chapter], audit_ids: set[str]) -> MapResult:
    res = MapResult(rng(chunk))
    allowed = {c.number: c.targets for c in chunk}
    hay = "".join(c.text for c in chunk)
    secs = npc_check.parse_sections(raw)
    for h in MAP_SECTIONS:
        first, lines = secs.get(h, (0, []))
        for b in npc_check.bullets(lines, first):
            text = b.text
            if b.indent:
                res.drops.append((h, "nested-bullet", text))
                continue
            if re.fullmatch(r"-\s*\(?none\)?\.?", text, re.I):
                continue
            why = cite_problem(text, allowed)
            if why:
                res.drops.append((h, why, text))
                continue
            span = bad_span(text, hay)
            if span:
                res.drops.append((h, f"quoted-span-not-found {span}", text))
                continue
            if h == "## Threads" and not re.match(rf"^-\s*\[({'|'.join(THREAD_TAGS)})\]", text):
                res.drops.append((h, "missing-thread-tag", text))
                continue
            if h == "## World" and not re.match(rf"^-\s*\[({'|'.join(WORLD_TAGS)})\]", text):
                res.drops.append((h, "missing-world-tag", text))
                continue
            if h == "## NPC Status":
                m = ROW_RE.match(text)
                if not m or m.group(2) not in STATUSES:
                    res.drops.append((h, "malformed-row", text))
                    continue
                res.npc_rows.append({
                    "name": m.group(1).strip(), "status": m.group(2), "location": m.group(3) or "—",
                    "disposition": m.group(4) or "—", "cite": m.group(5), "chunk": res.chunk,
                })
            if h == "## Audit":
                m = AUDIT_RE.match(text)
                if not m or m.group(1) not in audit_ids:
                    res.drops.append((h, "unknown-audit-id-or-tag", text))
                    continue
                res.audit.append({"id": m.group(1), "tag": m.group(2), "text": m.group(3), "chunk": res.chunk})
            res.kept[h].append(text)
    return res


# ── Stitch / route ──────────────────────────────────────────────────────────


def first_chapter(text: str) -> int:
    cs = cites(text)
    return cs[0][1] if cs and cs[0][1] >= 0 else 9999


def stitched(results: list[MapResult], heading: str, tag: str | None = None) -> list[str]:
    seen, out = set(), []
    for r in results:
        for t in r.kept[heading]:
            if tag and not t.startswith(f"- [{tag}]"):
                continue
            if t not in seen:
                seen.add(t)
                out.append(t)
    return sorted(out, key=first_chapter)  # stable: chunk order within a chapter


def load_identity(campaign: Path) -> tuple[dict[str, str], set[str]]:
    """``(form -> canonical, player-character canonicals)`` from the entity registry and players.yaml.

    Exact, casefolded name/alias equality only. A form that two entities claim is left out, so it
    stays unresolved rather than being given to either. Nothing is matched by similarity."""
    import yaml

    reg_p = campaign / "docs" / "entity_registry.yaml"
    claims: dict[str, set[str]] = {}
    if reg_p.is_file():
        for e in (yaml.safe_load(reg_p.read_text(encoding="utf-8")) or {}).get("entities", []):
            for form in [e["name"], *(e.get("aliases") or [])]:
                claims.setdefault(str(form).casefold(), set()).add(e["name"])
    forms = {f: next(iter(c)) for f, c in claims.items() if len(c) == 1}
    pcs: set[str] = set()
    pl_p = campaign / "config" / "players.yaml"
    if pl_p.is_file():
        data = yaml.safe_load(pl_p.read_text(encoding="utf-8")) or {}
        for p in data if isinstance(data, list) else data.get("players", []):
            for name in p.get("plays") or []:
                pcs.add(forms.get(str(name).casefold(), str(name)))
    return forms, pcs


def npc_table(results: list[MapResult], forms: dict[str, str], pcs: set[str]) -> tuple[str, int, str]:
    """Latest cited row per entity. A row's name is resolved to its registry canonical name by exact
    (casefolded) name/alias equality; an unresolved name keys on itself and is reported. Rows for
    player characters are dropped. Returns ``(table, rows, report)``."""
    latest: dict[str, dict] = {}
    seen_forms: dict[str, set[str]] = {}
    unresolved: set[str] = set()
    dropped_pc: set[str] = set()
    for r in results:
        for row in r.npc_rows:
            canon = forms.get(row["name"].casefold())
            if canon is None:
                unresolved.add(row["name"])
            key = canon or row["name"]
            if key in pcs:
                dropped_pc.add(row["name"])
                continue
            seen_forms.setdefault(key.casefold(), set()).add(row["name"])
            k = key.casefold()
            cur = latest.get(k)
            # "Unknown" means this chapter did not say, not that the status changed: it never
            # replaces a known status, however late it is.
            if cur is None or (
                first_chapter(row["cite"]) >= first_chapter(cur["cite"])
                and (row["status"] != "Unknown" or cur["status"] == "Unknown")
            ) or (cur["status"] == "Unknown" and row["status"] != "Unknown"):
                latest[k] = {**row, "key": key, "later": cur.get("later") if cur else None}
            elif row["status"] == "Unknown" and first_chapter(row["cite"]) > first_chapter(cur["cite"]):
                # Shown, not decided: a later report that does not state a status (it may be a
                # disappearance the map failed to call Missing). The GM reads both.
                cur["later"] = row
    rows = sorted(latest.values(), key=lambda x: x["key"].casefold())
    lines = ["| NPC | Status | Last Known Location | Disposition toward Party | Established |", "|---|---|---|---|---|"]
    cell = lambda s: s.replace("|", "/").strip() or "—"  # noqa: E731
    for x in rows:
        mark = "" if forms.get(x["name"].casefold()) else " ⚠"
        loc = cell(x["location"])
        if x.get("later") and first_chapter(x["later"]["cite"]) > first_chapter(x["cite"]):
            lt = x["later"]
            loc += f"; later, status not stated: {cell(lt['location'])} ({cell(lt['disposition'])}) {lt['cite']}"
        lines.append(f"| {cell(x['key'])}{mark} | {x['status']} | {loc} | {cell(x['disposition'])} | {x['cite']} |")
    merged = {k: v for k, v in seen_forms.items() if len(v) > 1}
    rep = ["# NPC table identity report", "",
           f"{len(rows)} rows. ⚠ marks a name the registry does not know (kept as written, never guessed).", "",
           f"## Forms merged by registry name/alias ({len(merged)})", ""]
    rep += [f"- {latest[k]['key']}: {', '.join(sorted(v))}" for k, v in sorted(merged.items())]
    rep += ["", f"## Unresolved names ({len(unresolved)}) — add to the registry or fix at source", ""]
    rep += [f"- {n}" for n in sorted(unresolved, key=str.casefold)]
    rep += ["", f"## Player-character rows dropped ({len(dropped_pc)})", ""] + [f"- {n}" for n in sorted(dropped_pc)]
    return "\n".join(lines), len(rows), "\n".join(rep) + "\n"


def audit_section(results: list[MapResult], items: list[tuple[str, str, str]]) -> tuple[str, dict]:
    """SUPPORTED iff some chunk tagged the item SHOWN (all such cites listed). BEGUN-only items
    stay NOT FOUND, with the begun evidence listed underneath for the GM."""
    shown: dict[str, list[str]] = {}
    begun: dict[str, list[str]] = {}
    for r in results:
        for a in r.audit:
            (shown if a["tag"] == "SHOWN" else begun).setdefault(a["id"], []).append(a["text"])
    out, cur = [], None
    counts = {"SUPPORTED": 0, "NOT FOUND IN SUMMARIES": 0, "of which begun": 0}
    verdicts = {}
    for i, f, t in items:
        if f != cur:
            out.append(f"\n### {f}\n")
            cur = f
        if i in shown:
            counts["SUPPORTED"] += 1
            verdicts[t] = "SUPPORTED"
            out.append(f'- "{t}" — `SUPPORTED`')
            out += [f"  - {e}" for e in sorted(dict.fromkeys(shown[i]), key=first_chapter)]
        else:
            counts["NOT FOUND IN SUMMARIES"] += 1
            verdicts[t] = "NOT FOUND"
            out.append(f'- "{t}" — `NOT FOUND IN SUMMARIES`')
            if i in begun:
                counts["of which begun"] += 1
                out += [f"  - begun, not shown done: {e}" for e in sorted(dict.fromkeys(begun[i]), key=first_chapter)]
    return "\n".join(out).lstrip("\n"), {"counts": counts, "verdicts": verdicts}


# ── Reduce ──────────────────────────────────────────────────────────────────

# (doc, heading, routed notes builder name, whether the last chunk's evidence is attached)
REDUCES = [
    ("world_state", "## Party", "party", True),
    ("world_state", "## Factions and Powers", "FACTION", False),
    ("world_state", "## Key NPCs", "NPC", False),
    ("world_state", "## Locations", "LOCATION", False),
    ("world_state", "## Items and Artifacts", "ITEM", False),
    ("world_state", "## Active Threats and Open Pressures", "THREAT", False),
    ("campaign_state", "## Resolved Plot Threads", "threads", False),
    ("campaign_state", "## Active Quests & Open Threads", "threads", True),
    ("campaign_state", "## Party Current Situation", "party", True),
]

SECTION_BRIEFS = {
    "## Party": "Who the party is NOW: name, level, rank, each PC's current capabilities, gear and standing, and where they are. Latest note wins where notes conflict.",
    "## Factions and Powers": "Each faction or power as it stands NOW: goals, leaders, relationship to the party, last known move.",
    "## Key NPCs": "The NPCs who matter NOW: who they are, where they stand with the party, what they want. One sub-entry per NPC; skip walk-ons.",
    "## Locations": "Places as they stand NOW: what each is, who controls it, what the party did there and left unresolved.",
    "## Items and Artifacts": "Significant items NOW: what each does, who holds it, open questions about it.",
    "## Active Threats and Open Pressures": "What is pressing on the party NOW and from whom. Only things the notes do not show resolved.",
    "## Resolved Plot Threads": "Every thread the notes show RESOLVED or ABANDONED: one bullet each, saying how it ended, citing the resolution.",
    "## Active Quests & Open Threads": "Every thread OPENED or ADVANCED whose resolution the notes do not show. One bullet each with its latest state. If it is listed, it is unfinished.",
    "## Party Current Situation": "Where the party is, what they just did, and what they are about to face, at the very end of the range.",
}


#: --world-budget: per-section word budgets and briefs. The Opus one-shot sections ran ~350-650 words;
#: these allow somewhat more, since the point of the experiment is richer-but-loadable.
WORLD_BUDGET = {
    "## Party": (700, "Who the party is NOW: name, level, location, and per PC only what is current and likely to matter next session (signature abilities, key items, standing)."),
    "## Factions and Powers": (450, "The factions and powers that matter NOW (active, pressing, or allied): goal, leader, stance toward the party, last move. At most about 10."),
    "## Key NPCs": (900, "The NPCs who matter NOW: active in recent chapters, tied to an open thread or threat, or travelling with the party. At most about 20; one or two lines each."),
    "## Locations": (450, "Places that matter NOW: where the party is, where open threads point, places with unfinished business. At most about 10."),
    "## Items and Artifacts": (450, "Items in play NOW: held by the party and significant, sought, or dangerous. At most about 12."),
    "## Active Threats and Open Pressures": (600, "What is pressing on the party NOW and from whom, most urgent first. Only what the notes do not show resolved."),
}
REFERENCE_FOR = {"## Factions and Powers": "FACTION", "## Key NPCs": "NPC", "## Locations": "LOCATION",
                 "## Items and Artifacts": "ITEM", "## Active Threats and Open Pressures": "THREAT"}
SUBJECT_RE = re.compile(r"^-\s*\[[A-Z]+\]\s*\*\*(.+?)\*\*")


def write_reference(out: Path, tag: str, notes: list[str]) -> tuple[str, int, int]:
    """Every checked note for one World tag, grouped by its bold subject (exact text), chapter order
    within a subject. Code only. Returns ``(relative path, subjects, notes)``."""
    groups: dict[str, list[str]] = {}
    for n in notes:
        m = SUBJECT_RE.match(n)
        groups.setdefault(m.group(1).strip() if m else "(no subject)", []).append(n)
    rel = f"reference/{tag.lower()}s.md"
    body = [f"# Reference: {tag.title()} notes", "",
            f"{len(notes)} checked notes, {len(groups)} subjects, chapter order within each. Generated by code from the map notes.", ""]
    for subj in sorted(groups, key=str.casefold):
        body += [f"## {subj}", *groups[subj], ""]
    dump(out / rel, "\n".join(body) + "\n")
    return rel, len(groups), len(notes)


def reduce_prompt(doc: str, heading: str, notes: list[str], extra: str, last_chunk: list[Chapter] | None,
                  budgeted: bool = False) -> tuple[str, str]:
    if budgeted:
        system = (HERE / "prompts" / "reduce_world.system.md").read_text(encoding="utf-8")
        words, brief = WORLD_BUDGET[heading]
        head = f"DOCUMENT: {doc}\nSECTION: {heading}\nBRIEF: {brief}\nWORD BUDGET: {words} words, hard limit.\n\n"
    else:
        system = (HERE / "prompts" / "reduce.system.md").read_text(encoding="utf-8")
        head = f"DOCUMENT: {doc}\nSECTION: {heading}\nBRIEF: {SECTION_BRIEFS[heading]}\n\n"
    user = (
        head
        + f"VERIFIED NOTES ({len(notes)} bullets, chapter order, every one already checked by code):\n\n"
        + "\n".join(notes)
        + ("\n\n" + extra if extra else "")
        + (
            f"\n\nEVIDENCE OF THE LAST CHUNK ONLY (chapters {rng(last_chunk)}), for the current state:\n"
            + "".join(c.block for c in last_chunk)
            if last_chunk else ""
        )
        + f"\n\nOUTLINE: write exactly this one `##` heading and its body, nothing else at that level:\n\n{heading}\n"
    )
    return system, user


# ── Driver ──────────────────────────────────────────────────────────────────


def call(client, system: str, user: str, max_tokens: int) -> tuple[str, float]:
    t = time.monotonic()
    out = stream_api(client, system, user, MODEL, max_tokens=max_tokens, silent=True)
    return out, time.monotonic() - t


def run_pool(items, fn, clients: dict[str, object], per_endpoint: int):
    """Yield ``(endpoint, item, fn(client, item))`` as each finishes.

    One shared queue, ``per_endpoint`` worker threads per endpoint, each thread holding its
    endpoint's client. Workers pull the next item when free, so a slow box takes fewer items
    instead of stalling the tail (no fixed split between boxes)."""
    import queue
    import threading

    todo: queue.Queue = queue.Queue()
    for it in items:
        todo.put(it)
    done: queue.Queue = queue.Queue()

    def worker(ep: str, client) -> None:
        while True:
            try:
                it = todo.get_nowait()
            except queue.Empty:
                return
            try:
                done.put((ep, it, fn(client, it), None))
            except BaseException as e:  # noqa: BLE001 - surfaced to the caller below
                done.put((ep, it, None, e))

    threads = [threading.Thread(target=worker, args=(ep, c), daemon=True)
               for ep, c in clients.items() for _ in range(per_endpoint)]
    for t in threads:
        t.start()
    for _ in range(len(items)):
        ep, it, res, err = done.get()
        if err is not None:
            raise err
        yield ep, it, res


def preflight(endpoints: list[str]) -> str | None:
    """A refusal message unless every endpoint answers /models and serves MODEL."""
    import urllib.request

    for ep in endpoints:
        url = ep.rstrip("/") + "/models"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                ids = [m.get("id") for m in json.load(r).get("data", [])]
        except Exception as e:  # noqa: BLE001
            return f"{short(ep)}: not answering ({type(e).__name__}: {e})"
        if MODEL not in ids:
            return f"{short(ep)}: serves {ids}, not {MODEL}; every endpoint must serve the same model"
    return None


def short(ep: str) -> str:
    return re.sub(r"^https?://|/v1/?$", "", ep)


def dump(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_map(args, chapters, chunks, audit, clients) -> list[MapResult]:
    mdir = args.out / "map"
    ids = {i for i, _, _ in audit}

    def one(client, item):
        k, chunk = item
        raw_p = mdir / f"chunk{k:02d}.{rng(chunk)}.out.md"
        if raw_p.is_file() and not args.force:
            return k, raw_p.read_text(encoding="utf-8"), 0.0, True
        system, user = map_prompt(chunk, audit)
        dump(mdir / f"chunk{k:02d}.{rng(chunk)}.user.md", user)
        for attempt in (1, 2):
            try:
                raw, secs = call(client, system, user, args.max_tokens)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"  chunk {k} retry after {type(e).__name__}: {e}", flush=True)
        dump(raw_p, raw)
        return k, raw, secs, False

    raws: dict[int, tuple[str, float, bool, str]] = {}
    t0 = time.monotonic()
    for n, (ep, (k, chunk), (_, raw, secs, cached)) in enumerate(
        run_pool(list(enumerate(chunks, 1)), one, clients, args.workers), 1
    ):
        raws[k] = (raw, secs, cached, ep)
        print(f"map {n:02d}/{len(chunks)} chunk {k:02d} ch {rng(chunk)} @{short(ep)} "
              f"{'cached' if cached else f'{secs:.0f}s'} ({len(raw)} chars) [elapsed {time.monotonic()-t0:.0f}s]", flush=True)
    results, timing = [], []
    for k, chunk in enumerate(chunks, 1):
        raw, secs, cached, ep = raws[k]
        res = check_map(raw, chunk, ids)
        results.append(res)
        timing.append({"chunk": k, "chapters": rng(chunk), "chars": sum(len(c.text) for c in chunk), "secs": round(secs, 1),
                       "cached": cached, "endpoint": ep,
                       "kept": {h: len(v) for h, v in res.kept.items()}, "dropped": len(res.drops)})
    per_ep = {ep: sum(1 for t in timing if t["endpoint"] == ep and not t["cached"]) for ep in clients}
    dump(args.out / "map_record.json", json.dumps(
        {"wall_secs": round(time.monotonic() - t0, 1), "workers_per_endpoint": args.workers,
         "calls_per_endpoint": per_ep, "chunks": timing}, indent=2))
    lines = ["# Map-check drops", ""]
    for r in results:
        if r.drops:
            lines.append(f"## Chunk {r.chunk} — {len(r.drops)} dropped")
            lines += [f"- [{s}] {why}: {t}" for s, why, t in r.drops]
            lines.append("")
    dump(args.out / "drops.md", "\n".join(lines) + "\n")
    return results


def run_reduce(args, chunks, results, audit, clients) -> None:
    rdir = args.out / "reduce"
    forms, pcs = load_identity(args.campaign)
    table, n_npcs, report = npc_table(results, forms, pcs)
    dump(args.out / "npc_table_report.md", report)
    threads = stitched(results, "## Threads")
    notes_for = {
        "party": stitched(results, "## Party"),
        "threads": threads,
        **{t: stitched(results, "## World", t) for t in WORLD_TAGS},
    }
    jobs = []
    for doc, heading, route, last in REDUCES:
        notes = notes_for[route]
        extra = ""
        if heading == "## Key NPCs":
            extra = "CODE-BUILT NPC STATUS TABLE (latest cited row per name; context, do not copy):\n\n" + table
        if heading == "## Active Threats and Open Pressures":
            extra = "THREAD LEDGER (OPENED / ADVANCED / RESOLVED / ABANDONED):\n\n" + "\n".join(threads)
        budgeted = args.world_budget and doc == "world_state"
        system, user = reduce_prompt(doc, heading, notes, extra, chunks[-1] if last else None, budgeted)
        slug = f"{doc}{'.budgeted' if budgeted else ''}.{heading[3:].lower().replace(' ', '_').replace('&', 'and')}"
        jobs.append((slug, doc, heading, system, user))

    outs: dict[str, str] = {}
    rec = {}

    def one(client, job):
        slug, doc, heading, system, user = job
        p = rdir / f"{slug}.out.md"
        dump(rdir / f"{slug}.user.md", user)
        if p.is_file() and not args.force:
            return slug, p.read_text(encoding="utf-8"), 0.0, len(user)
        raw, secs = call(client, system, user, args.max_tokens)
        dump(p, raw)
        return slug, raw, secs, len(user)

    for ep, _, (slug, raw, secs, n) in run_pool(jobs, one, clients, args.workers):
        outs[slug] = raw
        rec[slug] = {"secs": round(secs, 1), "prompt_chars": n, "endpoint": ep}
        print(f"reduce {slug} @{short(ep)} {secs:.0f}s ({n} prompt chars -> {len(raw)} chars)", flush=True)
    dump(args.out / "reduce_record.json", json.dumps(rec, indent=2))

    def body(slug: str, heading: str) -> str:
        secs = npc_check.parse_sections(outs[slug])
        return npc_check.section_text(secs, heading) or "(reduce call wrote no body)"

    by = {(d, h): s for s, d, h, _, _ in jobs}
    timeline = stitched(results, "## Events")
    world = [
        ("## Party", body(by[("world_state", "## Party")], "## Party")),
        ("## Factions and Powers", body(by[("world_state", "## Factions and Powers")], "## Factions and Powers")),
        ("## Key NPCs", body(by[("world_state", "## Key NPCs")], "## Key NPCs")),
        ("## Locations", body(by[("world_state", "## Locations")], "## Locations")),
        ("## Items and Artifacts", body(by[("world_state", "## Items and Artifacts")], "## Items and Artifacts")),
        ("## Active Threats and Open Pressures", body(by[("world_state", "## Active Threats and Open Pressures")], "## Active Threats and Open Pressures")),
        ("## Canon Events Timeline", (
            f"The full timeline ({len(timeline)} events, ch {args.since:03d}-{args.until:03d}, every one cited) "
            f"is a separate file: `{TIMELINE_FILE}`. It is code-stitched from the checked map notes, in "
            "chapter order, and is not loaded with this document."
        )),
    ]
    world_name = "world_state.chunked.md"
    if args.world_budget:
        world_name = "world_state.budgeted.md"
        budget_rec = {}
        for i, (h, b) in enumerate(world):
            if h in REFERENCE_FOR:
                rel, n_subj, n_notes = write_reference(args.out, REFERENCE_FOR[h], notes_for[REFERENCE_FOR[h]])
                b = b.rstrip() + f"\n\n_Full notes: `{rel}` ({n_subj} subjects, {n_notes} checked notes)._"
                world[i] = (h, b)
            if h in WORLD_BUDGET:
                words = len(re.sub(r"\[ch [^\]]*\]", "", b).split())  # citations don't count
                budget_rec[h] = {"budget": WORLD_BUDGET[h][0], "words": words, "over": words > WORLD_BUDGET[h][0]}
        dump(args.out / "world_budget_report.json", json.dumps(budget_rec, indent=2))
        for h, r in budget_rec.items():
            print(f"budget {h[3:]}: {r['words']}/{r['budget']} words{'  OVER' if r['over'] else ''}")
    dump(args.out / TIMELINE_FILE, (
        f"<!-- PROTOTYPE chunked-spark | canon events timeline | ch{args.since:03d}-{args.until:03d} | {MODEL} -->\n"
        f"# Canon Events Timeline\n\n" + "\n".join(timeline) + "\n"
    ))
    audit_md, audit_info = audit_section(results, audit)
    camp = [
        ("## Completed Encounters & Quests", "\n".join(stitched(results, "## Concluded"))),
        ("## Resolved Plot Threads", body(by[("campaign_state", "## Resolved Plot Threads")], "## Resolved Plot Threads")),
        ("## NPC Current States", table),
        ("## Active Quests & Open Threads", body(by[("campaign_state", "## Active Quests & Open Threads")], "## Active Quests & Open Threads")),
        ("## Party Current Situation", body(by[("campaign_state", "## Party Current Situation")], "## Party Current Situation")),
        ("## Audit: Tracking Claims", audit_md),
    ]
    hdr = f"<!-- PROTOTYPE chunked-spark draft | {{doc}} | ch{args.since:03d}-{args.until:03d} | {MODEL} | chunk {args.chunk_chars} -->\n"
    dump(args.out / world_name, hdr.format(doc="world_state") + "\n\n".join(f"{h}\n{b}" for h, b in world) + "\n")
    dump(args.out / "campaign_state.chunked.md", hdr.format(doc="campaign_state") + "\n\n".join(f"{h}\n{b}" for h, b in camp) + "\n")
    dump(args.out / "audit.json", json.dumps(audit_info, indent=2, ensure_ascii=False))
    print(f"wrote world_state.chunked.md, campaign_state.chunked.md ({n_npcs} NPC rows, audit {audit_info['counts']})")


def main() -> int:
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--since", type=int, default=2)
    ap.add_argument("--until", type=int, default=70)
    ap.add_argument("--chunk-chars", type=int, default=60000)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--model", default=MODEL, help=f"served model id on every endpoint (default {MODEL})")
    ap.add_argument("--endpoint", action="append", default=None, metavar="URL",
                    help=f"OpenAI-compatible endpoint serving {MODEL}; repeat for several boxes "
                         f"(default {ENDPOINT}). Every endpoint must serve the same model.")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent calls PER ENDPOINT (vLLM max_num_seqs is 8 on the Sparks)")
    ap.add_argument("--limit-chunks", type=int, default=0, help="map only the first N chunks (pilot)")
    ap.add_argument("--stage", choices=("map", "all"), default="all")
    ap.add_argument("--force", action="store_true", help="ignore cached map/reduce outputs")
    ap.add_argument("--world-budget", action="store_true",
                    help="world_state prose sections get word budgets + reference files; writes world_state.budgeted.md")
    ap.add_argument("--assemble-only", action="store_true",
                    help="no model calls: rebuild the documents from cached map/reduce outputs (refuses if any is missing)")
    args = ap.parse_args()
    MODEL = args.model

    chapters = load_chapters(args.campaign / "docs" / "summaries", args.since, args.until)
    chunks = make_chunks(chapters, args.chunk_chars)
    if args.limit_chunks:
        chunks = chunks[: args.limit_chunks]
    audit = load_audit(sorted((args.campaign / "docs" / "tracking").glob("tracking*.txt")))
    if args.assemble_only:
        missing = [k for k, c in enumerate(chunks, 1) if not (args.out / "map" / f"chunk{k:02d}.{rng(c)}.out.md").is_file()]
        missing += [s for s in ("world_state.party", "world_state.key_npcs") if not (args.out / "reduce" / f"{s}.out.md").is_file()]
        if missing or args.force:
            print(f"Error: --assemble-only needs every map/reduce output cached (missing: {missing[:5]})", file=sys.stderr)
            return 2
        MODEL = json.loads((args.out / "run_model.json").read_text())["model"] if (args.out / "run_model.json").is_file() else MODEL
        endpoints, clients = ["cache-only"], {"cache-only": None}
    else:
        endpoints = list(dict.fromkeys(args.endpoint or [ENDPOINT]))
        problem = preflight(endpoints)
        if problem:
            print(f"Error: {problem}", file=sys.stderr)
            return 2
        clients = {ep: client_from_args(argparse.Namespace(backend="dgx", endpoint=ep, model=MODEL)) for ep in endpoints}
        dump(args.out / "run_model.json", json.dumps({"model": MODEL, "endpoints": endpoints}))
    print(f"{len(chapters)} chapters, {len(chunks)} chunks, {len(audit)} audit items, "
          f"{len(endpoints)} endpoint(s) x {args.workers} workers: {', '.join(short(e) for e in endpoints)}")
    results = run_map(args, chapters, chunks, audit, clients)
    print("map kept:", {h: sum(len(r.kept[h]) for r in results) for h in MAP_SECTIONS},
          "dropped:", sum(len(r.drops) for r in results))
    if args.stage == "all":
        run_reduce(args, chunks, results, audit, clients)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
