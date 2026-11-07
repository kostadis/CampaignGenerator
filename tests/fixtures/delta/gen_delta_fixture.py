"""Regenerates the published half of tests/fixtures/delta/campaign using the real helpers."""
import json, shutil, yaml
from datetime import datetime, timezone
from pathlib import Path
from pipelines.summary_native import npc_compose, npc_publish, npc_slug

ROOT = Path("tests/fixtures/delta/campaign")
NOW = lambda: datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
CANARY = "CANARY-SECRET-7f3a"
shutil.rmtree(ROOT / "docs/npcs/summary_native", ignore_errors=True)
shutil.rmtree(ROOT / "docs/npcs/authored", ignore_errors=True)
for f in (ROOT / "docs/npcs").glob("*.md"): f.unlink()
(ROOT / "docs/npcs/authored").mkdir(parents=True)

SPEC = [
  ("Brannoc Ironvein", "ch001-002", "20260310T100000Z",
   "## Identity\n\nA dwarf smith of Emberfall who keeps his forge cold after his apprentice vanished. [ch 001 / entry]\n\n"
   "## History with the Party\n\n- Explains why the forge is cold. [ch 001 / 001.01]\n"
   "- Gives the party his apprentice's hammer and points them north. [ch 002 / 002.02]\n\n"
   "## Notable Quotes\n\n> \"A forge is a promise, and mine is broken.\"\n— Brannoc Ironvein [ch 001 / moment]\n\n"
   "## Last Observed State\n\nAs of chapter 002 the forge is still cold. [ch 002 / 002.02]\n",
   f"The apprentice never left of his own will. {CANARY}\n"),
  ("Envoy Sella Marr", "ch001-001", "20260310T101000Z",
   "## Identity\n\nA courteous envoy of the Lantern Guild with a ledger always at hand. [ch 001 / entry]\n\n"
   "## History with the Party\n\n- Rides into Emberfall and asks who speaks for the town. [ch 001 / 001.02]\n\n"
   "## Last Observed State\n\nAs of chapter 001 she is in the Emberfall square. [ch 001 / 001.02]\n",
   ""),
]
for subject, rng, run, body, secrets in SPEC:
    slug = npc_slug.slug_for(subject)
    stem = npc_slug.stem_for("npc", subject)
    rd = ROOT / "docs/npcs/summary_native" / rng
    (rd / "draft").mkdir(parents=True, exist_ok=True)
    draft = (f"<!-- summary_native npc draft | npc: {subject} | range: {rng} | run: {run} "
             f"| draft_key: k-{slug} | manual sha256: none | model: fixture | backend: fixture -->\n"
             f"---\nsubject: {subject}\n---\n\n" + body)
    (rd / "draft" / f"{stem}.md").write_text(draft, encoding="utf-8")
    auth = ROOT / "docs/npcs/authored" / f"{slug}.authored.yaml"
    auth.write_text(yaml.safe_dump({"subject": subject, "manual": [], "secrets": secrets},
                    allow_unicode=True, default_flow_style=False, width=10**6), encoding="utf-8")
    npc_compose.compose_gm(rd / "draft" / f"{stem}.md", auth, rd / "gm" / f"{stem}.md", subject, stem)
    (rd / "draft" / f"{stem}.verify.md").write_text(f"# Verification: {subject}\n\n**Verdict: pass**\n", encoding="utf-8")
    res = npc_publish.publish(ROOT, rd, names=[subject], now=NOW, _signoff_checker=lambda p, d: True)
    assert res[0].published, res
print(sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()))
