"""Copy selected passages verbatim from the raw experiment responses."""

import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    choices=[
        ('valphine','c','Valphine — integrated line edit',
         '“He\'s just eating alone.', 'We leave him to his breakfast.',
         'The exchange is folded into readable prose while her private reading of obligation remains. The connection through the Sending Stone is explicit.'),
        ('vukradin','b','Vukradin — contextual dialogue edit',
         '“So it\'s a', 'The local I have approached',
         'The mistaken calculation and correction survive; accidental repetition is reduced. His practical self-commentary and the aside about Soma remain.'),
        ('zenvon','c','Zenvon — integrated line edit',
         'Pip’s advice from our discussion', 'So the distraction has a use after all.',
         'The retrospective tense is natural, his assessment remains, and “For the same output” keeps its separate landing.'),
    ]
    parts=['# Selected passages from the editing tests\n\nThese are copied exactly from the unedited model responses, not hand-combined or repaired. These selections show different strengths; they are not one universal winning approach.\n\n[Compare every complete draft](index.html) · [Review](review.md)']
    for case,arm,title,start,end,note in choices:
        text=(args.results/case/arm/'response.md').read_text()
        if text.count(start)!=1 or text.count(end)!=1:
            raise ValueError(f'Passage anchors are not unique: {case}')
        excerpt=text[text.index(start):text.index(end)].strip()
        parts.append(f'## {title}\n\n{note}\n\n[Full raw response]({case}/{arm}/response.md) · [All approaches](index.html#{case})\n\n{excerpt}')
    target=args.results/'passages.md'
    if target.exists():
        raise ValueError('Passages already exist; refusing to overwrite')
    target.write_text('\n\n'.join(parts)+'\n')
    print(target)


if __name__=='__main__':
    main()
