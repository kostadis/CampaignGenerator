"""``summary_native npc-publish`` through the CLI: exit codes and output lines (spec 032 T043)."""

from __future__ import annotations

import pytest

from pipelines.summary_native import npc_draft, npc_publish, synth
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli

OUT = "docs/npcs/summary_native/ch002-006"
GOOD = "ok [ch 002 / 002.01]"


def _args(root, cmd, *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"), "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


def _body(cite):
    return "\n".join(f"{h}\n\n- ok [ch {cite}]\n" for h in synth.load_outline("npc_dossier"))


@pytest.fixture
def drafted(tmp_path, monkeypatch):
    root = npc_campaign(tmp_path)
    assert run_cli(_args(root, "npc-link"))[0] == 0
    state = {"cite": "002 / 002.01"}
    monkeypatch.setattr(npc_draft, "render_part", lambda *a, **k: _body(state["cite"]))
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    monkeypatch.setattr(npc_publish, "signoff_freshness", lambda *a, **k: npc_publish.SignoffFreshness(True))
    assert run_cli(_args(root, "npc-draft", "--mode", "one-shot", "--name", "Jimjar", "Eldeth Feldrun"))[0] == 0
    return root, state


def test_no_selection_refuses_with_exit_2_and_writes_nothing(drafted):
    root, _ = drafted
    rc, so, err = run_cli(_args(root, "npc-publish"))
    assert rc == 2 and err.startswith("Error:") and not so
    assert not (root / "docs/npcs/jimjar.md").exists()


def test_name_publishes_one_npc_and_prints_its_line(drafted):
    root, _ = drafted
    rc, so, err = run_cli(_args(root, "npc-publish", "--name", "Jimjar"))
    assert rc == 0, err
    assert so.strip() == "Jimjar: published (summary_native)"
    assert (root / "docs/npcs/jimjar.md").read_text().startswith("<!-- published by summary_native npc-publish")
    assert not (root / "docs/npcs/eldeth-feldrun.md").exists()


def test_name_may_repeat_and_all_publishes_every_gm_dossier(drafted):
    root, _ = drafted
    rc, so, _ = run_cli(_args(root, "npc-publish", "--name", "Jimjar", "--name", "Eldeth Feldrun"))
    assert rc == 0 and "Jimjar: published" in so and "Eldeth Feldrun: published" in so
    rc, so, _ = run_cli(_args(root, "npc-publish", "--all"))
    assert rc == 0 and so.count("published (summary_native)") == 2


def test_a_refusal_for_one_npc_exits_2_and_prints_the_reason(drafted):
    root, state = drafted
    state["cite"] = "002 / 002.99"                        # an invalid citation fails verification
    assert run_cli(_args(root, "npc-draft", "--mode", "one-shot", "--name", "Jimjar", "--force"))[0] == 0
    rc, so, _ = run_cli(_args(root, "npc-publish", "--name", "Jimjar", "Eldeth Feldrun"))
    assert rc == 2 and "Jimjar: refused (" in so and "Eldeth Feldrun: published" in so
    assert not (root / "docs/npcs/jimjar.md").exists()
    rc, so, _ = run_cli(_args(root, "npc-publish", "--name", "Jimjar", "--force"))
    assert rc == 2 and "verification failed" in so


def test_an_unknown_source_is_an_argparse_error(drafted):
    root, _ = drafted
    with pytest.raises(SystemExit):
        run_cli(_args(root, "npc-publish", "--name", "Jimjar", "--source", "nonsense"))


def test_publish_log_follows_a_non_default_npc_root_and_hand_edit_detection_still_works(tmp_path, monkeypatch):
    root = npc_campaign(tmp_path)
    monkeypatch.setattr(npc_draft, "render_part", lambda *a, **k: _body("002 / 002.01"))
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    monkeypatch.setattr(npc_publish, "signoff_freshness", lambda *a, **k: npc_publish.SignoffFreshness(True))
    nr = ["--npc-root", "docs/npcs/elsewhere"]
    assert run_cli(_args(root, "npc-link", *nr))[0] == 0
    assert run_cli(_args(root, "npc-draft", *nr, "--mode", "one-shot", "--name", "Jimjar"))[0] == 0
    rc, so, err = run_cli(_args(root, "npc-publish", *nr, "--name", "Jimjar"))
    assert rc == 0, err
    assert (root / "docs/npcs/elsewhere/publish_log.json").is_file()
    assert not (root / "docs/npcs/summary_native/publish_log.json").exists()
    target = root / "docs/npcs/jimjar.md"
    target.write_text(target.read_text() + "\nhand edit\n")
    rc, so, _ = run_cli(_args(root, "npc-publish", *nr, "--name", "Jimjar"))
    assert rc == 2 and "refused" in so
    assert run_cli(_args(root, "npc-publish", *nr, "--name", "Jimjar", "--force"))[0] == 0


def _args_no_dir(root, cmd, *extra):
    return [cmd, "--config", str(root / "config/config.yaml"),
            "--since", str(SINCE), "--until", str(UNTIL), *extra]


def test_publish_defaults_summaries_dir_to_docs_summaries(drafted):
    """#632: no --summaries-dir and no configured one -> the campaign's docs/summaries."""
    root, _ = drafted
    cfg = root / "config" / "grounding.yaml"
    assert not cfg.exists() or "summaries_dir" not in cfg.read_text()
    rc, so, err = run_cli(_args_no_dir(root, "npc-publish", "--name", "Jimjar"))
    assert rc == 0, err
    assert so.strip() == "Jimjar: published (summary_native)"


def test_publish_uses_configured_summaries_dir_over_fallback(drafted):
    """#632: a configured summaries_dir wins over the docs/summaries fallback."""
    root, _ = drafted
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "grounding.yaml").write_text("summary_native:\n  summaries_dir: docs/nowhere\n")
    rc, so, err = run_cli(_args_no_dir(root, "npc-publish", "--name", "Jimjar"))
    assert rc == 2 and "docs/nowhere" in err


def test_publish_names_what_was_tried_when_nothing_resolves(tmp_path):
    """#632: the refusal lists the flag, the config key and the fallback it looked at."""
    root = tmp_path / "bare"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("documents: {}\n")
    rc, so, err = run_cli(["npc-publish", "--config", str(root / "config/config.yaml"), "--all"])
    assert rc == 2
    assert "--summaries-dir" in err and "summaries_dir" in err and "docs/summaries" in err
