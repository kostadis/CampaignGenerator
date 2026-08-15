"""Tests for dnd_sheet.py's --batch wiring (feature 004-claude-api-batch).

dnd_sheet's docstring says "no vision required": pdf_to_markdown extracts
plain text via PyMuPDF and sends it to Claude as a string, not a multimodal
content-block list (despite stale docs elsewhere describing a vision path).
These tests assert that exact string is what reaches run_single_batch's
`user` param, mirroring what call_api receives on the non-batch path.
extract_text (the actual PyMuPDF call) is monkeypatched out — these tests
are about the --batch routing, not PDF parsing.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.content_ingest import dnd_sheet  # noqa: E402


class FakeCallAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, content, model, *args, **kwargs):
        self.calls.append({"system": system, "content": content, "model": model,
                           "kwargs": kwargs})
        return "# Test Character\n"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "# Test Character (batched)\n"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_extract_text(monkeypatch):
    monkeypatch.setattr(dnd_sheet, "extract_text", lambda pdf_path: "RAW SHEET TEXT")


@pytest.fixture
def fake_call_api(monkeypatch, fake_extract_text):
    fake = FakeCallAPI()
    monkeypatch.setattr(dnd_sheet, "call_api", fake)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch, fake_extract_text):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(dnd_sheet, "run_single_batch", fake)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_pdf_stub(tmp_path: Path) -> Path:
    # extract_text is monkeypatched out, so this file's contents never matter —
    # only its existence (main()'s pre-flight check) does.
    p = tmp_path / "soma.pdf"
    p.write_bytes(b"not a real pdf")
    return p


def test_default_path_uses_call_api_unchanged(monkeypatch, fake_call_api, tmp_path):
    """FR-011: no --batch => call_api called with the plain extracted-text
    string as `content`, no explicit max_tokens (its own 8096 default) —
    exactly as before this feature."""
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir),
    ])
    dnd_sheet.main()

    assert len(fake_call_api.calls) == 1
    call = fake_call_api.calls[0]
    assert "RAW SHEET TEXT" in call["content"]
    assert isinstance(call["content"], str)
    assert "max_tokens" not in call["kwargs"]
    assert (out_dir / "soma.md").exists()


def test_batch_flag_passes_same_string_payload_as_user(
    monkeypatch, fake_run_single_batch, tmp_path
):
    """The content-block-or-string payload built for call_api's `content` must
    reach run_single_batch unchanged as `user` — today that payload is a
    plain string (PyMuPDF text extraction), not a vision content-block list."""
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir), "--batch",
    ])
    dnd_sheet.main()

    assert len(fake_run_single_batch.calls) == 1
    call = fake_run_single_batch.calls[0]
    assert isinstance(call["user"], str)
    assert "RAW SHEET TEXT" in call["user"]
    assert call["max_tokens"] == 8096  # mirrors call_api's own default
    assert (out_dir / "soma.md").read_text(encoding="utf-8").startswith("# Test Character (batched)")


def test_batch_failure_exits_nonzero(monkeypatch, fake_extract_text, tmp_path, capsys):
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(dnd_sheet, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir), "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        dnd_sheet.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err


# ══ Feature 008: roster-named sheets & level archival ══════════════════════
#
# The converter is stubbed out entirely in this block (no API call, no PDF
# parsing) — what is under test is the orchestration around it: attribution,
# where the file lands, what is refused, and what a refusal leaves on disk.

import textwrap  # noqa: E402


def _sheet_markdown(name: str, player: str = "Kostadis",
                    class_level: str = "Druid 6", frontmatter: bool = True) -> str:
    """What the model returns for one character — the two identity channels."""
    body = textwrap.dedent(f"""\
        # {name}

        ## Identity
        - **Class & Level:** {class_level}
        - **Species:** Human
        - **Player:** {player}

        ## Combat
        - **HP:** 40
        """)
    if not frontmatter:
        return body
    return textwrap.dedent(f"""\
        ---
        name: {name}
        player: {player}
        species: Human
        class_level: {class_level}
        subclass: ""
        ---
        """) + body


def _campaign(tmp_path: Path, roster_yaml: str) -> Path:
    """A campaign tree shaped like Phandalin's: config/ beside docs/party/."""
    (tmp_path / "config").mkdir()
    (tmp_path / "docs" / "party").mkdir(parents=True)
    (tmp_path / "config" / "party.yaml").write_text(
        textwrap.dedent(roster_yaml), encoding="utf-8"
    )
    return tmp_path


