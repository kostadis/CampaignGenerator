"""The opt-in experiment must preserve sources and never call a model in dry-run."""

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / 'docs/experiments/narration-dialogue-edit'
spec = importlib.util.spec_from_file_location('dialogue_edit_experiment', DIRECTORY/'run_test.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def make_case(tmp_path):
    draft = tmp_path/'draft.md'
    source = tmp_path/'source.md'
    voice = tmp_path/'voice.md'
    draft.write_text('### Narrator\n\nI count the doors.\n\n“Yes, yes.”\n')
    source.write_text('The narrator counts the doors and agrees.\n')
    voice.write_text('Short and practical.\n')
    return {'id':'example','narrator':'Narrator','scene':'Doors','draft':str(draft),
            'source':str(source),'references':[str(voice)]}


def test_accepted_prompt_is_unchanged():
    assert hashlib.sha256((DIRECTORY/'narration_v1.md').read_bytes()).hexdigest() == (
        '67feb055f9efa13a384c3ae80d7c1b3eac20436c88d418aed2b79482806f2aa6')


def test_scene_body_removes_only_frontmatter():
    assert runner.scene_body('---\nscene: 1\n---\n\n### Narrator\n\n---\nText') == (
        '### Narrator\n\n---\nText\n')


def test_snapshots_refuse_overwrite(tmp_path):
    path = tmp_path/'artifact.md'
    runner.save_identical_or_new(path,'original')
    runner.save_identical_or_new(path,'original')
    with pytest.raises(ValueError,match='differs'):
        runner.save_identical_or_new(path,'changed')
    assert path.read_text() == 'original'


def test_preparation_never_calls_model_or_modifies_inputs(tmp_path):
    case = make_case(tmp_path)
    before = {path:Path(path).read_bytes() for path in [case['draft'],case['source'],*case['references']]}
    with patch('campaignlib.make_client') as client, patch('campaignlib.call_api') as api:
        runner.run_case(case,'a',tmp_path/'output',False)
    client.assert_not_called()
    api.assert_not_called()
    assert all(Path(path).read_bytes()==text for path,text in before.items())
    meta=json.loads((tmp_path/'output/example/a/run.json').read_text())
    assert meta['status']=='prepared'
    assert meta['model']=='gpt-6-astra'


def test_wrong_backend_identity_is_not_success(tmp_path):
    case=make_case(tmp_path)
    client=Mock()
    client.last_run_identity.as_dict.return_value={'model':'wrong','codex_reasoning_effort':'medium'}
    with patch('campaignlib.make_client',return_value=client), patch('campaignlib.call_api',return_value='### Narrator\n\n“Yes.”'):
        with pytest.raises(ValueError,match='identity'):
            runner.run_case(case,'a',tmp_path/'output',True)
    meta=json.loads((tmp_path/'output/example/a/run.json').read_text())
    assert meta['status']=='failed'
