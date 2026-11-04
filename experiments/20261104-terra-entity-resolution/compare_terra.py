"""Score the requested Terra run against the frozen Sol and local-model trials."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

EXPERIMENTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXPERIMENTS/'20261103-summary-entity-resolution'))
from evaluate import evaluate
sys.path.insert(0, str(EXPERIMENTS/'20261104-local-entity-resolution'))
from compare import metric


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(baseline, terra, local_comparison):
    base = json.loads((baseline/'report.json').read_text())
    result = evaluate(terra)
    for arm in ('context', 'surface_only'):
        old = base['arms'][arm]['model_record']
        new = result['arms'][arm]['model_record']
        assert new['model'] == 'gpt-6.1-terra' and new['effort'] == 'medium'
        for key in ('system_sha256', 'prompt_sha256', 'payload_sha256'):
            assert old[key] == new[key], f'{arm} task input changed: {key}'
    assert sha(baseline/'gold.json') == sha(terra/'gold.json'), 'hidden gold changed'
    differences = []
    for a, b in zip(base['arms']['context']['results'], result['arms']['context']['results']):
        assert a['id'] == b['id']
        if a['relation'] != b['relation'] or not b['evidence_check']['valid']:
            differences.append({'id': b['id'], 'strict': b['strict_source_expectation'],
                                'draft_expected': b['draft_expected_relation'], 'sol': a['relation'],
                                'terra': b['relation'], 'evidence_errors': b['evidence_check']['errors']})
    local = json.loads(local_comparison.read_text())
    def strip_reason(value):
        if isinstance(value, dict):
            return {k: strip_reason(v) for k, v in value.items() if k != 'reason'}
        if isinstance(value, list):
            return [strip_reason(v) for v in value]
        return value
    return {'sol_medium': strip_reason(metric(base)), 'terra_medium': strip_reason(metric(result)),
            'qwen_configs': [{'thinking': m['measurements']['context']['thinking'],
                              'structured_output': m['measurements']['context'].get('structured_output', 'none'),
                              'metrics': strip_reason(m['metrics'])} for m in local['local_modes']],
            'terra_vs_sol_differences': differences,
            'input_equality_verified': True, 'gold_sha256': sha(terra/'gold.json'),
            'model_records': {a: result['arms'][a]['model_record'] for a in ('context', 'surface_only')},
            'report_sha256': sha(terra/'report.json'),
            'limits': ['Small researcher-scored fixture; no independent GM adjudication or general model ranking.',
                       'Same exact task text and hidden expectations; model providers/settings are recorded.',
                       'Three exploratory cases remain separate from the thirteen clearer source expectations.',
                       'Experimental reference relationships only; no canonical registry writes.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--terra', type=Path, required=True)
    parser.add_argument('--local-comparison', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.baseline, args.terra, args.local_comparison)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('sol_medium', 'terra_medium', 'terra_vs_sol_differences')}, indent=2))


if __name__ == '__main__':
    main()
