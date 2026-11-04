"""Replay frozen mention-resolution prompts on an explicitly selected local endpoint.

All model calls use campaignlib.api. The transport observer captures settings,
served model, finish reason, usage, elapsed time and reasoning length; it never
changes task text, repairs semantic answers, or falls back to another provider.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from campaignlib.api import make_client, call_api


def sha(data):
    return hashlib.sha256(data).hexdigest()


def output_schema():
    context = {'type': 'object', 'additionalProperties': False,
               'required': ['granularity', 'location', 'encounter'],
               'properties': {'granularity': {'type': 'string', 'enum': ['individual', 'group', 'kind', 'unknown', 'nonreferent']},
                              'location': {'type': ['string', 'null']}, 'encounter': {'type': ['string', 'null']}}}
    evidence = {'type': 'object', 'additionalProperties': False, 'required': ['reference', 'quote'],
                'properties': {'reference': {'type': 'string'}, 'quote': {'type': 'string'}}}
    result = {'type': 'object', 'additionalProperties': False,
              'required': ['id', 'relation', 'left_context', 'right_context', 'evidence', 'reason'],
              'properties': {'id': {'type': 'string'},
                             'relation': {'type': 'string', 'enum': ['same_referent', 'distinct_referents', 'separate_scope', 'overlap_or_membership', 'ambiguous', 'corrected_nonreferent']},
                             'left_context': context, 'right_context': context,
                             'evidence': {'type': 'array', 'items': evidence}, 'reason': {'type': 'string'}}}
    return {'type': 'object', 'additionalProperties': False, 'required': ['results'],
            'properties': {'results': {'type': 'array', 'minItems': 16, 'maxItems': 16, 'items': result}}}


def parse_response(text, expected_ids):
    value = text.strip()
    if value.startswith('```'):
        value = value.split('\n', 1)[1].rsplit('```', 1)[0]
    parsed = json.loads(value)
    actual = [row['id'] for row in parsed['results']]
    if len(actual) != len(set(actual)) or set(actual) != set(expected_ids):
        raise ValueError('missing, duplicate or unrequested comparison results')
    return parsed


def save_arm(out, arm, output, expected_ids, metadata):
    """Keep protocol failures as results; never repair labels or broken JSON."""
    metadata = dict(metadata, raw_response_sha256=sha(output.encode()))
    try:
        if metadata['finish_reason'] != 'stop':
            raise ValueError('incomplete output: finish_reason is not stop')
        if metadata['served_model'] != metadata['model']:
            raise ValueError('server returned a different model')
        parsed = parse_response(output, expected_ids)
    except (ValueError, KeyError, TypeError) as error:
        metadata.update(status='protocol_failure', error_type=type(error).__name__, error=str(error))
    else:
        path = out/f'{arm}.response.json'
        path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2)+'\n')
        metadata.update(status='response_received_not_yet_scored', response_sha256=sha(path.read_bytes()))
    (out/f'{arm}.record.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return metadata['status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--thinking', choices=('on', 'off'), required=True)
    parser.add_argument('--max-tokens', type=int, default=16000)
    parser.add_argument('--resume', action='store_true', help='retain completed raw arms, including failures')
    parser.add_argument('--structured', choices=('none', 'json-schema'), default='none')
    args = parser.parse_args()
    baseline = args.baseline
    registration = json.loads((baseline/'registration.json').read_text())
    for filename, key in [('payload.json', 'payload_sha256'), ('gold.json', 'gold_sha256'),
                           ('input_hashes.json', 'input_hashes_sha256')]:
        if sha((baseline/filename).read_bytes()) != registration[key]:
            raise ValueError(f'baseline registration mismatch: {filename}')
    args.out.mkdir(parents=True, exist_ok=args.resume)
    for name in ('payload.json', 'gold.json', 'registration.json', 'reference_provenance.json', 'input_hashes.json'):
        if (args.out/name).exists():
            if not args.resume or (args.out/name).read_bytes() != (baseline/name).read_bytes():
                raise ValueError('existing run has different frozen inputs')
        else:
            shutil.copyfile(baseline/name, args.out/name)
    # Gold is retained for the evaluator; only the frozen prompt/system enter API calls.
    expected_ids = [case['id'] for case in json.loads((baseline/'payload.json').read_text())['cases']]
    thinking = args.thinking == 'on'
    if args.structured == 'json-schema':
        (args.out/'output_schema.json').write_text(json.dumps(output_schema(), sort_keys=True, indent=2)+'\n')
    failures = []
    for arm in ('context', 'surface_only'):
        record = json.loads((baseline/f'{arm}.record.json').read_text())
        system = (baseline/f'{arm}.system.txt').read_text()
        prompt = (baseline/f'{arm}.prompt.txt').read_text()
        if sha(system.encode()) != record['system_sha256'] or sha(prompt.encode()) != record['prompt_sha256']:
            raise ValueError('frozen task prompt changed')
        raw_path = args.out/f'{arm}.response.txt'
        saved_record = args.out/f'{arm}.record.json'
        if args.resume and saved_record.exists() and not raw_path.exists():
            saved = json.loads(saved_record.read_text())
            if saved.get('status') == 'protocol_failure':
                if (saved['model'] != args.model or saved['thinking'] != thinking or
                        saved['payload_sha256'] != registration['payload_sha256']):
                    raise ValueError('retained failure has different inputs/settings')
                failures.append(arm)
                print(f'{arm}: retaining recorded failure without raw output; no retry', flush=True)
                continue
        if raw_path.exists():
            if not args.resume:
                raise ValueError('raw arm already exists')
            for suffix, expected in [('system.txt', system), ('prompt.txt', prompt)]:
                if (args.out/f'{arm}.{suffix}').read_text() != expected:
                    raise ValueError('retained arm prompt/system changed')
            observed = json.loads((args.out/f'{arm}.transport.json').read_text())
            final = observed[-1]
            if (final.get('request_model') != args.model or final.get('max_tokens') != args.max_tokens
                    or final.get('structured', 'none') != args.structured
                    or (final.get('extra_body') or {}).get('chat_template_kwargs', {}).get('enable_thinking') != thinking):
                raise ValueError('retained arm used different local settings')
            output = raw_path.read_text()
            elapsed = sum(item['elapsed_seconds'] for item in observed)
            print(f'{arm}: retaining prior raw response without another call', flush=True)
        else:
            (args.out/f'{arm}.system.txt').write_text(system)
            (args.out/f'{arm}.prompt.txt').write_text(prompt)
            output, observed, elapsed = request(args, arm, system, prompt, thinking)
            raw_path.write_text(output)
            (args.out/f'{arm}.transport.json').write_text(json.dumps(observed, indent=2)+'\n')
            final = observed[-1]
        metadata = {
            'arm': arm, 'backend': 'dgx', 'endpoint': args.endpoint, 'model': args.model,
            'served_model': final['served_model'], 'effort': None, 'thinking': thinking,
            'temperature': 0, 'max_tokens': args.max_tokens,
            'structured_output': args.structured,
            'output_schema_sha256': sha((args.out/'output_schema.json').read_bytes()) if args.structured != 'none' else None,
            'payload_sha256': registration['payload_sha256'], 'system_sha256': record['system_sha256'],
            'prompt_sha256': record['prompt_sha256'],
            'baseline_response_sha256': record['response_sha256'], 'elapsed_seconds': elapsed,
            'usage': final['usage'], 'finish_reason': final['finish_reason'],
            'reasoning_characters': final['reasoning_characters'],
            'request_extras': final['extra_body'], 'recorded_at': datetime.now(timezone.utc).isoformat(),
            'client_error': final.get('client_error'),
            'gold_sent': False,
        }
        status = save_arm(args.out, arm, output, expected_ids, metadata)
        if status == 'protocol_failure':
            failures.append(arm)
        print(f'{arm}: {status} in {elapsed:.2f}s', flush=True)
    if failures:
        raise SystemExit(3)


def request(args, arm, system, prompt, thinking):
    client = make_client(backend='dgx', endpoint=args.endpoint, model_override=args.model)
    original = client.oai.chat.completions.create
    observed = []

    def capture(**kwargs):
        kwargs['temperature'] = 0
        if args.structured == 'json-schema':
            kwargs['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'reference_relationships', 'strict': True, 'schema': output_schema()}}
        started = time.perf_counter()
        try:
            response = original(**kwargs)
        except Exception as error:
            observed.append({'status': 'error', 'error_type': type(error).__name__,
                             'elapsed_seconds': time.perf_counter()-started})
            raise
        choice = response.choices[0]
        message = choice.message.model_dump()
        reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
        observed.append({'status': 'response', 'response_id': response.id,
                         'served_model': response.model, 'finish_reason': choice.finish_reason,
                         'usage': response.usage.model_dump() if response.usage else None,
                         'elapsed_seconds': time.perf_counter()-started,
                         'reasoning_characters': len(reasoning),
                         'request_model': kwargs['model'], 'temperature': kwargs['temperature'],
                             'structured': args.structured,
                         'max_tokens': kwargs['max_tokens'], 'extra_body': kwargs.get('extra_body')})
        (args.out/f'{arm}.transport.json').write_text(json.dumps(observed, indent=2)+'\n')
        return response

    client.oai.chat.completions.create = capture
    started = time.perf_counter()
    print(f'{arm}: {args.model}, thinking={args.thinking}, endpoint={args.endpoint}', flush=True)
    try:
        output = call_api(client, system, prompt, args.model, max_tokens=args.max_tokens, thinking=thinking)
    except RuntimeError as error:
        if not observed or observed[-1].get('status') != 'response':
            raise
        observed[-1]['client_error'] = str(error)
        output = ''
    elapsed = time.perf_counter()-started
    return output, observed, elapsed


if __name__ == '__main__':
    main()
