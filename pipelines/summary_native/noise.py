"""Deterministic noise classification primitives for the NPC number and status checks (spec 041).

Loaders for the two reviewed tables, sentence splitting with citation binding, a number/ordinal
tokenizer with label and idiom detection, and the noise-record and accounting value objects.
Deterministic: stdlib plus PyYAML only. This module makes no model call (AST-guarded by
tests/test_summary_native_no_llm.py).
"""
from __future__ import annotations

import re
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


def load_status_synonyms(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    # Local import: npc_verify will import this module for classification, so a module-level
    # import here would become a cycle.
    from .npc_verify import STATUS_WORDS

    p = Path(path) if path is not None else STATUS_SYNONYMS_PATH
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


_ABBREVIATIONS = frozenset({"st.", "mr.", "mrs.", "dr.", "vs.", "e.g.", "i.e.", "ch."})
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
                word = word_m.group(1).lower().lstrip("([\"'“‘") if word_m else ""
                abbrev = word in _ABBREVIATIONS
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


def tokens(claim: str) -> list[Token]:
    low = claim.lower()
    idiom_spans = [
        (m.start(), m.end(), phrase)
        for phrase in load_ordinal_idioms()
        for m in re.finditer(rf"(?<![\w-]){re.escape(phrase)}(?!\w)", low)
    ]
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
        label = group == "sceneid" or (numeric and (
            _LABEL_BEFORE_RE.search(before) is not None
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
