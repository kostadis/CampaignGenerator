"""Scene-anchored VTT extraction tied to gm-assist recap structure."""

import re
import sys
from collections import Counter
from pathlib import Path

from .api.client import stream_api
from .config import load_agent_prompt


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

    A scene the model returns nothing for is reported and NOT written
    (FR-006), so the next run asks for it again instead of skipping it
    forever. The returned list therefore holds only scenes that have a file.

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

        if not result.strip():
            # FR-006 / DM-4 — a scene the model returned nothing for is NOT
            # written, and the batched path (`run_batched_scene_extraction`,
            # status "empty") does the same. `exists` is the sole
            # skip-if-exists criterion, so writing a file with a blank
            # `## Verbatim moments` here would retire that scene permanently
            # on the strength of one empty response — and the two modes would
            # disagree about a session started in one and finished in the
            # other. Leaving no file means the next run asks again.
            #
            # Under `force=True` this also leaves any PRIOR extraction of
            # this scene intact rather than overwriting good output with
            # nothing.
            print(f"  Empty (no moments returned): {name}\n")
            continue

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


# The output-size projection used to decide how many scenes a batched request
# can safely cover before any response exists (research D4, 013 data-model §3).
#
# OUTPUT_CHARS_PER_BODY_CHAR is the MEDIAN ratio of extraction-output chars to
# gm-assist body chars, measured over 15 real scenes across two sessions
# (Pearson r = 0.784 between body length and output length; observed range
# 2.4–6.5). The median is used deliberately rather than a conservative upper
# bound: over-projecting causes an unnecessary split and under-projecting
# causes a short response whose tail scenes are re-requested next run — both
# errors cost exactly one extra transcript transmission, so the central
# estimate minimises expected cost. A conservative ×6.5 was measured to
# mis-split a session (23.0K actual → 35.7K projected → 2 groups) that fit
# comfortably in one group at the median multiplier.
OUTPUT_CHARS_PER_BODY_CHAR = 4.2

# Chars-per-token for GENERATED English/markdown prose (the projection's
# output side), not the transcript's own density — the source VTT runs at
# roughly 7.4 chars/token, and that ratio does NOT apply here.
CHARS_PER_TOKEN = 4.0


def project_scene_output(entry: dict) -> float:
    """Estimate OUTPUT TOKENS for one scene plan entry (research D4).

    `entry` is a dict as returned by `plan_scene_extraction` (keys include
    `i`, `name`, `body`, `slug`, `path`, `exists`). A missing or empty `body`
    projects to 0.

    This is an ESTIMATE used only to choose a grouping (`group_scenes`,
    below) and is then discarded — nothing downstream may treat it as
    authoritative (013 data-model DM-5). Correctness comes from the response
    split and the short-response retry path, neither of which consults it.
    """
    body = (entry.get("body") or "").strip()
    if not body:
        return 0.0
    return len(body) * OUTPUT_CHARS_PER_BODY_CHAR / CHARS_PER_TOKEN


def group_scenes(entries: list[dict], ceiling_tokens: float) -> list[dict]:
    """Pack scene plan entries into contiguous groups under a token ceiling.

    Returns a list of `{"index": int, "entries": list[dict], "projected_tokens":
    float}` dicts, `index` 1-based. Each group's `entries` is a contiguous
    slice of `entries` in the original order — scenes are never reordered
    (013 data-model DM-11).

    If the total projection over every entry fits `ceiling_tokens`, the whole
    set comes back as a single group (DM-7). Otherwise entries are packed
    greedily, in order, into the fewest groups whose individual projections
    each fit the ceiling (DM-8). A single entry whose own projection exceeds
    `ceiling_tokens` still gets a group of its own rather than being refused
    or merged with a neighbour (DM-9) — the caller reports the ceiling as
    exceeded for that group.

    Pure and deterministic: the same `(entries, ceiling_tokens)` always
    produces the same grouping (DM-10). No I/O, no randomness.
    """
    if not entries:
        return []

    projections = [project_scene_output(e) for e in entries]

    if sum(projections) <= ceiling_tokens:
        return [{"index": 1, "entries": list(entries), "projected_tokens": sum(projections)}]

    groups: list[dict] = []
    current_entries: list[dict] = []
    current_tokens = 0.0

    for entry, tokens in zip(entries, projections):
        if current_entries and current_tokens + tokens > ceiling_tokens:
            groups.append({
                "index": len(groups) + 1,
                "entries": current_entries,
                "projected_tokens": current_tokens,
            })
            current_entries = []
            current_tokens = 0.0
        current_entries.append(entry)
        current_tokens += tokens

    if current_entries:
        groups.append({
            "index": len(groups) + 1,
            "entries": current_entries,
            "projected_tokens": current_tokens,
        })

    return groups


