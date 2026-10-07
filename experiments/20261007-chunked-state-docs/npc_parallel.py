"""Run `summary_native npc-draft` as N parallel processes over disjoint --name groups (one per vLLM stream).

npc-draft drafts one NPC at a time; DeepSeek serves 6 streams. Each process gets its own runs/<stamp>
dir; the shared draft index.json can at worst lose an entry (a later run re-drafts it), never a dossier.

    python npc_parallel.py SELECTION_JSON CAMPAIGN_ROOT LOG_DIR [N]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sel, root, logs = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
n = int(sys.argv[4]) if len(sys.argv) > 4 else 6
names = [i["subject"] for i in json.loads(sel.read_text())["included"]]
groups = [names[k::n] for k in range(n)]
logs.mkdir(parents=True, exist_ok=True)
base = [str(Path.home() / ".venv/bin/summary_native"), "npc-draft", "--since", "2", "--until", "70",
        "--backend", "dgx", "--model", "deepseek-ai/DeepSeek-V4-Flash-0731",
        "--endpoint", "http://192.168.1.147:8001/v1"]
procs = []
for k, g in enumerate(groups):
    log = open(logs / f"npc_group{k}.log", "w")
    log.write(f"# group {k}: {g}\n")
    log.flush()
    procs.append((g, subprocess.Popen(base + ["--name", *g], cwd=root, stdout=log, stderr=subprocess.STDOUT)))
    time.sleep(2)  # distinct runs/<stamp> dirs
t0 = time.time()
for g, p in procs:
    p.wait()
    print(f"[{time.time() - t0:.0f}s] exit {p.returncode}: {g}", flush=True)
