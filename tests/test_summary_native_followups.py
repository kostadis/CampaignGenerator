"""Regressions for #509–#512: exact identity, portable drafts, incremental ranges."""

import json
import shutil

import pytest

from pipelines.summary_native import key_npcs, notes, schema, state_sections, synth
from pipelines.summary_native.pointers import check_paths
from tests import conftest_state as cs
from tests.test_summary_native_key_npcs import corpus_dossier, dossier


def test_reference_headings_resolve_aliases_without_rewriting_notes():
    forms, _, _ = state_sections.build_identity([('Ilvara Mizzrym', ['Ilvara'])], [])
    lines = [f'- [NPC] **{name}** — note {i}. [ch 002 / npcs]'
             for i, name in enumerate(['Ilvara', 'Ilvara Mizzrym', 'Ilvarra', 'Stranger'])]
    chunk = notes.check_chunk('## World\n' + '\n'.join(lines),
                              [notes.Chapter(2, cs.STATE_FIXTURE / 'unused', '', {'npcs'})])
    md = state_sections.reference_files([chunk], forms)['npcs']
    assert md.count('## Ilvara Mizzrym\n') == 1
    assert '## Ilvara\n' not in md
    assert '## Ilvarra\n' in md and '## Stranger\n' in md
    assert all(line in md for line in lines)
    assert '4 checked notes, 3 subjects' in md


def test_ambiguous_reference_alias_stays_unresolved():
    forms, _, _ = state_sections.build_identity([('Alpha', ['Vane']), ('Beta', ['Vane'])], [])
    note = notes.Note('world', '- [NPC] **Vane** — x [ch 002 / npcs]', 2, '002-002', tag='NPC', subject='Vane')
    assert '## Vane\n' in state_sections.reference_files([notes.CheckedChunk('002-002', [note])], forms)['npcs']


@pytest.mark.parametrize('prefix,valid', [
    ('<!-- provenance -->\n> contract\n> second line\n\n', True),
    ('> contract\n\narbitrary text\n', False),
    ('> first block\n\n> second block\n', False),
    ('arbitrary preamble\n', False),
])
def test_outline_accepts_only_one_leading_blockquote(prefix, valid):
    assert (synth.check_outline(prefix + '## A\nbody\n', ['## A']) == []) is valid


