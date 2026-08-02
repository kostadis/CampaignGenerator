"""Thread registry (#213 Phase 3, closes #154).

Two surfaces: canon (registry + propose/verbs/render — deterministic,
GM-gated) and speculation (LLM, notes staging, not tested against a model
here — only its payload builder). The classes #154 documented must be
impossible by construction: no [ch00] (log rows demand real chapter ints),
no duplicate threads (normalised title/alias collision is a check error).
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipelines.grounding.thread_registry import (  # noqa: E402
    build_speculation_payload,
    check_registry,
    load_registry,
    match_thread,
    norm_title,
    propose,
    render,
)

CLI = REPO / "pipelines/grounding/thread_registry.py"


def run_cli(cwd, *argv):
    return subprocess.run([sys.executable, str(CLI), *argv],
                          capture_output=True, text=True, cwd=cwd)


def _corpus(dirp: Path, chapter: int, facts: list[dict]) -> None:
    d = dirp / f"chapter_{chapter:02d}_x"
    d.mkdir(parents=True, exist_ok=True)
    (d / "merged.json").write_text(json.dumps(facts))


def _thread_fact(title, text, quote=None):
    fa = {"type": "thread", "subject": title, "fact": text}
    if quote:
        fa.update(source_quote=quote, quote_verified=True)
    return fa


# ── identity model ───────────────────────────────────────────────────────

def test_norm_title_collapses_the_154_duplicates():
    assert norm_title("Aletra's boss") == norm_title("aletras boss")
    assert norm_title("Aletra’s Boss") == "aletras-boss"
    # but distinct titles stay distinct — matching is exact, never similar
    assert norm_title("Aletra's boss") != norm_title("Aletra's mysterious boss")


def test_match_thread_uses_title_and_aliases_only():
    data = {"threads": [{"id": "aletra-boss", "title": "Aletra's boss",
                         "aliases": ["Aletra's mysterious boss"]}]}
    assert match_thread(data, "aletras boss")["id"] == "aletra-boss"
    assert match_thread(data, "Aletra's Mysterious Boss")["id"] == "aletra-boss"
    assert match_thread(data, "Aletra's employer") is None


# ── verbs via CLI (the ratification writers) ─────────────────────────────

def test_add_log_status_roundtrip(tmp_path):
    reg = tmp_path / "docs" / "thread_registry.yaml"
    r = run_cli(tmp_path, "--registry", str(reg), "add", "--id", "carver-march",
                "--title", "The Carver's march", "--opened", "30",
                "--tracker", "Carver threat")
    assert r.returncode == 0, r.stderr
    r = run_cli(tmp_path, "--registry", str(reg), "log", "--id", "carver-march",
                "--chapter", "40", "--change", "advanced",
                "--summary", "The march reaches the valley.",
                "--quote", "the horde crested the ridge")
    assert r.returncode == 0, r.stderr
    r = run_cli(tmp_path, "--registry", str(reg), "set-status",
                "--id", "carver-march", "--status", "resolved", "--chapter", "46")
    assert r.returncode == 0, r.stderr
    data = load_registry(reg)
    t = data["threads"][0]
    assert (t["status"], t["resolved"]) == ("resolved", 46)
    assert t["log"][0]["chapter"] == 40


def test_add_refuses_title_collision(tmp_path):
    reg = tmp_path / "reg.yaml"
    assert run_cli(tmp_path, "--registry", str(reg), "add", "--id", "a",
                   "--title", "Aletra's boss", "--opened", "1").returncode == 0
    r = run_cli(tmp_path, "--registry", str(reg), "add", "--id", "b",
                "--title", "aletras boss", "--opened", "2")
    assert r.returncode != 0
    assert "matches existing thread" in r.stderr


def test_resolve_without_chapter_refused(tmp_path):
    reg = tmp_path / "reg.yaml"
    run_cli(tmp_path, "--registry", str(reg), "add", "--id", "a",
            "--title", "T", "--opened", "1")
    r = run_cli(tmp_path, "--registry", str(reg), "set-status",
                "--id", "a", "--status", "resolved")
    assert r.returncode != 0 and "--chapter" in r.stderr


def test_check_rejects_ch00_class():
    data = {"threads": [{"id": "x", "title": "X", "status": "open", "opened": 1,
                         "log": [{"chapter": 0, "change": "advanced", "summary": "s"}]}]}
    errors = check_registry(data)
    assert any("real chapter number" in e for e in errors)


# ── propose ──────────────────────────────────────────────────────────────

def test_propose_groups_matches_and_preserves_rulings(tmp_path):
    _corpus(tmp_path, 40, [
        _thread_fact("Aletra's boss", "Aletra reports to someone unseen.",
                     quote="she answers to another"),
        _thread_fact("dragon slayer sword", "The sword hums near the hoard."),
    ])
    _corpus(tmp_path, 41, [
        _thread_fact("aletras boss", "The boss's demands escalate."),
    ])
    reg = tmp_path / "reg.yaml"
    reg.write_text(yaml.safe_dump({"version": 1, "threads": [
        {"id": "aletra-boss", "title": "Aletra's boss", "status": "open",
         "opened": 34, "aliases": [], "log": [
             {"chapter": 40, "change": "advanced", "summary": "known"}]},
    ]}))
    out = tmp_path / "proposals.yaml"
    total, pending = propose([str(tmp_path / "*" / "merged.json")], reg, out)
    data = yaml.safe_load(out.read_text())
    by_norm = {p["norm"]: p for p in data["proposals"]}
    # matched thread: ch40 already logged, only ch41 is fresh
    ab = by_norm["aletras-boss"]
    assert ab["matches"] == "aletra-boss"
    assert ab["chapters"] == [40, 41]
    assert ab["status"] == "pending"
    # unmatched: new-thread candidate
    assert by_norm["dragon-slayer-sword"]["matches"] is None
    assert by_norm["dragon-slayer-sword"]["evidence"][0].get("quote") is None

    # a GM ruling is a one-way door across re-proposes
    ab["status"] = "rejected"
    out.write_text(yaml.safe_dump({"proposals": list(by_norm.values())}))
    propose([str(tmp_path / "*" / "merged.json")], reg, out)
    data2 = yaml.safe_load(out.read_text())
    assert {p["norm"]: p["status"] for p in data2["proposals"]}["aletras-boss"] == "rejected"


def test_propose_skips_fully_logged_matches(tmp_path):
    _corpus(tmp_path, 40, [_thread_fact("Aletra's boss", "Known beat.")])
    reg = tmp_path / "reg.yaml"
    reg.write_text(yaml.safe_dump({"version": 1, "threads": [
        {"id": "aletra-boss", "title": "Aletra's boss", "status": "open",
         "opened": 34, "log": [{"chapter": 40, "change": "advanced",
                                "summary": "already ratified"}]},
    ]}))
    out = tmp_path / "proposals.yaml"
    total, pending = propose([str(tmp_path / "*" / "merged.json")], reg, out)
    assert pending == 0


# ── render ───────────────────────────────────────────────────────────────

def test_render_groups_by_status_with_real_chapters(tmp_path):
    data = {"version": 1, "threads": [
        {"id": "a", "title": "Open thing", "status": "open", "opened": 3,
         "tracker": "Echoes Score",
         "log": [{"chapter": 40, "change": "advanced", "summary": "Moved.",
                  "quote": "it moved"}]},
        {"id": "b", "title": "Done thing", "status": "resolved", "opened": 1,
         "resolved": 12, "log": []},
    ]}
    out = tmp_path / "threads.md"
    assert render(data, out) == 2
    text = out.read_text()
    assert "## Open (1)" in text and "## Resolved (1)" in text
    assert "[ch40] (advanced) Moved." in text
    assert "(tracker: Echoes Score)" in text
    assert "ch00" not in text
    assert "GM-ratified" in text


# ── speculation payload (the LLM sees canon + evidence, clearly split) ───

def test_speculation_payload_separates_canon_from_evidence(tmp_path):
    data = {"threads": [{"id": "a", "title": "Canon thread", "status": "open",
                         "log": [{"chapter": 5, "change": "opened",
                                  "summary": "It began."}]}]}
    props = tmp_path / "proposals.yaml"
    props.write_text(yaml.safe_dump({"proposals": [
        {"norm": "x", "title": "Wild hint", "status": "pending",
         "chapters": [7], "evidence": [{"chapter": 7, "fact": "A hint."}]},
        {"norm": "y", "title": "Rejected", "status": "rejected",
         "chapters": [8], "evidence": []},
    ]}))
    payload = build_speculation_payload(data, props)
    assert payload.index("RATIFIED THREADS (canon)") < payload.index(
        "HARVESTED THREAD EVIDENCE (not canon")
    assert "Canon thread" in payload and "Wild hint" in payload
    assert "Rejected" not in payload   # GM-rejected material never feeds ideas
