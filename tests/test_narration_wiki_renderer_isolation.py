import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_render_modules_never_import_or_read_wiki_tiers():
    renderers = [
        ROOT / "session_doc/narrate.py",
        ROOT / "session_doc/sd_narrate.py",
        ROOT / "session_doc/assemble.py",
    ]
    for path in renderers:
        text = path.read_text()
        tree = ast.parse(text)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        assert all("narration_wiki" not in ast.unparse(node) for node in imports)
        assert '"wiki"' not in text and "'wiki'" not in text


def test_bundled_narration_never_invokes_approval_or_assembly():
    path = ROOT / "session_doc/sd_narrate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert not calls & {"approve", "assemble", "promote"}