# ── Batched wire protocol (013 contracts/wire-protocol.md) ────────────────────
#
# One request per SceneGroup covers several scenes in a single exchange; the
# response must say, unambiguously and without a model call, which text
# belongs to which requested scene. `render_batched_user_prompt` builds the
# request side; `split_batched_response` is the deterministic parser for the
# reply. Both are pure text functions — no I/O, no API calls (DM-12, FR-004).

# Wire-protocol sentinel syntax (wire-protocol.md §1). `{i:02d}` is always
# `entry["i"]` from `plan_scene_extraction` — the scene's PLAN index, fixed
# before any group filtering and never re-derived from a scene's position
# within its (possibly non-contiguous) group (DM-1). `{name}` is echoed by
# the model for verification only; attribution is by index (DM-13).
BATCHED_SCENE_BEGIN = "<<<CG-SCENE {i:02d} BEGIN: {name}>>>"
BATCHED_SCENE_END = "<<<CG-SCENE {i:02d} END>>>"

# Parsing side. Both marker lines are anchored to column 0 (MULTILINE
# ^...$), so a scene name that happens to contain the literal text
# "<<<CG-SCENE" mid-line is just name text — only a line that STARTS with
# the sentinel prefix is ever read as a marker (research D5: "a scene name
# cannot forge one because names appear only after BEGIN: on a line that
# already began with the sentinel"). `.` does not match a newline, so a
# marker can never span more than one line.
#
# `[ \t\r]*` before the `$`: trailing blanks and a CR must not hide a
# marker. The `claude -p` subprocess path can hand back CRLF line endings,
# and `$` sitting hard against `>>>` would then match no BEGIN at all — the
# whole group fails as NO_SECTIONS and a response the GM already paid for is
# discarded, which is the most expensive possible reaction to a line ending.
# This cannot forge a marker: the sentinel prefix still has to start at
# column 0, and only whitespace is tolerated after the closing `>>>`.
_BATCHED_BEGIN_RE = re.compile(r"^<<<CG-SCENE (\d+) BEGIN: (.*)>>>[ \t\r]*$", re.MULTILINE)
_BATCHED_END_RE = re.compile(r"^<<<CG-SCENE (\d+) END>>>[ \t\r]*$", re.MULTILINE)

# Reconciliation failure reasons (wire-protocol.md §3). Any one of these
# fails the WHOLE group — nothing from it is written, for any scene in it
# (DM-14). Missing indices (a requested scene with no BEGIN at all) are
# deliberately NOT in this list — an absent scene is unfinished work, not
# evidence the response can't be trusted (wire-protocol.md §3).
BATCHED_UNKNOWN_INDEX = "UNKNOWN_INDEX"
BATCHED_DUPLICATE_INDEX = "DUPLICATE_INDEX"
BATCHED_NAME_MISMATCH = "NAME_MISMATCH"
BATCHED_NESTED_SECTION = "NESTED_SECTION"
BATCHED_NO_SECTIONS = "NO_SECTIONS"


