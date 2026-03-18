#!/usr/bin/env python3
"""Streamlit web UI for CampaignGenerator.

Run with:
  streamlit run app.py
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_CONFIG = str(SCRIPT_DIR / "config" / "config.yaml")

MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def path_status(path_str: str) -> str:
    if not path_str.strip():
        return ""
    return "✅" if Path(path_str).expanduser().exists() else "❌ not found"


def path_field(label: str, key: str, default: str = "", help: str = "", required: bool = False) -> str:
    label_text = f"{label} {'*(required)*' if required else '*(optional)*'}"
    val = st.text_input(label_text, value=st.session_state.get(key, default),
                        key=key, help=help)
    if val.strip():
        st.caption(path_status(val))
    return val.strip()


def multi_path_field(label: str, key: str, help: str = "", required: bool = False) -> list[str]:
    label_text = f"{label} {'*(required)*' if required else '*(optional)*'} — one path per line"
    val = st.text_area(label_text, value=st.session_state.get(key, ""),
                       key=key, help=help, height=100)
    paths = [p.strip() for p in val.splitlines() if p.strip()]
    for p in paths:
        st.caption(f"`{p}` {path_status(p)}")
    return paths


def format_command(cmd: list[str]) -> str:
    return shlex.join(str(c) for c in cmd)


def run_subprocess(cmd: list[str], output_placeholder) -> int:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(SCRIPT_DIR),
    )
    collected: list[str] = []
    for i, line in enumerate(proc.stdout):
        collected.append(line)
        if i % 3 == 0:
            output_placeholder.code("".join(collected), language=None)
    output_placeholder.code("".join(collected), language=None)
    proc.wait()
    return proc.returncode


def run_panel(cmd: list[str], key: str) -> None:
    """Show command preview and run button. Streams output on click."""
    st.divider()
    st.subheader("Command")
    st.code(format_command(cmd), language="bash")

    if not api_key_present():
        st.error("ANTHROPIC_API_KEY is not set in the environment — scripts will fail.")
        return

    if st.button("▶ Run", type="primary", key=f"{key}_run"):
        output_area = st.empty()
        with st.spinner("Running…"):
            rc = run_subprocess(cmd, output_area)
        if rc == 0:
            st.success("Done.")
        else:
            st.error(f"Process exited with code {rc}.")


# ── Pages ─────────────────────────────────────────────────────────────────────

def page_workflow_guide() -> None:
    st.title("CampaignGenerator — Workflow Guide")
    st.markdown("""
Use the sidebar to navigate to any tool. The recommended order for setting up a campaign
from scratch is shown below. For ongoing sessions, only run the steps that need updating.

---

### One-time setup

| Step | Tool | What it does |
|---|---|---|
| 1 | **D&D Sheet → Markdown** | Convert D&D Beyond PDFs to `.md` character sheets |
| 2 | **Make Tracking List** | Extract trackable events from your adventure module |

### After each session (update grounding docs)

| Step | Tool | What it does |
|---|---|---|
| 3 | **Campaign State** | What's been completed, current NPC states, active threads |
| 4 | **Distill World State** | Structured lore from raw session summaries |
| 5 | **Party Document** | Party roster, arc scores, relationships |
| 6 | **Planning Document** | NPC dossiers, threat arc scores, active plots |

### Session prep (run before each session)

| Step | Tool | What it does |
|---|---|---|
| 7 | **Session Prep** | Generate encounter docs from a beat or session outline |
| 8 | **NPC Table** | Quick reference table of all NPCs |
| 9 | **Query Summaries** | Look up a specific event or NPC ad-hoc |

---

### Tips

- **Campaign State** should be re-run with `--synthesize-only` after editing your tracking file
  to avoid re-paying the cost of the extract pass.
- Delete the `state_extractions/` (or `distill_extractions/`) folder to force a full re-extract.
- `planning.py` has two modes: **Build Dossiers** (run first, produces editable per-NPC files)
  and **Synthesize** (run after reviewing dossiers, produces `planning.md`).
