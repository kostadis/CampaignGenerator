"""Fixed production boundaries and native-agent handoffs, not executable skills."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    parents: tuple[str, ...]
    checks: tuple[str, ...]
    skills: tuple[str, ...]
    decision: str
    command: str | None = None


STAGES = {
    "prepare": Stage((), ("prep-scope",), ("campaign-prep", "gm-session-prep"), "Select and approve context and session prep"),
    "capture": Stage((), ("capture-integrity",), ("audio-to-vtt",), "Confirm captured source and session identity"),
    "identify": Stage(("capture",), ("speaker-attribution", "vtt-spell-pass"), ("speaker-attribution", "vtt-spell-pass"), "Resolve players, speakers and corrected transcript derivatives"),
    "events": Stage(("identify",), ("staged-consistency-0", "staged-consistency-1"), ("gmassist-precheck", "session-doc-run", "staged-consistency"), "Approve event order and scene structure", "enhance_summary"),
    "remove-recap": Stage(("events",), ("remove-recap",), ("remove-recap",), "Approve recap cuts and rescued new information"),
    "extract": Stage(("remove-recap", "identify"), ("quote-verification", "session-summary-consistency"), ("scene-extract", "staged-consistency", "session-summary-consistency"), "Approve quote provenance, attribution and corrections", "scene_extract"),
    "voice-smooth": Stage(("extract",), ("voice-smooth",), ("voice-smooth",), "Approve explicitly derived voiced material"),
    "no-mech": Stage(("voice-smooth",), ("no-mech",), ("no-mech",), "Approve mechanics edits while retaining events, discoveries, level changes and in-world magic"),
    "plan": Stage(("no-mech",), ("plan-scope",), (), "Approve narrator assignment and scene order", "sd_plan"),
    "narrate": Stage(("plan", "no-mech"), ("scrub", "voice-critic", "final-consistency", "transitions"), ("scrub", "voice-critic", "staged-consistency"), "Approve this exact narration and neighboring transitions", "sd_narrate"),
    "release": Stage(("narrate",), ("final-preview", "chapter-identity"), (), "Approve local session document and chapter identity", "assemble"),
    "memory": Stage(("release",), ("lineage", "entities", "events", "threads", "projections"), (), "Approve selected chapter updates and promote campaign state"),
    "prepare-next": Stage(("memory",), ("prep-scope",), ("campaign-prep", "gm-session-prep"), "Approve fresh context and next-session prep"),
}


def catalog():
    from dataclasses import asdict
    return {name: asdict(stage) for name, stage in STAGES.items()}
