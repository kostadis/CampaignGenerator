"""Blind readers across all three renderers. No model calls, no network.

Collects the nine drafts produced from one set of frozen messages — three
renderers x (one chapter + two single-scene arms) — verifies every one against
the hash its own run recorded, and lays them out for reading without telling the
reader which is which.

    astra   codex-cli / gpt-6-astra / medium          (archived, campaigns#237)
    fable   claude-code / claude-fable-5-1 / medium
    spark   dgx / DeepSeek-V4-Flash-0731 / no effort dial

One draft needs adjudicating rather than accepting. The fable chapter run
recorded `failed`: its structural check compared headings verbatim, and fable
spells `Rsolk's` where the plan spells `Rsolk’s`. The chapter is complete and
correctly ordered. This script re-derives that from the preserved response and
admits the draft only if the sole difference is typography — never on the
strength of the earlier run's say-so, and never by editing that run's record,
which stays as the honest report of what its check actually found.
"""
import hashlib
import html
import json
from pathlib import Path
import re
import secrets
import statistics

ROOT = Path(__file__).resolve().parent
EXPERIMENTS = ROOT.parent
CHAPTER_SRC = EXPERIMENTS / '20260907-phandalin-adaptation'
SCENE_SRC = EXPERIMENTS / '20260907-phandalin-scene-composition'
FABLE = EXPERIMENTS / '20260907-phandalin-fable-medium'

# key -> (response file, run.json holding its hash)
DRAFTS = {
    'astra:chapter': (CHAPTER_SRC / 'response.md', CHAPTER_SRC / 'run.json'),
    'astra:control': (SCENE_SRC / 'control/response.md', SCENE_SRC / 'control/run.json'),
    'astra:composition': (SCENE_SRC / 'composition/response.md', SCENE_SRC / 'composition/run.json'),
    'fable:chapter': (FABLE / 'chapter/response.md', FABLE / 'chapter/run.json'),
    'fable:control': (FABLE / 'control/response.md', FABLE / 'control/run.json'),
    'fable:composition': (FABLE / 'composition/response.md', FABLE / 'composition/run.json'),
    'spark:chapter': (ROOT / 'chapter/response.md', ROOT / 'chapter/run.json'),
    'spark:control': (ROOT / 'control/response.md', ROOT / 'control/run.json'),
    'spark:composition': (ROOT / 'composition/response.md', ROOT / 'composition/run.json'),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode() if isinstance(value, str) else value
    with path.open('xb') as handle:
        handle.write(data)


def normalize(text):
    return (text.replace('’', "'").replace('‘', "'")
                .replace('“', '"').replace('”', '"'))


def adjudicate(key, run, text, expected_headings, is_scene):
    """Return (admitted, record). A `failed` run is admitted only on proof.

    Three outcomes, and the difference between the last two is the point:

    - accepted    — the run's own check passed.
    - typography  — the sections are all there in order and differ only in
                    apostrophe style. A rejection over two characters.
    - contract    — the model did not follow the output contract. Admitted for
                    prose comparison when the shape is still one scene of
                    narration, and recorded as a violation, because excluding it
                    would hide the finding rather than report it.
    """
    record = {'draft': key, 'recorded_status': run['status'],
              'headings_found': re.findall(r'^#{1,6} .+$', text, re.M)}
    if run['status'] == 'rendered':
        record['verdict'] = 'accepted — its own run recorded success'
        return True, record
    record['expected_headings'] = expected_headings
    record['recorded_error'] = run.get('error')
    found = re.findall(r'^#{1,6} (.+)$' if is_scene else r'^## (.+)$', text, re.M)
    if [normalize(h) for h in found] == [normalize(h) for h in expected_headings]:
        differing = [{'expected': e, 'found': f}
                     for e, f in zip(expected_headings, found) if e != f]
        record['headings_differing_by_typography_only'] = differing
        record['verdict'] = (f'admitted — all {len(found)} sections present and in order; '
                             f'{len(differing)} heading(s) differ only in apostrophe style')
        return True, record
    if is_scene and len(record['headings_found']) == 1:
        record['contract_violation'] = (
            'The system prompt required "Output only the finished scene under the supplied '
            'section heading. Do not include a chapter title." The supplied heading was '
            f'{expected_headings[0]!r}; the model emitted {found[0]!r} instead. The body is '
            'still a single unbroken scene, so the prose is comparable, but this is an '
            'instruction-following failure and is reported as one.')
        record['verdict'] = 'admitted for prose comparison — output contract not followed'
        return True, record
    record['verdict'] = 'rejected — section structure genuinely differs'
    return False, record


def strip_leading_heading(text):
    """Drop a scene draft's opening heading line, for display only.

    Every scene draft is one scene under one heading, so the heading carries no
    prose. It does carry identity: one model wrote its own title instead of the
    supplied one, and leaving the headings in would let a reader pick that draft
    out of the blind panel on sight. Stripping uniformly keeps the blind read
    blind. Stored responses are untouched; the actual headings are in
    adjudication.json.
    """
    lines = text.lstrip().split('\n')
    if lines and lines[0].startswith('#'):
        lines = lines[1:]
    return '\n'.join(lines).strip()


def metrics(text):
    text = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text)
                  if p.strip() and not p.strip().startswith(('#', '---'))]
    quotes = [p for p in paragraphs if p.startswith(('"', '“', '‘'))]
    return {'words': len(text.split()), 'paragraphs': len(paragraphs),
            'median_paragraph_words': statistics.median(len(p.split()) for p in paragraphs),
            'quote_led_paragraphs': len(quotes),
            'quote_led_at_most_5_words': sum(len(p.split()) <= 5 for p in quotes),
            'typographic_apostrophes': text.count('’'),
            'ascii_apostrophes': text.count("'")}


