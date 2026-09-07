"""Build a neutral A/B reader; never change raw responses or reveal labels in HTML."""
import html
import json
import re
import statistics

from run import ROOT, json_text, save_new, sha, verify


def metrics(text):
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text)
                  if p.strip() and not p.strip().startswith('#')]
    quotes = [p for p in paragraphs if p.startswith(('“', '"', '‘'))]
    return {'words': len(text.split()), 'paragraphs': len(paragraphs),
            'median_paragraph_words': statistics.median(len(p.split()) for p in paragraphs),
            'quote_led_paragraphs': len(quotes),
            'quote_led_at_most_5_words': sum(len(p.split()) <= 5 for p in quotes)}


def prose(text):
    blocks = []
    for block in re.split(r'\n\s*\n', text.strip()):
        safe = html.escape(block)
        if block.startswith('## '):
            blocks.append('<h3>' + safe[3:] + '</h3>')
        else:
            safe = re.sub(r'\*([^*\n]+)\*', r'<em>\1</em>', safe)
            blocks.append('<p>' + safe + '</p>')
    return '\n'.join(blocks)


def main():
    case = json.loads((ROOT / 'case.json').read_text())
    verify(case)
    assignment = json.loads((ROOT / 'assignment.json').read_text())
    counts, panels = {}, []
    for label in ('A', 'B'):
        target = ROOT / assignment[label]
        run = json.loads((target / 'run.json').read_text())
        data = (target / 'response.md').read_bytes()
        if (run['status'] != 'rendered' or sha(data) != run['response_sha256']
                or sha((ROOT / 'case.json').read_bytes()) != run['case_sha256']):
            raise ValueError('Completed unchanged responses required')
        text = data.decode()
        save_new(ROOT / f'version-{label}.md', data)
        counts[label] = metrics(text)
        panels.append(f'<article id="version-{label}"><h2>Version {label}</h2>'
                      f'<a href="version-{label}.md">Open this draft separately</a>'
                      + prose(text) + '</article>')
    save_new(ROOT / 'metrics.json', json_text(counts))
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>House of a Thousand Faces — A/B reading comparison</title>
<style>
body{max-width:1500px;margin:2rem auto;padding:0 1.5rem;background:#faf8f3;color:#292825;font:17px/1.5 system-ui,sans-serif}
a{color:#285666}.columns{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}
article{min-width:0;background:white;padding:1.6rem;border:1px solid #ddd8cc}
article p{font:19px/1.65 Georgia,serif;overflow-wrap:anywhere;white-space:pre-wrap}
h1{line-height:1.2}h3{font:italic 22px/1.4 Georgia,serif}details{margin:2rem 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui,sans-serif}
@media(max-width:850px){.columns{grid-template-columns:1fr}}
</style></head><body><h1>The House of a Thousand Faces</h1>
<p>Two unedited drafts from the same reviewed scene, characters, examples, model,
and settings. Only composition guidance differs. Labels were randomly assigned.
Neither draft is campaign canon.</p>
<p>Which feels more like Soma living through the adventure? Which exchanges work,
and where does your attention drift? Neither length nor paragraph size is a score.</p>
<p><a href="#version-A">Version A</a> · <a href="#version-B">Version B</a></p>
'''
    page += '<div class="columns">' + ''.join(panels) + '</div>'
    page += '<details><summary>Reviewed source extraction</summary><pre>'
    page += html.escape((ROOT / 'inputs/source.md').read_text()) + '</pre></details>'
    page += '<details><summary>After reading: evaluation and experiment details (may influence your preference)</summary>'
    page += '<p><a href="review.md">Assistant evaluation</a> · <a href="README.md">Method and limitations</a> · '
    page += '<a href="assignment.json">Reveal which prompt produced each version</a></p></details></body></html>\n'
    save_new(ROOT / 'comparison.html', page)
    print(json_text({'status': 'built', 'versions': ['A', 'B'], 'metrics': counts}))


if __name__ == '__main__':
    main()