def test_promoted_bundle_validates_and_names_each_missing_file(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    cs.fake_models(monkeypatch)
    assert cs.run_cli(cs.extract_args(root))[0] == 0
    assert cs.run_cli(['synth', 'world_state', *cs.common(root), '--fallback-npc-lines'])[0] == 0
    drafts = cs.range_dir(root) / 'state/drafts'
    # Different destination from docs/: document-relative references still work.
    target = root / 'reviewed/grounding'
    shutil.copytree(drafts, target)
    document = target / 'world_state.draft.md'
    assert synth.check_outline(document.read_text(), synth.load_outline('world_state')) == []
    assert check_paths(document, root) == []
    args = ['check-pointers', str(document), '--config', str(root / 'config/config.yaml')]
    assert cs.run_cli(args)[0] == 0
    (target / 'reference/npcs.md').unlink()
    (target / schema.TIMELINE_FILE).unlink()
    rc, _, err = cs.run_cli(args)
    assert rc == 2 and 'reference/npcs.md' in err and schema.TIMELINE_FILE in err


def test_external_summary_path_survives_synth(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    cs.fake_models(monkeypatch)
    external = tmp_path / 'external-summaries'
    shutil.move(str(root / 'docs/summaries'), external)
    extra = ['--summaries-dir', str(external)]
    assert cs.run_cli(['build', *cs.common(root), '--force', *extra])[0] == 0
    assert cs.run_cli([*cs.extract_args(root), *extra])[0] == 0
    assert cs.run_cli(['synth', 'world_state', *cs.common(root), '--fallback-npc-lines', *extra])[0] == 0
    document = cs.range_dir(root) / 'state/drafts/world_state.draft.md'
    assert str(external) + '/NNN-*.md' in document.read_text()
    assert check_paths(document, root) == []


def test_copying_only_world_state_reports_missing_bundle(tmp_path):
    root = cs.state_campaign(tmp_path)
    doc = root / 'world_state.md'
    doc.write_text(state_sections.reading_contract((2, 5), {
        'summaries': 'docs/summaries', 'reference': 'reference', 'timeline': schema.TIMELINE_FILE,
    }))
    problems = check_paths(doc, root)
    assert len(problems) == 7
    for kind in state_sections.REFERENCE_KINDS:
        assert any(f'reference/{kind}.md' in p for p in problems)


def test_incremental_extract_reuses_older_ranges_and_rechecks_raw(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    fm = cs.fake_models(monkeypatch)
    assert cs.run_cli(['build', *cs.common(root), '--until', '4'])[0] == 0
    assert cs.run_cli([*cs.extract_args(root), '--until', '4'])[0] == 0
    previous = cs.range_dir(root).parent / 'ch002-004/state/notes'
    checked = previous / 'chunk01.002-002.checked.json'
    data = json.loads(checked.read_text())
    data['notes'] = []  # reused raw response must go through the current checker
    checked.write_text(json.dumps(data))
    before = {p.name: p.read_bytes() for p in previous.iterdir()}
    fm.extract_calls.clear()
    rc, out, err = cs.run_cli(cs.extract_args(root))
    assert rc == 0, err
    assert [c['range'] for c in fm.extract_calls] == ['005-005']
    assert '3 cached' in out
    assert json.loads((cs.notes_dir(root) / checked.name).read_text())['notes']
    assert before == {p.name: p.read_bytes() for p in previous.iterdir()}
    fm.extract_calls.clear()
    assert cs.run_cli(cs.extract_args(root, '--force'))[0] == 0
    assert len(fm.extract_calls) == 4


def _publication(root, rng='ch002-070', verify='pass'):
    destination = root / 'docs/npcs'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'ilvara-mizzrym.md').write_text(dossier(
        'Ilvara Mizzrym', 'A priestess [ch 002 / npcs].', 'Waits [ch 070 / end].', rng=rng, verify=verify))


def _new_note(text, subject=None):
    return [notes.CheckedChunk('071-071', [notes.Note('world', text, 71, '071-071', subject=subject)])]


def _plan(root, results, rng='ch002-071'):
    forms, _, _ = state_sections.build_identity([('Ilvara Mizzrym', ['Ilvara'])], [])
    return key_npcs.plan_key_npcs([(corpus_dossier('Ilvara Mizzrym', 70), 'recurring')], root,
                                  npc_root=root / 'npc', rng=rng, results=results, forms=forms)


def test_untouched_dossier_carries_with_pointer_and_report(tmp_path):
    _publication(tmp_path)
    plan = _plan(tmp_path, _new_note('- Ilvarra departs [ch 071 / end].'))
    assert plan[0].view and plan[0].carried_from == 'ch002-070'  # similar spelling is NOT an alias
    assembled = key_npcs.assemble(plan, None, '', 50, [], {})
    assert assembled.lines[0].endswith('→ docs/npcs/ilvara-mizzrym.md')
    assert 'carried over from ch002-070' in key_npcs.report_md(plan, assembled, 50, 10, 100)


@pytest.mark.parametrize('text,subject', [
    ('- [NPC] **Ilvara** — leaves [ch 071 / npcs].', 'Ilvara'),
    ('- The party meets ILVARA [ch 071 / end].', None),
    ('- Ilvara waits [ch 070 / end; ch 071 / end].', None),
])
def test_touched_npc_refuses_by_alias_or_mention_and_names_commands(tmp_path, text, subject):
    _publication(tmp_path)
    plan = _plan(tmp_path, _new_note(text, subject))
    assert plan[0].view is None
    msg = key_npcs.refusal_message(plan, 2, 71)
    assert 'ch002-070' in msg and 'ch002-071' in msg and 'added chapters' in msg
    for command in ('npc-draft', 'npc-verify', 'npc-compose', 'npc-publish'):
        assert f'summary_native {command} --since 2 --until 71 --name "Ilvara Mizzrym"' in msg
    assert '--fallback-npc-lines' in msg


@pytest.mark.parametrize('published,target,verify,accepted', [
    ('ch002-070', 'ch002-070', 'pass', True),
    ('ch002-070', 'ch002-005', 'pass', False),
    ('ch001-070', 'ch002-070', 'pass', False),
    ('ch003-070', 'ch002-071', 'pass', False),
    ('ch002-070', 'ch002-071', 'unverified(forced)', False),
])
def test_dossier_range_and_verification_boundaries(tmp_path, published, target, verify, accepted):
    _publication(tmp_path, published, verify)
    plan = _plan(tmp_path, [], target)
    assert (plan[0].view is not None) is accepted
    if not accepted:
        assert published in plan[0].missing and target in plan[0].missing
