import json, collections
from pipelines.summary_native import cli
from tests import _rebase_fixture as rf
def run(capsys, root, *argv, expect=0):
    code = cli.main(["delta", *argv, "--campaign-dir", str(root), "--json"])
    out = capsys.readouterr()
    return code, out.out, out.err
def test_x(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch)
    root = fx.root
    c,o,e = run(capsys, root, "rebase", "inspect")
    with capsys.disabled():
        print(c, o[:3000], e)
    srcs=[]
    for ch in (2,3,4,5):
        srcs += ["--source", str(fx.paths[ch])]
    c,o,e = run(capsys, root, "rebase", "prepare", *srcs)
    with capsys.disabled():
        print(c, o[:3000], e)
    d=json.loads(o)["data"]
    c,o,e = run(capsys, root, "rebase", "show", "--plan", d["plan_id"])
    sh=json.loads(o)["data"]
    with capsys.disabled():
        cnt=collections.Counter((l["chapter"],l["document"],l["reason"],l["origin"]) for l in sh["affected_lines"])
        print(cnt); print(sh["unknown_members"]); print(sh["followup_consumers"]); print(sh["stale"])
        print([ (l["line_id"],l["citation"]) for l in sh["affected_lines"] if l["document"]!="planning"])
        print(sh["sources"][0]["entries"])