def render_batched_user_prompt(entries: list[dict], template: str) -> str:
    """Render the user prompt for one batched-extraction group.

    Fills `template`'s only placeholder, `{scene_blocks}`, with one indexed
    block per entry. `template` is passed IN by the caller — the engine never
    loads a prompt itself, matching `run_scene_extraction`'s
    `system_prefix`/`extraction_instruction` contract. Prompts are the CLI's
    business; the engine orchestrates. The caller supplies
    `config/agents/scene_extract_batched_user.md`:

        ### 03 — The Margaster Hypothesis

        Summary bullets (use as scope):

        <entry's body>

    `entry["i"]` (as produced by `plan_scene_extraction`) is rendered
    zero-padded to two digits and used exactly as given — never re-derived
    from the entry's position in `entries` — so a group built from a
    filtered, non-contiguous slice of the plan (earlier scenes already on
    disk and skipped) still shows the model each scene's real plan index
    (DM-1). That heading is what the system prompt asks the model to copy
    verbatim into its `<<<CG-SCENE NN BEGIN: name>>>` marker, and it is the
    same index `split_batched_response` attributes the reply back by.
    """
    blocks = [
        f"### {entry['i']:02d} — {entry['name']}\n\n"
        f"Summary bullets (use as scope):\n\n"
        f"{(entry.get('body') or '').strip()}"
        for entry in entries
    ]
    return template.format(scene_blocks="\n\n".join(blocks))


def _normalize_batched_name(name: str) -> str:
    """Whitespace-only normalisation for echoed-name comparison (DM-13).

    Strips the ends and collapses internal whitespace runs — THAT IS ALL.
    Never case-folded, never punctuation-stripped, never similarity-scored.
    A mismatch is a hard failure, never a re-assignment: attribution is by
    index, and the name is a checksum on it, not a matching key.
    """
    return re.sub(r"\s+", " ", name.strip())


def _failed_batch_group(reason: str, detail: str) -> dict:
    """Build the `failed=True` shape of a SplitResult (see `split_batched_response`)."""
    return {"failed": True, "failure_reason": reason, "failure_detail": detail, "sections": []}


