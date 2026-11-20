from pathlib import Path
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
        "env:\n  MEMPALACE_BACKEND: turbovec\ndata_roots:\n  rpg_library_db: /x.db\nlibrary:\n"
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


# ---- #668: live set widened via the mempalace registry ----
import json


def _registry(cfgdir, palaces, palace_path=None):
    cfgdir.mkdir(parents=True, exist_ok=True)
    d = {"palaces": palaces}
    if palace_path:
        d["palace_path"] = palace_path
    (cfgdir / "config.json").write_text(json.dumps(d))


def test_env_config_dir_override(tmp_path):
    cfgdir = tmp_path / "elsewhere"
    with pytest.raises(PalaceRefused) as ei:
        require_library_palace(cfgdir / "palaces/x", tmp_path, {"MEMPALACE_CONFIG_DIR": str(cfgdir)})
    assert "config dir" in str(ei.value) and "inside" in str(ei.value)


def test_registered_palace_outside_config_dir_refused(tmp_path):
    live = tmp_path / "storm/.mempalace"
    _registry(tmp_path / ".mempalace", {"storm": str(live)})
    with pytest.raises(PalaceRefused) as ei:
        require_library_palace(live, tmp_path, {})
    assert "registered" in str(ei.value) and "equal to" in str(ei.value)
    with pytest.raises(PalaceRefused):
        require_library_palace(live / "sub", tmp_path, {})


def test_palace_path_key_refused(tmp_path):
    _registry(tmp_path / ".mempalace", {}, palace_path=str(tmp_path / "pp"))
    with pytest.raises(PalaceRefused):
        require_library_palace(tmp_path / "pp", tmp_path, {})


def test_ancestor_refused(tmp_path):
    for cand in (tmp_path, tmp_path / "src", tmp_path / ".mempalace/palaces"):
        with pytest.raises(PalaceRefused) as ei:
            require_library_palace(cand, tmp_path, {})
        assert "ancestor" in str(ei.value)


def test_unmarked_existing_palace_refused_marked_accepted(tmp_path):
    from pipelines.library.guard import MARKER

    pal = tmp_path / "lib/palace"
    pal.mkdir(parents=True)
    require_library_palace(pal, tmp_path, {})  # empty dir ok
    (pal / "chroma.sqlite3").write_text("x")
    with pytest.raises(PalaceRefused) as ei:
        require_library_palace(pal, tmp_path, {})
    assert "unmarked" in str(ei.value)
    (pal / MARKER).write_text("")
    assert require_library_palace(pal, tmp_path, {}) == pal.resolve()


def test_missing_and_invalid_registry_tolerated(tmp_path):
    p = tmp_path / "lib/palace"
    assert require_library_palace(p, tmp_path, {}) == p.resolve()
    (tmp_path / ".mempalace").mkdir()
    (tmp_path / ".mempalace/config.json").write_text("{not json")
    assert require_library_palace(p, tmp_path, {}) == p.resolve()
    (tmp_path / ".mempalace/config.json").write_text("[1]")
    assert require_library_palace(p, tmp_path, {}) == p.resolve()


def test_work_dir_inside_registered_palace_refused(tmp_path):
    from pipelines.library.guard import require_isolated_dir

    live = tmp_path / "storm/pal"
    _registry(tmp_path / ".mempalace", {"s": str(live)})
    with pytest.raises(PalaceRefused):
        require_isolated_dir(live / "work", "library.work_dir", tmp_path, {})


def test_hypostasis_paths_mempalace_refused(tmp_path):
    with pytest.raises(PalaceRefused) as ei:
        require_library_palace(tmp_path / "hm/x", tmp_path, {}, extra_live=[tmp_path / "hm"])
    assert "paths.mempalace" in str(ei.value)


def test_known_palaces_reads_registry(tmp_path):
    from pipelines.rlm.mempalace_client import known_palaces

    assert known_palaces(tmp_path / "none", {}) == []
    _registry(tmp_path / "c", {"a": "/x/a"}, palace_path="/x/p")
    assert set(known_palaces(tmp_path / "c", {})) == {Path("/x/a"), Path("/x/p")}
    assert known_palaces(None, {"MEMPALACE_CONFIG_DIR": str(tmp_path / "c")})
