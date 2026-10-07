"""npc_authored: the one reader of docs/npcs/authored/ (spec 032 T009)."""

from __future__ import annotations

import pytest

from pipelines.summary_native import npc_authored as na

GOOD = (
    "subject: Jimjar\n"
    "manual:\n"
    "  - Jimjar is a deep gnome, not a drow.\n"
    "  - He has a standing bet with Eldeth.\n"
    "secrets: |\n"
    "  Owes 400 gp to a fence.\n"
)


def _write(tmp_path, body, name="jimjar.authored.yaml"):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_load_manual_is_numbered_by_position(tmp_path):
    p = _write(tmp_path, GOOD)
    assert na.load_manual(p, "Jimjar") == [
        "Jimjar is a deep gnome, not a drow.",
        "He has a standing bet with Eldeth.",
    ]


def test_load_manual_never_returns_secrets(tmp_path):
    out = na.load_manual(_write(tmp_path, GOOD), "Jimjar")
    assert not any("400 gp" in m for m in out)


def test_load_secrets_is_byte_exact(tmp_path):
    assert na.load_secrets(_write(tmp_path, GOOD), "Jimjar") == "Owes 400 gp to a fence.\n"


def test_missing_file_means_nothing_authored(tmp_path):
    p = tmp_path / "nobody.authored.yaml"
    assert na.load_manual(p, "Nobody") == [] and na.load_secrets(p, "Nobody") == ""


def test_manual_and_secrets_are_optional(tmp_path):
    p = _write(tmp_path, "subject: Jimjar\n")
    assert na.load_manual(p, "Jimjar") == [] and na.load_secrets(p, "Jimjar") == ""


def test_subject_mismatch_refused(tmp_path):
    with pytest.raises(na.AuthoredError, match="does not match"):
        na.load_manual(_write(tmp_path, GOOD), "Eldeth")


@pytest.mark.parametrize(
    "body,msg",
    [
        ("manual: [a]\n", "subject is required"),
        ("subject: Jimjar\nnotes: x\n", "unknown key"),
        ("subject: Jimjar\nmanual: just a string\n", "must be a list"),
        ("subject: Jimjar\nmanual: [a, '', c]\n", "manual item 2"),
        ("subject: Jimjar\nmanual: [a, 3]\n", "manual item 2"),
        ("subject: Jimjar\nsecrets: [a]\n", "secrets must be a string"),
        ("- just\n- a list\n", "must be a mapping"),
    ],
)
def test_strict_validation(tmp_path, body, msg):
    with pytest.raises(na.AuthoredError, match=msg):
        na.load_manual(_write(tmp_path, body), "Jimjar")


def test_secrets_validated_even_when_only_manual_is_read(tmp_path):
    with pytest.raises(na.AuthoredError):
        na.load_manual(_write(tmp_path, "subject: Jimjar\nsecrets: [a]\n"), "Jimjar")


def test_yaml_error_does_not_echo_file_content(tmp_path):
    p = _write(tmp_path, "subject: Jimjar\nsecrets: SECRET-CANARY: : [unclosed\n")
    with pytest.raises(na.AuthoredError) as e:
        na.load_manual(p, "Jimjar")
    assert "SECRET-CANARY" not in str(e.value) and "not valid YAML" in str(e.value)


def test_unknown_key_error_names_keys_not_values(tmp_path):
    p = _write(tmp_path, "subject: Jimjar\nextra: SECRET-CANARY\n")
    with pytest.raises(na.AuthoredError) as e:
        na.load_manual(p, "Jimjar")
    assert "SECRET-CANARY" not in str(e.value)


def test_read_handbuilt_is_verbatim(tmp_path):
    p = _write(tmp_path, "# Eelrich Vane\n\n  odd   spacing\n", name="eelrich-vane.md")
    assert na.read_handbuilt(p) == "# Eelrich Vane\n\n  odd   spacing\n"


def test_read_handbuilt_missing_refused(tmp_path):
    with pytest.raises(na.AuthoredError, match="no hand-built dossier"):
        na.read_handbuilt(tmp_path / "nope.md")


def test_init_creates_a_loadable_empty_file(tmp_path):
    p = tmp_path / "authored" / "jimjar.authored.yaml"
    na.init_authored(p, "Jimjar")
    assert na.load_manual(p, "Jimjar") == [] and na.load_secrets(p, "Jimjar") == ""


def test_init_refuses_when_the_file_exists_and_leaves_it_alone(tmp_path):
    p = _write(tmp_path, GOOD)
    with pytest.raises(na.AuthoredError, match="already exists"):
        na.init_authored(p, "Jimjar")
    assert p.read_text() == GOOD


def test_init_quotes_an_awkward_subject(tmp_path):
    p = tmp_path / "x.authored.yaml"
    na.init_authored(p, "Sarith: the Elder")
    assert na.load_manual(p, "Sarith: the Elder") == []
