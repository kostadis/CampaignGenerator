"""Score displayed mneme verbatim hits; never infer coidentity from similarity."""
import re


def normalize(text):
    return ' '.join(text.split())


def parse_hits(output):
    # Related themes are model-tagged suggestions, not verbatim evidence.
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    output = output.split('  Related (LLM-tagged themes', 1)[0]
    header = re.compile(r'^  \[(\d+)\] ([^\n]+) / ([^\n]+)\n'
                        r'      Source: ([^\n]+)\n      Match: ([^\n]+)\n\n', re.M)
    starts = list(header.finditer(output))
    hits = []
    for i, match in enumerate(starts):
        body = output[match.end():starts[i+1].start() if i+1<len(starts) else len(output)]
        body = re.split(r'^  -{8,}\s*$', body, maxsplit=1, flags=re.M)[0]
        text = '\n'.join(line[6:] if line.startswith('      ') else line for line in body.splitlines()).strip()
        hits.append({'rank': int(match[1]), 'wing': match[2], 'room': match[3],
                     'source': match[4], 'match': match[5], 'text': text})
    return hits


def anchor(reference, passage, radius=60):
    return passage['text'][max(0, reference['start']-radius):reference['end']+radius]


def reference_ranks(reference, passage, hits):
    target = normalize(anchor(reference, passage))
    # The frozen corpus uses unique chapter-prefixed basenames. Require the
    # expected source chapter as well as exact normalized local target context.
    chapter = int(passage['chapter'])
    source_ranks, anchor_ranks = [], []
    for hit in hits:
        prefix = re.match(r'^(\d+)-', hit['source'])
        if not prefix or int(prefix[1]) != chapter:
            continue
        source_ranks.append(hit['rank'])
        if target in normalize(hit['text']):
            anchor_ranks.append(hit['rank'])
    return {'source_rank': min(source_ranks, default=None),
            'anchor_rank': min(anchor_ranks, default=None)}


def score_case(case, payload, hits, ks=(1, 5, 10)):
    refs = {r['id']: r for r in payload['references']}
    sides = {side: reference_ranks(refs[case[side]], payload['passages'][refs[case[side]]['passage']], hits)
             for side in ('left', 'right')}
    return {'id': case['id'], 'sides': sides,
            'coverage': {str(k): {
                'both_sources': all(v['source_rank'] is not None and v['source_rank'] <= k for v in sides.values()),
                'both_target_anchors': all(v['anchor_rank'] is not None and v['anchor_rank'] <= k for v in sides.values())}
                for k in ks}}
