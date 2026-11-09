from retrieval import parse_hits, score_case
import hashlib
import json

import pytest
from expand_sources import expand


def hit(text, source='004-session.md'):
    return f'  [1] summaries / party\n      Source: {source}\n      Match: cosine_sim=0.8  bm25=1.2\n\n      {text}\n\n  --------------------------------------------------------\n'


def fixture():
    return {'id':'q','left':'a','right':'b'}, {
        'passages':{'p':{'chapter':4,'text':'The first ogre fell. The second ogre ran.'}},
        'references':[{'id':'a','passage':'p','start':10,'end':14},
                      {'id':'b','passage':'p','start':31,'end':35}]}


def test_related_theme_is_never_verbatim_evidence():
    case,payload=fixture()
    text=payload['passages']['p']['text']
    output=hit('Unrelated passage.')+'  Related (LLM-tagged themes — review before drilling in)\n'+hit(text)
    hits=parse_hits(output)
    assert len(hits)==1
    assert not score_case(case,payload,hits)['coverage']['10']['both_target_anchors']


def test_matching_words_in_wrong_chapter_do_not_cover_targets():
    case,payload=fixture()
    hits=parse_hits(hit(payload['passages']['p']['text'],source='018-session.md'))
    scored=score_case(case,payload,hits)
    assert not scored['coverage']['10']['both_sources']
    assert not scored['coverage']['10']['both_target_anchors']


def test_source_hit_does_not_imply_target_coverage():
    case,payload=fixture()
    scored=score_case(case,payload,parse_hits(hit('A different ogre in the same chapter.')))
    assert scored['coverage']['1']['both_sources']
    assert not scored['coverage']['1']['both_target_anchors']


def test_verbatim_both_targets_and_whitespace_normalization():
    case,payload=fixture()
    hits=parse_hits(hit('The first ogre fell.\n      The second ogre ran.'))
    assert score_case(case,payload,hits)['coverage']['1']['both_target_anchors']


def expansion_fixture(tmp_path):
    case,payload=fixture()
    payload['cases']=[case]
    run=tmp_path/'run';run.mkdir()
    (run/'payload.json').write_text(json.dumps(payload))
    stdout=hit('Different source text.',source='018-session.md')
    (run/'request.stdout.txt').write_text(stdout)
    (run/'request.record.json').write_text(json.dumps({'returncode':0,
        'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest()}))
    (run/'registration.json').write_text(json.dumps({'payload_sha256':hashlib.sha256((run/'payload.json').read_bytes()).hexdigest(),
        'requests':{'request':'query'},'case_requests':{'q':{'bare':'request','context':'request'}}}))
    source=tmp_path/'campaign';source.mkdir()
    files=[]
    for name,text in [('004-session.md',payload['passages']['p']['text']),('018-session.md','Different source text.')]:
        (source/name).write_text(text)
        files.append({'path':name,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    toc=tmp_path/'toc.json'
    toc.write_text(json.dumps({'valid':True,'findings':[],'kinds':{'summaries':{'files':files}}}))
    return run,toc,source


def test_expansion_does_not_open_expected_but_unretrieved_source(tmp_path):
    run,toc,source=expansion_fixture(tmp_path)
    report=expand(run,toc,source)
    assert set(report['opened_sources'])=={'018-session.md'}
    assert report['modes']['context']['both_target_anchors_after_expansion']['10']==0


def test_expansion_refuses_source_changed_since_toc(tmp_path):
    run,toc,source=expansion_fixture(tmp_path)
    (source/'018-session.md').write_text('Edited after TOC.')
    with pytest.raises(AssertionError):
        expand(run,toc,source)


def test_expansion_refuses_ambiguous_source_basename(tmp_path):
    run,toc,source=expansion_fixture(tmp_path)
    data=json.loads(toc.read_text())
    data['kinds']['summaries']['files'].append({'path':'elsewhere/018-session.md','sha256':'unknown'})
    toc.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='ambiguous'):
        expand(run,toc,source)
