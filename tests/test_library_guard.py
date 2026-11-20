import pytest

from pipelines.library import ExitCode, PalaceRefused
from pipelines.library.guard import require_library_palace


def test_default_palace_refused(tmp_path):
    with pytest.raises(PalaceRefused):
        require_library_palace(tmp_path / ".mempalace/palaces/x", tmp_path)


def test_mempalace_root_itself_refused(tmp_path):
    with pytest.raises(PalaceRefused):
        require_library_palace(tmp_path / ".mempalace", tmp_path)


def test_campaign_palace_refused(tmp_path):
    with pytest.raises(PalaceRefused):
        require_library_palace(tmp_path / "src/campaigns/x/.mempalace", tmp_path)


@pytest.mark.parametrize("target", [".mempalace/palaces", "src/campaigns/c"])
def test_symlink_into_live_refused(tmp_path, target):
    (tmp_path / target).mkdir(parents=True)
    link = tmp_path / "innocent"
    link.symlink_to(tmp_path / target)
    with pytest.raises(PalaceRefused):
        require_library_palace(link, tmp_path)


def test_ok_resolves(tmp_path):
    p = tmp_path / "lib/palace"
    assert require_library_palace(p, tmp_path) == p.resolve()


def test_refusal_names_fix_and_exit_code(tmp_path):
    with pytest.raises(PalaceRefused) as ei:
        require_library_palace(tmp_path / ".mempalace/x", tmp_path)
    assert "library.palace" in str(ei.value)
    assert PalaceRefused.exit_code == ExitCode.REFUSED == 6


def test_work_dir_and_cache_dir_in_live_location_refused(tmp_path):
    from pipelines.library.config import load_library_config

    base = (
        "env:\n  MEMPALACE_BACKEND: turbovec\nrpg_library_db: /x.db\nlibrary:\n"
        f"  palace: {tmp_path / 'p'}\n  source_root: {tmp_path / 's'}\n"
        "  selection:\n    all_converted: true\n"
    )
    for extra in (f"  work_dir: {tmp_path / '.mempalace' / 'w'}\n",
                  f"  work_dir: {tmp_path / 'w'}\n  cache_dir: {tmp_path / 'src' / 'campaigns' / 'c'}\n"):
        h = tmp_path / "h.yaml"
        h.write_text(base + extra)
        with pytest.raises(PalaceRefused) as ei:
            load_library_config(h, {}, home=tmp_path)
        assert ei.value.exit_code == ExitCode.REFUSED
