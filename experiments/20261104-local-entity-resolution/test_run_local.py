import json
from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import run_local
from run_local import parse_response, save_arm, request


def test_plain_and_fenced_json_have_same_results():
    text = json.dumps({'results': [{'id': 'q1'}, {'id': 'q2'}]})
    assert parse_response(text, ['q1', 'q2']) == parse_response('```json\n'+text+'\n```', ['q1', 'q2'])


@pytest.mark.parametrize('ids', [['q1'], ['q1', 'q1'], ['q1', 'q2', 'q3']])
def test_missing_duplicate_or_extra_results_are_refused(ids):
    with pytest.raises(ValueError):
        parse_response(json.dumps({'results': [{'id': i} for i in ids]}), ['q1', 'q2'])


def test_malformed_output_is_not_repaired_into_an_answer():
    with pytest.raises(json.JSONDecodeError):
        parse_response('I think q1 is the same orc.', ['q1'])


def test_protocol_failure_keeps_raw_identity_without_passing(tmp_path):
    metadata = {'model': 'local', 'served_model': 'local', 'finish_reason': 'stop'}
    assert save_arm(tmp_path, 'context', '{broken', ['q1'], metadata) == 'protocol_failure'
    saved = json.loads((tmp_path/'context.record.json').read_text())
    assert saved['error_type'] == 'JSONDecodeError' and saved['raw_response_sha256']
    assert not (tmp_path/'context.response.json').exists()


@pytest.mark.parametrize('field,value', [('finish_reason', 'length'), ('served_model', 'another-model')])
def test_truncation_or_model_swap_cannot_pass(tmp_path, field, value):
    metadata = {'model': 'local', 'served_model': 'local', 'finish_reason': 'stop'}
    metadata[field] = value
    text = json.dumps({'results': [{'id': 'q1'}]})
    assert save_arm(tmp_path, 'context', text, ['q1'], metadata) == 'protocol_failure'


def fake_client():
    calls = []
    message = SimpleNamespace(model_dump=lambda: {'content': '{}', 'reasoning': ''})
    response = SimpleNamespace(id='test-response', model='local', usage=None,
                               choices=[SimpleNamespace(message=message, finish_reason='stop')])
    def create(**kwargs):
        calls.append(kwargs)
        return response
    client = SimpleNamespace(oai=SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    return client, calls


def test_schema_control_changes_transport_not_task_text(tmp_path, monkeypatch):
    client, calls = fake_client()
    monkeypatch.setattr(run_local, 'make_client', lambda **kwargs: client)
    def fake_api(selected, system, prompt, model, **kwargs):
        assert system == 'frozen system' and prompt == 'frozen prompt' and kwargs['thinking'] is False
        selected.oai.chat.completions.create(model=model, max_tokens=16000, messages=[{'role': 'user', 'content': prompt}])
        return '{}'
    monkeypatch.setattr(run_local, 'call_api', fake_api)
    args = SimpleNamespace(endpoint='http://local/v1', model='local', structured='json-schema',
                           max_tokens=16000, thinking='off', out=tmp_path)
    output, observed, elapsed = request(args, 'context', 'frozen system', 'frozen prompt', False)
    assert output == '{}' and observed[-1]['structured'] == 'json-schema'
    assert calls[0]['response_format']['type'] == 'json_schema'
    assert calls[0]['messages'][0]['content'] == 'frozen prompt'


def test_empty_final_content_retains_transport_metadata(tmp_path, monkeypatch):
    client, calls = fake_client()
    monkeypatch.setattr(run_local, 'make_client', lambda **kwargs: client)
    def empty_api(selected, system, prompt, model, **kwargs):
        selected.oai.chat.completions.create(model=model, max_tokens=16000, messages=[])
        raise RuntimeError('model returned empty output')
    monkeypatch.setattr(run_local, 'call_api', empty_api)
    args = SimpleNamespace(endpoint='http://local/v1', model='local', structured='none',
                           max_tokens=16000, thinking='on', out=tmp_path)
    output, observed, elapsed = request(args, 'context', 'system', 'prompt', True)
    assert output == '' and observed[-1]['served_model'] == 'local'
    assert observed[-1]['client_error'] == 'model returned empty output'


def test_resume_never_retries_recorded_failures_without_raw_output(tmp_path, monkeypatch):
    baseline, out = tmp_path/'baseline', tmp_path/'run'
    baseline.mkdir()
    out.mkdir()
    contents = {'payload.json': json.dumps({'cases': [{'id': 'q1'}]}), 'gold.json': '[]',
                'input_hashes.json': '{}', 'reference_provenance.json': '{}'}
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in contents.items()}
    contents['registration.json'] = json.dumps({'payload_sha256': hashes['payload.json'],
        'gold_sha256': hashes['gold.json'], 'input_hashes_sha256': hashes['input_hashes.json']})
    for name, text in contents.items():
        (baseline/name).write_text(text)
        (out/name).write_text(text)
    for arm in ('context', 'surface_only'):
        (baseline/f'{arm}.system.txt').write_text('system')
        (baseline/f'{arm}.prompt.txt').write_text('prompt')
        (baseline/f'{arm}.record.json').write_text(json.dumps({
            'system_sha256': hashlib.sha256(b'system').hexdigest(),
            'prompt_sha256': hashlib.sha256(b'prompt').hexdigest()}))
        (out/f'{arm}.record.json').write_text(json.dumps({'status': 'protocol_failure',
            'model': 'local', 'thinking': False, 'payload_sha256': hashes['payload.json']}))
    monkeypatch.setattr(sys, 'argv', ['run_local.py', '--baseline', str(baseline), '--out', str(out),
        '--endpoint', 'http://local/v1', '--model', 'local', '--thinking', 'off', '--resume'])
    def forbidden(*args, **kwargs):
        raise AssertionError('resume must not launch another model request')
    monkeypatch.setattr(run_local, 'request', forbidden)
    with pytest.raises(SystemExit) as caught:
        run_local.main()
    assert caught.value.code == 3
