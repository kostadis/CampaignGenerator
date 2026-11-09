from evaluate_large import metrics


def row(id, expected, predicted, valid=True, strict=True):
    return {'id':id,'expected':expected,'predicted':predicted,'evidence_valid':valid,'strict':strict}


def test_correct_relation_without_target_evidence_is_not_a_valid_success():
    result=metrics([row('a','same_referent','same_referent',valid=False)])
    assert result['strict_label_matches']==1
    assert result['strict_label_and_evidence_matches']==0
    assert result['all_evidence_failures']==['a']


def test_membership_is_not_coidentity_even_with_valid_quotes():
    result=metrics([row('a','overlap_or_membership','same_referent')])
    assert result['strict_false_coidentity']==['a']
    assert result['strict_label_matches']==0


def test_exploratory_success_does_not_inflate_strict_score():
    result=metrics([row('a','distinct_referents','same_referent'),
                    row('b','same_referent','same_referent',strict=False)])
    assert result['strict_cases']==1
    assert result['strict_label_matches']==0
    assert result['exploratory_label_matches']==1


def test_confident_distinctness_is_not_safe_abstention_on_an_unknown_link():
    result=metrics([row('a','ambiguous','distinct_referents')])
    assert result['abstentions']==0
    assert result['expected_ambiguous_nonabstentions']==['a']
    assert result['strict_false_coidentity']==[]
