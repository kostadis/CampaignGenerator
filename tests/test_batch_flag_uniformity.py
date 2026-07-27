"""T023 — every LLM-bearing CLI accepts the uniform --batch parameter (FR-002).

Static source-level sweep rather than per-CLI --help subprocesses: a script-path
subprocess in this repo resolves `campaignlib` through the editable-install
.pth (main checkout), which makes --help smoke tests flaky in worktrees. The
live --help loop is quickstart.md §2 and runs as part of T030 validation.

Registrar users get --batch from add_backend_args; the two hand-rolled
vocabulary copies (facts_to_state's parser — plural --endpoints collides with
the registrar — and ensemble.py's pass-through) must declare it themselves.
Wording sync for facts_to_state is asserted in tests/test_facts_to_state.py.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every LLM-bearing CLI that speaks the shared backend vocabulary via the
# registrar (contracts/cli-batch-flag.md grouping table).
REGISTRAR_CLIS = [
    "session_doc/scene_extract.py",
    "session_doc/sd_plan.py",
    "session_doc/sd_consistency.py",
    "session_doc/scrub_mechanics.py",
    "session_doc/sd_narrate.py",
    "session_doc/check_consistency.py",
    "session_doc/vtt_voice_compare.py",
    "session_doc/enhance_summary.py",
    "pipelines/session_prep/prep.py",
    "pipelines/session_prep/transform.py",
    "pipelines/content_ingest/dnd_sheet.py",
    "pipelines/rlm/query.py",
    "pipelines/grounding/planning.py",
    "pipelines/grounding/party.py",
    "pipelines/grounding/make_tracking.py",
    "pipelines/grounding/distill.py",
    "pipelines/grounding/campaign_state.py",
    "pipelines/grounding/npc_table.py",
    "pipelines/ensemble/synthesise_world_state.py",
    "pipelines/ensemble/synthesise_polish.py",
    "pipelines/ensemble/extract_facts.py",
    "pipelines/ensemble/polish.py",
    "scabard_sdk/scabard_sync.py",
]

# Hand-rolled vocabulary copies: must register --batch themselves.
HAND_ROLLED_CLIS = [
    "pipelines/ensemble/facts_to_state.py",
    "pipelines/ensemble/ensemble.py",
]


def test_registrar_clis_use_add_backend_args():
    missing = [p for p in REGISTRAR_CLIS
               if "add_backend_args(" not in (ROOT / p).read_text()]
    assert not missing, (
        f"CLIs no longer using the shared registrar (they'd lose --batch): "
        f"{missing}")


def test_hand_rolled_clis_declare_batch():
    missing = [p for p in HAND_ROLLED_CLIS
               if '"--batch"' not in (ROOT / p).read_text()]
    assert not missing, f"hand-rolled vocabulary copies missing --batch: {missing}"


def test_no_cli_registers_batch_twice():
    # add_backend_args owns --batch; a CLI that also declares it hand-rolled
    # would crash argparse with "conflicting option string" on every run.
    doubled = [p for p in REGISTRAR_CLIS
               if '"--batch"' in (ROOT / p).read_text()]
    assert not doubled, f"duplicate --batch registration (argparse conflict): {doubled}"
