"""Scene-anchored VTT extraction tied to gm-assist recap structure."""

import re
import sys
from pathlib import Path

from .api.client import stream_api


_SCENE_HEADING_RE = re.compile(r"^### +(.+?)\s*$")

# The heading rule for find_scenes_section, below. Any H2 (## but not ###)
# line, capturing what follows the marker on that same line — deliberately
# [ \t]+ rather than \s+ so the boundary never reaches across a blank line,
# because this same match doubles as the "is it Scenes" test.
_SCENES_H2_RE = re.compile(r"^##(?!#)[ \t]+(.*)$", re.MULTILINE)
_SCENES_TITLE_RE = re.compile(r"(?i)^scenes\b")


def find_scenes_section(text: str, start: int = 0) -> tuple[str, tuple[int, int]] | None:
    """Find a ``## Scenes`` section — the one heading rule for four call sites.

    Before this function existed, four places each answered "does this
    document have a ``## Scenes`` section, and what's in it" their own way:
    ``extract_scene_text`` (session_doc/io.py) compared a stripped line to
    the literal string ``"## Scenes"``; ``compose_summary_scenes``
    (campaignlib/lineage.py) matched a prefix-tolerant regex;
    ``parse_summary_scenes`` (pipelines/ensemble/summary_map.py) and this
    module's own ``parse_gmassist_scenes`` each lowercased and compared for
    exact equality. Four rules, three different verdicts on the same
    heading (issue #262). Scene boundaries are already a known-hard
    precision decision in this codebase — #227 closed an attempt to
    *infer* them outright as a dead end at 87% accuracy — so four
    independent guesses at merely *recognizing* a heading someone already
    wrote down is one guess too many.

    The rule adopted here is deliberately the LOOSEST of the four: match is
    case-insensitive, and text after ``Scenes`` on the heading line is
    tolerated (``## Scenes (12)``, ``## Scenes — Recap``) rather than
    rejected. That is a considered choice, not laziness: a strict rule fails
    CLOSED — it silently drops a real section, and every downstream
    consumer just sees "no scenes" with no signal that anything was missed.
    A loose rule fails open — at worst an oddly-worded heading gets treated
    as a scenes section, which is visible and cheap to correct. Between "a
    verbatim-bearing section quietly vanishes from extraction" and "an
    unusual heading briefly gets read as one," the second is the failure
    worth risking. The measured corpus (16,896 files, 570 ``## Scenes``
    occurrences) backs this in practice: the loose rule and the three strict
    ones agree on 566 of them, and the 4 they disagree on live in a report
    file no caller here reads anyway.

    Returns ``(body, (body_start, body_end))`` for the first ``## Scenes``
    heading found at or after character offset ``start``, or ``None`` if
    there is none. ``body`` is exactly ``text[body_start:body_end]`` —
    unstripped — covering the text after the heading LINE (only its own
    trailing newline is consumed) up to the next ``##``-but-not-``###``
    heading, or the end of the text.

    ``None`` means "no such section here" and is distinct from a section
    that exists but is empty (heading immediately followed by another ``##``
    heading, or by end of text), which returns ``("", (n, n))``. Collapsing
    that distinction would break ``parse_summary_scenes``, the one caller
    that relies on it to tell "this summary is unstructured" apart from
    "this summary's Scenes section has nothing in it" — both real states in
    the corpus, and only one of them means "there's no scene list to trust
    at all."

    ``start`` exists so a caller that wants every ``## Scenes`` section in a
    document can loop: pass the previous call's ``body_end`` back in as the
    next ``start``. ``session_doc.io.extract_scene_text`` does exactly that —
    alone among the four callers, it scans every section, and it did so
    before this refactor too (by accident; see its docstring). The other
    three take the first section and stop. This function only answers
    "where's the next one"; whether a caller stops after the first or keeps
    going is the caller's decision, unchanged by this refactor.

    This function unifies ONLY the heading rule and the section boundary.
    What counts as a scene title inside the section (a literal ``"### "``
    prefix here, a compiled regex there), how many sections a caller
    consumes, and what shape each caller returns are untouched — those are
    existing call-site behaviours nobody asked to change, and unifying past
    the boundary is not what #262 asked for.
    """
    matches = list(_SCENES_H2_RE.finditer(text, start))
    for i, m in enumerate(matches):
        if not _SCENES_TITLE_RE.match(m.group(1)):
            continue
        body_start = m.end()
        if body_start < len(text) and text[body_start] == "\n":
            body_start += 1
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        return text[body_start:body_end], (body_start, body_end)
    return None


