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
from quote_ledger import QuoteLedger

try:
    from flask import Flask, Response, jsonify, request, stream_with_context
except ImportError:
    print("Error: flask not installed. Run: pip install flask", file=sys.stderr)
    sys.exit(1)


app = Flask(__name__)
CONFIG: dict = {}
LEDGER: QuoteLedger | None = None


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

/* Tabs */
.tab-bar {
  background: #181825; border-bottom: 1px solid #313244;
  display: flex; flex-shrink: 0;
}
.tab {
  padding: 6px 14px; font-size: 11px; font-weight: 600; cursor: pointer;
  border-bottom: 2px solid transparent; color: #6c7086;
  transition: color .1s;
}
.tab:hover { color: #cdd6f4; }
.tab.active { color: #cba6f7; border-bottom-color: #cba6f7; }
.tab-badge {
  display: inline-block; font-size: 9px; font-weight: 700;
  padding: 1px 4px; border-radius: 3px; margin-left: 4px;
  background: #1e3a2a; color: #a6e3a1; text-transform: uppercase; letter-spacing: .04em;
}

.editor-pane {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}
.editor-pane.hidden { display: none; }

textarea.editor-ta {
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

/* VTT / Ledger panel */
.vtt-panel {
  background: #181825; border-left: 1px solid #313244;
  display: flex; flex-direction: column; overflow: hidden;
}
.vtt-panel .tab-bar {
  border-bottom: 1px solid #313244; flex-shrink: 0;
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

/* Quote ledger */
.ledger-toolbar {
  padding: 8px 12px; display: flex; gap: 6px; align-items: center;
  border-bottom: 1px solid #313244; flex-shrink: 0;
}
.ledger-stats { font-size: 10px; color: #6c7086; margin-left: auto; }
.ledger-section { margin-bottom: 12px; }
.ledger-section-header {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #6c7086; padding: 8px 12px 4px;
  cursor: pointer; user-select: none;
  display: flex; align-items: center; gap: 6px;
}
.ledger-section-header .arrow {
  font-size: 8px; transition: transform .15s; display: inline-block;
}
.ledger-section-header .arrow.open { transform: rotate(90deg); }
.ledger-section-header .count {
  font-size: 9px; font-weight: 600; color: #89b4fa;
}
.ledger-section-header.unassigned .count { color: #fab387; }
.quote-item {
  padding: 5px 12px; font-size: 11px; cursor: pointer;
  border-left: 3px solid transparent; transition: background .1s;
}
.quote-item:hover { background: #252535; }
.quote-item.active { background: #252535; border-left-color: #cba6f7; }
.quote-item .q-speaker {
  font-weight: 600; font-size: 10px; color: #cba6f7;
}
.quote-item .q-context {
  font-size: 10px; color: #6c7086; font-style: italic;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.quote-item .q-text {
  color: #a6adc8; font-size: 11px; line-height: 1.4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.quote-item.expanded .q-text {
  white-space: pre-wrap; word-break: break-word;
}
.quote-item .q-pinned {
  font-size: 8px; color: #a6e3a1; text-transform: uppercase; font-weight: 700;
}
.quote-assign {
  margin-top: 4px; display: none;
}
.quote-item.expanded .quote-assign { display: flex; gap: 4px; align-items: center; }
.quote-assign select {
  font-size: 10px; padding: 2px 4px; border-radius: 3px;
  background: #313244; color: #cdd6f4; border: 1px solid #45475a;
}
.quote-assign button {
  font-size: 10px; padding: 2px 8px;
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
  <button class="btn-neutral btn-sm" id="btn-extract"  onclick="runExtract()"  style="margin-left:8px">Extract</button>
  <button class="btn-neutral btn-sm" id="btn-assemble" onclick="assembleDoc()" style="margin-left:4px">Assemble Doc</button>
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
    <div class="tab-bar">
      <div class="tab active" id="tab-extraction" onclick="switchTab('extraction')">Extraction</div>
      <div class="tab" id="tab-roleplay" onclick="switchTab('roleplay')">
        Roleplay Context <span class="tab-badge" id="rp-badge" style="display:none">edited</span>
      </div>
    </div>

    <div class="editor-pane" id="pane-extraction">
      <textarea id="extraction" class="editor-ta"
                placeholder="Select a scene from the list to begin editing."
                spellcheck="false" oninput="onInput()"></textarea>
    </div>

    <div class="editor-pane hidden" id="pane-roleplay">
      <textarea id="roleplay-ctx" class="editor-ta"
                placeholder="No roleplay summary loaded. Set session-roleplay.md in the Streamlit app."
                spellcheck="false" oninput="onRpInput()"></textarea>
    </div>

    <div class="toolbar">
      <button class="btn-primary"  id="btn-save"     onclick="saveActive()"          disabled>Save</button>
      <button class="btn-neutral"  id="btn-open-ext"  onclick="openTyporaActive()"    disabled>Edit in Typora</button>
      <button class="btn-neutral"  id="btn-reload"    onclick="reloadActive()"        disabled>Reload</button>
      <button class="btn-success"  id="btn-narrate"   onclick="narrateScene()"        disabled>Narrate</button>
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
        <button class="btn-neutral btn-sm" id="btn-raw" onclick="toggleRaw()" disabled>Raw</button>
        <button class="btn-neutral btn-sm" onclick="clearOutput()" style="margin-left:4px">Clear</button>
      </div>
      <div id="raw-preview" style="display:none;padding:8px 14px;background:#0d0d1a;
           border-bottom:1px solid #313244;font-family:monospace;font-size:11px;
           color:#6c7086;white-space:pre-wrap;word-break:break-word;max-height:120px;overflow-y:auto"></div>
      <div id="narration-out"></div>
    </div>
  </div>

  <!-- ── VTT source / Quote Ledger ── -->
  <div class="vtt-panel">
    <div class="tab-bar">
      <div class="tab active" id="tab-vtt" onclick="switchRightTab('vtt')">VTT Source</div>
      <div class="tab" id="tab-ledger" onclick="switchRightTab('ledger')">Quote Ledger</div>
    </div>
    <div id="pane-vtt">
      <div class="vtt-scroll" id="vtt-scroll">
        <p style="color:#6c7086;font-size:12px;padding:8px 0">Loading…</p>
      </div>
    </div>
    <div id="pane-ledger" style="display:none;flex:1;overflow:hidden;flex-direction:column">
      <div class="ledger-toolbar">
        <button class="btn-neutral btn-sm" onclick="syncLedger()">Sync</button>
        <span class="ledger-stats" id="ledger-stats"></span>
      </div>
      <div class="vtt-scroll" id="ledger-scroll">
        <p style="color:#6c7086;font-size:12px;padding:8px 0">
          Click <b>Sync</b> to scan extraction files and build the quote ledger.
        </p>
      </div>
    </div>
  </div>

</div><!-- .columns -->

<script>
// Injected by server
const PAGE = __PAGE_CONFIG__;

let currentScene = null;
let narrating    = false;
let sse          = null;
let activeTab    = 'extraction';  // 'extraction' | 'roleplay'

// ── Tabs ──────────────────────────────────────────────────────────

function switchTab(tab) {
  activeTab = tab;
  document.getElementById('tab-extraction').classList.toggle('active', tab === 'extraction');
  document.getElementById('tab-roleplay').classList.toggle('active',   tab === 'roleplay');
  document.getElementById('pane-extraction').classList.toggle('hidden', tab !== 'extraction');
  document.getElementById('pane-roleplay').classList.toggle('hidden',   tab !== 'roleplay');
  // Token estimate only makes sense for extraction
  document.getElementById('token-est').style.visibility =
    tab === 'extraction' ? '' : 'hidden';
  updateEst();
}

// ── Scene list ────────────────────────────────────────────────────

async function loadScenes() {
  const scenes = await fetch('/api/scenes').then(r => r.json());
  document.getElementById('session-label').textContent = PAGE.sessionName;
  const list = document.getElementById('scene-list');
  if (scenes.length === 0) {
    list.innerHTML = '<div style="padding:12px;font-size:11px;color:#6c7086;line-height:1.6">' +
      'No plan yet.<br>Click <b style="color:#cba6f7">Extract</b> in the header<br>to run passes 1–4.' +
      '</div>';
  } else {
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
  }
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

  // Load roleplay context
  const rpData = await fetch(`/api/roleplay/${n}`).then(r => r.json());
  const rpTa = document.getElementById('roleplay-ctx');
  rpTa.value    = rpData.content || '';
  rpTa.disabled = false;
  const badge = document.getElementById('rp-badge');
  badge.style.display = rpData.is_local ? '' : 'none';

  const has = data.exists;
  document.getElementById('btn-save').disabled     = !has;
  document.getElementById('btn-narrate').disabled  = !has;
  document.getElementById('btn-open-ext').disabled = !has;
  document.getElementById('btn-reload').disabled   = !has;

  const outOk = await fetch(`/api/output/${n}`).then(r => r.ok);
  document.getElementById('btn-open-out').disabled = !outOk;
  document.getElementById('btn-raw').disabled = !outOk;
  // Refresh raw panel if it's open
  if (rawVisible) toggleRaw();

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
  const el = document.getElementById('token-est');
  if (activeTab !== 'extraction') { el.textContent = ''; return; }
  const text = document.getElementById('extraction').value;
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

function onInput()   { updateEst(); }
function onRpInput() { /* badge updated on save */ }

// ── Save ───────────────────────────────────────────────────────────

async function saveActive() {
  if (activeTab === 'roleplay') {
    await saveRoleplay();
  } else {
    await saveExtraction();
  }
}

async function saveExtraction() {
  if (currentScene === null) return;
  const content = document.getElementById('extraction').value;
  await fetch(`/api/extraction/${currentScene}`, {
    method:  'PUT',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({content}),
  });
  flash();
  loadScenes();
}

async function saveRoleplay() {
  if (currentScene === null) return;
  const content = document.getElementById('roleplay-ctx').value;
  await fetch(`/api/roleplay/${currentScene}`, {
    method:  'PUT',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({content}),
  });
  document.getElementById('rp-badge').style.display = '';
  flash();
}

function flash() {
  const el = document.getElementById('save-flash');
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1800);
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
    document.getElementById('btn-raw').disabled = false;
    setStatus('Done.');
    setTimeout(() => setStatus(''), 3000);
    loadScenes();
    if (rawVisible) toggleRaw();
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

// ── Extract (passes 1–4) ───────────────────────────────────────────

let extracting = false;

async function runExtract() {
  if (extracting || narrating) return;
  extracting = true;
  const btn = document.getElementById('btn-extract');
  btn.disabled = true;
  btn.textContent = 'Extracting…';

  const out = document.getElementById('narration-out');
  out.textContent = '';
  setStatus('Running extraction (passes 1–4)…');

  sse = new EventSource('/api/extract');

  sse.onmessage = e => {
    out.textContent += JSON.parse(e.data);
    out.scrollTop = out.scrollHeight;
  };

  sse.addEventListener('done', e => {
    sse.close(); sse = null;
    extracting = false;
    btn.disabled = false;
    btn.textContent = 'Extract';
    const rc = JSON.parse(e.data).returncode;
    setStatus(rc === 0 ? 'Extraction complete.' : 'Extraction failed — check output.');
    setTimeout(() => setStatus(''), 4000);
    loadScenes();
  });

  sse.onerror = () => {
    if (!sse) return;
    sse.close(); sse = null;
    extracting = false;
    btn.disabled = false;
    btn.textContent = 'Extract';
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

async function reloadRoleplay() {
  if (currentScene === null) return;
  const data = await fetch(`/api/roleplay/${currentScene}`).then(r => r.json());
  document.getElementById('roleplay-ctx').value = data.content || '';
  document.getElementById('rp-badge').style.display = data.is_local ? '' : 'none';
  setStatus('Reloaded from disk.');
  setTimeout(() => setStatus(''), 2000);
}

// ── Reload ─────────────────────────────────────────────────────────

async function reloadActive() {
  if (activeTab === 'roleplay') {
    await reloadRoleplay();
  } else {
    await reloadExtraction();
  }
}

// ── Open in Typora ─────────────────────────────────────────────────

async function openTyporaActive() {
  if (currentScene === null) return;
  const type = activeTab === 'roleplay' ? 'roleplay' : 'extraction';
  const res = await fetch(`/api/open/${type}/${currentScene}`, {method: 'POST'});
  if (!res.ok) setStatus('File not found.');
}

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

// ── Raw preview ────────────────────────────────────────────────────

let rawVisible = false;

async function toggleRaw() {
  const panel = document.getElementById('raw-preview');
  rawVisible = !rawVisible;
  document.getElementById('btn-raw').textContent = rawVisible ? 'Hide raw' : 'Raw';
  if (!rawVisible) { panel.style.display = 'none'; return; }
  if (currentScene === null) return;
  const res  = await fetch(`/api/raw/${currentScene}`);
  const data = await res.json();
  panel.style.display = '';
  panel.textContent = data.exists ? data.preview : '(no output file yet)';
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

// ── Right panel tabs ──────────────────────────────────────────

let rightTab = 'vtt';

function switchRightTab(tab) {
  rightTab = tab;
  document.getElementById('tab-vtt').classList.toggle('active', tab === 'vtt');
  document.getElementById('tab-ledger').classList.toggle('active', tab === 'ledger');
  const paneVtt    = document.getElementById('pane-vtt');
  const paneLedger = document.getElementById('pane-ledger');
  if (tab === 'vtt') {
    paneVtt.style.display = '';
    paneLedger.style.display = 'none';
  } else {
    paneVtt.style.display = 'none';
    paneLedger.style.display = 'flex';
  }
}

// ── Quote Ledger ─────────────────────────────────────────────

let ledgerData = null;
let expandedQuote = null;

async function syncLedger() {
  setStatus('Syncing quote ledger…');
  try {
    const res  = await fetch('/api/ledger/sync', {method: 'POST'});
    const data = await res.json();
    document.getElementById('ledger-stats').textContent =
      `${data.total} quotes · ${data.matched} matched · ${data.unassigned} unassigned`;
    setStatus(`Ledger synced: ${data.total} quotes found.`);
    setTimeout(() => setStatus(''), 3000);
    await loadLedger();
  } catch (e) {
    setStatus('Ledger sync error — check terminal.');
  }
}

async function loadLedger() {
  const res = await fetch('/api/ledger/quotes');
  ledgerData = await res.json();
  renderLedger();
}

function renderLedger() {
  if (!ledgerData) return;
  const el = document.getElementById('ledger-scroll');
  let html = '';

  // Unassigned section
  const ua = ledgerData.unassigned || [];
  if (ua.length > 0) {
    html += '<div class="ledger-section">';
    html += `<div class="ledger-section-header unassigned" onclick="toggleLedgerSection(this)">` +
            `<span class="arrow open">▶</span> Unassigned ` +
            `<span class="count">${ua.length}</span></div>`;
    html += '<div class="ledger-quotes">';
    html += ua.map(q => renderQuoteItem(q, null)).join('');
    html += '</div></div>';
  }

  // Per-scene sections
  for (const s of (ledgerData.scenes || [])) {
    const qs = s.quotes || [];
    const isActive = currentScene === s.index;
    html += '<div class="ledger-section">';
    html += `<div class="ledger-section-header${isActive ? ' style="color:#cba6f7"' : ''}" ` +
            `onclick="toggleLedgerSection(this)">` +
            `<span class="arrow${qs.length > 0 ? ' open' : ''}">▶</span> ` +
            `Scene ${s.index}: ${esc(s.narrator)}` +
            (s.scene_name ? ` — ${esc(s.scene_name)}` : '') +
            ` <span class="count">${qs.length}</span></div>`;
    html += `<div class="ledger-quotes"${qs.length === 0 ? ' style="display:none"' : ''}>`;
    html += qs.map(q => renderQuoteItem(q, s.index)).join('');
    html += '</div></div>';
  }

  if (!html) {
    html = '<p style="color:#6c7086;font-size:12px;padding:8px 12px">No quotes in ledger. Click <b>Sync</b>.</p>';
  }
  el.innerHTML = html;
}

function renderQuoteItem(q, sceneIdx) {
  const truncated = q.quote_text.length > 80
    ? q.quote_text.substring(0, 80) + '…'
    : q.quote_text;
  const pinnedTag = q.pinned ? ' <span class="q-pinned">pinned</span>' : '';
  // Build scene options for the move dropdown
  let options = '<option value="">— Unassign —</option>';
  if (ledgerData && ledgerData.scenes) {
    for (const s of ledgerData.scenes) {
      const sel = s.index === sceneIdx ? '' : '';
      options += `<option value="${s.index}">Scene ${s.index}: ${esc(s.narrator)}</option>`;
    }
  }
  return `<div class="quote-item" id="qi-${q.id}" onclick="toggleQuoteExpand(${q.id})">` +
    `<div class="q-speaker">${esc(q.character)}${pinnedTag}</div>` +
    `<div class="q-context">${esc(q.context)}</div>` +
    `<div class="q-text">${esc(truncated)}</div>` +
    `<div class="quote-assign">` +
      `<select id="qa-${q.id}">${options}</select> ` +
      `<button class="btn-primary btn-sm" onclick="event.stopPropagation();assignQuote(${q.id})">Move</button>` +
    `</div>` +
  `</div>`;
}

function toggleQuoteExpand(qid) {
  const el = document.getElementById('qi-' + qid);
  if (!el) return;
  const wasExpanded = el.classList.contains('expanded');
  // Collapse previous
  document.querySelectorAll('.quote-item.expanded').forEach(e => {
    e.classList.remove('expanded');
    // Restore truncated text
    const q = findQuote(parseInt(e.id.replace('qi-', '')));
    if (q) {
      const textEl = e.querySelector('.q-text');
      textEl.textContent = q.quote_text.length > 80
        ? q.quote_text.substring(0, 80) + '…' : q.quote_text;
    }
  });
  if (!wasExpanded) {
    el.classList.add('expanded');
    const q = findQuote(qid);
    if (q) {
      el.querySelector('.q-text').textContent = q.quote_text;
    }
  }
}

function findQuote(qid) {
  if (!ledgerData) return null;
  for (const q of (ledgerData.unassigned || [])) {
    if (q.id === qid) return q;
  }
  for (const s of (ledgerData.scenes || [])) {
    for (const q of (s.quotes || [])) {
      if (q.id === qid) return q;
    }
  }
  return null;
}

async function assignQuote(qid) {
  const sel = document.getElementById('qa-' + qid);
  const val = sel.value;
  const sceneIndex = val === '' ? null : parseInt(val);
  const res = await fetch('/api/ledger/assign', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({quote_id: qid, scene_index: sceneIndex}),
  });
  const data = await res.json();
  if (data.ok) {
    setStatus('Quote reassigned.');
    setTimeout(() => setStatus(''), 2000);
    await loadLedger();
  } else {
    setStatus('Assignment failed.');
  }
}

function toggleLedgerSection(header) {
  const arrow = header.querySelector('.arrow');
  const quotes = header.nextElementSibling;
  if (!quotes) return;
  const isOpen = arrow.classList.contains('open');
  if (isOpen) {
    arrow.classList.remove('open');
    quotes.style.display = 'none';
  } else {
    arrow.classList.add('open');
    quotes.style.display = '';
  }
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


def get_roleplay_path(n: int) -> Path | None:
    """Return the per-scene roleplay file path (may not exist yet)."""
    ext_path = get_extraction_path(n)
    if ext_path is None:
        return None
    return ext_path.with_name(ext_path.stem + "_roleplay.md")


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


def build_extract_cmd() -> list[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "session_doc.py"),
        CONFIG["session"],
        "--roleplay-extract-dir", CONFIG["roleplay_extract_dir"],
        "--by-scene",
        "--extract-dir", CONFIG["extract_dir"],
        "--extract-only",
        "--output", "/dev/null",
    ]
    for flag, key in [("--party", "party"), ("--voice-dir", "voice_dir"),
                      ("--summary-extract-dir", "summary_extract_dir"),
                      ("--session-summary", "session_summary"),
                      ("--characters", "characters")]:
        if CONFIG.get(key):
            cmd += [flag, CONFIG[key]]
    for ctx in CONFIG.get("context") or []:
        cmd += ["--context", ctx]
    if CONFIG.get("examples"):
        cmd += ["--examples", CONFIG["examples"]]
    return cmd


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
    # Use per-scene roleplay file if it exists, else fall back to global
    local_rp = get_roleplay_path(scene_num)
    if local_rp and local_rp.exists():
        cmd += ["--roleplay-summary", str(local_rp)]
    elif CONFIG.get("roleplay_summary"):
        cmd += ["--roleplay-summary", CONFIG["roleplay_summary"]]
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


@app.route("/api/roleplay/<int:n>", methods=["GET"])
def api_get_roleplay(n):
    local_path = get_roleplay_path(n)
    if local_path is None:
        return jsonify({"exists": False, "content": "", "is_local": False}), 404
    if local_path.exists():
        return jsonify({"exists": True, "content": local_path.read_text(encoding="utf-8"),
                        "is_local": True})
    # Fall back to global roleplay summary
    global_path = CONFIG.get("roleplay_summary")
    if global_path and Path(global_path).exists():
        return jsonify({"exists": True, "content": Path(global_path).read_text(encoding="utf-8"),
                        "is_local": False})
    return jsonify({"exists": False, "content": "", "is_local": False})


@app.route("/api/roleplay/<int:n>", methods=["PUT"])
def api_save_roleplay(n):
    local_path = get_roleplay_path(n)
    if local_path is None:
        return jsonify({"ok": False}), 404
    local_path.write_text(request.get_json()["content"], encoding="utf-8")
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


@app.route("/api/extract")
def api_extract():
    cmd = build_extract_cmd()

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


@app.route("/api/raw/<int:n>")
def api_raw(n):
    path = Path(CONFIG["output_dir"]) / f"scene{n}.md"
    if not path.exists():
        return jsonify({"exists": False})
    lines = path.read_text(encoding="utf-8").splitlines()
    head  = lines[:6]
    tail  = lines[-6:] if len(lines) > 12 else []
    sep   = ["…"] if tail else []
    preview = "\n".join(head + sep + tail)
    return jsonify({"exists": True, "preview": preview, "total_lines": len(lines)})


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
        while lines and lines[-1].strip() in ("", "---"):
            lines.pop()
        return "\n".join(lines)

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
    elif file_type == "roleplay":
        path = get_roleplay_path(n)
        # If per-scene file doesn't exist yet, create it from global then open
        if path and not path.exists():
            global_path = CONFIG.get("roleplay_summary")
            content = Path(global_path).read_text(encoding="utf-8") if global_path and Path(global_path).exists() else ""
            path.write_text(content, encoding="utf-8")
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


# ── Quote Ledger routes ───────────────────────────────────────────────────────

@app.route("/api/ledger/sync", methods=["POST"])
def api_ledger_sync():
    global LEDGER
    if LEDGER is None:
        db_path = Path(CONFIG["extract_dir"]) / "quote_ledger.db"
        LEDGER = QuoteLedger(db_path)
    scenes = load_scenes()
    result = LEDGER.sync(
        roleplay_dir=Path(CONFIG["roleplay_extract_dir"]),
        extract_dir=Path(CONFIG["extract_dir"]),
        scenes=scenes,
    )
    return jsonify(result)


@app.route("/api/ledger/quotes")
def api_ledger_quotes():
    if LEDGER is None:
        return jsonify({"scenes": [], "unassigned": []})
    scenes = load_scenes()
    return jsonify(LEDGER.get_quotes_grouped(scenes))


@app.route("/api/ledger/assign", methods=["POST"])
def api_ledger_assign():
    if LEDGER is None:
        return jsonify({"ok": False, "error": "ledger not synced"}), 400
    data = request.get_json()
    quote_id = data["quote_id"]
    scene_index = data.get("scene_index")  # None = unassign
    ok = LEDGER.assign(quote_id, scene_index)
    return jsonify({"ok": ok})


# ── Main ──────────────────────────────────────────────────────────────────────

DERIVED_SUBDIRS = {
    "extract_dir":          "scene_extractions",
    "roleplay_extract_dir": "vtt_roleplay_extractions",
    "summary_extract_dir":  "vtt_extractions",
}


def derive_paths(session_dir: Path) -> dict:
    """Return default sub-paths for a session directory."""
    result = {k: str(session_dir / v) for k, v in DERIVED_SUBDIRS.items()}
    result["output_dir"] = str(session_dir)
    # Auto-detect recap: prefer session-recap.md, else most recently modified .md
    md_files = sorted(session_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    preferred = session_dir / "session-recap.md"
    result["session"] = str(preferred if preferred.exists() else md_files[0]) if md_files else ""
    # Auto-detect VTT session summary
    for name in ("session-summary.md", "session-clean.md", "session_summary.md", "session_clean.md"):
        candidate = session_dir / name
        if candidate.exists():
            result["session_summary"] = str(candidate)
            break
    # Auto-detect roleplay summary
    roleplay_candidate = session_dir / "session-roleplay.md"
    if roleplay_candidate.exists():
        result["roleplay_summary"] = str(roleplay_candidate)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Web UI for reviewing and editing session_doc scene extractions."
    )
    parser.add_argument("session", nargs="?", metavar="FILE",
                        help="Session recap file. Omit when using --session-dir.")
    parser.add_argument("--session-dir", metavar="DIR",
                        help="Session directory — auto-derives all paths. "
                             "Defaults: scene_extractions/, vtt_roleplay_extractions/, "
                             "vtt_extracts/, output to the directory itself.")
    parser.add_argument("--extract-dir",          metavar="DIR")
    parser.add_argument("--roleplay-extract-dir",  metavar="DIR")
    parser.add_argument("--output-dir",            metavar="DIR", default=None)
    parser.add_argument("--party",                 metavar="FILE")
    parser.add_argument("--voice-dir",             metavar="DIR")
    parser.add_argument("--summary-extract-dir",   metavar="DIR")
    parser.add_argument("--session-summary", metavar="FILE",
                        help="Synthesised VTT session summary (e.g. session-summary.md)")
    parser.add_argument("--roleplay-summary", metavar="FILE",
                        help="Roleplay highlights document (session-roleplay.md) — "
                             "injected into every narration pass")
    parser.add_argument("--context",    nargs="+", metavar="FILE")
    parser.add_argument("--characters", metavar="NAMES")
    parser.add_argument("--examples",   metavar="DIR")
    parser.add_argument("--narrate-tokens", type=int, metavar="N")
    parser.add_argument("--port",           type=int, default=5000)
    args = parser.parse_args()

    # If --session-dir given, fill any unset args from derived defaults
    if args.session_dir:
        sd = Path(args.session_dir).expanduser().resolve()
        derived = derive_paths(sd)
        if not args.session:
            args.session = derived["session"]
        if not args.extract_dir:
            args.extract_dir = derived["extract_dir"]
        if not args.roleplay_extract_dir:
            args.roleplay_extract_dir = derived["roleplay_extract_dir"]
        if not args.summary_extract_dir:
            args.summary_extract_dir = derived["summary_extract_dir"]
        if not args.output_dir:
            args.output_dir = derived["output_dir"]
        if not args.session_summary and derived.get("session_summary"):
            args.session_summary = derived["session_summary"]
        if not args.roleplay_summary and derived.get("roleplay_summary"):
            args.roleplay_summary = derived["roleplay_summary"]

    # Validate required paths
    missing = []
    if not args.session:
        missing.append("session recap file (positional arg or --session-dir)")
    if not args.extract_dir:
        missing.append("--extract-dir")
    if not args.roleplay_extract_dir:
        missing.append("--roleplay-extract-dir")
    if missing:
        parser.error("Missing required arguments: " + ", ".join(missing))

    CONFIG.update({
        "session":              str(Path(args.session).expanduser().resolve()),
        "extract_dir":          str(Path(args.extract_dir).expanduser().resolve()),
        "roleplay_extract_dir": str(Path(args.roleplay_extract_dir).expanduser().resolve()),
        "output_dir":           str(Path(args.output_dir or ".").expanduser().resolve()),
        "party":     str(Path(args.party).expanduser().resolve())     if args.party     else None,
        "voice_dir": str(Path(args.voice_dir).expanduser().resolve()) if args.voice_dir else None,
        "summary_extract_dir":  str(Path(args.summary_extract_dir).expanduser().resolve()) if args.summary_extract_dir else None,
        "session_summary":  str(Path(args.session_summary).expanduser().resolve())  if args.session_summary  else None,
        "roleplay_summary": str(Path(args.roleplay_summary).expanduser().resolve()) if args.roleplay_summary else None,
        "context":    [str(Path(f).expanduser().resolve()) for f in args.context] if args.context else [],
        "characters": args.characters or None,
        "examples":   str(Path(args.examples).expanduser().resolve()) if args.examples else None,
        "narrate_tokens": args.narrate_tokens,
        "work_dir": str(Path(".").resolve()),
    })

    # Initialize quote ledger if extract dir exists
    global LEDGER
    db_path = Path(CONFIG["extract_dir"]) / "quote_ledger.db"
    LEDGER = QuoteLedger(db_path)

    print(f"  Session Doc UI")
    print(f"  Session:    {CONFIG['session']}")
    print(f"  Extractions:{CONFIG['extract_dir']}")
    print(f"  Output:     {CONFIG['output_dir']}")
    print(f"  Open http://localhost:{args.port} in your browser")
    print()
    app.run(port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
