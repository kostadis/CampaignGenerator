"""Scoped mention candidates over a synthetic evidence graph; never writes a registry.

Entity IDs are opaque. Labels are many-to-many. Location is a time-bounded
relationship, never part of the entity key. Missing facts keep candidates
possible; they are not negative evidence. Resolution produces proposals only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ContextIndex:
    def __init__(self, world: dict):
        self.world = world
        self.world_sha256 = sha(world)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE entities(id TEXT PRIMARY KEY, campaign TEXT, kind TEXT);
            CREATE TABLE labels(entity_id TEXT, label TEXT, PRIMARY KEY(entity_id,label));
            CREATE TABLE locations(id TEXT PRIMARY KEY, campaign TEXT, parent TEXT);
            CREATE TABLE facts(entity_id TEXT, property TEXT, value TEXT,
                valid_from INTEGER, valid_until INTEGER, evidence TEXT);
        """)
        ids = set()
        for entity in world["entities"]:
            if entity["id"] in ids:
                raise ValueError("duplicate entity ID")
            ids.add(entity["id"])
            self.db.execute("INSERT INTO entities VALUES(?,?,?)",
                            (entity["id"], entity["campaign"], entity["kind"]))
            for label in entity["labels"]:
                self.db.execute("INSERT INTO labels VALUES(?,?)", (entity["id"], label.casefold()))
        locations = {loc["id"]: loc for loc in world["locations"]}
        if len(locations) != len(world["locations"]):
            raise ValueError("duplicate location ID")
        for loc in world["locations"]:
            parent = loc.get("parent")
            if parent and (parent not in locations or locations[parent]["campaign"] != loc["campaign"]):
                raise ValueError("unknown or cross-campaign location parent")
            self.db.execute("INSERT INTO locations VALUES(?,?,?)", (loc["id"], loc["campaign"], parent))
        for loc in locations:
            self.ancestors(loc)  # Reject cycles before accepting facts.
        sources = {s["id"]: s for s in world["sources"]}
        for i, fact in enumerate(world["facts"]):
            entity = self.db.execute("SELECT * FROM entities WHERE id=?", (fact["entity_id"],)).fetchone()
            if not entity or fact["valid_from"] >= fact["valid_until"]:
                raise ValueError("unknown fact subject or invalid interval")
            evidence = fact["evidence"]
            source = sources[evidence["source"]]
            if not evidence["quote"] or source["text"].count(evidence["quote"]) != 1:
                raise ValueError("evidence quote must identify one exact source span")
            if source["campaign"] != entity["campaign"]:
                raise ValueError("cross-campaign evidence")
            if fact["property"] == "location":
                loc = locations.get(fact["value"])
                if not loc or loc["campaign"] != entity["campaign"]:
                    raise ValueError("unknown or cross-campaign fact location")
            self.db.execute("INSERT INTO facts VALUES(?,?,?,?,?,?)",
                            (fact["entity_id"], fact["property"], fact["value"],
                             fact["valid_from"], fact["valid_until"], json.dumps({
                                 "source": source["id"], "source_sha256": sha(source),
                                 "quote": evidence["quote"], "world_fact_pointer": f"/facts/{i}",
                                 "world_sha256": self.world_sha256})))
        self.db.commit()

    def ancestors(self, location):
        found = set()
        while location:
            if location in found:
                raise ValueError("location cycle")
            found.add(location)
            row = self.db.execute("SELECT parent FROM locations WHERE id=?", (location,)).fetchone()
            if not row:
                raise ValueError("unknown location")
            location = row["parent"]
        return found

    def within(self, location, scope):
        return scope in self.ancestors(location)

    def comparable(self, a, b):
        return self.within(a, b) or self.within(b, a)

    def resolve(self, mention: dict):
        """Use annotated context, not the evaluation's hidden expected identity."""
        # A copy of the query is evidence; none of these fields is a gold entity ID.
        allowed = {"id", "text", "label", "campaign", "kind", "scene_location",
                   "referent_locations", "at", "referent_at", "features", "number"}
        if set(mention) - allowed:
            raise ValueError("unexpected mention fields (gold answers must stay outside queries)")
        candidates = self.db.execute("""SELECT DISTINCT e.* FROM entities e
            JOIN labels l ON e.id=l.entity_id WHERE e.campaign=? AND e.kind=?
            AND l.label=? ORDER BY e.id""", (mention["campaign"], mention.get("kind", "creature"),
                                           mention["label"].casefold())).fetchall()
        scopes = mention.get("referent_locations", [])
        scope_origin = "explicit_referent" if scopes else "scene"
        if not scopes and mention.get("scene_location"):
            scopes = [mention["scene_location"]]
        for scope in scopes:
            row = self.db.execute("SELECT campaign FROM locations WHERE id=?", (scope,)).fetchone()
            if not row or row["campaign"] != mention["campaign"]:
                raise ValueError("unknown or cross-campaign query scope")
        at = mention.get("referent_at", mention.get("at"))
        constraints = [("location", scope) for scope in scopes] + list(mention.get("features", {}).items())
        contradictory_query = any(not self.comparable(a, b) for a in scopes for b in scopes)
        evaluated = []
        for candidate in candidates:
            matches, conflicts, unknown, source_conflicts = [], [], [], []
            for prop, wanted in constraints:
                rows = [] if at is None else self.db.execute("""SELECT * FROM facts
                    WHERE entity_id=? AND property=? AND valid_from<=? AND ?<valid_until
                    ORDER BY value,evidence""", (candidate["id"], prop, at, at)).fetchall()
                evidence = [{"value": r["value"], "valid_from": r["valid_from"],
                             "valid_until": r["valid_until"], **json.loads(r["evidence"])} for r in rows]
                values = {r["value"] for r in rows}
                check = {"property": prop, "wanted": wanted, "evidence": evidence}
                if not rows:
                    unknown.append(check)
                elif ((prop == "location" and any(not self.comparable(a, b) for a in values for b in values))
                      or (prop != "location" and len(values) > 1)):
                    source_conflicts.append(check)
                elif any(self.within(value, wanted) if prop == "location" else value == wanted for value in values):
                    matches.append(check)
                else:
                    # A coarse parent observation cannot rule out a more specific room.
                    if prop == "location" and any(self.within(wanted, value) for value in values):
                        unknown.append(check)
                    else:
                        conflicts.append(check)
            disposition = ("excluded" if conflicts else "conflicting_evidence" if source_conflicts else
                           "supported" if constraints and not unknown else "possible_unknown")
            evaluated.append({"entity_id": candidate["id"], "disposition": disposition,
                              "matches": matches, "contradictions": conflicts,
                              "unknowns": unknown, "source_conflicts": source_conflicts})
        possible = [c for c in evaluated if c["disposition"] != "excluded"]
        if contradictory_query:
            status = "conflicting_context"
        elif not candidates:
            status = "not_found"
        elif not possible:
            status = "no_supported_candidate"
        elif any(c["disposition"] == "conflicting_evidence" for c in possible):
            status = "conflicting_evidence"
        elif mention.get("number", "singular") == "plural":
            status = "candidate_group"
        elif len(possible) > 1:
            status = "ambiguous"
        elif possible[0]["disposition"] == "supported":
            status = "supported_candidate"
        else:
            status = "insufficient_evidence"
        return {"mention_id": mention["id"], "status": status,
                "candidate_ids": sorted(c["entity_id"] for c in possible),
                "proposed_entity_id": possible[0]["entity_id"] if status == "supported_candidate" else None,
                "at": at, "scope_origin": scope_origin, "scopes": scopes,
                "evaluated": evaluated, "world_sha256": self.world_sha256,
                "authority": "experimental candidate proposal; no canon merge or registry write",
                "coverage": "curated context and time-bounded facts; raw-text context extraction untested"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--mention", type=Path, required=True)
    args = parser.parse_args()
    result = ContextIndex(json.loads(args.world.read_text())).resolve(json.loads(args.mention.read_text()))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