PHANDALIN_ROSTER = """\
    characters:
    - name: Soma
      sheet: docs/party/Soma.md
    - name: Brewbarry
      sheet: docs/party/Brewbarry.md
"""


@pytest.fixture
def stub_convert(monkeypatch):
    """Replace the whole API round trip; record which PDFs reached it."""
    seen: list[str] = []

    def _convert(client, pdf_path, model, batch=False):
        seen.append(pdf_path.stem)
        return _sheet_markdown(pdf_path.stem)

    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown", _convert)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    return seen


def _pdf(tmp_path: Path, stem: str) -> Path:
    p = tmp_path / f"{stem}.pdf"
    p.write_bytes(b"not a real pdf")
    return p


def _run(monkeypatch, campaign: Path, *argv: str) -> None:
    monkeypatch.chdir(campaign)
    monkeypatch.setattr(sys, "argv", ["dnd_sheet.py", *argv])
    dnd_sheet.main()


# ── User story 2: roster naming ────────────────────────────────────────────

def test_roster_mode_writes_to_the_roster_path(monkeypatch, stub_convert,
                                               tmp_path, capsys):
    """FR-005/FR-002b: the roster names the file, and the run says which entry
    it matched."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    written = campaign / "docs" / "party" / "Soma.md"
    assert written.read_text(encoding="utf-8").startswith("---")
    assert not (campaign / "doc").exists()  # nothing landed in the legacy dir
    err = capsys.readouterr().err
    assert "Matched roster entry: Soma" in err
    assert str(written) in err


def test_output_filename_ignores_the_pdf_name(monkeypatch, tmp_path):
    """A D&D Beyond export is called Soma-4271883.pdf; the sheet is Soma.md."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = tmp_path / "Soma-4271883.pdf"
    pdf.write_bytes(b"not a real pdf")
    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown",
                        lambda *a, **kw: _sheet_markdown("Soma"))
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert (campaign / "docs" / "party" / "Soma.md").exists()
    assert not (campaign / "docs" / "party" / "Soma-4271883.md").exists()


def test_unattributable_pdf_writes_nothing_and_exits_1(monkeypatch, tmp_path,
                                                       capsys):
    """FR-003/FR-003a — the live Phandalin case: the sheet titles itself
    'Valphine Sotorra', the roster says 'Valphine'."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Valphine")
    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown",
                        lambda *a, **kw: _sheet_markdown("Valphine Sotorra"))
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert exc.value.code == 1
    assert list((campaign / "docs" / "party").iterdir()) == []
    err = capsys.readouterr().err
    assert "REFUSED Valphine.pdf" in err
    assert '"Valphine Sotorra"' in err          # what the sheet said
    assert "Brewbarry, Soma" in err             # what it could have meant
    assert "config/party.yaml" in err           # which file to fix
    assert "Nothing was written or moved." in err


def test_roster_filename_mismatch_prints_the_replacement_line(monkeypatch,
                                                              stub_convert,
                                                              tmp_path, capsys):
    """FR-006/D6: refuse, and hand back a line that can be pasted into the
    roster — never edit party.yaml on the GM's behalf."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Soma
          sheet: docs/party/soma.md
    """)
    original = (campaign / "config" / "party.yaml").read_text(encoding="utf-8")
    pdf = _pdf(tmp_path, "Soma")

    with pytest.raises(SystemExit):
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    err = capsys.readouterr().err
    assert "sheet: docs/party/soma.md" in err
    assert "sheet: docs/party/Soma.md" in err
    assert list((campaign / "docs" / "party").iterdir()) == []
    # The roster is hand-authored; this tool never writes to it.
    assert (campaign / "config" / "party.yaml").read_text(encoding="utf-8") == original


def test_missing_sheet_directory_refuses_instead_of_creating_it(monkeypatch,
                                                                stub_convert,
                                                                tmp_path, capsys):
    """Rosters are campaign-root-relative, so running from anywhere else
    resolves the sheet directory outside the campaign. Refuse rather than
    create a stray tree and write a character sheet into it."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Soma
          sheet: ../docs/party/Soma.md
    """)
    pdf = _pdf(tmp_path, "Soma")

    with pytest.raises(SystemExit):
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert not (tmp_path.parent / "docs").exists()
    assert "does not exist" in capsys.readouterr().err


def test_one_refusal_does_not_stop_the_other_pdfs(monkeypatch, tmp_path, capsys):
    """FR-004: three PDFs, one unattributable — the other two still land."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdfs = [_pdf(tmp_path, s) for s in ("Soma", "Nobody", "Brewbarry")]
    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown",
                        lambda client, pdf_path, model, batch=False:
                        _sheet_markdown(pdf_path.stem))
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, campaign, *[str(p) for p in pdfs],
             "--party-config", "config/party.yaml")

    assert exc.value.code == 1
    party = campaign / "docs" / "party"
    assert sorted(p.name for p in party.iterdir()) == ["Brewbarry.md", "Soma.md"]
    assert "REFUSED Nobody.pdf" in capsys.readouterr().err