def page(title, intro, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>'
            'body{max-width:1800px;margin:2rem auto;padding:0 1.5rem;background:#faf8f3;'
            'color:#292825;font:17px/1.55 system-ui,sans-serif}h1{line-height:1.2}'
            '.columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:1.5rem}'
            'article{min-width:0;background:#fff;padding:1.5rem;border:1px solid #ddd8cc}'
            '.prose{white-space:pre-wrap;overflow-wrap:anywhere;font:19px/1.65 Georgia,serif}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui,sans-serif}'
            'section{margin-top:2rem}details{margin:1.5rem 0}summary{cursor:pointer}'
            '.note{background:#fff6e0;border:1px solid #e6d9b0;padding:1rem}'
            '</style></head><body>'
            f'<h1>{html.escape(title)}</h1>{intro}{body}</body></html>')


def main():
    chapter_case = json.loads((CHAPTER_SRC / 'case.json').read_text())
    scene_case = json.loads((SCENE_SRC / 'case.json').read_text())
    expected = {'chapter': chapter_case['scene_headings'],
                'control': [scene_case['scene_heading']],
                'composition': [scene_case['scene_heading']]}

    texts, adjudications, missing = {}, [], []
    for key, (response_path, run_path) in DRAFTS.items():
        if not response_path.exists():
            missing.append(key)
            continue
        run = json.loads(run_path.read_text())
        text = response_path.read_text()
        if sha(text.encode()) != run['response_sha256']:
            raise ValueError(f'{key}: response does not match its recorded hash — edited?')
        arm = key.split(':')[1]
        admitted, record = adjudicate(key, run, text, expected[arm], arm != 'chapter')
        adjudications.append(record)
        if admitted:
            texts[key] = text
        else:
            missing.append(key)
    save_new(ROOT / 'adjudication.json', json_text(
        {'admitted': sorted(texts), 'not_admitted': sorted(missing),
         'records': adjudications}))
    if missing:
        print(json_text({'warning': 'building with drafts missing', 'missing': sorted(missing)}))

    historical = (CHAPTER_SRC / 'baseline.md').read_text()
    save_new(ROOT / 'metrics_all.json', json_text(
        {k: metrics(v) for k, v in sorted({**texts, 'historical:chapter': historical}.items())}))

    scene_keys = sorted(k for k in texts if not k.endswith(':chapter'))
    chapter_keys = sorted(k for k in texts if k.endswith(':chapter'))
    rng = secrets.SystemRandom()
    rng.shuffle(scene_keys)
    rng.shuffle(chapter_keys)
    labels = 'ABCDEFGHIJ'
    assignment = {
        'scene': {labels[i]: k for i, k in enumerate(scene_keys)},
        'chapter': {f'C{i + 1}': k for i, k in enumerate(chapter_keys)},
    }
    save_new(ROOT / 'combined_assignment.json', json_text(assignment))

    def panel(label, text):
        return (f'<article><h3>{html.escape(label)}</h3>'
                f'<div class="prose">{html.escape(text.strip())}</div></article>')

    panes = ''.join(panel(f'Draft {lab}', strip_leading_heading(texts[k]))
                    for lab, k in sorted(assignment['scene'].items()))
    source = (SCENE_SRC / 'inputs/source.md').read_text()
    save_new(ROOT / 'scene_blind_all.html', page(
        f'Blind read — {scene_case["scene_heading"]}',
        f'<p class="note">{len(scene_keys)} unedited single-scene drafts: three renderers '
        'across two prompt arms, randomly labelled. Identical source extraction, POV plan, '
        'examples and factual constraints throughout. Each draft\'s opening heading line is '
        'removed here, uniformly, so that no draft can be identified by its heading; the '
        'prose is otherwise unedited. Read all of them before opening '
        '<code>combined_assignment.json</code>.</p>',
        f'<section><div class="columns">{panes}</div>'
        f'<details><summary>Reviewed source extraction</summary>'
        f'<pre>{html.escape(source)}</pre></details></section>'))

    panes = ''.join(panel(f'Draft {lab}', texts[k])
                    for lab, k in sorted(assignment['chapter'].items()))
    panes += panel('The edited chapter that shipped (known baseline)', historical)
    save_new(ROOT / 'chapter_blind_all.html', page(
        'Blind read — Chapter 51, five scenes',
        f'<p class="note">{len(chapter_keys)} unedited generated chapters from identical '
        'messages, randomly labelled, beside the edited chapter that actually shipped. The '
        'baseline is openly labelled — its length and quote density identify it anyway.</p>',
        f'<section><div class="columns">{panes}</div></section>'))

    print(json_text({'status': 'built', 'drafts': len(texts),
                     'scene_drafts': len(scene_keys), 'chapter_drafts': len(chapter_keys),
                     'files': ['adjudication.json', 'metrics_all.json',
                               'combined_assignment.json', 'scene_blind_all.html',
                               'chapter_blind_all.html']}))


if __name__ == '__main__':
    main()
