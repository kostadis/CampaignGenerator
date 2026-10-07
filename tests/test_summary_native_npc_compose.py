"""``summary_native npc-compose`` and ``compose_gm`` (spec 032 T021, FR-018b)."""

from __future__ import annotations

import pytest

from pipelines.summary_native import npc_authored, npc_compose
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli, sha_tree

OUT = "docs/npcs/summary_native/ch002-006"
DRAFT = "<!-- summary_native npc draft | npc: Jimjar | run: X -->\n---\nsubject: Jimjar\n---\n\n## Identity\n\nA gnome.\n"


def _args(root, cmd, *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"),
        "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


def test_gm_dossier_is_draft_body_plus_secrets_byte_for_byte(tmp_path):
    draft = tmp_path / "d.md"
    draft.write_text(DRAFT)
    auth = tmp_path / "jimjar.authored.yaml"
    secrets = "Line one\n\n  indented é line\n"
    import yaml
    auth.write_text(yaml.safe_dump({"subject": "Jimjar", "manual": ["m"], "secrets": secrets}))
    res = npc_compose.compose_gm(draft, auth, tmp_path / "gm.md", "Jimjar")
    text = (tmp_path / "gm.md").read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    assert first.startswith("<!-- summary_native npc gm | npc: Jimjar | draft sha256: ")
    assert "<!-- summary_native npc draft" not in text           # the draft's provenance comment is dropped
    assert rest == "---\nsubject: Jimjar\n---\n\n## Identity\n\nA gnome.\n\n## Secrets\n" + secrets
    assert res.drafted and res.has_secrets and not res.hand_edited


def test_absent_parts_render_placeholders(tmp_path):
    npc_compose.compose_gm(None, tmp_path / "none.authored.yaml", tmp_path / "gm.md", "Jimjar")
    rest = (tmp_path / "gm.md").read_text().split("\n", 1)[1]
    assert rest == "_(not yet drafted)_\n\n## Secrets\n_(none authored)_\n"


def test_subject_mismatch_is_refused(tmp_path):
    auth = tmp_path / "x.authored.yaml"
    auth.write_text("subject: Somebody Else\nsecrets: s\n")
    with pytest.raises(npc_authored.AuthoredError):
        npc_compose.compose_gm(None, auth, tmp_path / "gm.md", "Jimjar")
    assert not (tmp_path / "gm.md").exists()


def test_sources_are_never_modified(tmp_path):
    draft, auth = tmp_path / "d.md", tmp_path / "j.authored.yaml"
    draft.write_text(DRAFT)
    auth.write_text("subject: Jimjar\nsecrets: s\n")
    before = sha_tree(tmp_path)
    npc_compose.compose_gm(draft, auth, tmp_path / "out" / "gm.md", "Jimjar")
    assert {k: v for k, v in sha_tree(tmp_path).items() if not k.startswith("out/")} == before


def test_hand_edit_detection_round_trip(tmp_path):
    draft, gm = tmp_path / "d.md", tmp_path / "gm.md"
    draft.write_text(DRAFT)
    auth = tmp_path / "j.authored.yaml"
    assert not npc_compose.compose_gm(draft, auth, gm, "Jimjar").hand_edited
    assert not npc_compose.compose_gm(draft, auth, gm, "Jimjar").hand_edited      # recompose is clean
    gm.write_text(gm.read_text() + "my note\n")
    assert npc_compose.compose_gm(draft, auth, gm, "Jimjar").hand_edited
    assert "my note" not in gm.read_text()                                         # discarded


def _drafted(tmp_path, monkeypatch):
    from pipelines.summary_native import npc_draft, synth
    root = npc_campaign(tmp_path)
    assert run_cli(_args(root, "npc-link"))[0] == 0
    body = "\n".join(f"{h}\n\n- ok [ch 002 / 002.01]\n" for h in synth.load_outline("npc_dossier"))
    monkeypatch.setattr(npc_draft, "render_part", lambda *a, **k: body)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    assert run_cli(_args(root, "npc-draft", "--mode", "one-shot", "--name", "Jimjar"))[0] == 0
    return root


def test_cli_recompose_after_secrets_edit_and_hand_edit_warning(tmp_path, monkeypatch):
    root = _drafted(tmp_path, monkeypatch)
    d = root / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Jimjar\nsecrets: |\n  first\n")
    rc, so, err = run_cli(_args(root, "npc-compose", "--name", "Jimjar"))
    assert rc == 0 and "composed" in so and err == ""
    gm = root / OUT / "gm/npc_jimjar.md"
    assert gm.read_text().endswith("## Secrets\nfirst\n")
    gm.write_text(gm.read_text() + "edit\n")
    rc, so, err = run_cli(_args(root, "npc-compose", "--name", "Jimjar"))
    assert rc == 0 and "unrecorded hand-edit; discarded" in err and "jimjar.authored.yaml" in err
    assert "edit" not in gm.read_text().rsplit("## Secrets", 1)[1]


def test_cli_default_composes_every_npc_with_a_draft(tmp_path, monkeypatch):
    root = _drafted(tmp_path, monkeypatch)
    rc, so, _ = run_cli(_args(root, "npc-compose"))
    assert rc == 0 and so.count("composed") == 1 and "Jimjar" in so


def test_cli_refusals(tmp_path, monkeypatch):
    root = _drafted(tmp_path, monkeypatch)
    rc, _, err = run_cli(_args(root, "npc-compose", "--name", "Spider"))      # no draft, no authored file
    assert rc == 2 and "neither a draft dossier nor an authored file" in err
    rc, _, err = run_cli(_args(root, "npc-compose", "--name", "Nobody"))
    assert rc == 2
    d = root / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Wrong\n")
    rc, _, err = run_cli(_args(root, "npc-compose"))
    assert rc == 2 and "does not match" in err


def test_cli_init_creates_and_never_overwrites(tmp_path, monkeypatch):
    root = _drafted(tmp_path, monkeypatch)
    f = root / "docs/npcs/authored/jimjar.authored.yaml"
    rc, so, _ = run_cli(_args(root, "npc-compose", "--init", "Jimjar"))
    assert rc == 0 and f.is_file() and "subject: Jimjar" in f.read_text()
    f.write_text("subject: Jimjar\nmanual: [mine]\n")
    before = f.read_bytes()
    rc, _, err = run_cli(_args(root, "npc-compose", "--init", "Jimjar"))
    assert rc == 2 and "already exists" in err and f.read_bytes() == before
    assert not (root / OUT / "gm/npc_spider.md").exists()                      # --init composes nothing
    rc, _, err = run_cli(_args(root, "npc-compose", "--init", "Not An Npc"))
    assert rc == 2
