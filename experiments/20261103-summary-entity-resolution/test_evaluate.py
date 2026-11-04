from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from evaluate import validate_evidence, candidate_graph
from prepare_cases import explicit_targets


def fixture():
    payload = {'passages': {'a': {'text': 'An ogre whistles in the hills.'},
                            'b': {'text': 'A second ogre blocks the pass.'}},
               'references': [{'id': 'r1', 'passage': 'a', 'start': 3, 'end': 7},
                              {'id': 'r2', 'passage': 'b', 'start': 9, 'end': 13}]}
    case = {'id': 'q1', 'left': 'r1', 'right': 'r2'}
    result = {'id': 'q1', 'relation': 'distinct_referents',
              'left_context': {'granularity': 'individual'},
              'right_context': {'granularity': 'individual'},
              'evidence': [{'reference': 'r1', 'quote': 'An ogre whistles in the hills.'},
                           {'reference': 'r2', 'quote': 'A second ogre blocks the pass.'}]}
    return payload, case, result


def test_verbatim_evidence_and_two_sides():
    payload, case, result = fixture()
    checked = validate_evidence(result, case, payload)
    assert checked['valid'] and len(checked['checked_spans']) == 2


def test_invented_quote_fails():
    payload, case, result = fixture()
    result['evidence'][0]['quote'] = 'The ogre is named John.'
    assert not validate_evidence(result, case, payload)['valid']


def test_single_side_is_not_enough():
    payload, case, result = fixture()
    result['evidence'].pop()
    assert not validate_evidence(result, case, payload)['valid']


def test_true_quote_about_wrong_mention_fails():
    payload, case, result = fixture()
    payload['passages']['a']['text'] += ' Another ogre carries a club.'
    result['evidence'][0]['quote'] = 'Another ogre carries a club.'
    check = validate_evidence(result, case, payload)
    assert not check['valid']
    assert any('does not cover marked reference' in error for error in check['errors'])


def test_membership_is_not_identity_merge():
    cases = [{'id': 'q1', 'left': 'a', 'right': 'b'}]
    results = [{'id': 'q1', 'relation': 'overlap_or_membership', 'evidence_check': {'valid': True}}]
    graph = candidate_graph(results, cases)
    assert not any(set(group) == {'a', 'b'} for group in graph['coidentity_candidate_clusters'])


def test_bad_evidence_cannot_create_coidentity_cluster():
    cases = [{'id': 'q1', 'left': 'a', 'right': 'b'}]
    results = [{'id': 'q1', 'relation': 'same_referent', 'evidence_check': {'valid': False}}]
    graph = candidate_graph(results, cases)
    assert not any(set(group) == {'a', 'b'} for group in graph['coidentity_candidate_clusters'])


def test_transitive_coidentity_contradiction_reported():
    cases = [{'id': 'q1', 'left': 'a', 'right': 'b'},
             {'id': 'q2', 'left': 'b', 'right': 'c'},
             {'id': 'q3', 'left': 'a', 'right': 'c'}]
    results = [{'id': q, 'relation': r, 'evidence_check': {'valid': True}}
               for q, r in [('q1', 'same_referent'), ('q2', 'same_referent'), ('q3', 'distinct_referents')]]
    assert candidate_graph(results, cases)['coidentity_distinctness_conflicts'] == ['q3']


def test_group_and_individual_cannot_merge():
    payload, case, result = fixture()
    result['relation'] = 'same_referent'
    result['left_context']['granularity'] = 'group'
    assert not validate_evidence(result, case, payload)['valid']


def test_ambiguity_does_not_require_fabricated_positive_quote():
    payload, case, result = fixture()
    result['relation'] = 'ambiguous'
    result['evidence'] = []
    assert validate_evidence(result, case, payload)['valid']


def test_explicit_target_display_preserves_raw_text_and_offsets():
    payload, _, _ = fixture()
    output = explicit_targets(payload)
    for reference in output['references']:
        assert reference['surface'] == 'ogre'
        assert '[[TARGET]]ogre[[/TARGET]]' in reference['marked_excerpt']
    assert output['passages'] == payload['passages']
    assert 'surface' not in payload['references'][0]
