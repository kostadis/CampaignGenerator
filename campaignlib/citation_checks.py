"""Wiring for campaignlib.citations' pure verification functions: file I/O
and console reporting for the extract-pass and synthesis-pass citation
checks.

Split out from citations.py (which documents itself as pure in-memory
verification, no I/O) because these two do file reads/writes and printing —
the same "package split by concern" pattern as pipelines.py sitting over
textproc.py. Originally lived as free functions in distill.py; moved here so
planning.py/party.py can share the same wiring instead of each re-deriving
it.
"""

from pathlib import Path

from .textproc import prepare_chunks
from .citations import (
    find_citation_refs,
    find_uncited_bullets,
    find_unreferenced_claims,
    render_report,
    render_sources_section,
    render_synthesis_report,
    verify_citations,
    verify_id_citations,
)


def check_citations(text: str, normalize, extract_files: list[Path],
                     chunk_size: int, split_chapters: str | None, extract_dir: Path,
                     tool_name: str = "distill.py") -> None:
    """Verify every `[cite: "..."]` tag in each extract file against its source
    chunk; print a summary and, if anything is flagged, write citation_report.md.

    Deterministic — no model call. Re-derives the same chunks
    run_extract_pipeline produced (same normalizer + chunk args) so each
    extract file lines up with the exact text it was extracted from.

    tool_name — attributed in the written report's opening line (default
                preserves distill.py's original wording).
    """
    normalized_text = normalize(text) if normalize else text
    chunks, _ = prepare_chunks(normalized_text, chunk_size, split_chapters, split_label="chapter")
    if len(chunks) != len(extract_files):
        print(f"  [citation check skipped — {len(chunks)} chunk(s) vs "
              f"{len(extract_files)} extract file(s); likely a resumed run "
              f"with mismatched chunking]")
        return

    results_by_file = {}
    total_cited = total_verified = total_uncited = 0
    for chunk, extract_file in zip(chunks, extract_files):
        extract_text = extract_file.read_text(encoding="utf-8")
        citations = verify_citations(extract_text, chunk)
        uncited = find_uncited_bullets(extract_text)
        results_by_file[extract_file.name] = (citations, uncited)
        total_cited += len(citations)
        total_verified += sum(1 for c in citations if c.verified)
        total_uncited += len(uncited)

    flagged = (total_cited - total_verified) + total_uncited
    missing_note = f", {total_uncited} bullet(s) missing a citation" if total_uncited else ""
    print(f"  Citation check: {total_verified}/{total_cited} cited claims verified{missing_note}.")
    if flagged:
        report_path = extract_dir / "citation_report.md"
        report_path.write_text(render_report(results_by_file, tool_name=tool_name), encoding="utf-8")
        print(f"  {flagged} flagged claim(s) for review — see {report_path}")


def check_synthesis_citations(world_state: str, known_ids: dict[int, str], extract_dir: Path,
                               tool_name: str = "distill.py",
                               flag_unreferenced: bool = True) -> str:
    """Verify every citation ID in the synthesized doc against the IDs
    CitationIdAssigner actually showed the model during synthesis; print a
    summary and, if anything is flagged, write synthesis_citation_report.md.
    Returns `world_state` with a mechanically-rendered `## Sources` section
    appended for the IDs actually used — the model never spends output
    tokens reproducing quote text, so this is the only place the quotes
    re-appear in the final document.

    Deterministic — no model call, no fuzzy text matching. Synthesis can
    only ever cite an ID it was shown, never invent a new one, so this is
    exact ID lookup.

    tool_name         — attributed in the written report's opening line
                         (default preserves distill.py's original wording).
    flag_unreferenced — when True (default), claims with no [n] marker
                         (find_unreferenced_claims) count toward the flagged
                         total and appear in the written report — the
                         behavior distill.py has always had, appropriate
                         when ~all input is extraction-derived and citable.
                         When False, those claims are excluded from both the
                         flagged count and the report, and instead printed
                         as a separate FYI line — for callers (planning.py/
                         party.py) whose synthesized output legitimately
                         draws most content from uncited reference material
                         (dossiers, character sheets), where the same
                         strict-coverage check would be pure noise. The
                         ID-fabrication check (verify_id_citations) always
                         counts fully either way — that's the real
                         anti-hallucination guarantee and it never weakens.
    """
    results = verify_id_citations(world_state, known_ids)
    unreferenced = find_unreferenced_claims(world_state)

    verified = sum(1 for r in results if r.verified)
    report_unreferenced = unreferenced if flag_unreferenced else []
    flagged = (len(results) - verified) + len(report_unreferenced)
    print(f"  Synthesis citation check: {verified}/{len(results)} citation IDs verified, "
          f"{len(report_unreferenced)} claim(s) missing a citation.")
    if not flag_unreferenced and unreferenced:
        print(f"  [{len(unreferenced)} claim(s) with no citation ID — not flagged for this tool]")
    if flagged:
        report_path = extract_dir / "synthesis_citation_report.md"
        report_path.write_text(
            render_synthesis_report(results, report_unreferenced, tool_name=tool_name),
            encoding="utf-8",
        )
        print(f"  {flagged} flagged item(s) for review — see {report_path}")

    used_ids = {n for _, nums in find_citation_refs(world_state) for n in nums}
    return world_state.rstrip() + "\n\n" + render_sources_section(used_ids, known_ids)
