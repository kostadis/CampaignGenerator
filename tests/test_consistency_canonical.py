"""Tests for CampaignGenerator#326: consistency-check tools auto-load the
campaign's entity_registry.yaml as an AUTHORITATIVE CANON prompt section,
and --context accumulates across repeats instead of overwriting.

Regression anchor for the Obelisk "Foreput"/"Dawnforge" incident (#117) and
the concrete defect test_provenance_incidents.py::
test_incident_4_the_glossary_is_searchable_at_all documents: "check_consistency
never loads the glossary." This test proves it now does — without anyone
having to remember to pass --context docs/entity_registry.yaml by hand.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_doc import check_consistency, sd_consistency  # noqa: E402

_REGISTRY_YAML = """\
version: 1
campaign: fixture
entities:
  - name: Kalan Strongbranch
    type: npc
    aliases: [Strongbranch, Kalan]
    note: Gatewarden; archmage
distinct:
  - [Ilvara, Sylvira]
rejected_aliases:
  - [Brother Eldin, Constable Eldrin Malavar]
  - [Cult of Talos, Talosians, Talos]
"""


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content)


def _make_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "campaign"
    (campaign_dir / "docs").mkdir(parents=True)
    (campaign_dir / "docs" / "entity_registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
    for _label in ("campaign_state", "world_state"):
        (campaign_dir / "docs" / f"{_label}.md").write_text(f"{_label} fixture.\n", encoding="utf-8")
    (campaign_dir / "config").mkdir()
    (campaign_dir / "config" / "config.yaml").write_text("documents:\n  - {label: campaign_state, path: ../docs/campaign_state.md}\n  - {label: world_state, path: ../docs/world_state.md}\n", encoding="utf-8")
    return campaign_dir


def test_check_consistency_auto_loads_registry_as_canon(tmp_path, monkeypatch):
    campaign_dir = _make_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Kalan Stormbranch showed up.", encoding="utf-8")

    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append({"system": system, "user": user})
        return "No issues found."

    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream_api)
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config" / "config.yaml"),
    ])

    check_consistency.main()

    assert len(calls) == 1
    user_prompt = _content_text(calls[0]["user"])
    assert "AUTHORITATIVE CANON" in user_prompt
    assert "Kalan Strongbranch" in user_prompt
    assert "Ilvara" in user_prompt and "Sylvira" in user_prompt  # distinct pair rendered
    assert "## Rejected aliases (settled negatives; do not re-propose)" in user_prompt
    assert (
        "**Brother Eldin** is NOT an alias of **Constable Eldrin Malavar**"
        in user_prompt
    )
    # import-dedup writes a rejected cluster as one group of 3+ names
    assert (
        "None of **Cult of Talos**, **Talosians**, **Talos** is an alias of another"
        in user_prompt
    )

    system_prompt = calls[0]["system"]
    assert "canon wins" in system_prompt.lower()


def test_check_consistency_context_accumulates_across_repeats(tmp_path, monkeypatch):
    """The #117 companion bug: repeated --context flags must not overwrite."""
    campaign_dir = _make_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    ctx_a = tmp_path / "a.md"
    ctx_a.write_text("Context A content.", encoding="utf-8")
    ctx_b = tmp_path / "b.md"
    ctx_b.write_text("Context B content.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config" / "config.yaml"),
        "--context", str(ctx_a),
        "--context", str(ctx_b),
    ])

    check_consistency.main()

    prompt = _content_text(calls[0])
    assert "Context A content." in prompt
    assert "Context B content." in prompt


def test_check_consistency_skips_auto_loaded_registry_context(
    tmp_path, monkeypatch, capsys
):
    campaign_dir = _make_campaign(tmp_path)
    registry = campaign_dir / "docs" / "entity_registry.yaml"
    registry_link = tmp_path / "registry-link.yaml"
    registry_link.symlink_to(registry)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config" / "config.yaml"),
        "--context", str(registry_link),
    ])

    check_consistency.main()

    prompt = _content_text(calls[0])
    assert prompt.count("AUTHORITATIVE CANON") == 1
    assert "version: 1" not in prompt
    stderr = capsys.readouterr().err
    assert str(registry_link) in stderr
    assert "already included as authoritative canon" in stderr


def _no_registry_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "campaign_no_registry"
    (campaign_dir / "config").mkdir(parents=True)
    (campaign_dir / "docs").mkdir()
    for _label in ("campaign_state", "world_state"):
        (campaign_dir / "docs" / f"{_label}.md").write_text(f"{_label} fixture.\n", encoding="utf-8")
    (campaign_dir / "config" / "config.yaml").write_text("documents:\n  - {label: campaign_state, path: ../docs/campaign_state.md}\n  - {label: world_state, path: ../docs/world_state.md}\n", encoding="utf-8")
    return campaign_dir


def test_check_consistency_no_registry_refuses_before_model_call(tmp_path, monkeypatch, capsys):
    """A check without canon reads as complete and is not, so a campaign with
    no docs/entity_registry.yaml is an error, never a silently skipped section."""
    campaign_dir = _no_registry_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    ctx = tmp_path / "party.md"
    ctx.write_text("Party roster.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config" / "config.yaml"),
        "--context", str(ctx),
    ])

    with pytest.raises(SystemExit) as exc:
        check_consistency.main()

    assert exc.value.code == 1
    assert calls == []
    assert "no entity registry" in capsys.readouterr().err