def _scenes_from_section(section_text: str) -> list[dict]:
    """Split one ``## Scenes`` section's body into ordered scene dicts.

    Scene titles are ``### `` headings (``_SCENE_HEADING_RE``) — the
    per-scene rule ``parse_gmassist_scenes`` has always used and keeps.
    ``section_text`` is already trimmed by ``find_scenes_section`` to stop
    before the next ``##`` heading, so nothing here needs to watch for that
    boundary itself.
    """
    scenes: list[dict] = []
    current: dict | None = None
    body: list[str] = []

    def flush():
        if current is not None:
            current["body"] = "\n".join(body).strip()
            scenes.append(current)

    for line in section_text.splitlines():
        m = _SCENE_HEADING_RE.match(line)
        if m:
            flush()
            current = {"name": m.group(1).strip(), "body": ""}
            body = []
            continue
        if current is not None:
            body.append(line)

    flush()
    return scenes


def parse_gmassist_scenes(text: str) -> list[dict]:
    """Parse the `## Scenes` block(s) of a gm-assist recap into ordered scene dicts.

    Returns a list of `{"name": str, "body": str}` — one per `### Scene Name`
    heading found under a `## Scenes` heading. `body` is the verbatim text
    between this scene's heading and the next `###` (or the end of that Scenes
    section), preserving the optional `#### subtitle` line and bullets.

    Every `## Scenes` section is accumulated, not just the first, because that
    is what this function already did — by a route nobody would design. The
    old line loop left the section on *any* `##` heading and set a flag back
    to False, and the entry test then fired again on a later `## Scenes`. So a
    document shaped `## Scenes ... ## NPCs ... ## Scenes` yielded scenes from
    both. Reproducing that is what keeps this refactor behaviour-preserving
    across the corpus: narrowing to the first section changes output on 25
    real files.

    One shape is not reproduced. Where two `## Scenes` headings were
    *adjacent* — nothing but an `# H1` between them — the old loop consumed
    the second as the terminator of the first and never re-tested that line,
    so those scenes were silently dropped. This version finds them. Exactly
    one file in a 16,896-file corpus has that shape and nothing reads it as
    input; dropping scenes because of where a chapter title fell is not
    behaviour worth preserving.

    Contrast `session_doc.io.extract_scene_text`, which takes the first
    section only. The two callers really did differ before #262, in opposite
    directions, and both differences were accidents of statement order rather
    than decisions. Each is preserved where it costs nothing; see that
    function's docstring for its side.

    Returns `[]` when no `## Scenes` section exists or it has no scene headings.
    Empty list is the signal to callers that no human-verified structure is
    available — they should bail out, not silently fall back to chunk mode.
    """
    scenes: list[dict] = []
    start = 0
    while True:
        found = find_scenes_section(text, start=start)
        if found is None:
            break
        body, (_body_start, body_end) = found
        scenes.extend(_scenes_from_section(body))
        start = body_end
    return scenes


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def snapshot_scene_for_rerun(out_file: "Path", new_text: str) -> bool:
    """Decide whether a re-extraction's `new_text` should overwrite `out_file`.

    Returns True if the caller should write `new_text` (content differs or no
    file existed), False if the existing file is byte-identical (no write
    needed). When content differs, the existing file is snapshotted to
    `<out_file>.prev` and any `<out_file>.reviewed` marker is removed —
    a re-run that changed content invalidates the GM's prior approval.
    """
    if not out_file.exists():
        return True
    old_text = out_file.read_text(encoding="utf-8")
    if old_text == new_text:
        return False
    prev = out_file.with_name(out_file.name + ".prev")
    prev.write_text(old_text, encoding="utf-8")
    reviewed = out_file.with_name(out_file.name + ".reviewed")
    if reviewed.exists():
        reviewed.unlink()
    return True


