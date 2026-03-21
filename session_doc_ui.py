#!/usr/bin/env python3
"""Web UI for reviewing and editing session_doc.py scene extractions before narration.

Usage (from campaign directory):
    python ~/CampaignGenerator/session_doc_ui.py \\
        --session session-mar \\
        --extract-dir scene_extractions/ \\
        --roleplay-extract-dir vtt_roleplay_extractions/ \\
        --output-dir . \\
        --party partyfile.md \\
        --voice-dir voice/ \\
        --narrate-tokens 4000

Then open http://localhost:5000 in your browser.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_doc import (estimate_narration_tokens, extraction_filename,
                         parse_extraction_file, parse_plan)

try:
    from flask import Flask, Response, jsonify, request, stream_with_context
except ImportError:
    print("Error: flask not installed. Run: pip install flask", file=sys.stderr)
    sys.exit(1)


app = Flask(__name__)
CONFIG: dict = {}


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Session Doc</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, sans-serif;
  background: #1e1e2e; color: #cdd6f4;
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
}
header {
  background: #181825; border-bottom: 1px solid #313244;
  padding: 8px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0;
}
header h1 { font-size: 13px; font-weight: 700; color: #cba6f7; }
#status-msg { font-size: 11px; color: #89b4fa; margin-left: auto; }

/* ── Three columns ── */
.columns {
  display: grid;
  grid-template-columns: 210px 1fr 320px;
  flex: 1; overflow: hidden;
}

/* Scene list */
.scenes { background: #181825; border-right: 1px solid #313244; overflow-y: auto; }
.scenes h2 {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: #6c7086; padding: 10px 12px 4px;
}
.scene-item {
  padding: 7px 12px; cursor: pointer;
  border-left: 3px solid transparent; transition: background .1s;
}
.scene-item:hover { background: #252535; }
.scene-item.active { background: #252535; border-left-color: #cba6f7; }
.scene-item .num { font-size: 10px; color: #6c7086; font-weight: 600; }
.scene-item .narrator { font-size: 12px; font-weight: 600; }
.scene-item .sname {
  font-size: 11px; color: #a6adc8;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.badges { display: flex; gap: 3px; margin-top: 3px; }
.badge {
  font-size: 9px; font-weight: 700; padding: 1px 5px;
  border-radius: 3px; text-transform: uppercase; letter-spacing: .05em;
}
.b-ext { background: #1e3a5f; color: #89b4fa; }
.b-nar { background: #1e3a2a; color: #a6e3a1; }

/* Editor column */
.editor-col { display: flex; flex-direction: column; overflow: hidden; }

.editor-header {
  background: #181825; border-bottom: 1px solid #313244;
  padding: 7px 12px; display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.editor-title { font-size: 13px; font-weight: 600; flex: 1; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.token-est { font-size: 11px; color: #6c7086; white-space: nowrap; flex-shrink: 0; }
.token-warn { color: #fab387 !important; }

textarea#extraction {
  flex: 1; background: #1e1e2e; color: #cdd6f4;
  border: none; outline: none; resize: none;
  padding: 12px 14px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 12px; line-height: 1.65;
}

.toolbar {
  background: #181825; border-top: 1px solid #313244;
  padding: 7px 12px; display: flex; gap: 6px; align-items: center; flex-shrink: 0;
}
.save-flash { font-size: 11px; color: #a6e3a1; opacity: 0; transition: opacity .4s; }
.save-flash.show { opacity: 1; }

/* Narration output */
.narration-panel {
  height: 220px; display: flex; flex-direction: column;
  flex-shrink: 0; border-top: 2px solid #313244;
}
.narration-header {
  background: #181825; padding: 5px 12px;
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.narration-header span {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: #6c7086;
}
#narration-out {
  flex: 1; overflow-y: auto;
  padding: 10px 14px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 12px; line-height: 1.6; color: #a6e3a1;
  white-space: pre-wrap; word-break: break-word;
  background: #141420;
}

/* VTT panel */
.vtt-panel {
  background: #181825; border-left: 1px solid #313244;
  display: flex; flex-direction: column; overflow: hidden;
}
.vtt-panel h2 {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: #6c7086; padding: 10px 12px 4px; flex-shrink: 0;
}
.vtt-scroll { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.vtt-chunk { margin-bottom: 16px; }
.vtt-chunk h3 {
  font-size: 11px; font-weight: 600; color: #89b4fa;
  margin-bottom: 5px; padding-bottom: 4px; border-bottom: 1px solid #313244;
}
.vtt-chunk pre {
  font-size: 11px; line-height: 1.5; color: #a6adc8;
  white-space: pre-wrap; word-break: break-word;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}

/* Buttons */
button {
  padding: 5px 11px; border: none; border-radius: 4px;
  font-size: 12px; font-weight: 500; cursor: pointer; transition: opacity .1s;
}
button:hover:not(:disabled) { opacity: .82; }
button:disabled { opacity: .35; cursor: default; }
.btn-primary  { background: #cba6f7; color: #1e1e2e; }
.btn-success  { background: #a6e3a1; color: #1e1e2e; }
.btn-neutral  { background: #313244; color: #cdd6f4; }
.btn-sm { font-size: 10px; padding: 3px 8px; }
</style>
</head>
<body>

<header>
  <h1>Session Doc</h1>
  <span id="session-label" style="font-size:12px;color:#6c7086"></span>
  <span id="status-msg"></span>
  <button class="btn-neutral btn-sm" id="btn-assemble" onclick="assembleDoc()" style="margin-left:8px">Assemble Doc</button>
  <button class="btn-neutral btn-sm" id="btn-open-assembled" onclick="openAssembled()" style="display:none;margin-left:4px">Open in Typora</button>
</header>

<div class="columns">

  <!-- ── Scene list ── -->
  <div class="scenes">
    <h2>Scenes</h2>
    <div id="scene-list"></div>
  </div>

  <!-- ── Editor + narration ── -->
  <div class="editor-col">
    <div class="editor-header">
      <span class="editor-title" id="editor-title">Select a scene</span>
      <span class="token-est" id="token-est"></span>
    </div>
    <textarea id="extraction"
              placeholder="Select a scene from the list to begin editing."
              spellcheck="false" oninput="onInput()"></textarea>
    <div class="toolbar">
      <button class="btn-primary"  id="btn-save"    onclick="saveExtraction()" disabled>Save</button>
      <button class="btn-neutral"  id="btn-open-ext" onclick="openTypora('extraction')" disabled>Edit in Typora</button>
      <button class="btn-neutral"  id="btn-reload"  onclick="reloadExtraction()" disabled>Reload</button>
      <button class="btn-success"  id="btn-narrate" onclick="narrateScene()"   disabled>Narrate</button>
      <span class="save-flash" id="save-flash">Saved</span>
      <span style="flex:1"></span>
      <button class="btn-neutral btn-sm" id="btn-open-out"
              onclick="openTypora('output')" disabled>Open narration in Typora</button>
    </div>

    <!-- narration output -->
    <div class="narration-panel">
      <div class="narration-header">
        <span>Narration output</span>
        <span style="flex:1"></span>
        <button class="btn-neutral btn-sm" onclick="clearOutput()">Clear</button>
      </div>
      <div id="narration-out"></div>
    </div>
  </div>

  <!-- ── VTT source ── -->
  <div class="vtt-panel">
    <h2>VTT Source</h2>
    <div class="vtt-scroll" id="vtt-scroll">
      <p style="color:#6c7086;font-size:12px;padding:8px 0">Loading…</p>
    </div>
  </div>

</div><!-- .columns -->

<script>
// Injected by server
const PAGE = __PAGE_CONFIG__;

let currentScene = null;
let narrating    = false;
let sse          = null;

// ── Scene list ────────────────────────────────────────────────────

async function loadScenes() {
  const scenes = await fetch('/api/scenes').then(r => r.json());
  document.getElementById('session-label').textContent = PAGE.sessionName;
  const list = document.getElementById('scene-list');
  list.innerHTML = scenes.map(s => `
    <div class="scene-item" id="si-${s.index}" onclick="selectScene(${s.index})">
      <div class="num">Scene ${s.index}</div>
      <div class="narrator">${esc(s.narrator)}</div>
      <div class="sname">${esc(s.scene || '—')}</div>
      <div class="badges">
        ${s.has_extraction ? '<span class="badge b-ext">Extracted</span>' : ''}
        ${s.has_output     ? '<span class="badge b-nar">Narrated</span>'  : ''}
      </div>
    </div>`).join('');
  return scenes;
}

// ── Select & load scene ───────────────────────────────────────────

async function selectScene(n) {
  currentScene = n;
  document.querySelectorAll('.scene-item').forEach(el => el.classList.remove('active'));
  document.getElementById(`si-${n}`)?.classList.add('active');

  const data = await fetch(`/api/extraction/${n}`).then(r => r.json());
  const ta = document.getElementById('extraction');
  ta.value    = data.content || '';
  ta.disabled = !data.exists;

  const has = data.exists;
  document.getElementById('btn-save').disabled     = !has;
  document.getElementById('btn-narrate').disabled  = !has;
  document.getElementById('btn-open-ext').disabled = !has;
  document.getElementById('btn-reload').disabled   = !has;

  const outOk = await fetch(`/api/output/${n}`).then(r => r.ok);
  document.getElementById('btn-open-out').disabled = !outOk;

  document.getElementById('editor-title').textContent =
    data.scene_label || `Scene ${n}`;

  updateEst();
}

// ── Token estimate ─────────────────────────────────────────────────

function estimateTokens(text) {
  const lines = text.split('\\n');
  if (lines[0].trim().match(/^tokens:\\s*\\d+/)) text = lines.slice(1).join('\\n');
  const hasDlg = /^[A-Z][^:\\n]+:\\s*"/m.test(text);
  const raw    = Math.floor(text.length / 4 * (hasDlg ? 4 : 3));
  return Math.max(500, Math.ceil(raw / 250) * 250);
}

function updateEst() {
  const text  = document.getElementById('extraction').value;
  const el    = document.getElementById('token-est');
  if (!text.trim()) { el.textContent = ''; el.className = 'token-est'; return; }
  const est   = estimateTokens(text);
  const limit = PAGE.defaultNarrateTokens;
  if (est > limit) {
    el.textContent = `~${est} tokens  ⚠ limit ${limit}`;
    el.className   = 'token-est token-warn';
  } else {
    el.textContent = `~${est} tokens`;
    el.className   = 'token-est';
  }
}

function onInput() { updateEst(); }

// ── Save ───────────────────────────────────────────────────────────

async function saveExtraction() {
  if (currentScene === null) return;
  const content = document.getElementById('extraction').value;
  await fetch(`/api/extraction/${currentScene}`, {
    method:  'PUT',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({content}),
  });
  const flash = document.getElementById('save-flash');
  flash.classList.add('show');
  setTimeout(() => flash.classList.remove('show'), 1800);
  loadScenes();
}

// ── Narrate ────────────────────────────────────────────────────────

async function narrateScene() {
  if (currentScene === null || narrating) return;
  await saveExtraction();

  narrating = true;
  const btn = document.getElementById('btn-narrate');
  btn.disabled = true;
  btn.textContent = 'Narrating…';

  const out = document.getElementById('narration-out');
  out.textContent = '';

  setStatus('Running narration…');

  sse = new EventSource(`/api/narrate/${currentScene}`);

  sse.onmessage = e => {
    out.textContent += JSON.parse(e.data);
    out.scrollTop = out.scrollHeight;
  };

  sse.addEventListener('done', e => {
    sse.close(); sse = null;
    narrating = false;
    btn.disabled = false;
    btn.textContent = 'Narrate';
    document.getElementById('btn-open-out').disabled = false;
    setStatus('Done.');
    setTimeout(() => setStatus(''), 3000);
    loadScenes();
  });

  sse.onerror = () => {
    if (!sse) return;
    sse.close(); sse = null;
    narrating = false;
    btn.disabled = false;
    btn.textContent = 'Narrate';
    setStatus('Stream error — check terminal.');
  };
}

// ── Reload from disk ───────────────────────────────────────────────

async function reloadExtraction() {
  if (currentScene === null) return;
  const data = await fetch(`/api/extraction/${currentScene}`).then(r => r.json());
  document.getElementById('extraction').value = data.content || '';
  updateEst();
  setStatus('Reloaded from disk.');
  setTimeout(() => setStatus(''), 2000);
}

// ── Open in Typora ─────────────────────────────────────────────────

async function openTypora(type) {
  if (currentScene === null) return;
  const res = await fetch(`/api/open/${type}/${currentScene}`, {method: 'POST'});
  if (!res.ok) setStatus('File not found.');
}

// ── VTT source ─────────────────────────────────────────────────────

async function loadVTT() {
  const {chunks} = await fetch('/api/vtt').then(r => r.json());
  document.getElementById('vtt-scroll').innerHTML = chunks.map(c => `
    <div class="vtt-chunk">
      <h3>${esc(c.name)}</h3>
      <pre>${esc(c.content)}</pre>
    </div>`).join('');
}

// ── Helpers ────────────────────────────────────────────────────────

function clearOutput() { document.getElementById('narration-out').textContent = ''; }
function setStatus(msg) { document.getElementById('status-msg').textContent = msg; }
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Assemble ───────────────────────────────────────────────────────

async function assembleDoc() {
  const btn = document.getElementById('btn-assemble');
  btn.disabled = true;
  btn.textContent = 'Assembling…';
  setStatus('Assembling session doc…');
  try {
    const res  = await fetch('/api/assemble', {method: 'POST'});
    const data = await res.json();
    if (data.ok) {
      setStatus(`Saved → ${data.filename}  (${data.scenes_included} scenes)`);
      const openBtn = document.getElementById('btn-open-assembled');
      openBtn.style.display = '';
      setTimeout(() => setStatus(''), 5000);
    } else {
      setStatus(`Assembly failed: ${data.error}`);
    }
  } catch (e) {
    setStatus('Assembly error — check terminal.');
  }
  btn.disabled = false;
  btn.textContent = 'Assemble Doc';
}

async function openAssembled() {
  const res = await fetch('/api/open/assembled/0', {method: 'POST'});
  if (!res.ok) setStatus('Could not open assembled file.');
}

// ── Init ───────────────────────────────────────────────────────────

async function checkAssembled() {
  const res = await fetch('/api/assembled_exists');
  if (res.ok) {
    const data = await res.json();
    if (data.exists) document.getElementById('btn-open-assembled').style.display = '';
  }
}

loadScenes();
loadVTT();
checkAssembled();
</script>
</body>
</html>
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_scenes() -> list[dict]:
    plan_path = Path(CONFIG["extract_dir"]) / "plan.md"
    if not plan_path.exists():
        return []
    sections = parse_plan(plan_path.read_text(encoding="utf-8"), total_chunks=99)
    result = []
    for i, s in enumerate(sections, 1):
        fname = extraction_filename(i, s["narrator"], s.get("scene", ""))
        extract_path = Path(CONFIG["extract_dir"]) / fname
        output_path  = Path(CONFIG["output_dir"]) / f"scene{i}.md"
        result.append({
            "index":          i,
            "narrator":       s["narrator"],
            "scene":          s.get("scene", ""),
            "focus":          s.get("focus", ""),
            "chunk_start":    s["chunk_start"],
            "chunk_end":      s["chunk_end"],
            "has_extraction": extract_path.exists(),
            "has_output":     output_path.exists(),
            "filename":       fname,
        })
    return result


def get_extraction_path(n: int) -> Path | None:
    scenes = load_scenes()
    if n < 1 or n > len(scenes):
        return None
    return Path(CONFIG["extract_dir"]) / scenes[n - 1]["filename"]


def open_in_typora(filepath: Path) -> None:
    try:
        win = subprocess.check_output(
            ["wslpath", "-w", str(filepath.resolve())]
        ).decode().strip()
        # PowerShell Start-Process handles UNC paths (\\wsl.localhost\...) correctly
        subprocess.Popen(["powershell.exe", "-c", f'Start-Process "{win}"'])
        print(f"  Opening: {win}")
    except Exception as e:
        print(f"  Warning: could not open file: {e}", file=sys.stderr)


def assembled_output_path() -> Path:
    session_stem = Path(CONFIG["session"]).stem
    return Path(CONFIG["output_dir"]) / f"{session_stem}-doc.md"


def build_narrate_cmd(scene_num: int) -> list[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "session_doc.py"),
        CONFIG["session"],
        "--roleplay-extract-dir", CONFIG["roleplay_extract_dir"],
        "--by-scene",
        "--from-extractions", CONFIG["extract_dir"],
        "--scene", str(scene_num),
        "--output", str(Path(CONFIG["output_dir"]) / f"scene{scene_num}.md"),
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--summary-extract-dir", "summary_extract_dir")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    if CONFIG.get("narrate_tokens"):
        cmd += ["--narrate-tokens", str(CONFIG["narrate_tokens"])]
    return cmd


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    page_config = json.dumps({
        "sessionName":         Path(CONFIG["session"]).name,
        "defaultNarrateTokens": CONFIG.get("narrate_tokens") or 1500,
    })
    return HTML.replace("__PAGE_CONFIG__", page_config)


@app.route("/api/scenes")
def api_scenes():
    return jsonify(load_scenes())


@app.route("/api/extraction/<int:n>", methods=["GET"])
def api_get_extraction(n):
    path = get_extraction_path(n)
    if path is None:
        return jsonify({"exists": False, "content": ""}), 404
    if not path.exists():
        return jsonify({"exists": False, "content": "", "scene_label": f"Scene {n}"})
    content = path.read_text(encoding="utf-8")
    scenes  = load_scenes()
    s       = scenes[n - 1] if n <= len(scenes) else {}
    label   = s.get("narrator", "")
    if s.get("scene"):
        label += f" — {s['scene']}"
    return jsonify({
        "exists":    True,
        "content":   content,
        "scene_label": label,
        "estimated_tokens": estimate_narration_tokens(content),
    })


@app.route("/api/extraction/<int:n>", methods=["PUT"])
def api_save_extraction(n):
    path = get_extraction_path(n)
    if path is None:
        return jsonify({"ok": False}), 404
    path.write_text(request.get_json()["content"], encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/output/<int:n>")
def api_get_output(n):
    path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    if not path.exists():
        return jsonify({"exists": False}), 404
    return jsonify({"exists": True})


@app.route("/api/vtt")
def api_vtt():
    vtt_dir = Path(CONFIG["roleplay_extract_dir"])
    chunks  = [
        {"name": f.stem, "content": f.read_text(encoding="utf-8")}
        for f in sorted(vtt_dir.glob("extract_*.md"))
    ]
    return jsonify({"chunks": chunks})


@app.route("/api/narrate/<int:n>")
def api_narrate(n):
    cmd = build_narrate_cmd(n)

    def generate():
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=0, cwd=CONFIG["work_dir"],
        )
        buf = ""
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            buf += ch
            if len(buf) >= 20 or ch == "\n":
                yield f"data: {json.dumps(buf)}\n\n"
                buf = ""
        if buf:
            yield f"data: {json.dumps(buf)}\n\n"
        proc.wait()
        yield f"event: done\ndata: {json.dumps({'returncode': proc.returncode})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/assembled_exists")
def api_assembled_exists():
    return jsonify({"exists": assembled_output_path().exists()})


@app.route("/api/assemble", methods=["POST"])
def api_assemble():
    scenes = load_scenes()
    if not scenes:
        return jsonify({"ok": False, "error": "no plan loaded"}), 400

    parts = []
    missing = []
    for s in scenes:
        p = Path(CONFIG["output_dir"]) / f"scene{s['index']}.md"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").strip())
        else:
            missing.append(s["index"])

    if not parts:
        return jsonify({"ok": False, "error": "no narrated scenes found"}), 400

    # Strip the repeated "# session-name" title and any surrounding --- dividers
    # from every scene, then emit one title at the top of the assembled file.
    session_name = Path(CONFIG["session"]).stem
    title_line   = f"# {session_name}"

    def strip_header(text: str) -> str:
        lines = text.split("\n")
        while lines and lines[0].strip() in ("", "---", title_line):
            lines.pop(0)
        return "\n".join(lines).strip()

    stripped = [strip_header(p) for p in parts]
    content  = f"{title_line}\n\n---\n\n" + "\n\n---\n\n".join(stripped) + "\n"

    out_path = assembled_output_path()
    out_path.write_text(content, encoding="utf-8")

    print(f"  Assembled {len(parts)} scenes → {out_path}")
    if missing:
        print(f"  Missing scenes (not yet narrated): {missing}")

    return jsonify({
        "ok": True,
        "filename": out_path.name,
        "scenes_included": len(parts),
        "scenes_missing":  missing,
    })


@app.route("/api/open/<file_type>/<int:n>", methods=["POST"])
def api_open(file_type, n):
    if file_type == "extraction":
        path = get_extraction_path(n)
    elif file_type == "output":
        path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    elif file_type == "assembled":
        path = assembled_output_path()
    else:
        return jsonify({"ok": False}), 400
    if path and path.exists():
        open_in_typora(path)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "file not found"}), 404


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Web UI for reviewing and editing session_doc scene extractions."
    )
    parser.add_argument("session", metavar="FILE",
                        help="Session recap file (e.g. session-mar)")
    parser.add_argument("--extract-dir", required=True, metavar="DIR",
                        help="Directory containing plan.md and extraction files")
    parser.add_argument("--roleplay-extract-dir", required=True, metavar="DIR",
                        help="VTT roleplay extractions (shown in right panel)")
    parser.add_argument("--output-dir", default=".", metavar="DIR",
                        help="Where sceneN.md output files are saved (default: .)")
    parser.add_argument("--party",               metavar="FILE")
    parser.add_argument("--voice-dir",           metavar="DIR")
    parser.add_argument("--summary-extract-dir", metavar="DIR")
    parser.add_argument("--narrate-tokens",      type=int, metavar="N")
    parser.add_argument("--port",                type=int, default=5000)
    args = parser.parse_args()

    CONFIG.update({
        "session":              str(Path(args.session).expanduser().resolve()),
        "extract_dir":          str(Path(args.extract_dir).expanduser().resolve()),
        "roleplay_extract_dir": str(Path(args.roleplay_extract_dir).expanduser().resolve()),
        "output_dir":           str(Path(args.output_dir).expanduser().resolve()),
        "party":     str(Path(args.party).expanduser().resolve())              if args.party              else None,
        "voice_dir": str(Path(args.voice_dir).expanduser().resolve())          if args.voice_dir          else None,
        "summary_extract_dir": str(Path(args.summary_extract_dir).expanduser().resolve()) if args.summary_extract_dir else None,
        "narrate_tokens": args.narrate_tokens,
        "work_dir": str(Path(".").resolve()),
    })

    print(f"  Session Doc UI")
    print(f"  Scenes:     {CONFIG['extract_dir']}")
    print(f"  Output:     {CONFIG['output_dir']}")
    print(f"  Open http://localhost:{args.port} in your browser")
    print()
    app.run(port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
