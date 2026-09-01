from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_route_step_sidebar_and_all_public_capabilities_are_present():
    router = (ROOT / "frontend/src/router.ts").read_text()
    workflow = (ROOT / "frontend/src/views/SessionWorkflow.vue").read_text()
    sidebar = (ROOT / "frontend/src/components/layout/AppSidebar.vue").read_text()
    view = (ROOT / "frontend/src/views/session/NarrationWiki.vue").read_text()
    assert "path: 'wiki'" in router
    assert "number: 7" in workflow
    assert "③ Narration Wiki" in sidebar
    for action in (
        "status", "collect", "measure", "index-check", "conflict-rule", "pattern-rule",
        "proposal-stage", "proposal-apply", "proposal-rule",
    ):
        assert action in (view + (ROOT / "frontend/src/api/narrationWiki.ts").read_text())


def test_ui_reuses_tokens_and_every_panel_has_both_axis_resize_scroll_contract():
    files = list((ROOT / "frontend/src/components/narration-wiki").glob("*.vue")) + [
        ROOT / "frontend/src/views/session/NarrationWiki.vue"
    ]
    for path in files:
        text = path.read_text()
        assert not any(token in text for token in ("#fff", "#000", "rgb(", "hsl("))
    style = (ROOT / "frontend/src/style.css").read_text()
    assert "min-width: 320px" in style
    assert "min-height: 160px" in style
    assert "resize: both" in style
    assert "overflow: scroll" in style
    assert "overflow: auto" in (ROOT / "frontend/src/views/session/NarrationWiki.vue").read_text()