def run_scene_extraction(
    client,
    *,
    vtt_text: str,
    scenes: list[dict],
    extract_dir: "Path",
    model: str,
    extraction_instruction: str,
    system_prefix: str = "",
    system_suffix: str = "",
    input_normalizer=None,
    cache_vtt: bool = True,
    filename_template: str = "{i:02d}_{slug}.md",
    max_tokens: int = 8192,
    force: bool = False,
) -> list[Path]:
    """For each scene in `scenes`, run a scene-anchored extraction over `vtt_text`.

    Each call sends the full VTT in the system prompt (cached as a prefix when
    `cache_vtt=True`) and a per-scene user prompt: the scene name + body from
    gm-assist plus `extraction_instruction`. Output is one markdown file per
    scene under `extract_dir`, named `NN_<slug>.md` by default.

    Existing files are skipped so a partial run can be resumed. Pass
    `force=True` to re-extract every scene; in that mode the prior file is
    snapshotted to `<file>.prev` (only if content differs) and any
    `<file>.reviewed` marker is cleared.

    extraction_instruction — the per-call task description. Receives `{name}`
                              and `{body}` substitutions and is rendered as the
                              user message. The caller controls the prompt — the
                              engine just orchestrates the loop and caching.
    system_prefix          — prepended to the system prompt (general-purpose
                              instructions that should be cached alongside the
                              VTT).
    system_suffix          — appended to the system prompt (e.g. NPC roster
                              from `format_npc_roster`).
    input_normalizer       — optional `Callable[[str], str]` applied to
                              `vtt_text` (alias normalization).
    """
    if not scenes:
        print("Error: no scenes provided — cannot run scene-anchored extraction.",
              file=sys.stderr)
        raise SystemExit(1)

    if input_normalizer:
        vtt_text = input_normalizer(vtt_text)

    extract_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total = len(scenes)

    parts = []
    if system_prefix:
        parts.append(system_prefix.strip())
    parts.append("# TRANSCRIPT (full session VTT)\n\n" + vtt_text.strip())
    if system_suffix:
        parts.append(system_suffix.strip())
    system_prompt = "\n\n".join(parts)

    for i, scene in enumerate(scenes, 1):
        name = scene["name"]
        body = scene.get("body", "").strip()
        slug = _slugify(name) or f"scene_{i}"
        out_file = extract_dir / filename_template.format(i=i, slug=slug)
        if out_file.exists() and not force:
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        user_prompt = extraction_instruction.format(name=name, body=body)
        action = "Re-extracting" if force and out_file.exists() else "Scene-extracting"
        print(f"  [{i}/{total}] {action}: {name}")
        print("  " + "─" * 56)
        result = stream_api(client, system_prompt, user_prompt, model,
                            max_tokens=max_tokens, cache_system=cache_vtt)
        print("  " + "─" * 56)

        new_text = format_scene_output(name, body, result)
        if snapshot_scene_for_rerun(out_file, new_text):
            out_file.write_text(new_text, encoding="utf-8")
            print(f"  Saved: {out_file.name}\n")
        else:
            print(f"  Unchanged (no overwrite): {out_file.name}\n")
        saved.append(out_file)

    return saved


def format_scene_output(name: str, body: str, result: str) -> str:
    """Render a scene extraction file body — shared by live and batch paths.

    Layout: front-matter + scene heading + scene summary (verbatim from
    gm-assist) + LLM-extracted verbatim moments. The live and batch paths
    must produce byte-identical files for the same `result` so that a
    user re-running with `--batch` sees no spurious diffs.
    """
    return (
        f"---\n"
        f"scene: {name}\n"
        f"source: gmassist\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"## Scene summary (from gm-assist, verbatim)\n\n"
        f"{body.strip()}\n\n"
        f"## Verbatim moments\n\n"
        f"{result.strip()}\n"
    )


def build_scene_extraction_system_prompt(
    *,
    vtt_text: str,
    system_prefix: str = "",
    system_suffix: str = "",
    input_normalizer=None,
) -> str:
    """Build the system prompt that scene-extraction reuses across all scenes.

    Same shape as the inline assembly in `run_scene_extraction` so live
    and batch callers share one cache breakpoint.
    """
    if input_normalizer:
        vtt_text = input_normalizer(vtt_text)
    parts: list[str] = []
    if system_prefix:
        parts.append(system_prefix.strip())
    parts.append("# TRANSCRIPT (full session VTT)\n\n" + vtt_text.strip())
    if system_suffix:
        parts.append(system_suffix.strip())
    return "\n\n".join(parts)


def plan_scene_extraction(
    *,
    scenes: list[dict],
    extract_dir: "Path",
    filename_template: str = "{i:02d}_{slug}.md",
) -> list[dict]:
    """Map scenes to per-scene custom_ids and on-disk paths.

    Returns one dict per scene: {i, name, body, slug, custom_id, path,
    exists}. Used by both the live loop (for resumability) and the batch
    submitter (to build one Request per non-existent scene).
    """
    plan = []
    for i, scene in enumerate(scenes, 1):
        name = scene["name"]
        body = scene.get("body", "").strip()
        slug = _slugify(name) or f"scene_{i}"
        out_file = extract_dir / filename_template.format(i=i, slug=slug)
        plan.append({
            "i": i,
            "name": name,
            "body": body,
            "slug": slug,
            "custom_id": f"{i:02d}_{slug}",
            "path": out_file,
            "exists": out_file.exists(),
        })
    return plan
