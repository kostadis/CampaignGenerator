"""Offline comparison only; preserve the frozen runner and raw model response.

The original reader's heading regex used DOTALL with a greedy heading capture.
This post-run helper fixes presentation without altering the experiment inputs.
"""
import html
import json
import re

from run import ROOT, SCENES, SESSION, metrics, save_new, sha, verify


def sections(text):
    pairs = re.findall(r'^## ([^\r\n]+)\r?\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if [title for title, _ in pairs] != [title for _, title in SCENES]:
        raise ValueError('Comparison requires the exact five headings in order')
    return {title: body.strip() for title, body in pairs}


def main():
    case = json.loads((ROOT / 'case.json').read_text())
    run = json.loads((ROOT / 'run.json').read_text())
    verify(case)
    if sha((ROOT / 'case.json').read_bytes()) != run['case_sha256']:
        raise ValueError('Case changed after generation')
    if run['status'] != 'rendered' or sha((ROOT / 'response.md').read_bytes()) != run['response_sha256']:
        raise ValueError('Completed unchanged response required')
    texts = {key: (ROOT / name).read_text() for key, name in
             [('baseline', 'baseline.md'), ('adaptation', 'response.md')]}
    counts = {key: metrics(value) for key, value in texts.items()}
    if json.loads((ROOT / 'metrics.json').read_text()) != counts:
        raise ValueError('Saved metrics differ from current texts')
    bodies = {key: sections(value) for key, value in texts.items()}
    blocks = []
    for index, (name, title) in enumerate(SCENES, 1):
        panes = ''.join(
            f'<article><h3>{label}</h3><div class="prose">{html.escape(bodies[key][title])}</div></article>'
            for key, label in [('baseline', 'Existing final chapter'),
                               ('adaptation', 'New adaptation — unedited')])
        source = (ROOT / 'inputs' / SESSION / 'scene_extractions_smoothed' / name).read_text()
        blocks.append(f'<section id="scene-{index}"><h2>{html.escape(title)}</h2>'
                      f'<div class="columns">{panes}</div><details>'
                      '<summary>Reviewed source extraction</summary>'
                      f'<pre>{html.escape(source)}</pre></details></section>')
    nav = ' · '.join(f'<a href="#scene-{i}">Scene {i}</a>' for i in range(1, 6))
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phandalin: factual record to literary adaptation</title>
<style>
body{max-width:1500px;margin:2rem auto;padding:0 1.5rem;background:#faf8f3;color:#292825;font:17px/1.55 system-ui,sans-serif}
a{color:#285666}nav{position:sticky;top:0;padding:.8rem;background:#faf8f3;border-bottom:1px solid #ddd8cc}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}article{min-width:0;background:#fff;padding:1.5rem;border:1px solid #ddd8cc}
.prose{white-space:pre-wrap;overflow-wrap:anywhere;font:19px/1.65 Georgia,serif}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui,sans-serif}
section{margin-top:3rem;scroll-margin-top:5rem}h1{line-height:1.2}details{margin:1.5rem 0}summary{cursor:pointer}
@media(max-width:850px){.columns{grid-template-columns:1fr}}
</style></head><body><h1>Phandalin: from the factual record to a story</h1>
<p>One new gpt-6-astra / medium chapter from five unchanged reviewed smoothed extractions.
The existing chapter was not shown to the narrator. The new response is unedited and is not campaign canon.</p>
<p><a href="response.md">New chapter</a> · <a href="review.md">Evaluation</a> ·
<a href="system_prompt.md">Writing contract</a> · <a href="README.md">Experiment design</a></p>
'''
    page += f'<nav>{nav}</nav>' + ''.join(blocks) + '</body></html>\n'
    save_new(ROOT / 'comparison.html', page)
    print(json.dumps({'status': 'built', 'scenes': len(blocks), 'metrics': counts}, indent=2))


if __name__ == '__main__':
    main()
