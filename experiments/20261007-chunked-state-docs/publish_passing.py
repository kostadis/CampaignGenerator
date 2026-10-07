"""Publish (npc-publish --name ...) every drafted NPC whose verify verdict is pass; list the rest.

    python publish_passing.py CAMPAIGN_ROOT
"""
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
draft = root / "docs/npcs/summary_native/ch002-070/draft"
passing, failing = [], []
for v in sorted(draft.glob("*.verify.md")):
    text = v.read_text(encoding="utf-8")
    name = re.search(r"^# Verification: (.+)$", text, re.M).group(1).strip()
    verdict = re.search(r"verdict:? *\**(pass|fail)", text, re.I)
    fails = "## Failures" in text and re.search(r"## Failures\s*\n\s*\n- ", text)
    (failing if fails or (verdict and verdict.group(1).lower() == "fail") else passing).append(name)
print(f"passing {len(passing)}, failing {len(failing)}: {failing}")
cmd = [str(Path.home() / ".venv/bin/summary_native"), "npc-publish", "--since", "2", "--until", "70", "--name", *passing]
r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
print(r.stdout[-3000:], r.stderr[-3000:], f"exit {r.returncode}", sep="\n")
json.dump({"published": passing, "not_published_verify_failed": failing},
          open(Path(__file__).resolve().parent / "run2" / "npc_publish.json", "w"), indent=2)
