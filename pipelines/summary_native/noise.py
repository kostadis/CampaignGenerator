"""Deterministic noise classification primitives for the NPC number and status checks (spec 041).

Loaders for the two reviewed tables, sentence splitting with citation binding, a number/ordinal
tokenizer with label and idiom detection, and the noise-record and accounting value objects.
Deterministic: stdlib plus PyYAML only. This module makes no model call (AST-guarded by
tests/test_summary_native_no_llm.py).
"""
from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import npc_check

DATA_DIR = Path(__file__).resolve().parent / "data"
ORDINAL_IDIOMS_PATH = DATA_DIR / "ordinal_idioms.yaml"
STATUS_SYNONYMS_PATH = DATA_DIR / "status_synonyms.yaml"

CLASSES = ("label", "idiom", "negated-status", "spelled-number", "synonym", "other-citation")


def legacy_code(noise_class: str) -> str:
    if noise_class not in CLASSES:
        raise ValueError(f"unknown noise class {noise_class!r}")
    return f"noise-{noise_class}"


# ---------------------------------------------------------------- table loaders

def _load_yaml(path: Path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{path}: cannot load reviewed table: {exc}") from exc


def _check_strings(path: Path, items, what: str) -> tuple[str, ...]:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: {what} must be a non-empty list")
    for s in items:
        if not isinstance(s, str) or not s.strip() or s != s.lower():
            raise ValueError(f"{path}: {what} entries must be non-blank lowercase strings, got {s!r}")
    return tuple(items)


def load_ordinal_idioms(path: Path | None = None) -> tuple[str, ...]:
    p = Path(path) if path is not None else ORDINAL_IDIOMS_PATH
    return _check_strings(p, _load_yaml(p), "ordinal idioms")


@lru_cache(maxsize=1)
def _default_status_synonyms() -> dict[str, tuple[str, ...]]:
    return _read_status_synonyms(STATUS_SYNONYMS_PATH)


def load_status_synonyms(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    if path is None:
        return dict(_default_status_synonyms())
    return _read_status_synonyms(Path(path))


def _read_status_synonyms(path: Path) -> dict[str, tuple[str, ...]]:
    # Local import: npc_verify will import this module for classification, so a module-level
    # import here would become a cycle.
    from .npc_verify import STATUS_WORDS

    p = Path(path)
    data = _load_yaml(p)
    if not isinstance(data, dict):
        raise ValueError(f"{p}: status synonyms must be a mapping")
    if set(data) != set(STATUS_WORDS):
        missing = sorted(set(STATUS_WORDS) - set(data))
        extra = sorted(set(data) - set(STATUS_WORDS))
        raise ValueError(f"{p}: keys must equal STATUS_WORDS exactly (missing {missing}, unexpected {extra})")
    return {k: _check_strings(p, v, f"synonyms for {k!r}") for k, v in data.items()}


# ---------------------------------------------------------------- sentences

@dataclass(frozen=True)
class SentenceClaim:
    line: int
    sentence: str
    claim: str
    citations: tuple[tuple[int, str], ...]
    inherited: bool


_ABBREVIATIONS = frozenset({"st.", "mr.", "mrs.", "dr.", "vs.", "e.g.", "i.e.", "ch.", "lt.", "capt.",
                            "gen.", "sgt.", "col.", "prof.", "sr.", "jr.", "mt.", "ft.", "no."})
_INITIAL_RE = re.compile(r"[A-Z]\.")
_TRAILING_BRACKET_RE = re.compile(r"\s*\[[^\[\]]*\]")
_LIST_NUMERAL_ONLY_RE = re.compile(r"^\s*(?:[-*]\s+)?\d+$")
_OPENERS = "\"'“‘("


def split_sentences(line: str) -> list[str]:
    """Split one draft line into sentences.

    A boundary is ``[.!?]`` followed by whitespace and an uppercase letter or opening quote. It is
    never inside ``[...]``, after a listed abbreviation, or after a leading list numeral. A citation
    bracket that trails the terminator stays with the sentence it closes.
    """
    out: list[str] = []
    n = len(line)
    start = 0
    depth = 0
    i = 0
    while i < n:
        c = line[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth = max(0, depth - 1)
        elif c in ".!?" and depth == 0:
            j = i
            while j < n and line[j] in ".!?":
                j += 1
            end = j
            while True:
                m = _TRAILING_BRACKET_RE.match(line, end)
                if not m:
                    break
                end = m.end()
            k = end
            while k < n and line[k].isspace():
                k += 1
            if k > end and k < n and (line[k].isupper() or line[k] in _OPENERS):
                word_m = re.search(r"(\S+)$", line[start:j])
                raw_word = word_m.group(1).lstrip("([\"'“‘") if word_m else ""
                word = raw_word.lower()
                abbrev = word in _ABBREVIATIONS or _INITIAL_RE.fullmatch(raw_word) is not None
                numeral = line[i] == "." and j == i + 1 and bool(_LIST_NUMERAL_ONLY_RE.match(line[start:i]))
                if not abbrev and not numeral:
                    out.append(line[start:end].strip())
                    start = k
                    i = k
                    continue
            i = j
            continue
        i += 1
    tail = line[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


def _valid_citations(text: str) -> list[tuple[int, str]]:
    seen: list[tuple[int, str]] = []
    for _bracket, cit in npc_check.citation_parts(text):
        if cit[0] >= 0 and cit not in seen:  # grammar-broken brackets are reported elsewhere
            seen.append(cit)
    return seen


def sentence_claims(draft_text: str) -> list[SentenceClaim]:
    claims: list[SentenceClaim] = []
    for lineno, line in enumerate(draft_text.splitlines(), start=1):
        if not line.strip():
            continue
        line_cits = _valid_citations(line)
        for sentence in split_sentences(line):
            own = _valid_citations(sentence)
            claim = re.sub(r"[ \t]+", " ", npc_check.BRACKET_RE.sub("", sentence)).strip()
            claims.append(SentenceClaim(
                line=lineno, sentence=sentence, claim=claim,
                citations=tuple(own if own else line_cits), inherited=not own,
            ))
    return claims


# ---------------------------------------------------------------- tokens

@dataclass(frozen=True)
class Token:
    surface: str
    kind: str  # "cardinal" | "ordinal"
    value: int | None
    span: tuple[int, int]
    spelled: bool
    label: bool
    idiom: str | None


_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_ORD_UNITS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
              "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
_ORD_TENS = {"twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60,
             "seventieth": 70, "eightieth": 80, "ninetieth": 90, "hundredth": 100}


def _alt(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_NUM_WORD = _alt(list(_UNITS) + list(_TENS) + list(_SCALES))
_SCALE_WORD = _alt(_SCALES)
_ORD_COMPOUND = rf"(?:{_alt(_TENS)})-(?:{_alt(k for k, v in _ORD_UNITS.items() if v <= 9)})"
_ORD_WORD = _alt(list(_ORD_UNITS) + list(_ORD_TENS))

_TOKEN_RE = re.compile(
    r"(?P<grouped>\d{1,3}(?:,\d{3})+)(?!\d)"
    r"|(?P<ordnum>\d+(?:st|nd|rd|th))\b"
    r"|(?P<sceneid>\d{3}\.\d{2})(?!\d)"
    r"|(?P<decimal>\d+\.\d+)"
    r"|(?P<digits>\d+)"
    rf"|\b(?P<ordcomp>{_ORD_COMPOUND})\b"
    rf"|\b(?P<ordword>{_ORD_WORD})\b"
    rf"|\b(?P<spelled>(?:a\s+(?=(?:{_SCALE_WORD})\b))?(?:{_NUM_WORD})"
    rf"(?:(?:[-\s]+|\s+and\s+(?=(?:{_NUM_WORD})\b))(?:{_NUM_WORD}))*)\b",
    re.IGNORECASE,
)

_LABEL_BEFORE_RE = re.compile(
    r"\b(?:chapters?|ch|scenes?|sessions?)\b\.?\s*(?:\d[\d.]*\s*[–—-]\s*)?$", re.IGNORECASE)
_LEADING_LIST_BEFORE_RE = re.compile(r"^\s*(?:[-*]\s+)?$")
# A bare parenthesised chapter reference, "(004)", "(004, 005)", "(004–006)" (#645). Summaries number
# chapters as zero-padded NNN, so the rule is a REQUIRED LEADING ZERO: "(100 gold)", "(12)", "(3 giants)",
# "(1,000)" stay story numbers, and so does a bare "(100)", which is as likely a quantity as chapter 100.
# Cost: a campaign past chapter 099 loses this shortcut for (100)+ and those get checked as numbers
# (a false positive for the GM to see, never a silent pass). The closing paren is required, so "(004 gold)"
# is not a label.
_PAREN_CHAPTER_RE = re.compile(r"\(\s*0\d{2}(?:\s*[,–—-]\s*0\d{2})*\s*\)")


def parse_spelled_cardinal(text: str) -> int | None:
    """Value of a spelled cardinal phrase, or None. Never a partial value."""
    words = [w for w in re.split(r"[-\s]+", text.lower().strip()) if w]
    if words and words[0] == "a":
        words[0] = "one"  # only reached for "a hundred/thousand/million"
    if not words:
        return None
    if words == ["zero"]:
        return 0
    total = cur = 0
    prev = None  # unit | teen | tens | hundred | scale | and
    group_hundred = False
    last_scale = None
    for idx, w in enumerate(words):
        if w == "and":
            if prev not in ("hundred", "scale") or idx == len(words) - 1:
                return None
            prev = "and"
        elif w == "zero":
            return None
        elif w in _UNITS:
            v = _UNITS[w]
            if v < 10:
                if prev not in (None, "hundred", "scale", "and", "tens"):
                    return None
                cur += v
                prev = "unit" if prev != "tens" else "tens_unit"
            else:
                if prev not in (None, "hundred", "scale", "and"):
                    return None
                cur += v
                prev = "teen"
        elif w in _TENS:
            if prev not in (None, "hundred", "scale", "and"):
                return None
            cur += _TENS[w]
            prev = "tens"
        elif w == "hundred":
            if prev != "unit" or group_hundred or not 1 <= cur <= 9:
                return None
            cur *= 100
            group_hundred = True
            prev = "hundred"
        elif w in ("thousand", "million"):
            scale = _SCALES[w]
            if prev not in ("unit", "tens_unit", "teen", "tens", "hundred") or cur == 0:
                return None
            if last_scale is not None and last_scale <= scale:
                return None
            total += cur * scale
            cur = 0
            group_hundred = False
            last_scale = scale
            prev = "scale"
        else:
            return None
    if prev == "and":
        return None
    return total + cur


def _ordinal_value(word: str) -> int | None:
    w = word.lower()
    if "-" in w:
        t, u = w.split("-", 1)
        return _TENS[t] + _ORD_UNITS[u]
    return _ORD_UNITS.get(w, _ORD_TENS.get(w))


@lru_cache(maxsize=4)
def _idioms(path: Path) -> tuple[str, ...]:
    return load_ordinal_idioms(path)


_SCENE_WORD_BEFORE_RE = re.compile(r"\bscenes?\b(?:\W+\w+){0,2}\W*$", re.IGNORECASE)


def tokens(claim: str, cited_chapters=()) -> list[Token]:
    """Tokens of one claim. ``NNN.SS`` is a scene label only beside the word "scene" or when NNN is a
    chapter the sentence cites; otherwise it is a decimal compared by surface (e.g. 120.50 gold)."""
    cited_chapters = frozenset(cited_chapters)
    low = claim.lower()
    idiom_spans = [
        (m.start(), m.end(), phrase)
        for phrase in _idioms(ORDINAL_IDIOMS_PATH)
        for m in re.finditer(rf"(?<![\w-]){re.escape(phrase)}(?!\w)", low)
    ]
    paren_spans = [(m.start(), m.end()) for m in _PAREN_CHAPTER_RE.finditer(claim)]
    out: list[Token] = []
    for m in _TOKEN_RE.finditer(claim):
        group = m.lastgroup
        surface = m.group(0)
        span = (m.start(), m.end())
        kind, value, spelled = "cardinal", None, False
        if group == "grouped":
            value = int(surface.replace(",", ""))
        elif group == "digits":
            value = int(surface)
        elif group == "ordnum":
            kind, value = "ordinal", int(re.match(r"\d+", surface).group(0))
        elif group in ("ordword", "ordcomp"):
            kind, value, spelled = "ordinal", _ordinal_value(surface), True
        elif group == "spelled":
            spelled, value = True, parse_spelled_cardinal(surface)
        # sceneid / decimal: value stays None, compared by surface

        before = claim[:span[0]]
        after = claim[span[1]:span[1] + 2]
        numeric = kind == "cardinal" and not spelled
        scene_label = group == "sceneid" and (
            _SCENE_WORD_BEFORE_RE.search(before) is not None
            or int(surface[:3]) in cited_chapters)
        label = scene_label or (numeric and (
            _LABEL_BEFORE_RE.search(before) is not None
            or (group == "digits" and len(surface) == 3
                and any(s <= span[0] and span[1] <= e for s, e in paren_spans))
            or (group == "digits" and _LEADING_LIST_BEFORE_RE.match(before) is not None
                and len(after) == 2 and after[0] in ".)" and after[1].isspace())
        ))
        idiom = None
        if kind == "ordinal":
            idiom = next((p for s, e, p in idiom_spans if s <= span[0] and span[1] <= e), None)
        out.append(Token(surface, kind, value, span, spelled, label, idiom))
    return out


# ---------------------------------------------------------------- records and accounting

@dataclass(frozen=True)
class NoiseRecord:
    check: str
    noise_class: str
    line: int
    token: str
    sentence: str
    cited_scenes: tuple[str, ...]
    resolved_by: str

    def __post_init__(self):
        if self.check not in ("number", "status"):
            raise ValueError(f"unknown check {self.check!r}")
        if self.noise_class not in CLASSES:
            raise ValueError(f"unknown noise class {self.noise_class!r}")

    @property
    def legacy_code(self) -> str:
        return legacy_code(self.noise_class)

    def to_dict(self) -> dict:
        return {"check": self.check, "noise_class": self.noise_class, "line": self.line,
                "token": self.token, "sentence": self.sentence,
                "cited_scenes": list(self.cited_scenes), "resolved_by": self.resolved_by}

    @classmethod
    def from_dict(cls, d: dict) -> "NoiseRecord":
        return cls(check=d["check"], noise_class=d["noise_class"], line=int(d["line"]),
                   token=d["token"], sentence=d["sentence"],
                   cited_scenes=tuple(d.get("cited_scenes", ())), resolved_by=d["resolved_by"])


@dataclass(frozen=True)
class CheckAccounting:
    examined: int = 0
    supported: int = 0
    noise: dict = field(default_factory=dict)
    findings: int = 0

    def __post_init__(self):
        unknown = set(self.noise) - set(CLASSES)
        if unknown:
            raise ValueError(f"unknown noise classes {sorted(unknown)}")
        object.__setattr__(self, "noise", {c: int(self.noise.get(c, 0)) for c in CLASSES})

    def check(self) -> None:
        total = self.supported + sum(self.noise.values()) + self.findings
        if self.examined != total:
            raise AssertionError(
                f"accounting does not partition: examined {self.examined} != supported "
                f"{self.supported} + noise {sum(self.noise.values())} + findings {self.findings}")

    def to_dict(self) -> dict:
        return {"examined": self.examined, "supported": self.supported,
                "noise": dict(self.noise), "findings": self.findings}

    @classmethod
    def from_dict(cls, d: dict) -> "CheckAccounting":
        return cls(examined=int(d.get("examined", 0)), supported=int(d.get("supported", 0)),
                   noise=dict(d.get("noise", {})), findings=int(d.get("findings", 0)))


# ---------------------------------------------------------------- number classification

def scene_name(citation: tuple[int, str]) -> str:
    return f"ch {citation[0]:03d} / {citation[1]}"


def is_bare_one(token: Token) -> bool:
    """Draft-side bare "one" is a pronoun or determiner far more often than a count (R3a)."""
    return token.kind == "cardinal" and token.spelled and token.surface.casefold() == "one"


def token_key(token: Token) -> tuple:
    """Comparison key: (kind, value) when the value is known, else the case-folded surface."""
    if token.value is not None:
        return ("v", token.kind, token.value)
    return ("s", token.kind, token.surface.casefold())


@dataclass(frozen=True)
class FindingInfo:
    """Structured facts behind one GM-facing number/ordinal finding."""

    tokens: tuple[str, ...]
    sentence: str
    cited_scenes: tuple[str, ...]
    evidence_texts: tuple[str, ...]  # resolved cited occurrences, citation order


@dataclass(frozen=True)
class NumberAnalysis:
    findings: tuple  # npc_verify.Finding
    infos: dict  # Finding -> FindingInfo
    noise: tuple[NoiseRecord, ...]
    noise_texts: tuple[str | None, ...]  # parallel to noise: resolving evidence text, if any
    accounting: CheckAccounting
    uncited_sentences: int  # examined nothing: no own or inherited citation
    unresolved_citations: tuple[str, ...]  # a citation with 0 or >1 occurrences contributed no text


def analyse_numbers(draft_text: str, evidence) -> NumberAnalysis:
    """Classify every number/ordinal token of every cited sentence (spec 041, R2-R5, R3a).

    ``evidence`` is an ``npc_check.EvidenceIndex``. Accounting counts TOKENS throughout, so
    ``findings`` is the number of unsupported tokens, not the number of Finding objects (one
    Finding lists all of a sentence's unsupported tokens). That keeps
    ``examined == supported + sum(noise) + findings`` a true partition of examined tokens.
    """
    from .npc_verify import Finding

    findings: list = []
    infos: dict = {}
    records: list[NoiseRecord] = []
    texts: list[str | None] = []
    noise_counts = {c: 0 for c in CLASSES}
    examined = supported = finding_tokens = uncited = 0
    unresolved: list[str] = []
    token_cache: dict[tuple[int, str], list[Token]] = {}

    def evidence_tokens(cit):
        if cit not in token_cache:
            occ = evidence.items_at(*cit)
            token_cache[cit] = (
                [t for t in tokens(occ[0].text) if not t.label] if len(occ) == 1 else None)
        return token_cache[cit]

    for sc in sentence_claims(draft_text):
        if not sc.citations:
            uncited += 1
            continue
        scenes = tuple(scene_name(c) for c in sc.citations)
        resolvable = []
        for cit in sc.citations:
            if evidence_tokens(cit) is None:
                if scene_name(cit) not in unresolved:
                    unresolved.append(scene_name(cit))
            else:
                resolvable.append(cit)
        if not resolvable:
            # No cited occurrence resolves (0 or >1 matches): the old checker skipped such a
            # sentence entirely, and its line already carries its own citation finding. Examine
            # nothing, so no noise item is invented for a line that never produced a finding.
            continue
        first_text = evidence.items_at(*resolvable[0])[0].text

        def note(cls, tok, resolved_by, text):
            nonlocal examined
            examined += 1
            noise_counts[cls] += 1
            records.append(NoiseRecord("number", cls, sc.line, tok.surface, sc.sentence, scenes, resolved_by))
            texts.append(text)

        unsupported: list[Token] = []
        for tok in tokens(sc.claim, tuple(c[0] for c in sc.citations)):
            if is_bare_one(tok):
                continue
            if tok.label:
                note("label", tok, "", first_text)
                continue
            if tok.idiom:
                note("idiom", tok, tok.idiom, first_text)
                continue
            key = token_key(tok)
            hits = []  # (citation, matched evidence token or None)
            for cit in resolvable:
                hit = next((e for e in evidence_tokens(cit) if token_key(e) == key), None)
                hits.append((cit, hit))
            matched = [(c, h) for c, h in hits if h is not None]
            if len(matched) == len(hits):
                normalised = next(
                    (h for _c, h in matched
                     if (tok.spelled or h.spelled) and tok.surface.casefold() != h.surface.casefold()),
                    None)
                if normalised is not None:
                    note("spelled-number", tok, normalised.surface,
                         evidence.items_at(*matched[0][0])[0].text)
                else:
                    examined += 1
                    supported += 1
            elif matched:
                cit = matched[0][0]
                note("other-citation", tok, scene_name(cit), evidence.items_at(*cit)[0].text)
            else:
                examined += 1
                finding_tokens += 1
                unsupported.append(tok)
        if unsupported:
            code = ("ordinal-inconsistency" if any(t.kind == "ordinal" for t in unsupported)
                    else "number-inconsistency")
            listed = ", ".join(f'"{t.surface}"' for t in unsupported)
            finding = Finding(
                code, sc.line, sc.sentence,
                f"draft says {listed}; no scene this sentence cites contains it "
                f"(cited: {', '.join(scenes)})")
            findings.append(finding)
            infos[finding] = FindingInfo(
                tuple(t.surface for t in unsupported), sc.sentence, scenes,
                tuple(evidence.items_at(*c)[0].text for c in resolvable))

    accounting = CheckAccounting(examined, supported, noise_counts, finding_tokens)
    accounting.check()
    return NumberAnalysis(tuple(findings), infos, tuple(records), tuple(texts), accounting,
                          uncited, tuple(unresolved))


def classify_numbers(draft_text: str, evidence):
    """``(findings, noise_records, accounting)`` for the number/ordinal check."""
    a = analyse_numbers(draft_text, evidence)
    return list(a.findings), list(a.noise), a.accounting


# ---------------------------------------------------------------- status classification

_NOT_ESTABLISHED_PATTERNS = (
    re.compile(r"\bno (?:further )?status\b.*\bestablished\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bstatus\b.*\b(?:is|remains) (?:not|un)\s?(?:established|known|stated|confirmed)\b",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:not|un)known whether\b", re.IGNORECASE),
    re.compile(r"\bunclear whether\b", re.IGNORECASE),
)


def is_not_established(sentence: str) -> str | None:
    """The matched phrase if the sentence is a closed-pattern "status not established" non-claim (R7)."""
    for pattern in _NOT_ESTABLISHED_PATTERNS:
        m = pattern.search(sentence)
        if m:
            return m.group(0)
    return None


_CLAUSE_BREAK_RE = re.compile(r";|\s[—–]\s|,?\s+but\s|,\s*however\b|,\s*yet\s", re.IGNORECASE)


def clause_spans(sentence: str) -> list[tuple[int, int]]:
    """Spans of the clauses of a sentence, split at ';', a spaced dash, 'but', ', however' and ', yet'."""
    spans, start = [], 0
    for m in _CLAUSE_BREAK_RE.finditer(sentence):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(sentence)))
    return spans


def classify_status(draft_text: str, sections: dict, evidence):
    """``(findings, noise_records, accounting)`` for the status-word check (spec 041, R7).

    Scope is unchanged: the Last Observed State section plus the first MAP section. A literal status
    word is supported by the whole evidence text. A synonym resolves a word only when it appears in a
    scene the sentence cites; a "not established" phrase negates only the clause containing it.
    """
    from . import schema
    from .npc_verify import LAST_STATE, STATUS_UNSUPPORTED, _STATUS_RE, Finding, _strip_frontmatter

    synonyms = load_status_synonyms()
    if isinstance(evidence, str):  # raw dossier text: parse it the way npc_verify.build_context does
        evidence = npc_check.EvidenceIndex.of(npc_check.split_chapters(_strip_frontmatter(evidence)))
    evidence_text = evidence.text
    scopes = [sections.get(LAST_STATE, (0, [])), sections.get(schema.MAP_SECTIONS[0], (0, []))]
    findings: list = []
    records: list[NoiseRecord] = []
    noise_counts = {c: 0 for c in CLASSES}
    examined = supported = 0
    seen: set[tuple[int, str, str]] = set()

    def present(word: str) -> bool:
        return re.search(rf"\b{re.escape(word)}\b", evidence_text, re.IGNORECASE) is not None

    def in_cited(word: str, cits) -> bool:
        for cit in cits:
            occ = evidence.items_at(*cit)
            if len(occ) == 1 and re.search(rf"\b{re.escape(word)}\b", occ[0].text, re.IGNORECASE):
                return True
        return False

    for start, lines in scopes:
        for off, ln in enumerate(lines):
            lineno = start + off + 1
            line_cits = _valid_citations(ln)
            for sentence in split_sentences(ln):
                cits = _valid_citations(sentence) or line_cits
                scenes = tuple(scene_name(c) for c in cits)
                clauses = clause_spans(sentence)
                for m in _STATUS_RE.finditer(sentence):
                    w = m.group(1).casefold()
                    if (lineno, sentence, w) in seen:
                        continue
                    seen.add((lineno, sentence, w))
                    examined += 1
                    a, b = next(((x, y) for x, y in clauses if x <= m.start() < max(y, x + 1)), (0, len(sentence)))
                    phrase = is_not_established(sentence[a:b])
                    if phrase is not None:
                        noise_counts["negated-status"] += 1
                        records.append(NoiseRecord("status", "negated-status", lineno, w, sentence, scenes, phrase))
                    elif present(w):
                        supported += 1
                    else:
                        syn = next((s for s in synonyms[w] if in_cited(s, cits)), None)
                        if syn is not None:
                            noise_counts["synonym"] += 1
                            records.append(NoiseRecord("status", "synonym", lineno, w, sentence, scenes, syn))
                        else:
                            findings.append(Finding(
                                STATUS_UNSUPPORTED, lineno, sentence,
                                f'draft says "{w}"; neither it nor a listed synonym appears in the evidence '
                                f'(sentence cites: {", ".join(scenes) if scenes else "none"})'))
    accounting = CheckAccounting(examined, supported, noise_counts, len(findings))
    accounting.check()
    return findings, records, accounting
