"""Compare reduce variants that share one map: timing from logs, quote/citation checks, hand-verified facts."""
import json
import re
import subprocess
import sys
from pathlib import Path

CAMP = "/home/kostadis/out-of-the-abyss/out-of-the-abyss"
PY = "/home/kostadis/.venv/bin/python"
RUNS = [("Qwen3-Next (Spark)", "run3", "run3.log"), ("Sonnet 5.5 medium", "run3_sonnet", "run3_sonnet.log"),
        ("Sonnet 5.5 high", "run3_sonnet_hi", "run3_sonnet_hi.log"), ("Opus 5.5 low", "run3_opus_lo", "run3_opus_lo.log"),
        ("Opus 5.5 medium", "run3_opus", "run3_opus.log")]
TRUTH = {"Ilvara Mizzrym": "Dead", "Sarith Kzekarit": "Dead", "Buppido": "Dead", "Glabbagool": "Alive"}


def facts(run: str) -> str:
    world = Path(run, "world_state.chunked.md").read_text(encoding="utf-8")
    head = world.split("## Factions")[0]
    lvl = bool(re.search(r"[Ll]evel:?\**:? *(9|nine)|[Ll]evel 9|level nine|ninth level|9th level", head))
    name = "Ember Vanguard" in head and not re.search(r'known as the "?Ember Grapple', head)
    return f"level9={'✓' if lvl else '✗'} name={'✓' if name else '✗'}"


rows = []
for label, run, log in RUNS:
    secs = [float(s) for s in re.findall(r"^reduce .* (\d+)s \(", Path(log).read_text(encoding="utf-8"), re.M)]
    out = json.loads(subprocess.run([PY, "check_doc.py", CAMP, f"{run}/world_state.chunked.md"],
                                    capture_output=True, text=True, check=True).stdout)
    camp = json.loads(subprocess.run([PY, "check_doc.py", CAMP, f"{run}/campaign_state.chunked.md"],
                                     capture_output=True, text=True, check=True).stdout)
    rows.append((label, max(secs) if secs else 0, sum(secs), out, camp, facts(run)))

print(f"{'reduce model':<20}{'slowest call':>13}{'sum calls':>11}{'world chars':>12}{'quotes ok':>12}"
      f"{'cit. invalid':>13}{'scenes%':>9}{'entities':>9}  facts")
for label, mx, sm, w, c, f in rows:
    print(f"{label:<20}{mx:>12.0f}s{sm:>10.0f}s{w['chars']:>12}{str(w['quoted_spans_verbatim']) + '/' + str(w['quoted_spans']):>12}"
          f"{w['bracket_citation_parts_invalid']:>13}{w['scene_coverage_pct']:>9}{w['registry_entities_named']:>9}  {f}")
print("\ncampaign_state prose quotes (excl. audit are not separated here; audit text is code-written and identical across runs):")
for label, mx, sm, w, c, f in rows:
    print(f"  {label:<20} quotes {c['quoted_spans_verbatim']}/{c['quoted_spans']}  invalid citations {c['bracket_citation_parts_invalid']}")
