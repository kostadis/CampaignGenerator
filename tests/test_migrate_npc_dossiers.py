"""Two-step docs/npcs/ migration (spec 032 T030, FR-022a-d), modelled on test_migrate_wiring."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from campaignlib.npc import PUBLISH_HEADER_PREFIX
from server import migrate_npc_dossiers as mig
from server.migrate_npc_dossiers import CLASSIFICATION_NAME, MigrationError, apply, main, propose

MARKED = "---\nname: Hedrack\naliases: []\nsource_extracts: [1, 2]\n---\n\nbody\n"
UNMARKED = "# Eelrich Vane\n\nA hand-written dossier.\n"


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def _campaign(tmp_path, *, git=True, files=None):
    root = tmp_path / "camp"
    npcs = root / "docs" / "npcs"
    npcs.mkdir(parents=True)
    (root / "config").mkdir()
    files = {"hedrack.md": MARKED, "eelrich-vane.md": UNMARKED} if files is None else files
    for name, body in files.items():
        (npcs / name).write_text(body, encoding="utf-8")
    if git:
        _git(root, "init", "-q")
        _commit(root, "Eelrich Vane NPC and session outputs")
    return root


def _load(root):
    return yaml.safe_load((root / "docs/npcs" / CLASSIFICATION_NAME).read_text(encoding="utf-8"))


def _entry(doc, path):
    return next(e for e in doc["entries"] if e["path"] == path)


def _settle(root, **dispositions):
    p = root / "docs/npcs" / CLASSIFICATION_NAME
    doc = yaml.safe_load(p.read_text())
    for e in doc["entries"]:
        if e["path"] in dispositions:
            e["disposition"] = dispositions[e["path"]]
    p.write_text(yaml.safe_dump(doc, sort_keys=False))


# ── --propose ────────────────────────────────────────────────────────────────

def test_marked_file_is_distilled_and_unmarked_is_unknown(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    doc = _load(root)
    assert _entry(doc, "hedrack.md")["disposition"] == "distilled"
    assert _entry(doc, "hedrack.md")["evidence"]["source_extracts_marker"] is True
    assert _entry(doc, "eelrich-vane.md")["disposition"] == "unknown"
    assert _entry(doc, "eelrich-vane.md")["evidence"]["source_extracts_marker"] is False


def test_sidecars_and_state_files_are_distilled(tmp_path):
    root = _campaign(tmp_path, files={"hedrack.new_notes.002.md": "x\n", ".dedup_state.json": "{}\n",
                                      ".sidecar_merge_state.json": "{}\n"})
    (root / "docs/npcs/merged_sidecars").mkdir()
    (root / "docs/npcs/merged_sidecars/a.md").write_text("old\n")
    propose(root)
    doc = _load(root)
    for name in ("hedrack.new_notes.002.md", ".dedup_state.json", ".sidecar_merge_state.json", "merged_sidecars/"):
        assert _entry(doc, name)["disposition"] == "distilled", name


def test_commit_wording_never_sets_a_disposition(tmp_path):
    root = _campaign(tmp_path)   # the commit message is "Eelrich Vane NPC and session outputs"
    propose(root)
    entry = _entry(_load(root), "eelrich-vane.md")
    assert "Eelrich Vane NPC" in entry["evidence"]["git"]["added"]["subject"]   # shown as evidence
    assert entry["disposition"] == "unknown"                                    # and only as evidence


def test_a_file_changed_since_added_is_flagged_hand_edited(tmp_path):
    root = _campaign(tmp_path)
    (root / "docs/npcs/hedrack.md").write_text(MARKED + "A hand edit.\n")
    propose(root)
    e = _entry(_load(root), "hedrack.md")
    assert e["flags"] == ["hand-edited"]
    assert e["evidence"]["git"]["changed_since_added"] is True
    assert "flags" not in _entry(_load(root), "eelrich-vane.md")


def test_later_commits_are_listed(tmp_path):
    root = _campaign(tmp_path)
    (root / "docs/npcs/hedrack.md").write_text(MARKED + "more\n")
    _commit(root, "fix canon")
    propose(root)
    git = _entry(_load(root), "hedrack.md")["evidence"]["git"]
    assert [c["subject"] for c in git["later_commits"]] == ["fix canon"]
    assert git["changed_since_added"] is True


def test_outside_git_the_evidence_is_unavailable(tmp_path):
    root = _campaign(tmp_path, git=False)
    propose(root)
    doc = _load(root)
    assert doc["proposed_at_commit"] is None
    assert _entry(doc, "eelrich-vane.md")["evidence"]["git"] == "unavailable"
    assert _entry(doc, "hedrack.md")["disposition"] == "distilled"   # marker needs no git
    assert "flags" not in _entry(doc, "hedrack.md")


def test_output_is_deterministic(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    first = (root / "docs/npcs" / CLASSIFICATION_NAME).read_bytes()
    (root / "docs/npcs" / CLASSIFICATION_NAME).unlink()
    propose(root)
    assert (root / "docs/npcs" / CLASSIFICATION_NAME).read_bytes() == first
    assert [e["path"] for e in yaml.safe_load(first)["entries"]] == ["eelrich-vane.md", "hedrack.md"]


def test_propose_moves_nothing_and_never_calls_a_mutating_git_command(tmp_path, monkeypatch):
    root = _campaign(tmp_path)
    before = {p.name: p.read_bytes() for p in (root / "docs/npcs").iterdir()}
    seen = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        if cmd and cmd[0] == "git":
            seen.append(cmd[1])
        return real(cmd, *a, **kw)

    monkeypatch.setattr(mig.subprocess, "run", spy)
    propose(root)
    assert {c for c in seen} <= {"rev-parse", "log", "diff"}
    assert {p.name: p.read_bytes() for p in (root / "docs/npcs").iterdir() if p.name != CLASSIFICATION_NAME} == before


def test_nothing_to_classify_on_a_migrated_campaign(tmp_path, capsys):
    root = _campaign(tmp_path, files={})
    (root / "docs/npcs/distilled").mkdir()
    (root / "docs/npcs/jimjar.md").write_text(PUBLISH_HEADER_PREFIX + " | source: summary_native -->\nbody\n")
    assert propose(root) is None
    assert "nothing to classify" in capsys.readouterr().out
    assert not (root / "docs/npcs" / CLASSIFICATION_NAME).exists()


def test_a_rerun_keeps_a_disposition_the_gm_set(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    propose(root)
    assert _entry(_load(root), "eelrich-vane.md")["disposition"] == "authored"


# ── --apply ──────────────────────────────────────────────────────────────────

def test_apply_refuses_while_any_entry_is_unknown(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    with pytest.raises(MigrationError, match="unknown"):
        apply(root, provenance_path=None)
    assert (root / "docs/npcs/hedrack.md").exists()
    assert main(["--campaign-dir", str(root), "--apply"]) == 1


def test_apply_refuses_without_a_classification_when_files_are_loose(tmp_path):
    root = _campaign(tmp_path)
    with pytest.raises(MigrationError, match="--propose"):
        apply(root, provenance_path=None)


def test_apply_refuses_on_sha_drift_after_propose(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    (root / "docs/npcs/hedrack.md").write_text(MARKED + "edited after propose\n")
    with pytest.raises(MigrationError, match="hedrack.md: changed since --propose"):
        apply(root, provenance_path=None)
    assert (root / "docs/npcs/hedrack.md").exists() and not (root / "docs/npcs/distilled").exists()


def test_apply_refuses_a_file_added_or_removed_since_propose(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    (root / "docs/npcs/new.md").write_text("late\n")
    with pytest.raises(MigrationError, match="new.md: added"):
        apply(root, provenance_path=None)
    (root / "docs/npcs/new.md").unlink()
    (root / "docs/npcs/hedrack.md").unlink()
    with pytest.raises(MigrationError, match="hedrack.md: removed"):
        apply(root, provenance_path=None)


def test_apply_refuses_an_existing_target_without_force(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    (root / "docs/npcs/distilled").mkdir()
    (root / "docs/npcs/distilled/hedrack.md").write_text("already here\n")
    with pytest.raises(MigrationError, match="already exist"):
        apply(root, provenance_path=None)
    assert (root / "docs/npcs/hedrack.md").exists()                      # nothing moved
    assert (root / "docs/npcs/eelrich-vane.md").exists()
    apply(root, force=True, provenance_path=None)
    assert (root / "docs/npcs/distilled/hedrack.md").read_text() == MARKED


def test_apply_moves_entries_byte_identical(tmp_path, capsys):
    root = _campaign(tmp_path)
    (root / "docs/npcs/merged_sidecars").mkdir()
    (root / "docs/npcs/merged_sidecars/old.md").write_bytes(b"\xff\x00 raw bytes\n")
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    want = {"hedrack.md": hashlib.sha256(MARKED.encode()).hexdigest(),
            "eelrich-vane.md": hashlib.sha256(UNMARKED.encode()).hexdigest()}
    apply(root, provenance_path=None)
    npcs = root / "docs/npcs"
    assert hashlib.sha256((npcs / "distilled/hedrack.md").read_bytes()).hexdigest() == want["hedrack.md"]
    assert hashlib.sha256((npcs / "authored/eelrich-vane.md").read_bytes()).hexdigest() == want["eelrich-vane.md"]
    assert (npcs / "distilled/merged_sidecars/old.md").read_bytes() == b"\xff\x00 raw bytes\n"
    assert sorted(p.name for p in npcs.iterdir()) == ["authored", "distilled", CLASSIFICATION_NAME]
    out = capsys.readouterr().out
    assert "npc-publish --authored-all" in out


def test_apply_is_resumable_and_repeatable(tmp_path):
    root = _campaign(tmp_path)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    apply(root, provenance_path=None)
    apply(root, provenance_path=None)   # entries already at their targets: not an error
    assert propose(root) is None        # and a re-propose has nothing to classify


GROUNDING = """\
# grounding config
planning:
  dossiers:
    summaries: null   # keep
    dossier_dir: docs/npcs/   # the old place
    extract_dir: null