- The **Pipeline** mode in Session Prep automatically stops at FLAGS — review the output
  and re-run as needed.
""")


def page_dnd_sheet(model: str) -> None:
    st.title("D&D Sheet → Markdown")
    st.caption("Convert D&D Beyond PDF character sheets to structured markdown via Claude vision.")

    pdfs = multi_path_field("PDF file(s)", key="dnd_pdfs", required=True)
    output = path_field("Output file", key="dnd_output",
                        help="For a single PDF. Leave blank to print to terminal.")
    output_dir = path_field("Output directory", key="dnd_output_dir",
                            help="For multiple PDFs. One .md file per PDF.")

    if len(pdfs) > 1 and output:
        st.warning("--output only works for a single PDF. Use --output-dir for multiple files.")

    cmd = [PYTHON, str(SCRIPT_DIR / "dnd_sheet.py")] + pdfs + ["--model", model]
    if output and len(pdfs) == 1:
        cmd += ["--output", output]
    elif output_dir:
        cmd += ["--output-dir", output_dir]

    run_panel(cmd, "dnd_sheet")


def page_make_tracking(model: str) -> None:
    st.title("Make Tracking List")
    st.caption("Extract a tracking list from an adventure module so Campaign State never misses key events.")

    input_path = path_field("Adventure module markdown file", key="mt_input", required=True)
    output = path_field("Output file (.txt)", key="mt_output",
                        default="docs/tracking.txt", required=True)

    st.info("Review and edit the generated tracking.txt before using it with Campaign State. "
            "Items are phrased neutrally — verify they match your campaign's actual events.")

    cmd = [PYTHON, str(SCRIPT_DIR / "make_tracking.py"),
           input_path, "--output", output, "--model", model]

    run_panel(cmd, "make_tracking")


def page_campaign_state(model: str) -> None:
    st.title("Campaign State")
    st.caption("Generate a grounding document: completed quests, current NPC states, active threads.")

    synth_only = st.checkbox("--synthesize-only (skip extract, use existing extractions)",
                             key="cs_synth_only")

    if not synth_only:
        input_path = path_field("Session summaries file", key="cs_input", required=True)
    else:
        input_path = ""

    output = path_field("Output file", key="cs_output",
                        default="docs/campaign_state.md", required=True)
    track_file = path_field("Tracking file (--track-file)", key="cs_track_file",
                            help="Text file with events to explicitly track, one per line. "
                                 "Generate with Make Tracking List.")
    track_inline = st.text_area("Additional inline tracking items (one per line)",
                                key="cs_track_inline", height=80)
    extract_dir = path_field("Extract dir", key="cs_extract_dir",
                             help="Default: <output_dir>/state_extractions/")
    chunk_size = st.number_input("Chunk size (chars)", value=60000, step=5000,
                                 min_value=10000, key="cs_chunk_size")

    if synth_only and not extract_dir:
        st.warning("--synthesize-only requires --extract-dir pointing to existing extractions.")

    cmd = [PYTHON, str(SCRIPT_DIR / "campaign_state.py")]
    if not synth_only and input_path:
        cmd.append(input_path)
    if output:
        cmd += ["--output", output]
    if track_file:
        cmd += ["--track-file", track_file]
    track_items = [t.strip() for t in track_inline.splitlines() if t.strip()]
    if track_items:
        cmd += ["--track"] + track_items
    if extract_dir:
        cmd += ["--extract-dir", extract_dir]
    if synth_only:
        cmd.append("--synthesize-only")
    cmd += ["--chunk-size", str(chunk_size), "--model", model]

    run_panel(cmd, "campaign_state")


def page_distill(model: str) -> None:
    st.title("Distill World State")
    st.caption("Convert raw session summaries into a structured world_state.md lore document.")

    synth_only = st.checkbox("--synthesize-only", key="distill_synth_only")

    if not synth_only:
        input_path = path_field("Session summaries file", key="distill_input", required=True)
    else:
        input_path = ""

    output = path_field("Output file", key="distill_output",
                        default="docs/world_state.md", required=True)
    extract_dir = path_field("Extract dir", key="distill_extract_dir",
                             help="Default: <output_dir>/distill_extractions/")
    chunk_size = st.number_input("Chunk size (chars)", value=60000, step=5000,
                                 min_value=10000, key="distill_chunk_size")

    cmd = [PYTHON, str(SCRIPT_DIR / "distill.py")]
    if not synth_only and input_path:
        cmd.append(input_path)
    if output:
        cmd += ["--output", output]
    if extract_dir:
        cmd += ["--extract-dir", extract_dir]
    if chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]
    if synth_only:
        cmd.append("--synthesize-only")
    cmd += ["--model", model]

    run_panel(cmd, "distill")


def page_party(model: str) -> None:
    st.title("Party Document")
    st.caption("Generate party.md from character sheets, session summaries, and arc scores.")

    synth_only = st.checkbox("--synthesize-only", key="party_synth_only")

    char_files = multi_path_field("Character sheet files (.md)", key="party_chars", required=True)

    if not synth_only:
        summaries = path_field("Session summaries file", key="party_summaries")
    else:
        summaries = ""

    backstory_files = multi_path_field("Backstory files", key="party_backstory")
    arc_score_files = multi_path_field("Arc score mechanic files", key="party_arc_scores",
                                       help="Full arc score definitions (triggers, thresholds, abilities)")
    context_files = multi_path_field("Context files", key="party_context",
                                     help="e.g. docs/campaign_state.md")
    output = path_field("Output file", key="party_output",
                        default="docs/party.md", required=True)
    extract_dir = path_field("Extract dir", key="party_extract_dir",
                             help="Default: <output_dir>/party_extractions/")
    chunk_size = st.number_input("Chunk size (chars)", value=60000, step=5000,
                                 min_value=10000, key="party_chunk_size")

    cmd = [PYTHON, str(SCRIPT_DIR / "party.py")]
    if char_files:
        cmd += ["--character"] + char_files
    if summaries and not synth_only:
        cmd += ["--summaries", summaries]
    if backstory_files:
        cmd += ["--backstory"] + backstory_files
    if arc_score_files:
        cmd += ["--arc-scores"] + arc_score_files
    if context_files:
        cmd += ["--context"] + context_files
    if output:
        cmd += ["--output", output]
    if extract_dir:
        cmd += ["--extract-dir", extract_dir]
    if chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]
    if synth_only:
        cmd.append("--synthesize-only")
    cmd += ["--model", model]

    run_panel(cmd, "party")


def page_planning(model: str) -> None:
    st.title("Planning Document")
    st.caption("Generate planning.md from NPC dossiers and threat arc scores, or build dossier files from summaries.")

    mode = st.radio("Mode", ["Synthesize planning.md", "Build dossier files from summaries"],
                    key="plan_mode")

    if mode == "Build dossier files from summaries":
        st.info("Extracts per-NPC dossier files from your session summaries. "
                "Review and edit the results, then switch to Synthesize mode.")
        summaries = path_field("Session summaries file", key="plan_build_summaries", required=True)
        dossier_dir = path_field("Dossier output directory", key="plan_dossier_dir",
                                 default="docs/npcs/")
        extract_dir = path_field("Extract dir", key="plan_build_extract_dir",
                                 help="Default: ./planning_extractions/")
        chunk_size = st.number_input("Chunk size (chars)", value=60000, step=5000,
                                     min_value=10000, key="plan_build_chunk_size")

        cmd = [PYTHON, str(SCRIPT_DIR / "planning.py"),
               "--summaries", summaries, "--build-dossiers", "--model", model]
        if dossier_dir:
            cmd += ["--dossier-dir", dossier_dir]
        if extract_dir:
            cmd += ["--extract-dir", extract_dir]
        if chunk_size != 60000:
            cmd += ["--chunk-size", str(chunk_size)]

    else:
        synth_only = st.checkbox("--synthesize-only", key="plan_synth_only")

        npc_files = multi_path_field("NPC dossier files", key="plan_npc",
                                     help="Output of Build Dossiers mode, or hand-written dossiers")
        arc_score_files = multi_path_field("Threat arc score files", key="plan_arc_scores",
                                           help="e.g. brundar_echo.md, kraken_echoes.md")

        if not synth_only:
            summaries = path_field("Session summaries file", key="plan_summaries")
        else:
            summaries = ""

        context_files = multi_path_field("Context files", key="plan_context",
                                         help="e.g. docs/campaign_state.md")
        output = path_field("Output file", key="plan_output",
                            default="docs/planning.md", required=True)
        extract_dir = path_field("Extract dir", key="plan_extract_dir",
                                 help="Default: <output_dir>/planning_extractions/")
        chunk_size = st.number_input("Chunk size (chars)", value=60000, step=5000,
                                     min_value=10000, key="plan_chunk_size")

        cmd = [PYTHON, str(SCRIPT_DIR / "planning.py")]
        if npc_files:
            cmd += ["--npc"] + npc_files
        if arc_score_files:
            cmd += ["--arc-scores"] + arc_score_files
        if summaries and not synth_only:
            cmd += ["--summaries", summaries]
        if context_files:
            cmd += ["--context"] + context_files
        if output:
            cmd += ["--output", output]
        if extract_dir:
            cmd += ["--extract-dir", extract_dir]
        if chunk_size != 60000:
            cmd += ["--chunk-size", str(chunk_size)]
        if synth_only:
            cmd.append("--synthesize-only")
        cmd += ["--model", model]

    run_panel(cmd, "planning")


def page_query(model: str) -> None:
    st.title("Query Summaries")
    st.caption("Search session summaries for a specific event, NPC, or topic.")

    input_path = path_field("Session summaries file", key="query_input", required=True)
    query_text = st.text_input("Query **(required)**",
                               placeholder='e.g. "Did the party clear Gnomengarde?"',
                               key="query_text")
    col1, col2 = st.columns(2)
    with col1:
        hits_only = st.checkbox("--hits-only (raw extracts, no synthesis)", key="query_hits_only")
    with col2:
        verbose = st.checkbox("--verbose (show per-chunk progress)", key="query_verbose")
    output = path_field("Output file", key="query_output",
                        help="Optional — saves the answer to a file")
    chunk_size = st.number_input("Chunk size (chars)", value=40000, step=5000,
                                 min_value=10000, key="query_chunk_size")

    if not query_text.strip():
        st.warning("Enter a query before running.")

    cmd = [PYTHON, str(SCRIPT_DIR / "query.py"),
           input_path, query_text, "--model", model, "--chunk-size", str(chunk_size)]
    if hits_only:
        cmd.append("--hits-only")
    if verbose:
        cmd.append("--verbose")
    if output:
        cmd += ["--output", output]

    run_panel(cmd, "query")


def page_session_prep(model: str) -> None:
    st.title("Session Prep")
    st.caption("Generate encounter documents from a session beat or numbered outline.")

    input_mode = st.radio("Input mode",
                          ["Single beat", "Session file (numbered outline)",
                           "Session text (inline outline)"],
                          key="prep_input_mode")

    if input_mode == "Single beat":
        beat = st.text_area("Session beat", key="prep_beat", height=100,
                            placeholder="The party arrives at Icespire Hold and confronts Xal'vosh")
        st.caption("Can also be a file path to a .md file.")
    elif input_mode == "Session file (numbered outline)":
        session_file = path_field("Session outline file", key="prep_session_file", required=True)
    else:
        session_text = st.text_area("Session outline", key="prep_session_text", height=150,
                                    placeholder="1. Travel to Icespire Hold\n2. Confront Xal'vosh\n3. Cryovain reveal")

    st.divider()

    prep_mode = st.radio("Prep mode", ["single", "pipeline"], key="prep_mode",
                         help="single = one API call. pipeline = Lore Oracle → Encounter Architect → Voice Keeper")
    if prep_mode == "pipeline":
        st.info("Pipeline mode stops at FLAGS automatically in the UI — "
                "review the output and re-run if needed.")

    config = path_field("Config file", key="prep_config", default=DEFAULT_CONFIG)
    output = path_field("Output file", key="prep_output",
                        help="Saves the final response (Voice Keeper for pipeline, encounter for single)")
    no_log = st.checkbox("--no-log (skip saving log file)", key="prep_no_log")

    cmd = [PYTHON, str(SCRIPT_DIR / "prep.py"), "--mode", prep_mode, "--model", model]

    if input_mode == "Single beat":
        if st.session_state.get("prep_beat", "").strip():
            cmd += ["--beat", st.session_state["prep_beat"].strip()]
    elif input_mode == "Session file (numbered outline)":
        file_val = st.session_state.get("prep_session_file", "").strip()
        if file_val:
            cmd += ["--session", file_val]
    else:
        text_val = st.session_state.get("prep_session_text", "").strip()
        if text_val:
            cmd += ["--session-text", text_val]

    if config:
        cmd += ["--config", config]
    if output:
        cmd += ["--output", output]
    if no_log:
        cmd.append("--no-log")

    run_panel(cmd, "prep")


def page_npc_table(model: str) -> None:
    st.title("NPC Table")
    st.caption("Generate a quick-reference NPC table from config documents.")

    docs_str = st.text_input("Document labels (space-separated)",
                             value=st.session_state.get("npc_docs_str", "world_state"),
                             key="npc_docs_str",
                             help="Labels defined in your config.yaml — e.g. world_state planning campaign_state")
    config = path_field("Config file", key="npc_config", default=DEFAULT_CONFIG)
    output = path_field("Output file", key="npc_output",
                        help="Optional — saves the table to a file")
    no_log = st.checkbox("--no-log", key="npc_no_log")

    docs_list = docs_str.split()
    cmd = [PYTHON, str(SCRIPT_DIR / "npc_table.py"),
           "--docs"] + docs_list + ["--config", config, "--model", model]
    if output:
        cmd += ["--output", output]
    if no_log:
        cmd.append("--no-log")

    run_panel(cmd, "npc_table")


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
    "npc":       "#4e9af1",   # blue
    "faction":   "#f1814e",   # orange
    "location":  "#4ef1a0",   # green
    "plot":      "#c44ef1",   # purple
    "arc_score": "#f1e14e",   # yellow
    "party":     "#4ef1e1",   # teal
}

NODE_SHAPES = {
    "npc":       "dot",
    "faction":   "diamond",
    "location":  "square",
    "plot":      "triangle",
    "arc_score": "star",
    "party":     "dot",
}


def build_graph_html(data: dict, filter_types: set[str]) -> str:
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:red'>pyvis not installed. Run: pip install pyvis</p>"

    net = Network(height="680px", width="100%", bgcolor="#1a1a2e", font_color="white",
                  directed=True)
    net.set_options("""{
      "physics": {
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 180,
          "springConstant": 0.06,
          "damping": 0.4
        },
        "stabilization": {"iterations": 150}
      },
      "nodes": {
        "size": 22,
        "font": {"size": 13, "strokeWidth": 2, "strokeColor": "#1a1a2e"},
        "borderWidth": 2,
        "borderWidthSelected": 4
      },
      "edges": {
        "font": {"size": 10, "align": "middle", "strokeWidth": 0},
        "arrows": {"to": {"enabled": true, "scaleFactor": 0.6}},
        "smooth": {"type": "curvedCW", "roundness": 0.1},
        "color": {"opacity": 0.7}
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true
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
        tooltip = f"<b>{ent['label']}</b><br><i>{etype}</i><br>{ent.get('summary', '')}"
        net.add_node(eid, label=ent["label"], color=color, shape=shape,
                     title=tooltip, group=etype)

    for edge in data.get("edges", []):
        src, tgt = edge.get("source"), edge.get("target")
        if src in entity_ids and tgt in entity_ids:
            net.add_edge(src, tgt, label=edge.get("label", ""), title=edge.get("label", ""),
                         color="#aaaaaa")

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        return open(f.name).read()


def page_connections(model: str) -> None:
    st.title("Connection Graph")
    st.caption("Visualize relationships between NPCs, factions, locations, and plot threads.")

    # ── File selection ────────────────────────────────────────────────────────
    docs_dir = SCRIPT_DIR / "docs"
    md_files: list[Path] = []
    if docs_dir.exists():
        md_files = sorted(docs_dir.rglob("*.md"))

    all_md = [str(f.relative_to(SCRIPT_DIR)) for f in md_files]
    extra_raw = st.text_area("Additional markdown files (one path per line)",
                             key="cg_extra_files", height=80,
                             help="Files outside docs/ — paste absolute or relative paths")
    extra_files = [p.strip() for p in extra_raw.splitlines() if p.strip()]

    if all_md:
        selected = st.multiselect("Documents to include", all_md,
                                  default=all_md[:min(4, len(all_md))],
                                  key="cg_selected_docs")
    else:
        selected = []
        st.info("No .md files found in docs/. Add files or use the extra paths field above.")

    all_selected = selected + extra_files

    # ── Cache file ────────────────────────────────────────────────────────────
    cache_path = SCRIPT_DIR / "docs" / "connections.json"
    cache_exists = cache_path.exists()

    col1, col2 = st.columns([2, 1])
    with col1:
        extract_btn = st.button("Extract connections (calls Claude API)",
                                type="primary", key="cg_extract",
                                disabled=not all_selected or not api_key_present())
    with col2:
        if cache_exists:
            st.caption(f"Cache: `docs/connections.json` ✅  "
                       f"({cache_path.stat().st_size // 1024}KB)")
        else:
            st.caption("No cache yet — click Extract to generate.")

    if extract_btn and all_selected:
        parts = []
        for rel_path in all_selected:
            p = (SCRIPT_DIR / rel_path).expanduser().resolve()
            if p.is_file():
                parts.append(f"<!-- {rel_path} -->\n\n{p.read_text(encoding='utf-8').strip()}")
            elif p.is_dir():
                st.warning(f"Skipping directory (provide file paths, not folders): {rel_path}")
            else:
                st.warning(f"File not found: {rel_path}")
        if parts:
            combined = "\n\n---\n\n".join(parts)
            st.info(f"Extracting from {len(parts)} document(s) ({len(combined):,} chars)…")
            with st.spinner("Calling Claude to extract entities and relationships…"):
                from campaignlib import make_client, stream_api
                client = make_client()
                raw = stream_api(client, CONNECTIONS_SYSTEM, combined, model,
                                 max_tokens=4096, silent=True)
            # Parse JSON — strip code fences if Claude wrapped it
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:])
            if raw.endswith("```"):
                raw = "\n".join(raw.splitlines()[:-1])
            try:
                data = json.loads(raw)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                st.success(f"Extracted {len(data.get('entities', []))} entities and "
                           f"{len(data.get('edges', []))} relationships. Cached to docs/connections.json")
                st.session_state["cg_data"] = data
            except json.JSONDecodeError as e:
                st.error(f"Could not parse Claude's response as JSON: {e}")
                st.code(raw[:2000], language="json")

    # ── Load data ─────────────────────────────────────────────────────────────
    data: dict | None = st.session_state.get("cg_data")
    if data is None and cache_exists:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        st.session_state["cg_data"] = data

    if not data:
        st.stop()

    entities = data.get("entities", [])
    edges = data.get("edges", [])

    # ── Filters ───────────────────────────────────────────────────────────────
    st.divider()
    all_types = sorted({e.get("type", "npc") for e in entities})
    st.subheader("Filters")
    filter_cols = st.columns(len(all_types) or 1)
    filter_types: set[str] = set()
    for i, t in enumerate(all_types):
        color = NODE_COLORS.get(t, "#888")
        label = f":{t.replace('_', ' ').title()}"
        if filter_cols[i].checkbox(t.replace("_", " ").title(), value=True,
                                   key=f"cg_filter_{t}"):
            filter_types.add(t)

    # ── Stats ─────────────────────────────────────────────────────────────────
    visible_ids = {e["id"] for e in entities if e.get("type") in filter_types}
    visible_edges = [e for e in edges
                     if e.get("source") in visible_ids and e.get("target") in visible_ids]
    st.caption(f"{len(visible_ids)} nodes · {len(visible_edges)} edges visible "
               f"(total: {len(entities)} entities, {len(edges)} relationships)")

    # ── Graph ─────────────────────────────────────────────────────────────────
    graph_html = build_graph_html(data, filter_types)
    components.html(graph_html, height=700, scrolling=False)

    # ── Legend ────────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Legend")
    leg_cols = st.columns(len(NODE_COLORS))
    for i, (etype, color) in enumerate(NODE_COLORS.items()):
        leg_cols[i].markdown(
            f"<span style='background:{color};padding:2px 8px;border-radius:4px;"
            f"color:#000;font-size:12px'>{etype.replace('_',' ').title()}</span>",
            unsafe_allow_html=True,
        )

    # ── Entity table ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Entity List")
    search = st.text_input("Search entities", key="cg_search", placeholder="Type to filter…")
    rows = [e for e in entities
            if e.get("type") in filter_types
            and (not search or search.lower() in e["label"].lower()
                 or search.lower() in e.get("summary", "").lower())]
    if rows:
        st.dataframe(
            [{"Name": e["label"], "Type": e.get("type", ""),
              "Summary": e.get("summary", "")} for e in rows],
            use_container_width=True, hide_index=True,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="CampaignGenerator",
        page_icon="🎲",
        layout="wide",
    )

    with st.sidebar:
        st.title("🎲 CampaignGenerator")
        page = st.radio("Navigate", [
            "Workflow Guide",
            "Connection Graph",
            "D&D Sheet → Markdown",
            "Make Tracking List",
            "Campaign State",
            "Distill World State",
            "Party Document",
            "Planning Document",
            "Query Summaries",
            "Session Prep",
            "NPC Table",
        ], key="nav_page")

        st.divider()
        st.subheader("Model")
        model = st.selectbox("Claude model", MODELS, key="global_model", label_visibility="collapsed")

        st.divider()
        if api_key_present():
            st.success("API key set ✅")
        else:
            st.error("ANTHROPIC_API_KEY not set")

    if page == "Workflow Guide":
        page_workflow_guide()
    elif page == "Connection Graph":
        page_connections(model)
    elif page == "D&D Sheet → Markdown":
        page_dnd_sheet(model)
    elif page == "Make Tracking List":
        page_make_tracking(model)
    elif page == "Campaign State":
        page_campaign_state(model)
    elif page == "Distill World State":
        page_distill(model)
    elif page == "Party Document":
        page_party(model)
    elif page == "Planning Document":
        page_planning(model)
    elif page == "Query Summaries":
        page_query(model)
    elif page == "Session Prep":
        page_session_prep(model)
    elif page == "NPC Table":
        page_npc_table(model)


if __name__ == "__main__":
    main()
