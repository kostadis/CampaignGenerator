"""Tests for server/routers/connections.py pure functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import connections
from campaignlib.api.codex_cli import CodexRunIdentity
from server.routers.connections import (
    ExtractRequest,
    _slug,
    canonicalize,
    find_simple_paths,
    merge,
    neighbors_of,
)


def test_extract_returns_codex_run_identity_without_second_model_call(monkeypatch, tmp_path):
    source = tmp_path / "world.md"
    source.write_text("A compact world state.", encoding="utf-8")
    identity = CodexRunIdentity(
        backend="codex-cli",
        model="gpt-5.6-sol",
        model_source="explicit",
        codex_reasoning_effort="max",
        codex_reasoning_effort_source="explicit",
        codex_reasoning_override=True,
    )

    class Client:
        last_run_identity = identity

    calls = 0

    def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        return '{"entities": [], "edges": []}'

    monkeypatch.setattr(connections, "resolve_selection", lambda *a, **k: type(
        "Selection", (), {"model": "gpt-5.6-sol"}
    )())
    monkeypatch.setattr(connections, "client_from_args", lambda selection: Client())
    monkeypatch.setattr(connections, "stream_api", fake_stream)

    result = connections.extract_connections(
        ExtractRequest(files=[str(source)], cache_path=str(tmp_path / "connections.json")),
        object(),
    )

    assert calls == 1
    assert result["run_identity"] == identity.as_dict()


def test_extract_non_codex_response_does_not_invent_run_identity(monkeypatch, tmp_path):
    source = tmp_path / "world.md"
    source.write_text("A compact world state.", encoding="utf-8")

    class Client:
        last_run_identity = None

    monkeypatch.setattr(connections, "resolve_selection", lambda *a, **k: type(
        "Selection", (), {"model": "claude-sonnet-4-6"}
    )())
    monkeypatch.setattr(connections, "client_from_args", lambda selection: Client())
    monkeypatch.setattr(
        connections,
        "stream_api",
        lambda *a, **k: '{"entities": [], "edges": []}',
    )

    result = connections.extract_connections(
        ExtractRequest(files=[str(source)], cache_path=str(tmp_path / "connections.json")),
        object(),
    )
    assert "run_identity" not in result


# ── _slug ─────────────────────────────────────────────────────────────────────

def test_slug_basic():
    assert _slug("Xalvosh") == "xalvosh"
    assert _slug("Captain Tolubb") == "captain_tolubb"
    assert _slug("Brundar's Echo") == "brundar_s_echo"
    assert _slug("  Multi   Space  ") == "multi_space"
    assert _slug("") == ""


# ── canonicalize ──────────────────────────────────────────────────────────────

def test_canonicalize_rewrites_ids_to_type_slug():
    data = {
        "entities": [
            {"id": "x1", "label": "Xalvosh", "type": "npc", "summary": "A sea mage."},
            {"id": "f1", "label": "Kraken Society", "type": "faction", "summary": ""},
        ],
        "edges": [
            {"source": "x1", "target": "f1", "label": "member of"},
        ],
    }
    out = canonicalize(data)
    ids = {e["id"] for e in out["entities"]}
    assert ids == {"npc_xalvosh", "faction_kraken_society"}
    assert out["edges"] == [
        {"source": "npc_xalvosh", "target": "faction_kraken_society", "label": "member of"}
    ]


def test_canonicalize_drops_invalid_types():
    data = {
        "entities": [
            {"id": "a", "label": "Good", "type": "npc"},
            {"id": "b", "label": "Bad", "type": "invalid_type"},
            {"id": "c", "label": "", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "x"},  # drops: b invalid
            {"source": "a", "target": "c", "label": "x"},  # drops: c empty
        ],
    }
    out = canonicalize(data)
    assert len(out["entities"]) == 1
    assert out["entities"][0]["id"] == "npc_good"
    assert out["edges"] == []


def test_canonicalize_dedupes_edges():
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "knows"},
            {"source": "a", "target": "b", "label": "knows"},  # dup
            {"source": "a", "target": "b", "label": "hates"},  # different label, kept
        ],
    }
    out = canonicalize(data)
    assert len(out["edges"]) == 2


def test_canonicalize_drops_self_loops():
    data = {
        "entities": [{"id": "a", "label": "Solo", "type": "npc"}],
        "edges": [{"source": "a", "target": "a", "label": "self"}],
    }
    out = canonicalize(data)
    assert out["edges"] == []


def test_canonicalize_collapses_duplicate_labels():
    """Two entities with the same canonical id collapse to one (last wins)."""
    data = {
        "entities": [
            {"id": "x1", "label": "Xalvosh", "type": "npc", "summary": "old"},
            {"id": "x2", "label": "xalvosh", "type": "npc", "summary": "new"},
        ],
        "edges": [],
    }
    out = canonicalize(data)
    assert len(out["entities"]) == 1
    assert out["entities"][0]["summary"] == "new"


# ── merge ─────────────────────────────────────────────────────────────────────

def test_merge_preserves_old_entities_adds_new():
    old = {
        "entities": [
            {"id": "npc_a", "label": "A", "type": "npc", "summary": "first"},
        ],
        "edges": [],
    }
    new = {
        "entities": [
            {"id": "npc_b", "label": "B", "type": "npc", "summary": "second"},
        ],
        "edges": [],
    }
    out = merge(old, new)
    ids = {e["id"] for e in out["entities"]}
    assert ids == {"npc_a", "npc_b"}


def test_merge_prefers_new_summary_on_collision():
    old = {"entities": [{"id": "npc_a", "label": "A", "type": "npc", "summary": "old"}], "edges": []}
    new = {"entities": [{"id": "npc_a", "label": "A", "type": "npc", "summary": "new"}], "edges": []}
    out = merge(old, new)
    summaries = {e["id"]: e["summary"] for e in out["entities"]}
    assert summaries["npc_a"] == "new"


def test_merge_unions_edges_and_dedupes():
    a = {"id": "npc_a", "label": "A", "type": "npc"}
    b = {"id": "npc_b", "label": "B", "type": "npc"}
    old = {"entities": [a, b], "edges": [{"source": "npc_a", "target": "npc_b", "label": "knows"}]}
    new = {"entities": [a, b], "edges": [
        {"source": "npc_a", "target": "npc_b", "label": "knows"},  # dup
        {"source": "npc_a", "target": "npc_b", "label": "hates"},  # new
    ]}
    out = merge(old, new)
    labels = sorted(e["label"] for e in out["edges"])
    assert labels == ["hates", "knows"]


def test_merge_drops_dangling_edges():
    """Edges pointing at entities that fell out of the union are dropped."""
    old = {
        "entities": [{"id": "npc_a", "label": "A", "type": "npc"}],
        "edges": [{"source": "npc_a", "target": "npc_ghost", "label": "knew"}],
    }
    new = {"entities": [{"id": "npc_b", "label": "B", "type": "npc"}], "edges": []}
    out = merge(old, new)
    assert out["edges"] == []


# ── find_simple_paths ─────────────────────────────────────────────────────────

def _linear_graph():
    """A — B — C — D"""
    return {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
            {"id": "d", "label": "D", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "l1"},
            {"source": "b", "target": "c", "label": "l2"},
            {"source": "c", "target": "d", "label": "l3"},
        ],
    }


def test_paths_linear():
    paths = find_simple_paths(_linear_graph(), "a", "d", max_hops=5, max_paths=10)
    assert len(paths) == 1
    assert [n["id"] for n in paths[0]["nodes"]] == ["a", "b", "c", "d"]
    assert paths[0]["length"] == 3


def test_paths_respects_max_hops():
    paths = find_simple_paths(_linear_graph(), "a", "d", max_hops=2, max_paths=10)
    assert paths == []


def test_paths_undirected_traversal():
    """Edges are undirected for path-finding — A→B→C edge set still finds C from A."""
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
        ],
        "edges": [
            # All edges point "forward" but we want to find paths from C to A too.
            {"source": "a", "target": "b", "label": "l1"},
            {"source": "b", "target": "c", "label": "l2"},
        ],
    }
    paths = find_simple_paths(data, "c", "a", max_hops=5, max_paths=10)
    assert len(paths) == 1
    assert [n["id"] for n in paths[0]["nodes"]] == ["c", "b", "a"]


def test_paths_no_simple_cycles():
    """Simple paths — no node appears twice."""
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "l1"},
            {"source": "b", "target": "c", "label": "l2"},
            {"source": "c", "target": "a", "label": "l3"},  # closes triangle
        ],
    }
    paths = find_simple_paths(data, "a", "c", max_hops=5, max_paths=10)
    # Two paths: a-b-c (length 2) and a-c (length 1, via the triangle-closing edge)
    assert len(paths) == 2
    assert paths[0]["length"] == 1
    assert paths[1]["length"] == 2


def test_paths_multiple_routes_sorted_by_length():
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
            {"id": "d", "label": "D", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "d", "label": "direct"},
            {"source": "a", "target": "b", "label": "via"},
            {"source": "b", "target": "c", "label": "via"},
            {"source": "c", "target": "d", "label": "via"},
        ],
    }
    paths = find_simple_paths(data, "a", "d", max_hops=5, max_paths=10)
    assert [p["length"] for p in paths] == [1, 3]


def test_paths_unknown_entity_returns_empty():
    assert find_simple_paths(_linear_graph(), "a", "ghost", 5, 10) == []
    assert find_simple_paths(_linear_graph(), "ghost", "d", 5, 10) == []


def test_paths_source_equals_target():
    assert find_simple_paths(_linear_graph(), "a", "a", 5, 10) == []


def test_paths_respects_max_paths():
    # Three distinct paths A→D possible; cap to 2.
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
            {"id": "d", "label": "D", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "d", "label": "1"},
            {"source": "a", "target": "b", "label": "2"},
            {"source": "b", "target": "d", "label": "3"},
            {"source": "a", "target": "c", "label": "4"},
            {"source": "c", "target": "d", "label": "5"},
        ],
    }
    paths = find_simple_paths(data, "a", "d", max_hops=5, max_paths=2)
    assert len(paths) == 2


# ── neighbors_of ──────────────────────────────────────────────────────────────

def test_neighbors_returns_both_directions():
    data = {
        "entities": [
            {"id": "a", "label": "A", "type": "npc"},
            {"id": "b", "label": "B", "type": "npc"},
            {"id": "c", "label": "C", "type": "npc"},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "knows"},
            {"source": "c", "target": "a", "label": "hunts"},
        ],
    }
    neighbors = neighbors_of(data, "a")
    by_id = {n["entity"]["id"]: n for n in neighbors}
    assert by_id["b"]["direction"] == "out"
    assert by_id["b"]["edge_label"] == "knows"
    assert by_id["c"]["direction"] == "in"
    assert by_id["c"]["edge_label"] == "hunts"


def test_neighbors_unknown_entity():
    assert neighbors_of({"entities": [], "edges": []}, "ghost") == []
