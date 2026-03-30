"""Connections API — extract entities/relationships, generate graph HTML."""

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

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
            return f.read()
    finally:
        os.unlink(tmp_path)


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


@router.post("/extract")
def extract_connections(req: ExtractRequest):
    """Call Claude API to extract entities and relationships from documents."""
    CHAR_LIMIT = 600_000

    parts = []
    for fp in req.files:
        p = Path(fp).expanduser().resolve()
        if p.is_file():
            parts.append(f"<!-- {fp} -->\n\n{p.read_text(encoding='utf-8').strip()}")

    if not parts:
        return JSONResponse({"error": "No valid files provided"}, status_code=400)

    combined = "\n\n---\n\n".join(parts)
    if len(combined) > CHAR_LIMIT:
        return JSONResponse(
            {"error": f"Combined text is {len(combined):,} chars — exceeds {CHAR_LIMIT:,} limit"},
            status_code=400,
        )

    # Import campaignlib for API call
    import sys
    script_dir = str(Path(__file__).resolve().parent.parent.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from campaignlib import make_client, stream_api

    client = make_client()
    raw = stream_api(client, CONNECTIONS_SYSTEM, combined, req.model,
                     max_tokens=4096, silent=True)

    # Strip code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.splitlines()[:-1])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"JSON parse error: {e}", "raw": raw[:2000]}, status_code=500)

    # Cache to file
    cache = Path(req.cache_path) if req.cache_path else Path.cwd() / "docs" / "connections.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "entities": len(data.get("entities", [])),
        "edges": len(data.get("edges", [])),
        "data": data,
        "cache_path": str(cache),
    }


@router.get("/data")
def get_connection_data(cache_path: str = ""):
    """Load cached connections.json."""
    cache = Path(cache_path) if cache_path else Path.cwd() / "docs" / "connections.json"
    if not cache.exists():
        return {"data": None}
    data = json.loads(cache.read_text(encoding="utf-8"))
    return {"data": data}


class GraphRequest(BaseModel):
    filter_types: list[str] = []


@router.post("/graph")
def get_graph_html(req: GraphRequest, cache_path: str = ""):
    """Generate pyvis graph HTML from cached data."""
    cache = Path(cache_path) if cache_path else Path.cwd() / "docs" / "connections.json"
    if not cache.exists():
        return HTMLResponse("<p style='color:#fab387'>No connections data. Run Extract first.</p>")

    data = json.loads(cache.read_text(encoding="utf-8"))
    filter_set = set(req.filter_types) if req.filter_types else {
        "npc", "faction", "location", "plot", "arc_score", "party"
    }
    html = _build_graph_html(data, filter_set)
    return HTMLResponse(html)