# ── User story 1: archival ─────────────────────────────────────────────────

def _existing_sheet(campaign: Path, name: str, class_level: str) -> Path:
    p = campaign / "docs" / "party" / f"{name}.md"
    p.write_text(_sheet_markdown(name, class_level=class_level, frontmatter=False),
                 encoding="utf-8")
    return p


def test_level_up_round_trip(monkeypatch, stub_convert, tmp_path, capsys):
    """FR-011/FR-012/FR-016: the level-5 sheet is retrievable at its archive
    path, the new one is at the roster's path, and the run says both."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    old = _existing_sheet(campaign, "Soma", "Druid 5")
    old_text = old.read_text(encoding="utf-8")
    pdf = _pdf(tmp_path, "Soma")

    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    archived = campaign / "docs" / "party" / "old" / "level" / "5" / "Soma.md"
    assert archived.read_text(encoding="utf-8") == old_text
    assert old.exists()                                   # the new sheet is here
    assert old.read_text(encoding="utf-8") != old_text     # and it is the new one
    err = capsys.readouterr().err
    assert f"Archived: {old} -> {archived}  (level 5)" in err


def test_rerunning_the_same_conversion_refuses_rather_than_overwriting(
    monkeypatch, stub_convert, tmp_path, capsys
):
    """FR-014. The second run must not quietly destroy what the first archived."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    _existing_sheet(campaign, "Soma", "Druid 5")
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    archived = campaign / "docs" / "party" / "old" / "level" / "5" / "Soma.md"
    # The sheet just written records Druid 6, so a re-run wants level 6 — force
    # the collision by putting the level back where it was.
    _existing_sheet(campaign, "Soma", "Druid 5")
    kept = archived.read_text(encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert exc.value.code == 1
    assert archived.read_text(encoding="utf-8") == kept
    assert "already exists" in capsys.readouterr().err


def test_multiclass_sheet_refuses_and_moves_nothing(monkeypatch, stub_convert,
                                                    tmp_path, capsys):
    """FR-013: the archive is keyed by one level; picking one out of two is
    inventing precision the source lacks."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    old = _existing_sheet(campaign, "Soma", "Fighter 9 / Bard 2")
    old_text = old.read_text(encoding="utf-8")
    pdf = _pdf(tmp_path, "Soma")

    with pytest.raises(SystemExit):
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert old.read_text(encoding="utf-8") == old_text
    assert not (campaign / "docs" / "party" / "old").exists()
    assert '"Fighter 9 / Bard 2"' in capsys.readouterr().err


def test_nothing_is_touched_before_the_api_call_returns(monkeypatch, tmp_path):
    """FR-015/D7 — the crash-safety guarantee, stated as a test: with the
    converter failing, the character must still have their sheet and no
    archive directory may exist. This is why no rollback path is needed."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    old = _existing_sheet(campaign, "Soma", "Druid 5")
    old_text = old.read_text(encoding="utf-8")
    pdf = _pdf(tmp_path, "Soma")

    def _boom(*a, **kw):
        raise RuntimeError("the API call died mid-run")

    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown", _boom)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)

    with pytest.raises(RuntimeError):
        _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert old.read_text(encoding="utf-8") == old_text
    assert not (campaign / "docs" / "party" / "old").exists()


# ── User story 3: the player behind the character ──────────────────────────

ROSTER_WITH_PLAYER = """\
    characters:
    - name: Soma
      sheet: docs/party/Soma.md
      player: Wade
"""


def test_roster_player_replaces_the_downloaders_name(monkeypatch, stub_convert,
                                                     tmp_path, capsys):
    """FR-008: the stub converter stamps 'Kostadis' into every sheet, exactly
    as a D&D Beyond download does — that is the GM, not the player."""
    campaign = _campaign(tmp_path, ROSTER_WITH_PLAYER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    written = (campaign / "docs" / "party" / "Soma.md").read_text(encoding="utf-8")
    assert "player: Wade" in written
    assert "- **Player:** Wade" in written
    assert "Kostadis" not in written
    assert "Player: Kostadis -> Wade  (from party.yaml)" in capsys.readouterr().err


def test_the_substitution_does_not_revert_on_a_second_conversion(monkeypatch,
                                                                 stub_convert,
                                                                 tmp_path):
    campaign = _campaign(tmp_path, ROSTER_WITH_PLAYER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")
    # Bump the level so the second run has a free archive slot.
    sheet = campaign / "docs" / "party" / "Soma.md"
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("Druid 6", "Druid 5"),
                     encoding="utf-8")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    assert "Kostadis" not in sheet.read_text(encoding="utf-8")
    archived = campaign / "docs" / "party" / "old" / "level" / "5" / "Soma.md"
    assert "player: Wade" in archived.read_text(encoding="utf-8")


def test_a_ragged_model_response_still_rewrites_both_channels(monkeypatch,
                                                              tmp_path):
    """Real model output is not guaranteed to start exactly at `---`. If the
    leading whitespace reached the substitution, the frontmatter would keep the
    downloader's name while the prose showed the roster's — and
    `player_map_from_config` reads the frontmatter."""
    campaign = _campaign(tmp_path, ROSTER_WITH_PLAYER)
    pdf = _pdf(tmp_path, "Soma")
    monkeypatch.setattr(dnd_sheet, "pdf_to_markdown",
                        lambda *a, **kw: "\n\n  " + _sheet_markdown("Soma"))
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    written = (campaign / "docs" / "party" / "Soma.md").read_text(encoding="utf-8")
    assert written.startswith("---")
    assert "player: Wade" in written
    assert "- **Player:** Wade" in written
    assert "Kostadis" not in written


def test_no_roster_player_empties_the_field_and_says_why(monkeypatch,
                                                         stub_convert,
                                                         tmp_path, capsys):
    """FR-009: never carry the downloaded value forward as a fallback."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml")

    written = (campaign / "docs" / "party" / "Soma.md").read_text(encoding="utf-8")
    assert "Kostadis" not in written
    assert "none recorded in party.yaml" in capsys.readouterr().err


# ── Legacy modes (FR-017, FR-018) ──────────────────────────────────────────

def test_no_party_config_writes_the_pdf_stem_into_doc(monkeypatch, stub_convert,
                                                      tmp_path, capsys):
    """FR-018 and the --output-dir default flip (D11): with no flags at all the
    tool must still write into doc/, exactly as before."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf))

    assert (campaign / "doc" / "Soma.md").exists()
    assert "roster naming and archival were not applied" in capsys.readouterr().err


def test_explicit_output_suppresses_roster_naming_and_says_so(monkeypatch,
                                                             stub_convert,
                                                             tmp_path, capsys):
    """FR-017: an explicit path wins, and the run states what it skipped."""
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    out = tmp_path / "elsewhere" / "soma.md"
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml",
         "--output", str(out))

    assert out.exists()
    assert not (campaign / "docs" / "party" / "Soma.md").exists()
    assert "roster naming and archival were skipped" in capsys.readouterr().err


def test_explicit_output_dir_also_suppresses_roster_naming(monkeypatch,
                                                           stub_convert,
                                                           tmp_path, capsys):
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/party.yaml",
         "--output-dir", str(tmp_path / "out"))

    assert (tmp_path / "out" / "Soma.md").exists()
    assert not (campaign / "docs" / "party" / "Soma.md").exists()
    assert "roster naming and archival were skipped" in capsys.readouterr().err


def test_unreadable_party_config_degrades_to_legacy_with_a_notice(monkeypatch,
                                                                  stub_convert,
                                                                  tmp_path, capsys):
    campaign = _campaign(tmp_path, PHANDALIN_ROSTER)
    pdf = _pdf(tmp_path, "Soma")
    _run(monkeypatch, campaign, str(pdf), "--party-config", "config/nope.yaml")

    assert (campaign / "doc" / "Soma.md").exists()
    err = capsys.readouterr().err
    assert "--party-config not found" in err
    assert "roster naming and archival were not applied" in err
