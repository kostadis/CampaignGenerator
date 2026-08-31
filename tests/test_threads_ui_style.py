"""Source-contract guards for feature 018 Threads presentation."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
THREADS = FRONTEND / "views" / "grounding" / "Threads.vue"
GLOBAL_STYLE = FRONTEND / "style.css"


def _thread_source() -> str:
    assert THREADS.exists(), f"{THREADS} is missing"
    return THREADS.read_text(encoding="utf-8")


def _template_source() -> str:
    source = _thread_source()
    match = re.search(r"<template>(.*)</template>\s*<style\s+scoped>", source, flags=re.S)
    assert match, "Threads.vue has no template block"
    return match.group(1)


def _scoped_style_source() -> str:
    source = _thread_source()
    match = re.search(r"<style\s+scoped>(.*?)</style>", source, flags=re.S)
    assert match, "Threads.vue has no scoped style block"
    return match.group(1)


def _global_custom_properties() -> set[str]:
    source = GLOBAL_STYLE.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", source, flags=re.S)
    assert root, "style.css has no :root token block"
    return set(re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", root.group(1)))


def _css_rule(selector: str) -> str:
    style = _scoped_style_source()
    match = re.search(rf"{re.escape(selector)}\s*\{{(.*?)\}}", style, flags=re.S)
    assert match, f"Threads.vue has no {selector} scoped style rule"
    return match.group(1)


def _declarations(selector: str) -> dict[str, str]:
    body = _css_rule(selector)
    return {
        name.strip(): value.strip()
        for name, value in re.findall(r"([-\w]+)\s*:\s*([^;]+);", body)
    }


def test_threads_root_is_bounded_and_owns_both_scroll_axes() -> None:
    declarations = _declarations(".threads")

    assert declarations.get("height") == "100%"
    assert declarations.get("box-sizing") == "border-box"
    assert declarations.get("overflow") == "auto"


def test_threads_root_does_not_force_a_horizontal_scrollbar() -> None:
    declarations = _declarations(".threads")

    assert declarations.get("overflow-x") != "scroll"


def test_threads_uses_only_defined_application_custom_properties() -> None:
    style = _scoped_style_source()
    used_properties = set(re.findall(r"var\((--[a-zA-Z0-9_-]+)", style))

    assert used_properties
    assert used_properties <= _global_custom_properties()


def test_threads_rejects_legacy_variables_and_light_palette() -> None:
    style = _scoped_style_source().lower()
    legacy_variables = {"--muted", "--border", "--chip", "--panel"}
    legacy_colors = {
        "#666",
        "#888",
        "#ccc",
        "#ddd",
        "#eee",
        "#dbeafe",
        "#fafafa",
        "#f5c2c7",
        "#fff5f5",
        "#842029",
    }

    assert not {name for name in legacy_variables if name in style}
    assert not {color for color in legacy_colors if color in style}
    assert not re.search(r"var\(\s*--[a-zA-Z0-9_-]+\s*,", style)


def test_threads_uses_standard_header_and_control_classes() -> None:
    template = _template_source()

    assert '<div class="page-header">' in template
    assert "<h2>Threads</h2>" in template
    assert 'class="subtitle"' in template

    controls = re.findall(r"<(?:input|select)\b([^>]*)>", template, flags=re.S)
    assert controls
    assert all(re.search(r'class="[^"]*\bfield-input\b', attrs) for attrs in controls)

    buttons = re.findall(r"<button\b([^>]*)>", template, flags=re.S)
    assert buttons
    assert all(
        re.search(r'class="[^"]*\bbtn-(?:primary|success|neutral)\b', attrs)
        for attrs in buttons
    )


def test_threads_renders_loading_and_text_bearing_semantic_statuses() -> None:
    template = _template_source()

    assert re.search(r'v-if="loading"[^>]*>\s*Loading threads…\s*<', template)
    assert ':class="`status-${harvestStatus}`"' in template
    assert "Harvest: {{ harvestStatus }}" in template
    assert ':class="`status-${p.status || \'pending\'}`"' in template
    assert "{{ p.status || 'pending' }}" in template
    assert ':class="`status-${group.status}`"' in template
    assert "{{ group.status }}" in template


def test_threads_controls_define_dark_surface_and_focus_treatment() -> None:
    declarations = _declarations(".field-input")
    focus_declarations = _declarations(".field-input:focus")

    assert declarations.get("background") == "var(--bg-base)"
    assert declarations.get("color") == "var(--text)"
    assert declarations.get("border") == "1px solid var(--bg-surface1)"
    assert focus_declarations.get("border-color") == "var(--mauve)"


def test_threads_root_can_shrink_inside_the_application_flex_region() -> None:
    declarations = _declarations(".threads")

    assert declarations.get("width") == "100%"
    assert declarations.get("min-width") == "0"


def test_threads_dynamic_overflow_uses_browser_layout_only() -> None:
    source = _thread_source()

    assert "ResizeObserver" not in source
    assert "MutationObserver" not in source
    assert not re.search(r"addEventListener\s*\(\s*['\"]resize['\"]", source)
    assert not re.search(r"\bonresize\b", source)
    assert not re.search(r"\bset(?:Timeout|Interval)\s*\(", source)
    assert not re.search(
        r"\b(?:width|scroll(?:Left|Top|Position)?)\w*\s*=\s*ref\s*\(",
        source,
        flags=re.I,
    )
    assert not re.search(r"\.(?:scrollLeft|scrollTop)\s*=", source)
    assert not re.search(
        r"(?:localStorage|sessionStorage).*?(?:width|scroll)",
        source,
        flags=re.I | re.S,
    )
