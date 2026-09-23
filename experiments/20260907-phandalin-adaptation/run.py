"""One isolated narration experiment; never writes campaign or production files.

prepare freezes a Git snapshot and exact input messages without a model call.
render makes one text-only call through CampaignGenerator's existing adapter.
reader builds an offline comparison without editing the generated response.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CG = ROOT.parents[1]
REPO = Path('/home/kostadis/phandalin')
REF = 'bbf4e3c064b4e13b47ed523606a62936638a0cc6'
SESSION = 'Phandalin/summaries/20260902'
MODEL = 'gpt-6-astra'
EFFORT = 'medium'
SCENES = [
    ('01_rumors_and_preparations_at_the_common_chord.md', 'Vukradin — Patrons of the Chord'),
    ('02_the_sewer_stakeout.md', 'Vukradin — Nine Crates at Low Tide'),
    ('03_encounter_in_the_sewers.md', 'Vukradin — Lost in Rsolk’s Tunnels'),
    ('04_the_stakeout_of_denvar.md', 'Soma — Denvar’s Unsettled Account'),
    ('05_the_dead_drop_at_the_house_of_a_thousand_faces.md', 'Soma — Harpers Behind the Wall'),
]
VOICES = {
    'Vukradin': 'vukradin', 'Soma': 'soma',
    'Valphine Sotorra': 'valphine', 'Brewbarry': 'brewbarry',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode()
    with path.open('xb') as out:
        out.write(data)


def read_git(path):
    return subprocess.check_output(['git', '-C', str(REPO), 'show', f'{REF}:{path}'])


def prepare():
    if (ROOT / 'inputs').exists() or (ROOT / 'case.json').exists():
        raise ValueError('Prepared inputs already exist; use the frozen case or a fresh experiment directory')
    paths = [f'{SESSION}/scene_extractions_smoothed/{name}' for name, _ in SCENES]
    paths += [f'Phandalin/voice/{slug}_new_pipeline.md' for slug in VOICES.values()]
    paths += [f'Phandalin/examples/{slug}.md' for slug in ('vukradin', 'soma')]
    paths += ['Phandalin/voice/_genre.md', 'Phandalin/notes/scrub_register_policy.md',
              'Phandalin/config/party.yaml', 'Phandalin/config/players.yaml',
              f'{SESSION}/narration3/plan.md', f'{SESSION}/voice_smooth.sources.yaml',
              f'{SESSION}/session_doc.md']
    # Resolve every source before creating the snapshot.
    data = {path: read_git(path) for path in paths}
    manifest = {}
    for path, content in data.items():
        target = ROOT / 'inputs' / path
        save_new(target, content)
        manifest[str(target.relative_to(ROOT))] = sha(content)
    refs = []
    for name, slug in VOICES.items():
        source = data[f'Phandalin/voice/{slug}_new_pipeline.md'].decode()
        starts = list(re.finditer(r'(?m)^[^\n]+ voice specification:\n', source))
        if len(starts) != 1 or '\nFailure-prevention rules:' not in source:
            raise ValueError(f'Unrecognized explicitly declared voice structure: {name}')
        description = source[starts[0].end():].split('\nFailure-prevention rules:', 1)[0].strip()
        refs.append(f'## {name}\n\n{description}')
    references = '\n\n'.join(refs) + '\n'
    save_new(ROOT / 'character_references.md', references)
    baseline = data[f'{SESSION}/session_doc.md']
    save_new(ROOT / 'baseline.md', baseline)
    user = [
        '# Chapter to write\n\n# Chapter 51: We’re famous. Why are we famous?',
        '## Fixed section headings\n\n' + '\n'.join('## ' + title for _, title in SCENES),
        '## Campaign style\n\n' + (ROOT / 'campaign_style.md').read_text(),
        '# Character descriptions\n\n' + references,
        '# Fixed POV plan\n\n' + data[f'{SESSION}/narration3/plan.md'].decode(),
    ]
    for slug in ('vukradin', 'soma'):
        user.append(f'# Established prose examples: {slug}\n\n'
                    'Style reference only; these are other events, not this session.\n\n'
                    + data[f'Phandalin/examples/{slug}.md'].decode())
    for name, title in SCENES:
        user.append(f'# Reviewed source for {title}\n\n'
                    + data[f'{SESSION}/scene_extractions_smoothed/{name}'].decode())
    save_new(ROOT / 'user_prompt.md', '\n\n---\n\n'.join(user) + '\n')
    for name in ('run.py', 'system_prompt.md', 'campaign_style.md',
                 'character_references.md', 'user_prompt.md', 'baseline.md'):
        manifest[name] = sha((ROOT / name).read_bytes())
    case = {
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'campaign_repository': str(REPO), 'campaign_commit': REF,
        'generator_commit': subprocess.check_output(['git', '-C', str(CG), 'rev-parse', 'HEAD'], text=True).strip(),
        'model': MODEL, 'reasoning_effort': EFFORT, 'backend': 'codex-cli',
        'input_sha256': manifest, 'scene_headings': [title for _, title in SCENES],
        'design': 'One complete chapter from five frozen reviewed smoothed extractions; existing POV plan retained. Baseline is for comparison only and is not sent to the model.',
        'treatment': 'New adaptation contract; actual character-description sections; concise synthesized campaign style; unchanged declared narrator examples and source extractions.',
        'limits': 'Exploratory comparison to an existing edited chapter, not a controlled or repeated A/B. This changes several prompt/reference choices together. Historical baseline model is not attested.',
        'max_tokens_argument': 32000,
        'token_limit_note': 'The Codex subscription adapter accepts but does not enforce the API-style max_tokens argument.',
    }
    save_new(ROOT / 'case.json', json.dumps(case, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'status': 'prepared', 'sources': len(paths),
                      'system_words': len((ROOT / 'system_prompt.md').read_text().split()),
                      'user_words': len((ROOT / 'user_prompt.md').read_text().split())}, indent=2))


def verify(case):
    changed = [p for p, expected in case['input_sha256'].items()
               if sha((ROOT / p).read_bytes()) != expected]
    if changed:
        raise ValueError(f'Frozen inputs changed: {changed}')


def render():
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    if (ROOT / 'run.json').exists() or (ROOT / 'response.md').exists():
        raise ValueError('A model attempt already exists; preserve it and use a new attempt directory')
    sys.path.insert(0, str(CG))
    from campaignlib import make_client, call_api
    os.environ.setdefault('CG_CODEX_TIMEOUT', '1800')
    run = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
           'case_sha256': sha((ROOT / 'case.json').read_bytes()),
           'requested_model': MODEL, 'requested_reasoning_effort': EFFORT,
           'backend': 'codex-cli'}
    def save_run():
        (ROOT / 'run.json').write_text(json.dumps(run, indent=2, ensure_ascii=False) + '\n')
    save_run()
    try:
        client = make_client(backend='codex-cli', model_override=MODEL,
                             reasoning_effort=EFFORT, reasoning_effort_source='cli')
        response = call_api(client, (ROOT / 'system_prompt.md').read_text(),
                            (ROOT / 'user_prompt.md').read_text(), MODEL, max_tokens=32000)
        save_new(ROOT / 'response.md', response)
        run['response_sha256'] = sha(response.encode())
        run['actual_identity'] = client.last_run_identity.as_dict()
        if run['actual_identity']['model'] != MODEL or run['actual_identity']['codex_reasoning_effort'] != EFFORT:
            raise ValueError('Backend selection differs from the requested experiment')
        verify(case)
        run['headings'] = re.findall(r'^## (.+)$', response, re.M)
        if run['headings'] != case['scene_headings']:
            raise ValueError('Generated section headings differ from the fixed five-scene plan; raw response preserved')
        run['status'] = 'rendered'
    except BaseException as exc:
        run['status'] = 'failed'
        run['error'] = str(exc)
        raise
    finally:
        run['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_run()
    print(json.dumps(run, indent=2, ensure_ascii=False))


def metrics(text):
    text = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text)
                  if p.strip() and not p.strip().startswith(('#', '---'))]
    quotes = [p for p in paragraphs if p.startswith(('"', '“', '‘'))]
    return {'words': len(text.split()), 'paragraphs': len(paragraphs),
            'median_paragraph_words': statistics.median(len(p.split()) for p in paragraphs),
            'quote_led_paragraphs': len(quotes),
            'quote_led_at_most_5_words': sum(len(p.split()) <= 5 for p in quotes)}


def reader():
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    run = json.loads((ROOT / 'run.json').read_text())
    if run['status'] != 'rendered' or sha((ROOT / 'response.md').read_bytes()) != run['response_sha256']:
        raise ValueError('No completed unchanged response to compare')
    texts = {key: (ROOT / name).read_text() for key, name in [('baseline', 'baseline.md'), ('adaptation', 'response.md')]}
    counts = {key: metrics(value) for key, value in texts.items()}
    save_new(ROOT / 'metrics.json', json.dumps(counts, indent=2) + '\n')
    def sections(text):
        return {m.group(1): m.group(2).strip() for m in re.finditer(r'^## (.+)\n(.*?)(?=^## |\Z)', text, re.M | re.S)}
    bodies = {key: sections(value) for key, value in texts.items()}
    blocks = []
    for index, (name, title) in enumerate(SCENES, 1):
        source = (ROOT / 'inputs' / SESSION / 'scene_extractions_smoothed' / name).read_text()
        panes = ''.join(f'<article><h3>{label}</h3><div class="prose">{html.escape(bodies[key][title])}</div></article>'
                        for key, label in [('baseline', 'Existing final chapter'), ('adaptation', 'New adaptation — unedited')])
        blocks.append(f'<section id="scene-{index}"><h2>{html.escape(title)}</h2><div class="columns">{panes}</div>'
                      f'<details><summary>Reviewed source extraction</summary><pre>{html.escape(source)}</pre></details></section>')
    nav = ' · '.join(f'<a href="#scene-{i}">Scene {i}</a>' for i in range(1, 6))
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phandalin: factual record to literary adaptation</title>
<style>body{max-width:1500px;margin:2rem auto;padding:0 1.5rem;background:#faf8f3;color:#292825;font:17px/1.55 system-ui,sans-serif}a{color:#285666}nav{position:sticky;top:0;padding:.8rem;background:#faf8f3;border-bottom:1px solid #ddd8cc}.columns{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}article{min-width:0;background:#fff;padding:1.5rem;border:1px solid #ddd8cc}.prose{white-space:pre-wrap;overflow-wrap:anywhere;font:19px/1.65 Georgia,serif}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui,sans-serif}section{margin-top:3rem;scroll-margin-top:5rem}h1{line-height:1.2}details{margin:1.5rem 0}summary{cursor:pointer}@media(max-width:850px){.columns{grid-template-columns:1fr}}</style></head><body>
<h1>Phandalin: from the factual record to a story</h1><p>One new gpt-6-astra / medium chapter from the five reviewed smoothed extractions. The existing chapter was not shown to the narrator. The new response is preserved unedited and is not campaign canon.</p>
<p><a href="response.md">Read the new chapter</a> · <a href="review.md">Read the evaluation</a> · <a href="system_prompt.md">Writing contract</a> · <a href="case.json">Frozen inputs and limitations</a></p>
'''+f'<nav>{nav}</nav>'+''.join(blocks)+'</body></html>\n'
    save_new(ROOT / 'comparison.html', page)
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'render', 'reader'])
    globals()[parser.parse_args().action]()
