"""Apply the unchanged evaluator and compare local modes with the frozen baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

PREVIOUS = Path(__file__).resolve().parent.parent/'20261103-summary-entity-resolution'
sys.path.insert(0, str(PREVIOUS))
from evaluate import evaluate


def metric(report):
    context = report['arms']['context']
    control = report['arms']['surface_only']
    return {'strict_exact_matches': context['strict_exact_matches'],
            'strict_label_and_evidence_matches': sum(r['strict_source_expectation'] and
                  r['matches_draft_expectation'] and r['evidence_check']['valid'] for r in context['results']),
            'strict_cases': context['strict_cases'],
            'evidence_failures': context['evidence_failures'],
            'strict_false_coidentity': context['strict_false_coidentity'],
            'surface_only_abstentions': control['abstentions'],
            'exploratory_unresolved_coidentity': [r['id'] for r in context['results']
                  if not r['strict_source_expectation'] and r['draft_expected_relation'] == 'ambiguous'
                  and r['relation'] == 'same_referent'],
            'exploratory': [{'id': r['id'], 'relation': r['relation'],
                             'draft_expected': r['draft_expected_relation'],
                             'reason': r['reason']}
                            for r in context['results'] if not r['strict_source_expectation']],
            'coidentity_conflicts': report['candidate_graph']['coidentity_distinctness_conflicts']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--local', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads((args.baseline/'report.json').read_text())
    base_metrics = metric(baseline)
    modes = []
    for run in args.local:
        measurements = {}
        records = {arm: json.loads((run/f'{arm}.record.json').read_text()) for arm in ('context', 'surface_only')}
        for arm in ('context', 'surface_only'):
            record = records[arm]
            original = baseline['arms'][arm]['model_record']
            for key in ('system_sha256', 'prompt_sha256', 'payload_sha256'):
                if record[key] != original[key]:
                    raise ValueError(f'{arm} input differs from frozen baseline: {key}')
            measurements[arm] = {key: record[key] for key in ('model', 'served_model', 'thinking',
                    'temperature', 'max_tokens', 'elapsed_seconds', 'usage', 'finish_reason',
                    'reasoning_characters', 'request_extras')}
            measurements[arm]['structured_output'] = record.get('structured_output', 'none')
            measurements[arm]['output_schema_sha256'] = record.get('output_schema_sha256')
            measurements[arm]['status'] = record['status']
        failures = {arm: {'status': rec['status'], 'error': rec.get('error'),
                          'raw_response_sha256': rec.get('raw_response_sha256')}
                    for arm, rec in records.items() if rec['status'] == 'protocol_failure'}
        if failures:
            control_path = run/'surface_only.response.json'
            control_abstentions = None
            if control_path.exists():
                control_data = json.loads(control_path.read_text())
                control_abstentions = sum(row['relation'] == 'ambiguous' for row in control_data['results'])
            modes.append({'run': str(run), 'metrics': {'strict_exact_matches': None,
                         'strict_cases': base_metrics['strict_cases'], 'surface_only_abstentions': control_abstentions,
                         'protocol_failures': failures}, 'measurements': measurements,
                         'matches_baseline_on_this_test': False, 'differences': [],
                         'report_sha256': None})
            continue
        result = evaluate(run)
        metrics = metric(result)
        parity = (metrics['strict_exact_matches'] >= base_metrics['strict_exact_matches']
                  and not metrics['evidence_failures']
                  and not metrics['strict_false_coidentity']
                  and not metrics['coidentity_conflicts']
                  and not metrics['exploratory_unresolved_coidentity']
                  and metrics['surface_only_abstentions'] >= base_metrics['surface_only_abstentions'])
        differences = []
        for original, local in zip(baseline['arms']['context']['results'], result['arms']['context']['results']):
            if original['id'] != local['id']:
                raise ValueError('comparison case order differs')
            if original['relation'] != local['relation'] or not local['evidence_check']['valid']:
                differences.append({'id': local['id'], 'strict': local['strict_source_expectation'],
                                    'draft_expected': local['draft_expected_relation'],
                                    'baseline': original['relation'], 'local': local['relation'],
                                    'evidence_errors': local['evidence_check']['errors'],
                                    'reason': local['reason']})
        modes.append({'run': str(run), 'metrics': metrics, 'measurements': measurements,
                      'matches_baseline_on_this_test': parity, 'differences': differences,
                      'report_sha256': hashlib.sha256((run/'report.json').read_bytes()).hexdigest()})
    output = {'baseline_model': 'gpt-6.1-sol', 'baseline_effort': 'medium',
              'baseline_metrics': base_metrics, 'local_modes': modes,
              'criteria': 'Complete parseable outputs; 13/13 stricter source expectations; zero quotation/target failures, strict false coidentity or graph conflicts; 16/16 words-only abstentions; no new exact-identity assertion on the unresolved exploratory membership case.',
              'limits': ['Small researcher-scored fixture, not general model equivalence or GM adjudication.',
                         'Prompts, systems, payload, draft gold, case order and evaluator are unchanged.',
                         'Codex medium and local thinking modes are not matched compute budgets.',
                         'Local elapsed time is measured; no comparable Codex timing was recorded.',
                         'The local server is shared and requests may overlap; elapsed times are observational, not isolated throughput benchmarks.',
                         'The structured follow-up adds native output-schema enforcement; system and user text remain byte-identical.',
                         'Source-backed candidate proposals remain unreviewed; no registry changes.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'baseline': base_metrics, 'local_modes': [
        {'thinking': m['measurements']['context']['thinking'], 'metrics': m['metrics'],
         'matches_baseline_on_this_test': m['matches_baseline_on_this_test'], 'differences': m['differences']}
        for m in modes]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
