"""Connections API — extract entities/relationships, persist, query, visualize."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Make campaignlib importable regardless of CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib import (  # noqa: E402
    find_registry,
    build_alias_normalizer,
    client_from_args,
    format_npc_roster,
    load_alias_map,
    stream_api,
)

router = APIRouter()

CONNECTIONS_SYSTEM = """\
You are extracting named entities and relationships from D&D campaign documents.

Output a single JSON object with exactly this structure:
{
  "entities": [
    {"id": "snake_case_unique_id", "label": "Display Name", "type": "TYPE", "summary": "one sentence"}
  ],
  "edges": [
    {"source": "id1", "target": "id2", "label": "relationship"}
  ]
}

Entity types (use exactly these strings):
  npc       — named non-player characters
  faction   — organizations, cults, societies, guilds
  location  — named places, dungeons, regions
  plot      — active quests, plot threads, missions
  arc_score — tracking scores (e.g. Brundar's Echo, Planar Distortion Score)
  party     — player characters

Rules:
- Every entity that appears must have a unique snake_case id.
- The "summary" field is one sentence describing who/what this entity is.
- For edges, use concise relationship labels: "member of", "enemy of", "ally of",
  "located in", "triggered by", "seeks", "controls", "allied with", "hunts", etc.
- Only create edges between entities that appear in your entities list.
- Do not invent entities or relationships not present in the source documents.
- Output only valid JSON. No preamble, no code fences, no commentary.
"""

NODE_COLORS = {
    "npc":       "#4e9af1",
    "faction":   "#f1814e",
    "location":  "#4ef1a0",
    "plot":      "#c44ef1",
    "arc_score": "#f1e14e",
    "party":     "#4ef1e1",
}

NODE_SHAPES = {
    "npc":       "dot",
    "faction":   "diamond",
    "location":  "square",
    "plot":      "triangle",
    "arc_score": "star",
    "party":     "dot",
}

EDGE_COLORS = {
    "hostile":  "#ff4444",
    "allied":   "#44ff88",
    "member":   "#ffaa44",
    "located":  "#44aaff",
    "triggers": "#ff44ff",
    "seeks":    "#ffff44",
    "default":  "#cccccc",
}


def _edge_color(label: str) -> str:
    ll = label.lower()
    if any(w in ll for w in ("enemy", "hostile", "hunts", "opposes", "against", "fights", "kills")):
        return EDGE_COLORS["hostile"]
    if any(w in ll for w in ("ally", "allied", "support", "serves", "works for", "loyal", "friend")):
        return EDGE_COLORS["allied"]
    if any(w in ll for w in ("member", "belongs", "part of", "controls", "leads", "commands", "runs")):
        return EDGE_COLORS["member"]
    if any(w in ll for w in ("located", "based", "found at", " at ", "resides", "in ", "operates")):
        return EDGE_COLORS["located"]
    if any(w in ll for w in ("trigger", "activates", "causes", "linked", "tied to", "scores")):
        return EDGE_COLORS["triggers"]
    if any(w in ll for w in ("seeks", "pursues", "wants", "searches", "hunts for", "after")):
        return EDGE_COLORS["seeks"]
    return EDGE_COLORS["default"]


# ── Canonicalization and merge (pure functions, unit-testable) ───────────────

_VALID_TYPES = {"npc", "faction", "location", "plot", "arc_score", "party"}


def _slug(s: str) -> str:
    """Lowercase, non-alnum → underscore, collapse repeats, strip edges."""
    s = re.sub(r"[^a-z0-9]+", "_", s.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def canonicalize(data: dict) -> dict:
    """Rewrite entity IDs to `{type}_{slug(label)}` so they're stable across runs.

    Edge source/target get rewritten via an old→new map; edges referencing
    dropped entities are discarded. Duplicates (same canonical id) collapse
    to the last one seen within a single extraction payload.
    """
    old_to_new: dict[str, str] = {}
    entities: dict[str, dict] = {}
    for ent in data.get("entities", []):
        label = (ent.get("label") or "").strip()
        etype = (ent.get("type") or "").strip()
        if not label or etype not in _VALID_TYPES:
            continue
        new_id = f"{etype}_{_slug(label)}"
        if not new_id.endswith("_") and _slug(label):
            old_id = ent.get("id") or new_id
            old_to_new[old_id] = new_id
            entities[new_id] = {
                "id": new_id,
                "label": label,
                "type": etype,
                "summary": ent.get("summary", ""),
            }

    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in data.get("edges", []):
        src = old_to_new.get(edge.get("source"))
        tgt = old_to_new.get(edge.get("target"))
        if not src or not tgt or src == tgt:
            continue
        label = edge.get("label", "")
        key = (src, tgt, label)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": src, "target": tgt, "label": label})

    return {"entities": list(entities.values()), "edges": edges}


def merge(old: dict, new: dict) -> dict:
    """Union old + new. For entity id collisions, prefer new (fresher summary).

    Edges dedupe by (source, target, label). Both inputs should already be
    canonicalized.
    """
    entities = {e["id"]: e for e in old.get("entities", [])}
    for ent in new.get("entities", []):
        entities[ent["id"]] = ent

    edge_map: dict[tuple[str, str, str], dict] = {}
    for e in old.get("edges", []):
        edge_map[(e["source"], e["target"], e.get("label", ""))] = e
    for e in new.get("edges", []):
        edge_map[(e["source"], e["target"], e.get("label", ""))] = e

    # Drop edges that reference entities no longer present (shouldn't
    # happen after canonicalize, but belt-and-braces).
    valid = set(entities.keys())
    edges = [e for e in edge_map.values() if e["source"] in valid and e["target"] in valid]

    return {"entities": list(entities.values()), "edges": edges}


def find_simple_paths(
    data: dict, source: str, target: str, max_hops: int, max_paths: int
) -> list[dict]:
    """Return all simple paths (no repeated nodes) of length ≤ max_hops.

    Paths are undirected — "A allied with B" connects A and B regardless of
    which one was source in the edge. Direction is preserved per-edge in the
    output so callers can see "A → allied with → B" or "B → allied with → A".
    """
    entities = {e["id"]: e for e in data.get("entities", [])}
    if source not in entities or target not in entities or source == target:
        return []

    # Undirected adjacency: neighbor id → list of (edge_dict, direction_from_current)
    adj: dict[str, list[tuple[dict, str]]] = {}
    for edge in data.get("edges", []):
        s, t = edge.get("source"), edge.get("target")
        if s in entities and t in entities:
            adj.setdefault(s, []).append((edge, "out"))
            adj.setdefault(t, []).append((edge, "in"))

    results: list[dict] = []

    def dfs(current: str, nodes: list[str], path_edges: list[dict], depth: int):
        if len(results) >= max_paths:
            return
        if current == target and path_edges:
            results.append({
                "length": len(path_edges),
                "nodes": [
                    {"id": nid, "label": entities[nid]["label"], "type": entities[nid]["type"]}
                    for nid in nodes
                ],
                "edges": path_edges,
            })
            return
        if depth >= max_hops:
            return
        for edge, _direction in adj.get(current, []):
            neighbor = edge["target"] if edge["source"] == current else edge["source"]
            if neighbor in nodes:
                continue
            dfs(
                neighbor,
                nodes + [neighbor],
                path_edges + [dict(edge)],
                depth + 1,
            )

    dfs(source, [source], [], 0)
    results.sort(key=lambda p: (p["length"], tuple(n["id"] for n in p["nodes"])))
    return results[:max_paths]


def neighbors_of(data: dict, entity_id: str) -> list[dict]:
    """Return deduped 1-hop neighbors with edge label and direction."""
    entities = {e["id"]: e for e in data.get("entities", [])}
    if entity_id not in entities:
        return []
    seen: dict[str, dict] = {}
    for edge in data.get("edges", []):
        if edge.get("source") == entity_id and edge.get("target") in entities:
            nid = edge["target"]
            key = f"{nid}::{edge.get('label', '')}::out"
            if key not in seen:
                seen[key] = {
                    "entity": entities[nid],
                    "edge_label": edge.get("label", ""),
                    "direction": "out",
                }
        elif edge.get("target") == entity_id and edge.get("source") in entities:
            nid = edge["source"]
            key = f"{nid}::{edge.get('label', '')}::in"
            if key not in seen:
                seen[key] = {
                    "entity": entities[nid],
                    "edge_label": edge.get("label", ""),
                    "direction": "in",
                }
    return list(seen.values())


# ── Graph HTML rendering (unchanged) ──────────────────────────────────────────


def _build_graph_html(data: dict, filter_types: set[str]) -> str:
    """Build a pyvis graph and return the HTML string."""
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:red'>pyvis not installed on server. Run: pip install pyvis</p>"

    net = Network(height="100%", width="100%", bgcolor="#1a1a2e", font_color="white",
                  directed=True)
    net.set_options("""{
      "physics": {
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 200,
          "springConstant": 0.06,
          "damping": 0.4
        },
        "stabilization": {"iterations": 150}
      },
      "nodes": {
        "size": 22,
        "font": {"size": 14, "strokeWidth": 3, "strokeColor": "#1a1a2e"},
        "borderWidth": 2,
        "borderWidthSelected": 4
      },
      "edges": {
        "font": {
          "size": 11,
          "align": "middle",
          "color": "#ffffff",
          "strokeWidth": 3,
          "strokeColor": "#1a1a2e"
        },
        "arrows": {"to": {"enabled": true, "scaleFactor": 0.6}},
        "smooth": {"type": "curvedCW", "roundness": 0.15},
        "width": 1.5,
        "selectionWidth": 3
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 80,
        "navigationButtons": true,
        "hideEdgesOnDrag": true
      }
    }""")

    entity_ids = set()
    for ent in data.get("entities", []):
        if ent.get("type") not in filter_types:
            continue
        eid = ent["id"]
        entity_ids.add(eid)
        etype = ent.get("type", "npc")
        color = NODE_COLORS.get(etype, "#888888")
        shape = NODE_SHAPES.get(etype, "dot")
        tooltip = f"{ent['label']} [{etype}]\n{ent.get('summary', '')}"
        net.add_node(eid, label=ent["label"], color=color, shape=shape,
                     title=tooltip, group=etype)

    for edge in data.get("edges", []):
        src, tgt = edge.get("source"), edge.get("target")
        rel = edge.get("label", "")
        if src in entity_ids and tgt in entity_ids:
            ecolor = _edge_color(rel)
            net.add_edge(src, tgt, label=rel, title=rel,
                         color={"color": ecolor, "highlight": "#ffffff", "opacity": 0.85},
                         font={"color": "#ffffff", "strokeWidth": 3, "strokeColor": "#1a1a2e"})

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        tmp_path = f.name
    try:
        net.save_graph(tmp_path)
        with open(tmp_path) as f:
            html = f.read()
    finally:
        os.unlink(tmp_path)

    # Strip pyvis's Bootstrap card wrapper — otherwise the graph renders
    # inside a tiny white box with fixed dimensions inside the iframe.
    override_css = """
    <style>
      html, body { height: 100%; width: 100%; margin: 0; padding: 0;
                   background: #1a1a2e; overflow: hidden; }
      .card { border: none !important; background: #1a1a2e !important;
              height: 100% !important; width: 100% !important;
              margin: 0 !important; padding: 0 !important; }
      .card-body, #card-body, div.card > div { padding: 0 !important;
              height: 100% !important; width: 100% !important; }
      #mynetwork { height: 100vh !important; width: 100vw !important;
                   background: #1a1a2e !important; border: none !important; }
    </style>
    """
    html = html.replace("</head>", override_css + "</head>", 1)
    return html


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_cache(cache_path: str) -> Path:
    return Path(cache_path) if cache_path else Path.cwd() / "docs" / "connections.json"


def _load_cache(cache_path: str) -> dict | None:
    cache = _default_cache(cache_path)
    if not cache.exists():
        return None
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/list-docs")
def list_docs(docs_dir: str = ""):
    """List .md files in a directory."""
    if not docs_dir.strip():
        return {"files": []}
    d = Path(docs_dir).expanduser().resolve()
    if not d.is_dir():
        return {"files": [], "error": f"Not a directory: {d}"}
    files = sorted(str(f) for f in d.rglob("*.md"))
    return {"files": files, "base": str(d)}


class ExtractRequest(BaseModel):
    files: list[str]
    model: str = "claude-sonnet-4-6"
    cache_path: str = ""
    dossier_dir: str = ""
    replace: bool = False


@router.post("/extract")
def extract_connections(req: ExtractRequest):
    """Call Claude to extract entities/relationships, canonicalize IDs, merge into cache."""
    CHAR_LIMIT = 600_000

    # Server has no campaign CWD, so derive the registry (if any) from the
    # request's dossier dir campaign root: <campaign>/docs/npcs -> <campaign>.
    # find_registry returns None for non-standard layouts, so this only ever
    # opts into a registry when one actually sits beside the dossiers.
    alias_map = (
        load_alias_map(req.dossier_dir,
                       registry_path=find_registry(Path(req.dossier_dir).parent.parent))
        if req.dossier_dir else {}
    )
    normalize, _ = build_alias_normalizer(alias_map)
    roster = format_npc_roster(alias_map)

    parts = []
    for fp in req.files:
        p = Path(fp).expanduser().resolve()
        if p.is_file():
            content = normalize(p.read_text(encoding="utf-8").strip())
            parts.append(f"<!-- {fp} -->\n\n{content}")

    if not parts:
        return JSONResponse({"error": "No valid files provided"}, status_code=400)

    combined = "\n\n---\n\n".join(parts)
    if len(combined) > CHAR_LIMIT:
        return JSONResponse(
            {"error": f"Combined text is {len(combined):,} chars — exceeds {CHAR_LIMIT:,} limit"},
            status_code=400,
        )

    system = CONNECTIONS_SYSTEM + (("\n\n" + roster) if roster else "")

    # req has no backend/endpoint fields, so this resolves identically to the
    # old bare make_client() — just routed through the one approved seam.
    client = client_from_args(req)
    # 32K output gives room for ~300 entities + ~500 edges. 4K truncates large
    # campaigns mid-string and produces unparseable JSON.
    raw = stream_api(client, system, combined, req.model, max_tokens=32000, silent=True)

    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.splitlines()[:-1])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        looks_truncated = not raw.rstrip().endswith("}")
        hint = (
            " — response appears truncated (hit output token cap). "
            "Try extracting fewer documents at once; they'll merge into the same cache."
            if looks_truncated else ""
        )
        return JSONResponse(
            {"error": f"JSON parse error: {e}{hint}", "raw": raw[-2000:]},
            status_code=500,
        )

    data = canonicalize(data)

    cache = _default_cache(req.cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)

    merged_into_existing = cache.exists() and not req.replace
    if merged_into_existing:
        try:
            old = json.loads(cache.read_text(encoding="utf-8"))
            data = merge(old, data)
        except json.JSONDecodeError:
            pass  # corrupt cache — start fresh

    cache.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "entities": len(data.get("entities", [])),
        "edges": len(data.get("edges", [])),
        "data": data,
        "cache_path": str(cache),
        "merged": merged_into_existing,
    }


@router.get("/data")
def get_connection_data(cache_path: str = ""):
    """Load cached connections.json."""
    data = _load_cache(cache_path)
    return {"data": data}


class GraphRequest(BaseModel):
    filter_types: list[str] = []


@router.post("/graph")
def get_graph_html(req: GraphRequest, cache_path: str = ""):
    """Generate pyvis graph HTML from cached data."""
    data = _load_cache(cache_path)
    if data is None:
        return HTMLResponse("<p style='color:#fab387'>No connections data. Run Extract first.</p>")

    filter_set = set(req.filter_types) if req.filter_types else {
        "npc", "faction", "location", "plot", "arc_score", "party"
    }
    html = _build_graph_html(data, filter_set)
    return HTMLResponse(html)


@router.get("/paths")
def get_paths(
    source: str,
    target: str,
    max_hops: int = 4,
    max_paths: int = 50,
    cache_path: str = "",
):
    """Find simple paths between two entities. Undirected traversal, direction preserved per-edge."""
    data = _load_cache(cache_path)
    if data is None:
        return {"error": "No connections data. Run Extract first.", "paths": []}

    entities = {e["id"]: e for e in data.get("entities", [])}
    if source not in entities:
        return {"error": f"Unknown source entity: {source}", "paths": []}
    if target not in entities:
        return {"error": f"Unknown target entity: {target}", "paths": []}

    max_hops = max(1, min(max_hops, 8))
    max_paths = max(1, min(max_paths, 500))

    paths = find_simple_paths(data, source, target, max_hops, max_paths)
    return {
        "source": source,
        "target": target,
        "paths": paths,
        "count": len(paths),
    }


@router.get("/context")
def get_context(
    entity_id: str,
    docs_dir: str = "",
    dossier_dir: str = "",
    cache_path: str = "",
):
    """Return entity + 1-hop neighbors + list of doc files mentioning it."""
    data = _load_cache(cache_path)
    if data is None:
        return {"error": "No connections data.", "entity": None}

    entities = {e["id"]: e for e in data.get("entities", [])}
    entity = entities.get(entity_id)
    if not entity:
        return {"error": f"Unknown entity: {entity_id}", "entity": None}

    hops = neighbors_of(data, entity_id)

    # Build search terms: canonical label plus any aliases from the dossier map.
    terms = [entity["label"]]
    if dossier_dir:
        alias_map = load_alias_map(
            dossier_dir, registry_path=find_registry(Path(dossier_dir).parent.parent))
        for canonical, aliases in alias_map.items():
            if canonical.lower() == entity["label"].lower():
                terms.extend(aliases)
                break

    source_files: list[str] = []
    if docs_dir:
        docs_path = Path(docs_dir).expanduser().resolve()
        if docs_path.is_dir():
            pattern = re.compile(
                r"\b(" + "|".join(re.escape(t) for t in terms if t) + r")\b",
                flags=re.IGNORECASE,
            )
            for md in sorted(docs_path.rglob("*.md")):
                try:
                    if pattern.search(md.read_text(encoding="utf-8")):
                        source_files.append(str(md))
                except OSError:
                    continue

    return {
        "entity": entity,
        "neighbors": hops,
        "source_files": source_files,
        "search_terms": terms,
    }