def split_batched_response(text: str, entries: list[dict]) -> dict:
    """Split one batched-group response back into per-scene sections.

    Deterministic and purely textual — no model call, no similarity
    matching (DM-12, FR-004). `entries` is the group's
    `plan_scene_extraction`-shaped request list (only `i` and `name` are
    read); `text` is the model's raw response for that group. Writing the
    result to disk is the caller's job (wire-protocol.md §5) — this
    function never touches the filesystem.

    Returns a SplitResult — a plain dict (matching this module's existing
    convention: `plan_scene_extraction` and `group_scenes` both return
    dicts, not classes), shaped:

        {"failed": bool, "failure_reason": str | None, "failure_detail": str,
         "sections": [{"i": int, "name": str, "status": str, "body": str | None}, ...]}

    `failed=True` means the WHOLE group is unreconcilable (wire-protocol.md
    §3, DM-14) — `sections` is then empty, and nothing from this response is
    usable for any scene in it. `failure_reason` is one of
    `BATCHED_UNKNOWN_INDEX` / `BATCHED_DUPLICATE_INDEX` /
    `BATCHED_NAME_MISMATCH` / `BATCHED_NESTED_SECTION` / `BATCHED_NO_SECTIONS`.

    When not failed, `sections` holds exactly one entry per requested scene,
    in request order — not response order, because attribution is by index
    (DM-13) and a caller should never have to care what order the model
    happened to close its sections in. `status` is one of:

      - `"complete"`   BEGIN and a matching END are both present, and the
                       body between them is non-empty after stripping.
      - `"empty"`      BEGIN and END are both present, but the body is
                       blank after stripping. This is a FINISHED result —
                       the transcript genuinely held nothing for that scene
                       — and is deliberately distinct from `"incomplete"`
                       (spec Edge Cases): writing an `"empty"` scene to disk
                       would make the next run's skip-if-exists treat
                       unfinished work as done.
      - `"incomplete"` BEGIN is present with no matching END — unfinished
                       work (a short response, most often).
      - `"absent"`     No BEGIN at all for this requested index.

    `body` is populated only for `"complete"` sections.

    Text outside any BEGIN/END pair — preamble, inter-scene commentary,
    trailing notes — is discarded. It is never appended to an adjacent
    scene: only the span strictly between one scene's own matched markers
    ever becomes that scene's body.
    """
    requested = {e["i"]: e["name"] for e in entries}

    begins = [
        {"i": int(m.group(1)), "name": m.group(2), "start": m.start(), "end": m.end()}
        for m in _BATCHED_BEGIN_RE.finditer(text)
    ]
    ends = [
        {"i": int(m.group(1)), "start": m.start(), "end": m.end()}
        for m in _BATCHED_END_RE.finditer(text)
    ]

    if not begins:
        if entries:
            return _failed_batch_group(
                BATCHED_NO_SECTIONS,
                "response contained no <<<CG-SCENE ... BEGIN>>> marker",
            )
        return {"failed": False, "failure_reason": None, "failure_detail": "", "sections": []}

    unknown = [b for b in begins if b["i"] not in requested]
    if unknown:
        return _failed_batch_group(
            BATCHED_UNKNOWN_INDEX,
            f"BEGIN carries index {unknown[0]['i']:02d}, not among the requested scenes",
        )

    dupes = [i for i, n in Counter(b["i"] for b in begins).items() if n > 1]
    if dupes:
        return _failed_batch_group(
            BATCHED_DUPLICATE_INDEX,
            f"index {dupes[0]:02d} opened more than once",
        )

    for b in begins:
        if _normalize_batched_name(b["name"]) != _normalize_batched_name(requested[b["i"]]):
            return _failed_batch_group(
                BATCHED_NAME_MISMATCH,
                f"scene {b['i']:02d}: echoed name {b['name']!r} != "
                f"requested {requested[b['i']]!r}",
            )

    # Merge BEGIN/END events in the order they appear in the TEXT (not in
    # request order) to pair each BEGIN with its own closing END and to
    # catch NESTED_SECTION: a section is "open" from its BEGIN until its
    # matching END, and a new BEGIN is never allowed to appear while one is
    # still open. Without this check, "the body is the text between the
    # markers" would let one section's window silently swallow another
    # section's entire BEGIN/.../END block.
    events = sorted(
        [{"kind": "begin", **b} for b in begins] + [{"kind": "end", **e} for e in ends],
        key=lambda ev: ev["start"],
    )
    closes: dict[int, dict] = {}
    open_begin: dict | None = None
    for ev in events:
        if ev["kind"] == "begin":
            if open_begin is not None:
                return _failed_batch_group(
                    BATCHED_NESTED_SECTION,
                    f"scene {ev['i']:02d} BEGIN appears before scene "
                    f"{open_begin['i']:02d}'s END",
                )
            open_begin = ev
        elif open_begin is not None and ev["i"] == open_begin["i"]:
            closes[open_begin["i"]] = {"begin": open_begin, "end": ev}
            open_begin = None
        # else: an END whose index doesn't match the currently open section
        # (or nothing is open at all) — stray, not one of the five defined
        # failure modes. It closes nothing and is otherwise ignored; this is
        # what lets a corrupted END marker (a continuation seam landing
        # inside the sentinel line) degrade its own scene to "incomplete"
        # rather than being mistaken for some other scene's closing marker.

    begins_by_i = {b["i"]: b for b in begins}
    sections = []
    for e in entries:
        i = e["i"]
        b = begins_by_i.get(i)
        if b is None:
            sections.append({"i": i, "name": e["name"], "status": "absent", "body": None})
            continue
        pair = closes.get(i)
        if pair is None:
            sections.append({"i": i, "name": e["name"], "status": "incomplete", "body": None})
            continue
        body = text[pair["begin"]["end"]:pair["end"]["start"]].strip()
        if body:
            sections.append({"i": i, "name": e["name"], "status": "complete", "body": body})
        else:
            sections.append({"i": i, "name": e["name"], "status": "empty", "body": None})

    return {"failed": False, "failure_reason": None, "failure_detail": "", "sections": sections}


