"""
fivetools_copy.py — Python port of 5etools' ``DataUtil.generic.copyApplier``.

5etools entities can be defined as a thin override of an existing entity:

    {
        "name": "Aljanor Keenblade",
        "source": "OotA",
        "_copy": {
            "name": "Knight",
            "source": "MM",
            "_mod": {"*": {"mode": "replaceTxt", "replace": "the knight", "with": "Aljanor"}}
        }
    }

Nothing in MemPalace can usefully match "Aljanor" until ``_copy`` is
resolved into the full inherited entity. This module is the resolver.

Reference implementation:
    /home/kroussos/src/5etools-kostadis/js/utils.js  (class ``copyApplier``)

Coverage:
* Same-file parents.
* Cross-file parents via ``_meta.dependencies.<prop>`` + the per-prop
  ``index.json`` shard map (e.g. ``data/bestiary/index.json``).
* Top-level prop overrides (entity-level keys win over parent values).
* ``_mod`` operations covering everything the canonical 5e data uses.

Limitations:
* ``_copy._templates`` (monster templates) — logged as warning, skipped.
* ``_copy._preserve`` — handled implicitly: parent fills missing keys, so
  any field already on the child is preserved.

Pure module — no I/O outside ``load_dependency_pool`` (which is a
deliberate filesystem read against a known data root).
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# Entry-array props that ``_mod`` "*" applies to (matches JS
# ``COPY_ENTRY_PROPS``). Bestiary-flavored.
_COPY_ENTRY_PROPS = (
    "action", "bonus", "reaction", "trait", "legendary", "mythic",
    "variant", "spellcasting",
    "actionHeader", "bonusHeader", "reactionHeader",
    "legendaryHeader", "mythicHeader",
)

# Prop ordering inside _mod (mirrors JS _PROPS_TAIL). "_" and "*" run last.
_PROPS_TAIL = ("_", "*")


# Per-prop shard directory under the 5etools data root. Empty value =
# single-file (e.g. races.json) — no cross-file deps possible.
_PROP_SHARD_DIR = {
    "monster": "bestiary",
    "monsterFluff": "bestiary",
    "spell": "spells",
    "spellFluff": "spells",
    "class": "class",
    "subclass": "class",
    "classFeature": "class",
    "subclassFeature": "class",
}


# ── Public API ─────────────────────────────────────────────────────────────


def resolve_copies(
    entities: list[dict],
    *,
    prop: str,
    extra_pool: list[dict] | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> list[dict]:
    """Resolve every ``_copy`` reference in ``entities`` (in place).

    Parents are looked up first in ``entities`` itself, then in
    ``extra_pool`` (typically loaded via ``load_dependency_pool``).
    Entities without ``_copy`` are returned unchanged.

    Returns the same list for chaining.
    """
    on_warn = on_warning or (lambda msg: logger.warning("_copy: %s", msg))
    pool: dict[tuple[str, str], dict] = {}
    for src in (extra_pool or [], entities):
        for ent in src:
            if not isinstance(ent, dict):
                continue
            key = _entity_key(ent)
            if key:
                # First-seen wins (matches JS merge-cache behavior).
                pool.setdefault(key, ent)

    resolver = _CopyResolver(prop=prop, parent_pool=pool, on_warning=on_warn)
    for ent in entities:
        if isinstance(ent, dict) and "_copy" in ent:
            resolver.resolve(ent)
    return entities


def load_dependency_pool(
    raw_doc: dict,
    *,
    prop: str,
    data_root: Path,
    on_warning: Callable[[str], None] | None = None,
) -> list[dict]:
    """Load the parent pool for cross-file ``_copy`` resolution.

    Reads ``_meta.dependencies.<prop>`` (a list of source codes) and
    walks ``<data_root>/<shard_dir>/index.json`` to find the file backing
    each source. Returns the concatenated ``<prop>`` list across all
    dependency files.

    Returns an empty list when the doc has no dependencies for this
    prop, when the shard dir is unknown, or when the index file is
    missing. Errors are logged, never raised — a missing dep just means
    some _copy refs won't resolve.
    """
    on_warn = on_warning or (lambda msg: logger.warning("_copy deps: %s", msg))
    if not isinstance(raw_doc, dict):
        return []
    deps = ((raw_doc.get("_meta") or {}).get("dependencies") or {}).get(prop) or []
    if not deps:
        return []
    shard_dir = _PROP_SHARD_DIR.get(prop)
    if not shard_dir:
        on_warn(f"no shard directory mapping for prop {prop!r}; skipping deps {deps!r}")
        return []
    index_path = Path(data_root) / shard_dir / "index.json"
    if not index_path.is_file():
        on_warn(f"index file missing: {index_path}")
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        on_warn(f"index parse failed at {index_path}: {exc}")
        return []
    pool: list[dict] = []
    seen_files: set[str] = set()
    for src in deps:
        fname = index.get(src)
        if not fname:
            on_warn(f"dependency {src!r} not in {index_path}")
            continue
        if fname in seen_files:
            continue
        seen_files.add(fname)
        dep_path = index_path.parent / fname
        try:
            dep_doc = json.loads(dep_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            on_warn(f"dep load failed at {dep_path}: {exc}")
            continue
        pool.extend(e for e in (dep_doc.get(prop) or []) if isinstance(e, dict))
    return pool


def _entity_key(entity: dict) -> tuple[str, str] | None:
    name = entity.get("name")
    src = entity.get("source")
    if not isinstance(name, str) or not isinstance(src, str):
        return None
    return (name.lower().strip(), src.lower().strip())


# ── Resolver ──────────────────────────────────────────────────────────────


class _CopyResolver:
    def __init__(
        self,
        *,
        prop: str,
        parent_pool: dict[tuple[str, str], dict],
        on_warning: Callable[[str], None],
    ):
        self.prop = prop
        self.pool = parent_pool
        self.on_warning = on_warning
        self._resolving: set[tuple[str, str]] = set()

    # ── Top-level resolve ─────────────────────────────────────────────────

    def resolve(self, entity: dict) -> dict:
        if "_copy" not in entity:
            return entity
        copy_meta = entity["_copy"] or {}
        parent_name = (copy_meta.get("name") or "")
        parent_src = (copy_meta.get("source") or "")
        key = (parent_name.lower().strip(), parent_src.lower().strip())

        if key in self._resolving:
            self.on_warning(
                f"_copy cycle: {entity.get('name')!r} -> "
                f"{parent_name!r}/{parent_src!r}"
            )
            entity.pop("_copy", None)
            return entity

        parent = self.pool.get(key)
        if parent is None:
            self.on_warning(
                f"_copy parent missing: {entity.get('name')!r} -> "
                f"{parent_name!r}/{parent_src!r}"
            )
            entity.pop("_copy", None)
            return entity

        # Recursively resolve the parent first, but make a deep copy so
        # mutations don't leak back into shared pool entries.
        if "_copy" in parent:
            self._resolving.add(key)
            try:
                self.resolve(parent)
            finally:
                self._resolving.discard(key)

        copy_from = copy.deepcopy(parent)

        # Templates — bestiary-only feature; warn and proceed.
        if copy_meta.get("_templates"):
            self.on_warning(
                f"_copy._templates not supported for {entity.get('name')!r} "
                f"(parent {parent_name!r}); template ignored"
            )

        self._merge_parent_fields(copy_from, entity, copy_meta)

        mod = copy_meta.get("_mod") or {}
        if mod:
            self._normalize_mods(mod)
            self._resolve_variables(mod, entity)
            for prop_key, mod_infos in sorted(mod.items(), key=_mod_prop_sort_key):
                infos = mod_infos if isinstance(mod_infos, list) else [mod_infos]
                for info in infos:
                    self._apply_mod(entity, copy_from, prop_key, info)

        entity["_isCopy"] = True
        entity.pop("_copy", None)
        return entity

    # ── Field merge from parent ───────────────────────────────────────────

    def _merge_parent_fields(self, copy_from: dict, copy_to: dict, copy_meta: dict) -> None:
        """For every key in the parent, fill ``copy_to`` only if it's
        missing. Explicit ``null`` on the child means "delete this key
        from the merged result" (mirrors JS).

        ``_copy._preserve`` is honored implicitly: anything already on
        copy_to is left alone.
        """
        for k, v in copy_from.items():
            if k in ("_copy", "_isCopy", "__copy", "__prop"):
                continue
            if k in copy_to:
                if copy_to[k] is None:
                    # Explicit null suppresses parent value.
                    del copy_to[k]
                # else: keep child's value (preserve)
                continue
            copy_to[k] = copy.deepcopy(v)

    # ── Mod normalization + variable resolution ──────────────────────────

    @staticmethod
    def _normalize_mods(mod: dict) -> None:
        for k, v in list(mod.items()):
            if not isinstance(v, list):
                mod[k] = [v]

    def _resolve_variables(self, mod: dict, entity: dict) -> None:
        """Resolve ``<$variable>`` placeholders inside _mod values.

        5etools uses ``<$short_name$>``, ``<$summon_spell_level$>`` etc.
        Most are creature-template-only (which we don't support) so we
        only handle the small set the canonical bestiary actually uses.
        Unknown placeholders are left intact.
        """
        # Known substitutions — kept minimal on purpose.
        subs = {}
        if entity.get("name"):
            subs["<$name$>"] = entity["name"]
            short = entity.get("shortName") or entity["name"].split(" ")[0]
            subs["<$short_name$>"] = short
        if not subs:
            return

        def _walk(node: Any) -> Any:
            if isinstance(node, str):
                out = node
                for k, v in subs.items():
                    out = out.replace(k, v)
                return out
            if isinstance(node, list):
                return [_walk(x) for x in node]
            if isinstance(node, dict):
                return {k: _walk(v) for k, v in node.items()}
            return node

        for k in list(mod.keys()):
            mod[k] = _walk(mod[k])

    # ── Mod dispatch ──────────────────────────────────────────────────────

    def _apply_mod(
        self,
        copy_to: dict,
        copy_from: dict,
        prop_key: str,
        mod_info: Any,
    ) -> None:
        if isinstance(mod_info, str):
            if mod_info == "remove":
                if prop_key in ("_", "*"):
                    return
                copy_to.pop(prop_key, None)
            else:
                self.on_warning(f"unhandled string mod {mod_info!r} on prop {prop_key!r}")
            return

        mode = (mod_info or {}).get("mode")
        if not mode:
            self.on_warning(f"mod info without mode on prop {prop_key!r}: {mod_info!r}")
            return

        if prop_key == "*":
            for p in _COPY_ENTRY_PROPS:
                self._apply_one_mod(copy_to, copy_from, [p], mod_info, mode)
            return
        if prop_key == "_":
            self._apply_one_mod(copy_to, copy_from, [], mod_info, mode)
            return

        path = prop_key.split(".")
        self._apply_one_mod(copy_to, copy_from, path, mod_info, mode)

    def _apply_one_mod(
        self,
        copy_to: dict,
        copy_from: dict,
        path: list[str],
        mod_info: dict,
        mode: str,
    ) -> None:
        try:
            handler = _MOD_DISPATCH[mode]
        except KeyError:
            self.on_warning(f"unhandled mod mode {mode!r} (path={path!r})")
            return
        try:
            handler(self, copy_to, copy_from, path, mod_info)
        except Exception as exc:  # noqa: BLE001 — convert mod errors to warnings
            self.on_warning(
                f"mod {mode!r} on path {path!r} for {copy_to.get('name')!r} failed: {exc}"
            )

    # ── Mod handlers (all bound methods so they share state) ─────────────

    def _do_appendStr(self, copy_to, copy_from, path, info):
        cur = _path_get(copy_to, path)
        joiner = info.get("joiner") or ""
        new_str = info.get("str") or ""
        merged = f"{cur}{joiner}{new_str}" if cur else new_str
        _path_set(copy_to, path, merged)

    def _do_replaceName(self, copy_to, copy_from, path, info):
        ents = _path_get(copy_to, path)
        if not isinstance(ents, list):
            return
        rx = self._make_regex(info)
        with_str = info.get("with") or ""
        for ent in ents:
            if isinstance(ent, dict) and isinstance(ent.get("name"), str):
                ent["name"] = rx.sub(with_str, ent["name"])

    def _do_replaceTxt(self, copy_to, copy_from, path, info):
        target = _path_get(copy_to, path) if path else copy_to
        rx = self._make_regex(info)
        with_str = info.get("with") or ""
        props = info.get("props") or [None, "entries", "headerEntries", "footerEntries"]
        tag_insensitive = bool(info.get("tagInsensitive"))

        def _replace_in_str(s: str) -> str:
            if not isinstance(s, str):
                return s
            if tag_insensitive:
                return rx.sub(with_str, s)
            # Skip {@tag ...} segments.
            chunks = re.split(r"(\{@[^{}]*\})", s)
            for i, chunk in enumerate(chunks):
                if chunk.startswith("{@"):
                    continue
                chunks[i] = rx.sub(with_str, chunk)
            return "".join(chunks)

        def _walk(node: Any) -> Any:
            if isinstance(node, str):
                return _replace_in_str(node)
            if isinstance(node, list):
                return [_walk(x) for x in node]
            if isinstance(node, dict):
                return {k: _walk(v) for k, v in node.items()}
            return node

        if not path:
            # "_" mode — apply to the whole entity except identity fields.
            for k in list(copy_to.keys()):
                if k in ("name", "source", "page", "_copy", "_isCopy", "__prop"):
                    continue
                copy_to[k] = _walk(copy_to[k])
            return

        if isinstance(target, list):
            # Per-entry: apply to selected props on each entry, plus pure
            # strings if `null` is in props.
            new_list = []
            for it in target:
                if isinstance(it, str) and (None in props):
                    new_list.append(_replace_in_str(it))
                elif isinstance(it, dict):
                    out = dict(it)
                    for p in props:
                        if p is None:
                            continue
                        if p in out:
                            out[p] = _walk(out[p])
                    new_list.append(out)
                else:
                    new_list.append(it)
            _path_set(copy_to, path, new_list)
        elif isinstance(target, str):
            _path_set(copy_to, path, _replace_in_str(target))
        elif isinstance(target, (dict, list)):
            _path_set(copy_to, path, _walk(target))

    def _do_prependArr(self, copy_to, copy_from, path, info):
        items = _ensure_list(info.get("items"))
        cur = _path_get(copy_to, path) or []
        if not isinstance(cur, list):
            cur = [cur]
        _path_set(copy_to, path, items + cur)

    def _do_appendArr(self, copy_to, copy_from, path, info):
        items = _ensure_list(info.get("items"))
        cur = _path_get(copy_to, path) or []
        if not isinstance(cur, list):
            cur = [cur]
        _path_set(copy_to, path, cur + items)

    def _do_appendIfNotExistsArr(self, copy_to, copy_from, path, info):
        items = _ensure_list(info.get("items"))
        cur = _path_get(copy_to, path) or []
        if not isinstance(cur, list):
            cur = [cur]
        new_items = [it for it in items if it not in cur]
        _path_set(copy_to, path, cur + new_items)

    def _do_replaceArr(self, copy_to, copy_from, path, info, *, throw: bool = True):
        items = _ensure_list(info.get("items"))
        cur = _path_get(copy_to, path)
        if not isinstance(cur, list):
            if throw:
                raise ValueError(f"replaceArr: prop {'.'.join(path)} is not an array")
            return False
        ix = self._find_replace_index(cur, info.get("replace"))
        if ix is None:
            if throw:
                raise ValueError(f"replaceArr: target not found at {'.'.join(path)}")
            return False
        new_list = cur[:ix] + items + cur[ix + 1 :]
        _path_set(copy_to, path, new_list)
        return True

    def _do_replaceOrAppendArr(self, copy_to, copy_from, path, info):
        ok = self._do_replaceArr(copy_to, copy_from, path, info, throw=False)
        if not ok:
            self._do_appendArr(copy_to, copy_from, path, info)

    def _do_insertArr(self, copy_to, copy_from, path, info):
        items = _ensure_list(info.get("items"))
        cur = _path_get(copy_to, path) or []
        if not isinstance(cur, list):
            cur = [cur]
        idx = info.get("index")
        idx = idx if isinstance(idx, int) else len(cur)
        idx = max(0, min(idx, len(cur)))
        _path_set(copy_to, path, cur[:idx] + items + cur[idx:])

    def _do_removeArr(self, copy_to, copy_from, path, info):
        cur = _path_get(copy_to, path)
        if not isinstance(cur, list):
            return
        names = info.get("names")
        if isinstance(names, str):
            names = [names]
        if isinstance(names, list):
            new_list = [
                it for it in cur
                if not (isinstance(it, dict) and it.get("name") in names)
            ]
            _path_set(copy_to, path, new_list)
            return
        items = info.get("items")
        if isinstance(items, str):
            items = [items]
        if isinstance(items, list):
            new_list = [it for it in cur if it not in items]
            _path_set(copy_to, path, new_list)
            return
        # Fallback: clear the array.
        if info.get("force"):
            _path_set(copy_to, path, [])

    def _do_renameArr(self, copy_to, copy_from, path, info):
        cur = _path_get(copy_to, path)
        if not isinstance(cur, list):
            return
        renames = info.get("renames") or []
        rename_map = {}
        for r in renames:
            if isinstance(r, dict):
                rename_map[r.get("rename")] = r.get("with")
        for it in cur:
            if isinstance(it, dict) and it.get("name") in rename_map:
                it["name"] = rename_map[it.get("name")]

    def _do_setProp(self, copy_to, copy_from, path, info):
        sub = info.get("prop")
        full_path = list(path)
        if sub:
            full_path = full_path + sub.split(".")
        _path_set(copy_to, full_path, copy.deepcopy(info.get("value")))

    def _do_prefixSuffixStringProp(self, copy_to, copy_from, path, info):
        sub = info.get("prop")
        full_path = list(path)
        if sub:
            full_path = full_path + sub.split(".")
        cur = _path_get(copy_to, full_path)
        if not isinstance(cur, str):
            return
        prefix = info.get("prefix") or ""
        suffix = info.get("suffix") or ""
        _path_set(copy_to, full_path, f"{prefix}{cur}{suffix}")

    def _do_scalarAddProp(self, copy_to, copy_from, path, info):
        sub = info.get("prop")
        full_path = list(path)
        if sub:
            full_path = full_path + sub.split(".")
        cur = _path_get(copy_to, full_path)
        if isinstance(cur, (int, float)):
            _path_set(copy_to, full_path, cur + (info.get("scalar") or 0))

    def _do_scalarMultProp(self, copy_to, copy_from, path, info):
        sub = info.get("prop")
        full_path = list(path)
        if sub:
            full_path = full_path + sub.split(".")
        cur = _path_get(copy_to, full_path)
        if isinstance(cur, (int, float)):
            new_val = cur * (info.get("scalar") or 1)
            if info.get("floor"):
                new_val = int(new_val)
            _path_set(copy_to, full_path, new_val)

    def _do_calculateProp(self, copy_to, copy_from, path, info):
        # The JS impl supports a small DSL; rather than port it now we
        # warn and skip. Real-data usage is sparse and template-only.
        self.on_warning(f"calculateProp not implemented (path={path!r})")

    # Bestiary-specific mods

    def _do_addSenses(self, copy_to, copy_from, path, info):
        senses = copy_to.get("senses")
        if not isinstance(senses, list):
            senses = []
            copy_to["senses"] = senses
        for new in _ensure_list(info.get("senses")):
            if isinstance(new, dict):
                kind = (new.get("type") or "").lower()
                rng = new.get("range")
                txt = f"{kind} {rng} ft." if rng else kind
            elif isinstance(new, str):
                txt = new
            else:
                continue
            if txt and txt not in senses:
                senses.append(txt)

    def _do_addSaves(self, copy_to, copy_from, path, info):
        saves = copy_to.setdefault("save", {})
        for k, v in (info or {}).items():
            if k == "mode":
                continue
            saves[k] = v

    def _do_addSkills(self, copy_to, copy_from, path, info):
        skills = copy_to.setdefault("skill", {})
        for k, v in (info or {}).items():
            if k == "mode":
                continue
            skills[k] = v

    def _do_addAllSaves(self, copy_to, copy_from, path, info):
        bonus = info.get("bonus") or 0
        for ab in ("str", "dex", "con", "int", "wis", "cha"):
            if ab not in copy_to:
                continue
            mod = (copy_to[ab] - 10) // 2 + bonus
            saves = copy_to.setdefault("save", {})
            saves[ab] = f"+{mod}" if mod >= 0 else str(mod)

    def _do_addAllSkills(self, copy_to, copy_from, path, info):
        bonus = info.get("bonus") or 0
        skills = copy_to.setdefault("skill", {})
        for sk, ab in _SKILL_ABILITY.items():
            if ab not in copy_to or sk in skills:
                continue
            mod = (copy_to[ab] - 10) // 2 + bonus
            skills[sk] = f"+{mod}" if mod >= 0 else str(mod)

    def _do_addSpells(self, copy_to, copy_from, path, info):
        # Append to the first spellcasting block; create one if missing.
        sc_list = copy_to.setdefault("spellcasting", [])
        if not sc_list:
            sc_list.append({"name": "Spellcasting", "type": "spellcasting", "spells": {}})
        target = sc_list[0]
        spells = target.setdefault("spells", {})
        for level, payload in (info.get("spells") or {}).items():
            slot = (spells.get(level) or {})
            new_slot = dict(slot)
            existing = list(new_slot.get("spells") or [])
            for s in (payload or {}).get("spells", []):
                if s not in existing:
                    existing.append(s)
            new_slot["spells"] = existing
            if "slots" in payload:
                new_slot["slots"] = payload["slots"]
            spells[level] = new_slot

    def _do_replaceSpells(self, copy_to, copy_from, path, info):
        sc_list = copy_to.get("spellcasting") or []
        if not sc_list:
            return
        target = sc_list[0]
        spells = target.setdefault("spells", {})
        for level, payload in (info.get("spells") or {}).items():
            spells[level] = dict(payload or {})

    def _do_removeSpells(self, copy_to, copy_from, path, info):
        sc_list = copy_to.get("spellcasting") or []
        if not sc_list:
            return
        target = sc_list[0]
        spells = target.get("spells") or {}
        for level, payload in (info.get("spells") or {}).items():
            cur = spells.get(level)
            if not isinstance(cur, dict):
                continue
            removed = set((payload or {}).get("spells") or [])
            cur["spells"] = [s for s in (cur.get("spells") or []) if s not in removed]

    def _do_maxSize(self, copy_to, copy_from, path, info):
        max_sz = info.get("max")
        order = ["T", "S", "M", "L", "H", "G"]
        if max_sz not in order:
            return
        cap = order.index(max_sz)
        sizes = copy_to.get("size")
        if not isinstance(sizes, list):
            return
        copy_to["size"] = [s for s in sizes if s in order and order.index(s) <= cap] or [max_sz]

    def _do_scalarMultXp(self, copy_to, copy_from, path, info):
        cr = copy_to.get("cr")
        if isinstance(cr, dict) and isinstance(cr.get("xp"), (int, float)):
            cr["xp"] = int(cr["xp"] * (info.get("scalar") or 1))
        # If cr is a bare string/int we don't have an XP table to multiply
        # against here. Skip silently — the field is informational.

    def _do_scalarAddHit(self, copy_to, copy_from, path, info):
        scalar = info.get("scalar") or 0
        target = _path_get(copy_to, path) if path else copy_to
        if not isinstance(target, list):
            return
        for it in target:
            if isinstance(it, dict) and isinstance(it.get("entries"), list):
                it["entries"] = [
                    _shift_hit(e, scalar) if isinstance(e, str) else e
                    for e in it["entries"]
                ]

    def _do_scalarAddDc(self, copy_to, copy_from, path, info):
        scalar = info.get("scalar") or 0
        target = _path_get(copy_to, path) if path else copy_to
        if not isinstance(target, list):
            return
        for it in target:
            if isinstance(it, dict) and isinstance(it.get("entries"), list):
                it["entries"] = [
                    _shift_dc(e, scalar) if isinstance(e, str) else e
                    for e in it["entries"]
                ]

    # Helpers shared between mods

    @staticmethod
    def _make_regex(info: dict) -> re.Pattern:
        replace = info.get("replace") or ""
        flags_str = info.get("flags") or ""
        flags = 0
        if "i" in flags_str:
            flags |= re.IGNORECASE
        if "s" in flags_str:
            flags |= re.DOTALL
        if "m" in flags_str:
            flags |= re.MULTILINE
        return re.compile(replace, flags)

    @staticmethod
    def _find_replace_index(arr: list, replace_spec: Any) -> int | None:
        if isinstance(replace_spec, dict):
            if "index" in replace_spec:
                idx = replace_spec["index"]
                return idx if 0 <= idx < len(arr) else None
            if "regex" in replace_spec:
                rx = re.compile(
                    replace_spec["regex"],
                    re.IGNORECASE if (replace_spec.get("flags") or "").find("i") >= 0 else 0,
                )
                for i, it in enumerate(arr):
                    if isinstance(it, dict) and isinstance(it.get("name"), str) and rx.search(it["name"]):
                        return i
                    if isinstance(it, str) and rx.search(it):
                        return i
                return None
            return None
        if isinstance(replace_spec, str):
            for i, it in enumerate(arr):
                if isinstance(it, dict) and it.get("name") == replace_spec:
                    return i
                if it == replace_spec:
                    return i
            return None
        return None


# ── Sort key for _mod props ────────────────────────────────────────────────


def _mod_prop_sort_key(item: tuple[str, Any]) -> tuple:
    prop = item[0]
    if prop in _PROPS_TAIL:
        return (1, _PROPS_TAIL.index(prop))
    return (0, prop)


# ── Path helpers ──────────────────────────────────────────────────────────


def _path_get(obj: Any, path: list[str]) -> Any:
    cur = obj
    for seg in path:
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _path_set(obj: Any, path: list[str], value: Any) -> None:
    if not path:
        return
    cur = obj
    for seg in path[:-1]:
        if isinstance(cur, dict):
            if seg not in cur or not isinstance(cur[seg], (dict, list)):
                cur[seg] = {}
            cur = cur[seg]
        else:
            return
    last = path[-1]
    if isinstance(cur, dict):
        cur[last] = value


def _ensure_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# Skill → ability table for addAllSkills.
_SKILL_ABILITY = {
    "athletics": "str",
    "acrobatics": "dex", "sleight of hand": "dex", "stealth": "dex",
    "arcana": "int", "history": "int", "investigation": "int",
    "nature": "int", "religion": "int",
    "animal handling": "wis", "insight": "wis", "medicine": "wis",
    "perception": "wis", "survival": "wis",
    "deception": "cha", "intimidation": "cha", "performance": "cha",
    "persuasion": "cha",
}


# Bonus shifters for scalarAddHit / scalarAddDc.
_HIT_RE = re.compile(r"\{@hit\s*([+\-]?\d+)\}")
_DC_RE = re.compile(r"\{@dc\s*(\d+)\}")


def _shift_hit(s: str, scalar: int) -> str:
    def _shift(m: re.Match) -> str:
        return f"{{@hit {int(m.group(1)) + scalar}}}"
    return _HIT_RE.sub(_shift, s)


def _shift_dc(s: str, scalar: int) -> str:
    def _shift(m: re.Match) -> str:
        return f"{{@dc {int(m.group(1)) + scalar}}}"
    return _DC_RE.sub(_shift, s)


# ── Mod dispatch table (built after all _do_* methods are defined) ────────


_MOD_DISPATCH: dict[str, Callable[..., Any]] = {
    "appendStr": _CopyResolver._do_appendStr,
    "replaceName": _CopyResolver._do_replaceName,
    "replaceTxt": _CopyResolver._do_replaceTxt,
    "prependArr": _CopyResolver._do_prependArr,
    "appendArr": _CopyResolver._do_appendArr,
    "appendIfNotExistsArr": _CopyResolver._do_appendIfNotExistsArr,
    "replaceArr": _CopyResolver._do_replaceArr,
    "replaceOrAppendArr": _CopyResolver._do_replaceOrAppendArr,
    "insertArr": _CopyResolver._do_insertArr,
    "removeArr": _CopyResolver._do_removeArr,
    "renameArr": _CopyResolver._do_renameArr,
    "setProp": _CopyResolver._do_setProp,
    "prefixSuffixStringProp": _CopyResolver._do_prefixSuffixStringProp,
    "scalarAddProp": _CopyResolver._do_scalarAddProp,
    "scalarMultProp": _CopyResolver._do_scalarMultProp,
    "calculateProp": _CopyResolver._do_calculateProp,
    "addSenses": _CopyResolver._do_addSenses,
    "addSaves": _CopyResolver._do_addSaves,
    "addSkills": _CopyResolver._do_addSkills,
    "addAllSaves": _CopyResolver._do_addAllSaves,
    "addAllSkills": _CopyResolver._do_addAllSkills,
    "addSpells": _CopyResolver._do_addSpells,
    "replaceSpells": _CopyResolver._do_replaceSpells,
    "removeSpells": _CopyResolver._do_removeSpells,
    "maxSize": _CopyResolver._do_maxSize,
    "scalarMultXp": _CopyResolver._do_scalarMultXp,
    "scalarAddHit": _CopyResolver._do_scalarAddHit,
    "scalarAddDc": _CopyResolver._do_scalarAddDc,
}
