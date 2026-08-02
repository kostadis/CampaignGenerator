"""Pins the shared Extraction & State service's per-fact output contract
(research D3) — the boundary between ``pipelines/ensemble/ensemble_merge.py``
(the producer) and ``event_spine.rows_from_corpus`` / ``thread_registry``
``propose`` (the consumers, on the State Projection side of the service
split).

Both consumers ``continue`` past a fact whose ``type`` doesn't match
(``event`` / ``thread``) rather than raising — by design, so an extraction
pass emitting a type neither consumer cares about is not an error. The
cost of that design is that an upstream KEY RENAME degrades silently: rows
just stop appearing, and the failure surfaces later as an inexplicably thin
grounding doc (research D3). This test is the trip-wire — it builds a fact
record the way ``ensemble_merge.py`` actually emits one (running the real
``merge_facts`` + ``stamp_*`` helpers ``main()`` calls, not a hand-invented
shape) and asserts every key a projection consumer reads is present, AND
that a record with a matching ``type`` actually produces a row on both
sides. If a future rename drops one of these keys, THIS test fails loudly
instead of the event spine or thread registry quietly shrinking.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipelines.ensemble.ensemble_merge import (  # noqa: E402
    merge_facts,
    stamp_lineage,
    stamp_offsets,
    stamp_scene_index,
)
from pipelines.grounding.event_spine import rows_from_corpus  # noqa: E402
from pipelines.grounding.thread_registry import harvest  # noqa: E402

# The keys every projection consumer reads off a merged.json fact record
# (research D3's table, collapsed to one set; data-model.md's "Fact-corpus
# record"). Absence of ANY of these here means ensemble_merge.py stopped
# emitting it — the failure this test exists to catch.
CONSUMED_KEYS = {
    "type", "fact", "subject", "scene_index", "quote_offset",
    "source_quote", "quote_verified", "source",
}


def _emit_like_ensemble_merge(tmp_path: Path, pass_outputs: dict, document: str,
                              chunk_size: int, lineage: dict) -> list[dict]:
    """Reproduce ensemble_merge.main()'s post-processing pipeline — merge,
    then the n_samples collapse, then quote_offset, then scene_index, then
    lineage — so the fixture is the real producer shape, not an invented
    one. (main() itself isn't called: it also parses argv and writes files,
    neither of which this contract test needs.)
    """
    merged = merge_facts(pass_outputs, similarity=0.85)
    for f in merged:
        runs = f["passes"]
        f["n_samples"] = len(runs)
        f["passes"] = sorted({p.split("#")[0] for p in runs})
    stamp_offsets(merged, document)
    stamp_scene_index(merged, document, chunk_size, structural=False)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "lineage.json").write_text(json.dumps(lineage))
    stamp_lineage(merged, workdir)
    return merged


def _write_corpus(tmp_path: Path, chapter: int, records: list[dict]) -> Path:
    corpus = tmp_path / f"chapter_{chapter:02d}_x" / "merged.json"
    corpus.parent.mkdir(parents=True, exist_ok=True)
    corpus.write_text(json.dumps(records))
    return corpus


def test_merged_record_carries_every_key_projection_consumers_read(tmp_path):
    document = ('The party enters the vault. "Orc nine dies here," the '
                "guide says. Aletra's shadowy patron watches from afar.")
    pass_outputs = {
        "lens_a#1": [
            {"type": "event", "subject": "combat", "fact": "Orc nine dies.",
             "source_quote": "Orc nine dies here", "quote_verified": True},
        ],
    }
    merged = _emit_like_ensemble_merge(
        tmp_path, pass_outputs, document, chunk_size=1000,
        lineage={"kind": "scenes", "session": "20260505"})

    assert len(merged) == 1
    record = merged[0]
    missing = CONSUMED_KEYS - record.keys()
    assert not missing, (
        f"merged.json record is missing key(s) {missing} that a "
        f"projection consumer reads — upstream shape drift: {record}"
    )

    # ...and a matching `type` actually yields a row, not just a present key.
    corpus = _write_corpus(tmp_path, 4, merged)
    rows = rows_from_corpus(corpus)
    assert len(rows) == 1
    assert rows[0]["event"] == "Orc nine dies."
    assert rows[0]["source"] == {"kind": "scenes", "session": "20260505"}
    assert rows[0]["scene"] is not None and rows[0]["seq"] is not None


def test_thread_typed_record_yields_a_proposal_group(tmp_path):
    document = "Aletra's shadowy patron watches from afar, unseen."
    pass_outputs = {
        "lens_a#1": [
            {"type": "thread", "subject": "Aletra's patron",
             "fact": "A shadowy patron is watching Aletra.",
             "source_quote": "Aletra's shadowy patron watches from afar",
             "quote_verified": True},
        ],
    }
    merged = _emit_like_ensemble_merge(
        tmp_path, pass_outputs, document, chunk_size=1000,
        lineage={"kind": "summary"})

    record = merged[0]
    missing = CONSUMED_KEYS - record.keys()
    assert not missing, f"missing key(s) {missing}: {record}"

    corpus = _write_corpus(tmp_path, 7, merged)
    groups = harvest([str(corpus)])
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert group["title"] == "Aletra's patron"
    assert group["evidence"][0]["fact"] == "A shadowy patron is watching Aletra."
    assert group["evidence"][0].get("source") == "summary"


def test_a_non_matching_type_is_skipped_not_errored(tmp_path):
    """Documents the actual failure mode this contract test exists to catch
    upstream of: a fact whose `type` doesn't match ``event``/``thread``
    silently produces zero rows, with no error at all. If ``type`` itself
    were renamed, every record would land here — this test would then fail
    only if CONSUMED_KEYS' presence check above were also bypassed, which is
    why that check runs first and unconditionally.
    """
    pass_outputs = {
        "lens_a#1": [
            {"type": "npc", "subject": "Prutha", "fact": "Not an event or thread.",
             "source_quote": "", "quote_verified": False},
        ],
    }
    merged = _emit_like_ensemble_merge(
        tmp_path, pass_outputs, document="irrelevant",
        chunk_size=1000, lineage={"kind": "scenes"})
    corpus = _write_corpus(tmp_path, 4, merged)
    assert rows_from_corpus(corpus) == []
    assert harvest([str(corpus)]) == {}