# ── Batched engine (013 data-model.md §2, §6) ─────────────────────────────
#
# `run_batched_scene_extraction` is a SIBLING of `run_scene_extraction`, not a
# `batched=` flag bolted onto it (research D1) — the per-scene loop above is
# untouched by everything below, byte-for-byte (FR-009, SC-008). It reuses
# `plan_scene_extraction`, `build_scene_extraction_system_prompt`,
# `group_scenes`, `render_batched_user_prompt`, `split_batched_response`,
# `format_scene_output` and `snapshot_scene_for_rerun` rather than
# reimplementing any of them.

def run_batched_scene_extraction(
    client,
    *,
    vtt_text: str,
    scenes: list[dict],
    extract_dir: "Path",
    model: str,
    user_template: str,
    system_prefix: str = "",
    system_suffix: str = "",
    input_normalizer=None,
    cache_vtt: bool = True,
    filename_template: str = "{i:02d}_{slug}.md",
    max_tokens: int = 32000,
    force: bool = False,
) -> dict:
    """Extract several scenes per exchange instead of one call per scene.

    Same inputs as `run_scene_extraction` plus `user_template` (the batched
    user-prompt template — see `render_batched_user_prompt`) and a higher
    default `max_tokens`, which here is the per-GROUP ceiling `group_scenes`
    packs against, not a per-scene budget. `user_template` is passed IN by
    the caller — this engine never loads a prompt itself, matching
    `run_scene_extraction`'s `extraction_instruction` contract; prompts are
    the CLI's business (`config/agents/scene_extract_batched_user.md`).

    THE CRITICAL RULE (013 data-model DM-2/DM-3, FR-008a/FR-008b, task T019):
    already-extracted scenes are filtered out BEFORE projection, grouping or
    any request is built — never sent, never projected, never counted toward
    group sizing, and only discarded after the fact. A scene already on disk
    (per `plan_scene_extraction`'s `exists`) is excluded unless `force=True`,
    exactly the same criterion `run_scene_extraction` uses, so a session
    started in one mode and finished in the other converges on the same set
    (DM-4). If nothing is left to request, this makes ZERO API calls (DM-3) —
    today's free no-op stays free.

    The system prompt (full VTT + system_prefix/suffix, via
    `build_scene_extraction_system_prompt`) is built exactly ONCE, outside
    the group loop, so the transcript is assembled a single time no matter
    how many groups are sent. Each group then costs exactly one
    `stream_api` call — `transcript_transmissions` in the returned report
    equals the number of groups, which is the number this feature exists to
    shrink.

    Only `"complete"` sections (wire-protocol.md §4) are written, and only
    through the shared path: `format_scene_output(entry["name"],
    entry["body"], section["body"])` then `snapshot_scene_for_rerun` — never
    a bespoke writer, so batched output is structurally indistinguishable
    from per-scene output (SC-006) and force semantics (`.prev` snapshot only
    on a real content change, `.reviewed` cleared, no write when identical)
    come along for free (FR-014). `"empty"` sections are a finished result
    (the transcript genuinely held nothing for that scene) and are reported
    but never written — writing them would make the next run's
    skip-if-exists treat unfinished work as done. `"incomplete"` and
    `"absent"` sections, and every scene in a `"failed"` group (DM-14), are
    reported as missing and nothing is written for them either.

    Returns a run-report dict (013 data-model §6) rather than a bare list of
    paths — the report has to say more than `run_scene_extraction`'s return
    value does (how many groups, whether the ceiling forced a split, which
    scenes came back short) so the CLI can render it. This function only
    orchestrates and reports; it never formats that report into prose
    (retrieval/render separation — the report IS the human checkpoint's
    input, not a rendering of one).

    system_prefix, system_suffix, input_normalizer, cache_vtt,
    filename_template, force — same meaning as `run_scene_extraction`.
    """
    if not scenes:
        print("Error: no scenes provided — cannot run scene-anchored extraction.",
              file=sys.stderr)
        raise SystemExit(1)

    extract_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_scene_extraction(
        scenes=scenes, extract_dir=extract_dir, filename_template=filename_template,
    )

    # T019 / DM-2 / FR-008a — THE line. `entries` is what gets projected,
    # grouped and sent; nothing else. Do not build the request set from
    # `plan` and filter afterwards — that sends every scene, including
    # already-extracted ones, and only discards them once the response
    # (and its cost) already exists.
    entries = plan if force else [p for p in plan if not p["exists"]]
    skipped = [] if force else [p for p in plan if p["exists"]]

    report: dict = {
        "scenes_total": len(plan),
        "scenes_skipped": len(skipped),
        "scenes_requested": len(entries),
        "projected_tokens_total": 0.0,
        "scenes_written": 0,
        "scenes_empty": [],
        "scenes_missing": [],
        "groups_used": 0,
        "transcript_transmissions": 0,
        "ceiling_exceeded": False,
        "saved": [],
        "group_failures": [],
    }

    # T020 / DM-3 / FR-008b — nothing left to request, so make NO call.
    if not entries:
        print("All scenes already extracted — nothing to do.")
        return report

    groups = group_scenes(entries, max_tokens)
    report["ceiling_exceeded"] = len(groups) > 1 or any(
        g["projected_tokens"] > max_tokens for g in groups
    )
    # T050 (013 Phase 6) — the sum of every group's own projection, so the
    # CLI can print "Projected output: N tok" next to the group count. This
    # is what lets a future run be compared against its own actual output
    # and OUTPUT_CHARS_PER_BODY_CHAR re-tuned from evidence instead of guessed.
    report["projected_tokens_total"] = sum(g["projected_tokens"] for g in groups)

    # T021 — built ONCE, reused across every group in the loop below.
    system_prompt = build_scene_extraction_system_prompt(
        vtt_text=vtt_text,
        system_prefix=system_prefix,
        system_suffix=system_suffix,
        input_normalizer=input_normalizer,
    )

    total_groups = len(groups)
    for group in groups:
        idx = group["index"]
        group_entries = group["entries"]
        names = ", ".join(e["name"] for e in group_entries)
        count = len(group_entries)
        action = "Batch re-extracting" if force else "Batch-extracting"
        print(f"  [{idx}/{total_groups}] {action} {count} scene"
              f"{'s' if count != 1 else ''}: {names}")
        print("  " + "─" * 56)
        user_prompt = render_batched_user_prompt(group_entries, user_template)
        result = stream_api(client, system_prompt, user_prompt, model,
                            max_tokens=max_tokens, cache_system=cache_vtt)
        print("  " + "─" * 56)

        report["groups_used"] += 1
        report["transcript_transmissions"] += 1

        split = split_batched_response(result, group_entries)
        if split["failed"]:
            report["group_failures"].append({
                "group": idx,
                "reason": split["failure_reason"],
                "detail": split["failure_detail"],
            })
            report["scenes_missing"].extend(e["name"] for e in group_entries)
            print(f"  Group {idx} FAILED ({split['failure_reason']}): "
                  f"{split['failure_detail']}\n")
            continue

        entries_by_i = {e["i"]: e for e in group_entries}
        for section in split["sections"]:
            # T022 — map the section back to its plan entry by `i`. The
            # entry's `body` is the gm-assist SUMMARY BULLETS (scope); the
            # section's `body` is the MODEL'S EXTRACTED MOMENTS (result).
            # `format_scene_output(name, body, result)` wants them in that
            # order — swapping them would silently write the bullets as the
            # extraction.
            entry = entries_by_i[section["i"]]
            status = section["status"]
            if status == "complete":
                new_text = format_scene_output(entry["name"], entry["body"], section["body"])
                out_file = entry["path"]
                if snapshot_scene_for_rerun(out_file, new_text):
                    out_file.write_text(new_text, encoding="utf-8")
                    print(f"  Saved: {out_file.name}")
                else:
                    print(f"  Unchanged (no overwrite): {out_file.name}")
                report["scenes_written"] += 1
                report["saved"].append(out_file)
            elif status == "empty":
                report["scenes_empty"].append(entry["name"])
                print(f"  Empty (no moments returned): {entry['name']}")
            else:  # "incomplete" or "absent" — unfinished work, not written.
                report["scenes_missing"].append(entry["name"])
                print(f"  Missing ({status}): {entry['name']}")
        print()

    return report
