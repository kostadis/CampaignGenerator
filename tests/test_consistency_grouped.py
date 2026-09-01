"""Grouped multi-document consistency checks for Stage 2 batch review."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from campaignlib.consistency import (
    ConsistencyDocument,
    GroupedConsistencyProtocolError,
    normalize_grouped_response,
    render_grouped_prompt,
)
from session_doc import check_consistency


def _documents() -> list[ConsistencyDocument]:
    return [
        ConsistencyDocument("D01", Path("scenes/01_arrival.md"), "Arrival text."),
        ConsistencyDocument("D02", Path("scenes/02_departure.md"), "Departure text."),
    ]


def _valid_response() -> str:
    return """\
<<<CG-CHECK D01 BEGIN>>>
**Location**: quote block 2
**Target text**: Arrival text.
**Issue**: The speaker name conflicts with canon.
**Evidence**: AUTHORITATIVE CANON names the speaker Aria.
**Suggested fix**: Correct the speaker label.
<<<CG-CHECK D01 END>>>

<<<CG-CHECK D02 BEGIN>>>
CLEAN
<<<CG-CHECK D02 END>>>

<<<CG-CROSS BEGIN>>>
CLEAN
<<<CG-CROSS END>>>
"""


def test_render_grouped_prompt_contains_each_target_once_and_context_once():
    prompt = render_grouped_prompt(_documents(), ["Canon exact.", "Party exact."])

    assert prompt.count("Arrival text.") == 1
    assert prompt.count("Departure text.") == 1
    assert prompt.count("Canon exact.") == 1
    assert prompt.count("Party exact.") == 1
    assert "D01" in prompt and "scenes/01_arrival.md" in prompt
    assert "peer targets" in prompt


def test_render_grouped_prompt_adds_only_matching_glossary_anchors():
    documents = [
        ConsistencyDocument(
            "D01",
            Path("scenes/01_arrival.md"),
            "Oral and Vance meets Aria.",
        ),
        ConsistencyDocument(
            "D02",
            Path("scenes/02_departure.md"),
            "A clean departure.",
        ),
    ]
    context = [
        "## transcription_corrections.md\n\n"
        "| Wrong | Right |\n"
        "|---|---|\n"
        "| Oral and Vance, Mark Gordon | **Aurelan Vance** |\n"
        "| Summa | **Soma** |"
    ]

    prompt = render_grouped_prompt(documents, context)

    assert prompt.count("`Oral and Vance` → **Aurelan Vance**") == 1
    assert "`Mark Gordon` →" not in prompt
    assert prompt.count("| Oral and Vance, Mark Gordon | **Aurelan Vance** |") == 1
    assert "`Summa` →" not in prompt


def test_normalize_grouped_response_maps_ids_to_paths_and_counts_findings():
    result = normalize_grouped_response(_valid_response(), _documents())

    assert result.issue_count == 1
    assert "# Grouped Consistency Report" in result.report
    assert "## D01 — `scenes/01_arrival.md`" in result.report
    assert "## D02 — `scenes/02_departure.md`" in result.report
    assert "## Cross-document findings" in result.report
    assert "<<<CG-" not in result.report


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_valid_response().replace("D02 BEGIN", "D03 BEGIN"), "unknown section"),
        (_valid_response().replace("<<<CG-CROSS BEGIN>>>", "<<<CG-CHECK D01 BEGIN>>>"), "duplicate section"),
        (_valid_response().replace("<<<CG-CHECK D02 BEGIN>>>\nCLEAN\n<<<CG-CHECK D02 END>>>\n\n", ""), "missing section"),
        (_valid_response().replace("CLEAN\n<<<CG-CHECK D02 END>>>", "<<<CG-CROSS BEGIN>>>\nCLEAN\n<<<CG-CROSS END>>>\n<<<CG-CHECK D02 END>>>"), "nested section"),
        ("Preamble that must not be accepted.\n" + _valid_response(), "outside section"),
        (_valid_response().replace("<<<CG-CHECK D02 BEGIN>>>\nCLEAN", "<<<CG-CHECK D02 BEGIN>>>\n"), "empty section"),
        (_valid_response().replace("<<<CG-CHECK D02 BEGIN>>>", "<<<CG-CHECK D02 START>>>"), "malformed marker"),
    ],
)
def test_grouped_protocol_fails_closed(response, message):
    with pytest.raises(GroupedConsistencyProtocolError, match=message):
        normalize_grouped_response(response, _documents())


def test_grouped_protocol_requires_complete_fields_for_every_finding():
    response = _valid_response().replace(
        "**Suggested fix**: Correct the speaker label.",
        "**Suggested fix**: Correct the speaker label.\n\n"
        "**Location**: quote block 4\n"
        "**Target text**: Arrival text.\n"
        "**Issue**: A second mismatch.\n"
        "**Evidence**: The transcript disagrees.",
    )

    with pytest.raises(GroupedConsistencyProtocolError, match="per finding"):
        normalize_grouped_response(response, _documents())


def test_grouped_protocol_rejects_finding_excerpt_from_another_target():
    response = _valid_response().replace(
        "**Target text**: Arrival text.",
        "**Target text**: Departure text.",
    )

    with pytest.raises(GroupedConsistencyProtocolError, match="not found verbatim"):
        normalize_grouped_response(response, _documents())


def _campaign(tmp_path: Path) -> tuple[list[Path], Path, Path, Path]:
    campaign = tmp_path / "campaign"
    docs_dir = campaign / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "entity_registry.yaml").write_text(
        "version: 1\ncampaign: fixture\nentities:\n  - name: Exact Canon\n    type: npc\n",
        encoding="utf-8",
    )
    config = campaign / "config.yaml"
    config.write_text("documents: []\n", encoding="utf-8")
    scene_a = campaign / "01_arrival.md"
    scene_b = campaign / "02_departure.md"
    scene_a.write_text("Arrival target.", encoding="utf-8")
    scene_b.write_text("Departure target.", encoding="utf-8")
    context = campaign / "prep.md"
    context.write_text("Shared prep evidence.", encoding="utf-8")
    return [scene_a, scene_b], context, config, campaign


def test_grouped_cli_uses_one_call_and_writes_one_normalized_report(
    tmp_path, monkeypatch, capsys
):
    scenes, context, config, _campaign_dir = _campaign(tmp_path)
    output = tmp_path / "grouped-report.md"
    calls = []

    def fake_stream(client, system, user, model, **kwargs):
        calls.append((system, user, model, kwargs))
        return _valid_response().replace("Arrival text.", "Arrival target.")

    monkeypatch.setattr(check_consistency, "client_from_args", lambda args: object())
    monkeypatch.setattr(check_consistency, "stream_api", fake_stream)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_consistency",
            str(scenes[0]),
            str(scenes[1]),
            "--config",
            str(config),
            "--context",
            str(context),
            "--backend",
            "codex-cli",
            "--output",
            str(output),
        ],
    )

    check_consistency.main()

    assert len(calls) == 1
    system, user, _model, _kwargs = calls[0]
    assert "several peer" in system and "session documents" in system
    assert user.count("Shared prep evidence.") == 1
    assert user.count("Arrival target.") == 1
    assert user.count("Departure target.") == 1
    assert output.read_text(encoding="utf-8").startswith("# Grouped Consistency Report")
    stdout = capsys.readouterr().out
    assert "Documents : 2" in stdout
    assert "Model calls: 1" in stdout
    assert "model_calls=1 shared_context_chars=" in stdout
    assert "Found 1 potential issue" in stdout


def test_grouped_cli_protocol_failure_preserves_existing_report(
    tmp_path, monkeypatch, capsys
):
    scenes, context, config, _campaign_dir = _campaign(tmp_path)
    output = tmp_path / "grouped-report.md"
    output.write_text("previous valid report", encoding="utf-8")
    monkeypatch.setattr(check_consistency, "client_from_args", lambda args: object())
    monkeypatch.setattr(check_consistency, "stream_api", lambda *a, **k: "truncated")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_consistency",
            str(scenes[0]),
            str(scenes[1]),
            "--config",
            str(config),
            "--context",
            str(context),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        check_consistency.main()

    assert excinfo.value.code == 1
    assert "invalid grouped consistency response" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "previous valid report"


def test_grouped_cli_rejects_duplicate_document_before_model_call(
    tmp_path, monkeypatch, capsys
):
    scenes, context, config, _campaign_dir = _campaign(tmp_path)
    monkeypatch.setattr(
        check_consistency,
        "client_from_args",
        lambda args: (_ for _ in ()).throw(AssertionError("model client constructed")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_consistency",
            str(scenes[0]),
            str(scenes[0]),
            "--config",
            str(config),
            "--context",
            str(context),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        check_consistency.main()

    assert excinfo.value.code == 1
    assert "duplicate document" in capsys.readouterr().err