def test_check_consistency_registry_via_context_does_not_substitute(tmp_path, monkeypatch):
    """Passing a registry file through --context does not stand in for the
    campaign's own docs/entity_registry.yaml."""
    campaign_dir = _no_registry_campaign(tmp_path)
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    explicit_registry = tmp_path / "entity_registry.yaml"
    explicit_registry.write_text(_REGISTRY_YAML, encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path),
        "--config", str(campaign_dir / "config" / "config.yaml"),
        "--context", str(explicit_registry),
    ])

    with pytest.raises(SystemExit):
        check_consistency.main()
    assert calls == []


@pytest.mark.parametrize("layout", ["root_only", "root_and_config_dir"])
def test_check_consistency_rejects_misplaced_config(tmp_path, monkeypatch, capsys, layout):
    """<campaign>/config/config.yaml is the only valid location; a root
    config.yaml is an error even when a correct config/config.yaml exists."""
    campaign_dir = _make_campaign(tmp_path)
    root_config = campaign_dir / "config.yaml"
    root_config.write_text("documents: []\n", encoding="utf-8")
    if layout == "root_only":
        (campaign_dir / "config" / "config.yaml").unlink()
        config_arg = root_config
    else:
        config_arg = campaign_dir / "config" / "config.yaml"
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", [
        "check_consistency", str(doc_path), "--config", str(config_arg),
    ])

    with pytest.raises(SystemExit) as exc:
        check_consistency.main()

    assert exc.value.code == 2
    assert calls == []
    assert "misplaced config" in capsys.readouterr().err


def test_sd_consistency_auto_loads_registry_as_canon(tmp_path, monkeypatch):
    campaign_dir = _make_campaign(tmp_path)
    recap_path = campaign_dir / "session-summary.md"
    recap_path.write_text("Kalan Stormbranch showed up.", encoding="utf-8")
    ctx = campaign_dir / "docs" / "campaign_state.md"
    ctx.write_text("Campaign state.", encoding="utf-8")
    out_path = campaign_dir / "consistency_report.md"

    calls = []
    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        sd_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.chdir(campaign_dir)
    monkeypatch.setattr(sys, "argv", [
        "sd_consistency", str(recap_path),
        "--context", str(ctx),
        "--out", str(out_path),
    ])

    sd_consistency.main()

    assert len(calls) == 1
    prompt = _content_text(calls[0])
    assert "AUTHORITATIVE CANON" in prompt
    assert "Kalan Strongbranch" in prompt


def test_sd_consistency_skips_auto_loaded_registry_context(
    tmp_path, monkeypatch, capsys
):
    campaign_dir = _make_campaign(tmp_path)
    registry = campaign_dir / "docs" / "entity_registry.yaml"
    registry_link = tmp_path / "registry-link.yaml"
    registry_link.symlink_to(registry)
    recap_path = campaign_dir / "session-summary.md"
    recap_path.write_text("Narration.", encoding="utf-8")
    out_path = campaign_dir / "consistency_report.md"

    calls = []
    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        sd_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.chdir(campaign_dir)
    monkeypatch.setattr(sys, "argv", [
        "sd_consistency", str(recap_path),
        "--context", str(registry_link),
        "--out", str(out_path),
    ])

    sd_consistency.main()

    prompt = _content_text(calls[0])
    assert prompt.count("AUTHORITATIVE CANON") == 1
    assert "version: 1" not in prompt
    stderr = capsys.readouterr().err
    assert str(registry_link) in stderr
    assert "already included as authoritative canon" in stderr


def test_sd_consistency_explicit_registry_remains_when_not_auto_loaded(
    tmp_path, monkeypatch
):
    campaign_dir = tmp_path / "campaign_no_registry"
    campaign_dir.mkdir()
    recap_path = campaign_dir / "session-summary.md"
    recap_path.write_text("Narration.", encoding="utf-8")
    explicit_registry = tmp_path / "entity_registry.yaml"
    explicit_registry.write_text(_REGISTRY_YAML, encoding="utf-8")
    out_path = campaign_dir / "consistency_report.md"

    calls = []
    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        sd_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.chdir(campaign_dir)
    monkeypatch.setattr(sys, "argv", [
        "sd_consistency", str(recap_path),
        "--context", str(explicit_registry),
        "--out", str(out_path),
    ])

    sd_consistency.main()

    prompt = _content_text(calls[0])
    assert "AUTHORITATIVE CANON" not in prompt
    assert "version: 1" in prompt


@pytest.mark.parametrize(
    "config_text, extra_context, expected",
    [
        ("documents:\n  - {label: world_state, path: ../docs/world_state.md}\n",
         None, "'campaign_state' is not in"),
        ("documents:\n  - {label: campaign_state, path: ''}\n"
         "  - {label: world_state, path: ../docs/world_state.md}\n",
         None, "'campaign_state' has no path in"),
        (None, "missing-context.md", "context file not found: "),
    ],
    ids=["label_absent", "empty_path", "context_missing"],
)
def test_check_consistency_missing_input_refuses_before_model_call(
    tmp_path, monkeypatch, capsys, config_text, extra_context, expected
):
    """A skipped grounding doc or context file yields a report that looks
    complete and is not, so every missing input is fatal before the model call."""
    campaign_dir = _make_campaign(tmp_path)
    config = campaign_dir / "config" / "config.yaml"
    if config_text is not None:
        config.write_text(config_text, encoding="utf-8")
    doc_path = campaign_dir / "session-doc.md"
    doc_path.write_text("Narration.", encoding="utf-8")
    argv = ["check_consistency", str(doc_path), "--config", str(config)]
    if extra_context:
        argv += ["--context", str(tmp_path / extra_context)]

    calls = []
    monkeypatch.setattr(check_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        check_consistency, "stream_api",
        lambda client, system, user, model, **kw: calls.append(user) or "No issues found.",
    )
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        check_consistency.main()

    assert exc.value.code == 1
    assert calls == []
    assert expected in capsys.readouterr().err