other:
  dossier_dir: docs/npcs/
"""
PLANNING = """\
# planning config
npcs:
  - name: Hedrack
    dossier: docs/npcs/hedrack.md   # distilled
  - name: Eelrich
    dossier: "docs/npcs/eelrich-vane.md"
  - name: Elsewhere
    dossier: notes/elsewhere.md
  - name: Published
    dossier: docs/npcs/jimjar.md
factions:
  - name: F
    arc_score: x
"""


def test_config_rewrites_preserve_comments_and_report_out_of_tree_values(tmp_path, capsys):
    root = _campaign(tmp_path)
    (root / "docs/npcs/jimjar.md").write_text(PUBLISH_HEADER_PREFIX + " | source: summary_native -->\nbody\n")
    (root / "config/grounding.yaml").write_text(GROUNDING)
    (root / "config/planning.yaml").write_text(PLANNING)
    propose(root)
    _settle(root, **{"eelrich-vane.md": "authored"})
    result = apply(root, provenance_path=None)
    g = (root / "config/grounding.yaml").read_text()
    assert "    dossier_dir: docs/npcs/distilled/   # the old place\n" in g
    assert "  dossier_dir: docs/npcs/\n" in g                       # `other.dossier_dir` is not ours
    assert g.replace("docs/npcs/distilled/", "docs/npcs/") == GROUNDING
    p = (root / "config/planning.yaml").read_text()
    assert "    dossier: docs/npcs/distilled/hedrack.md   # distilled\n" in p
    assert '    dossier: "docs/npcs/authored/eelrich-vane.md"\n' in p
    assert "    dossier: notes/elsewhere.md\n" in p                 # out of tree: unchanged
    assert "    dossier: docs/npcs/jimjar.md\n" in p                # published, not classified: unchanged
    assert any("notes/elsewhere.md" in n for n in result["notes"])
    assert yaml.safe_load(p)["factions"] == [{"name": "F", "arc_score": "x"}]
    assert "not changed" in capsys.readouterr().out


def test_config_only_campaign_is_rewritten_without_a_classification(tmp_path):
    root = _campaign(tmp_path, files={})
    (root / "config/grounding.yaml").write_text(GROUNDING)
    apply(root, provenance_path=None)
    assert "dossier_dir: docs/npcs/distilled/   # the old place" in (root / "config/grounding.yaml").read_text()


def test_provenance_globs_are_reported_not_edited(tmp_path, capsys):
    root = _campaign(tmp_path, files={})
    prov = tmp_path / "provenance.yaml"
    prov.write_text('x:\n  paths: ["docs/npcs/*.md"]\n')
    apply(root, provenance_path=prov)
    out = capsys.readouterr().out
    assert f"{prov}:2" in out
    assert prov.read_text() == 'x:\n  paths: ["docs/npcs/*.md"]\n'


def test_force_without_apply_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        main(["--campaign-dir", str(tmp_path), "--propose", "--force"])


def test_exactly_one_of_propose_and_apply(tmp_path):
    with pytest.raises(SystemExit):
        main(["--campaign-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["--campaign-dir", str(tmp_path), "--propose", "--apply"])


def test_cli_help_runs_as_module(tmp_path):
    result = subprocess.run([sys.executable, "-m", "server.migrate_npc_dossiers", "--help"],
                            cwd=tmp_path, capture_output=True, text=True, check=True,
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent)))
    assert "--propose" in result.stdout and "--apply" in result.stdout
