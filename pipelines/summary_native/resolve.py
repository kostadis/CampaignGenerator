"""The one place the registry and canon paths are decided (feature 031).

Precedence, everywhere: command-line flag > ``grounding.yaml``
``summary_native.<key>`` > default. ``validate``, ``build`` and ``synth`` (and
so synth's registry-staleness hash) all call these, so a registry configured in
``grounding.yaml`` hashes identically at build and at synth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from campaignlib.registry import find_registry

from . import schema


class ConfigRefusal(ValueError):
    """A configured/flagged value that cannot be used; the message is user-facing."""


class PathRefusal(ConfigRefusal):
    """A configured/flagged path that cannot be used; the message is user-facing."""


def _configured(flag, cfg, key: str) -> str | None:
    """The flag, else the grounding.yaml value; a hand-edited non-string is refused."""
    if flag:
        return flag
    value = (cfg or {}).get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise PathRefusal(f"grounding.yaml summary_native.{key} must be a path string, got {value!r}")
    return value


def resolve_canon_path(root, out_root, flag, cfg) -> Path:
    """``--canon`` > ``summary_native.canon_file`` > ``<out_root>/canon.yaml``.

    The default may be absent (no rulings yet). A path the GM named explicitly
    must exist: silently reading a typo'd path as "no rulings" would re-flag
    every pair already ruled distinct.
    """
    given = _configured(flag, cfg, "canon_file")
    if not given:
        return Path(out_root) / "canon.yaml"
    p = schema.resolve_under(root, given)
    if not p.is_file():
        raise PathRefusal(f"canon file {p}: not found (set explicitly via --canon or summary_native.canon_file)")
    return p


def resolve_registry_path(root, flag, cfg) -> Path | None:
    """``--registry`` > ``summary_native.registry`` > auto-discover under ``root``.

    A value may be a file or a directory (a directory is searched for
    ``docs/entity_registry.yaml``). Auto-discovery returns None when absent.
    """
    given = _configured(flag, cfg, "registry")
    if not given:
        return find_registry(root)  # the campaign root, not the cwd
    p = schema.resolve_under(root, given)
    if p.is_dir():
        found = find_registry(p)
        if found is None:
            raise PathRefusal(f"registry {p}: no entity_registry.yaml found under {p}/docs/")
        return found
    if not p.is_file():
        raise PathRefusal(f"registry {p}: not found (set explicitly via --registry or summary_native.registry)")
    return p


# ── Extract and prose settings (spec 033) ───────────────────────────────────


@dataclass(frozen=True)
class ExtractSettings:
    backend: str
    model: str | None  # None: let the backend / its own resolution decide
    chunk_chars: int


@dataclass(frozen=True)
class ProseSettings:
    backend: str
    model: str | None
    effort: str | None  # None unless the backend is claude-code (or a flag asked for one)
    budgets: dict[str, int]


def _block(cfg, name: str) -> dict:
    value = (cfg or {}).get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigRefusal(f"grounding.yaml summary_native.{name} must be a mapping, got {value!r}")
    return value


def _positive_int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigRefusal(f"{what} must be a whole number of at least 1, got {value!r}")
    return value


def _model_for(flag, block: dict, backend: str, default_backend: str, default_model: str) -> str | None:
    """A model id belongs to its backend, so one backend's model never reaches another.

    A flag always wins. The configured model applies only when the effective backend is the one
    it was written for. A configured model equal to the schema default belongs to the schema's
    backend (the saved file always carries it), so it is not carried to any other backend.
    """
    if flag:
        return flag
    given = block.get("model")
    if given is None or (isinstance(given, str) and not given.strip()):
        return default_model if backend == default_backend else None
    if not isinstance(given, str):
        raise ConfigRefusal(f"grounding.yaml summary_native model must be a string, got {given!r}")
    written_for = block.get("backend") or default_backend
    if given == default_model:
        written_for = default_backend
    return given.strip() if backend == written_for else None


def resolve_extract(cfg, *, backend=None, model=None, chunk_chars=None) -> ExtractSettings:
    """``--backend/--model/--chunk-chars`` > ``summary_native.extract`` > ``schema.py``."""
    block = _block(cfg, "extract")
    eff_backend = backend or block.get("backend") or schema.DEFAULT_DRAFT_BACKEND
    eff_model = _model_for(model, block, eff_backend, schema.DEFAULT_DRAFT_BACKEND, schema.DEFAULT_DRAFT_MODEL)
    if chunk_chars is not None:
        chars = _positive_int(chunk_chars, "--chunk-chars")
    else:
        chars = _positive_int(block.get("chunk_chars", schema.DEFAULT_CHUNK_CHARS), "summary_native.extract.chunk_chars")
    return ExtractSettings(eff_backend, eff_model, chars)


def resolve_prose(cfg, *, backend=None, model=None, effort=None) -> ProseSettings:
    """``--backend/--model/--claude-code-effort`` > ``summary_native.prose`` > ``schema.py``.

    ``budgets`` merge over ``schema.DEFAULT_WORLD_BUDGETS``; an unknown section name refuses.
    """
    block = _block(cfg, "prose")
    eff_backend = backend or block.get("backend") or schema.DEFAULT_PROSE_BACKEND
    eff_model = _model_for(model, block, eff_backend, schema.DEFAULT_PROSE_BACKEND, schema.DEFAULT_PROSE_MODEL)
    if effort:
        eff_effort = effort  # a flag is passed on; the backend refuses it where it does not apply
    elif eff_backend == "claude-code":
        eff_effort = block.get("effort") or schema.DEFAULT_PROSE_EFFORT
    else:
        eff_effort = None
    budgets = dict(schema.DEFAULT_WORLD_BUDGETS)
    given = block.get("budgets") or {}
    if not isinstance(given, dict):
        raise ConfigRefusal(f"grounding.yaml summary_native.prose.budgets must be a mapping, got {given!r}")
    unknown = sorted(set(given) - set(budgets))
    if unknown:
        raise ConfigRefusal(
            f"grounding.yaml summary_native.prose.budgets: unknown section(s) {unknown}; known: {sorted(budgets)}"
        )
    for k, v in given.items():
        budgets[k] = _positive_int(v, f"summary_native.prose.budgets[{k!r}]")
    return ProseSettings(eff_backend, eff_model, eff_effort, budgets)
