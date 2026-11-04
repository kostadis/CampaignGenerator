"""Read-only campaign adapter; writes only an explicitly chosen derived SQLite index.

Edges describe recorded dependencies, never story truth or authority grants. Every
edge cites a metadata field. Historical file versions remain separate even when
the path is reused. No model, network, registry mutation, or publication calls.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from campaignlib.registry import load_registry
from provenance.manifest import load_manifest
from provenance.tiers import classify


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Index:
    def __init__(self, db: Path, workspace: Path | None = None):
        self.workspace = workspace.resolve() if workspace else None
        self.reads: dict[str, str] = {}
        self.parsed_records = {}
        if workspace:
            if db.resolve().is_relative_to(self.workspace):
                raise ValueError("index output must be outside the source workspace")
            db.parent.mkdir(parents=True, exist_ok=True)
            if db.exists():
                raise ValueError("index exists; choose a fresh output path")
            self.db = sqlite3.connect(db)
            self.db.executescript("""
                CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT, campaign TEXT,
                    path TEXT, sha256 TEXT, properties TEXT);
                CREATE TABLE edges(src TEXT, dst TEXT, predicate TEXT,
                    evidence TEXT, PRIMARY KEY(src,dst,predicate,evidence));
                CREATE INDEX edge_source ON edges(src);
            """)
            self.manifest = load_manifest(self.workspace / "provenance.yaml")
            self.manifest_sha256 = digest((self.workspace / "provenance.yaml").read_bytes())
        else:
            self.db = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def safe_path(self, campaign: str, rel: str) -> Path:
        if campaign not in self.manifest.campaigns:
            raise ValueError(f"undeclared campaign: {campaign}")
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe campaign-relative path: {rel}")
        root = (self.workspace / self.manifest.campaigns[campaign].root).resolve()
        if not root.is_relative_to(self.workspace):
            raise ValueError("campaign root escapes workspace")
        result = root / path
        if not result.resolve().is_relative_to(root):
            raise ValueError(f"path escapes campaign: {rel}")
        return result

    def read(self, campaign: str, rel: str) -> bytes:
        data = self.safe_path(campaign, rel).read_bytes()
        key = f"{campaign}/{rel}"
        value = digest(data)
        if key in self.reads and self.reads[key] != value:
            raise ValueError(f"input changed during indexing: {key}")
        self.reads[key] = value
        return data

    def node(self, kind, campaign, key, *, path=None, sha=None, **properties):
        identity = digest(encoded([kind, campaign, key]).encode())
        row = (identity, kind, campaign, path, sha, encoded(properties))
        existing = self.db.execute("SELECT * FROM nodes WHERE id=?", (identity,)).fetchone()
        if existing and tuple(existing) != row:
            raise ValueError(f"conflicting node definition: {kind}/{key}")
        self.db.execute("INSERT OR IGNORE INTO nodes VALUES(?,?,?,?,?,?)", row)
        return identity

    def artifact(self, campaign, rel, expected=None):
        observed = None
        try:
            observed = digest(self.read(campaign, rel))
        except FileNotFoundError:
            pass
        sha = expected or observed
        if sha is not None and not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"invalid digest for {rel}")
        c = self.manifest.campaigns[campaign]
        tier = classify(rel, c.tiers)
        return self.node("artifact", campaign, [rel, sha], path=rel, sha=sha,
                         observed_sha256=observed,
                         materialization=("missing" if observed is None else
                                          "matches" if observed == sha else "different"),
                         tier=tier.tier.value,
                         tier_ambiguous=[x.value for x in tier.ambiguous],
                         generated_by=c.generated_by(rel),
                         classification_manifest_sha256=self.manifest_sha256)

    def edge(self, src, dst, predicate, record, pointer):
        # Edge evidence must identify an existing JSON/YAML field, not just a
        # plausible-looking filename. Broad fields remain explicitly broad.
        evidence_node = self.get(record)
        if len({self.get(src)["campaign"], self.get(dst)["campaign"], evidence_node["campaign"]}) != 1:
            raise ValueError("cross-campaign edge refused")
        key = (evidence_node["campaign"], evidence_node["path"])
        if key not in self.parsed_records:
            self.parsed_records[key] = yaml.safe_load(self.read(*key))
        value = self.parsed_records[key]
        for token in pointer.split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        self.db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?)",
                        (src, dst, predicate, encoded({"record": record, "field": "/" + pointer})))

    def get(self, node):
        row = self.db.execute("SELECT * FROM nodes WHERE id=?", (node,)).fetchone()
        result = dict(row)
        result["properties"] = json.loads(result["properties"])
        return result

    def import_registry(self, campaign):
        decl = self.manifest.campaigns[campaign].identity.registry
        if not decl:
            return {"status": "no-store", "campaign": campaign}
        data = self.read(campaign, decl)
        registry = load_registry(self.safe_path(campaign, decl))
        source = self.artifact(campaign, decl, digest(data))
        binding = self.node("registry_binding", campaign, decl, source=source,
                            scope="explicit registry names/aliases only")
        self.edge(source, binding, "identity_store", source, "entities")
        canonical = {}
        for i, entity in enumerate(registry.entities):
            eid = self.node("entity", campaign, [entity.type, entity.name],
                            name=entity.name, entity_type=entity.type)
            canonical[entity.name] = eid
            self.edge(source, eid, "declares_entity", source, f"entities/{i}")
            for j, alias in enumerate([entity.name, *entity.aliases]):
                surface = self.node("surface", campaign, alias.strip().casefold(),
                                    folded=alias.strip().casefold())
                self.edge(surface, eid, "explicit_name_of", source,
                          f"entities/{i}/name" if j == 0 else f"entities/{i}/aliases/{j-1}")
        for key in ("distinct", "rejected_aliases"):
            for i, group in enumerate(getattr(registry, key)):
                guard = self.node("identity_guard", campaign, [key, group],
                                  guard=key, names=group)
                self.edge(source, guard, "declares_guard", source, f"{key}/{i}")
                for name in group:
                    if name in canonical:
                        self.edge(guard, canonical[name], "keeps_distinct", source, f"{key}/{i}")
        return {"status": "indexed", "campaign": campaign,
                "entities": len(registry.entities), "registry_sha256": digest(data)}

    def import_bundle(self, campaign: str, bundle: str):
        """Explicit adapter for the legacy grounding-delta records, not a generic guesser."""
        def rel(name):
            return str(Path(bundle) / name)

        def read_json(name):
            return json.loads(self.read(campaign, rel(name)))

        manifest = read_json("manifest.json")
        plan = read_json("application_plan.json")
        receipt = read_json("application_manifest.json")
        mapping = read_json("review_mapping.json")
        decisions = read_json("decisions.json")
        items = read_json("review_items.json")
        check = read_json("runs/final_consistency.record.json")
        check_result = read_json("final_consistency.json")
        full_check = read_json("runs/consistency.record.json")
        required = ["manifest.json", "application_plan.json", "application_manifest.json",
                    "review_mapping.json", "decisions.json", "review_items.json",
                    "runs/final_consistency.record.json", "final_consistency.json",
                    "runs/consistency.record.json"]
        records = {name: self.artifact(campaign, rel(name)) for name in required}
        self.common_errors = []

        def require(condition, explanation):
            if not condition:
                self.common_errors.append(explanation)

        review_id = manifest["review_id"]
        require(all(value == review_id for value in [plan["review_id"], receipt["review_id"],
                decisions.get("reviewId"), items.get("reviewId")]), "review identity mismatch")
        require(bool(decisions.get("savedAt")), "no saved human decision")
        require(not decisions.get("discuss") and not decisions.get("unmarked"),
                "unresolved review decisions")
        require(check["overall"] == check_result["overall"] == "pass", "final check did not pass")
        require(full_check.get("overall") in ("pass", "needs_revision"), "full check absent/failed")
        for filename, field in [("decisions.json", "decision_sha256"),
                                ("review_mapping.json", "mapping_sha256"),
                                ("application_plan.json", "application_plan_sha256"),
                                ("review_items.json", "review_items_sha256")]:
            require(receipt.get(field) == digest(self.read(campaign, rel(filename))),
                    f"receipt binding mismatch: {filename}")
        source = plan["source"]
        source_node = self.artifact(campaign, source["path"], source["sha256"])
        snapshot = self.artifact(campaign, source["snapshot"], source["sha256"])
        # A later source edit makes reuse stale; it does not erase historical
        # approval of the retained source snapshot.
        current_source_matches = self.get(source_node)["properties"]["materialization"] == "matches"
        require(self.get(snapshot)["properties"]["materialization"] == "matches",
                f"source snapshot unavailable or changed: {source['snapshot']}")
        require(manifest["source"]["sha256"] == source["sha256"], "manifest/source hash mismatch")
        extra_nodes = []
        for path, sha in plan.get("extra_inputs", {}).items():
            node = self.artifact(campaign, rel(path), sha)
            extra_nodes.append(node)
            require(self.get(node)["properties"]["materialization"] == "matches",
                    f"extra input unavailable or changed: {path}")
        result = []
        for member_index, member in enumerate(plan["members"]):
            name = member["document"]
            errors = list(self.common_errors)
            def member_require(condition, message):
                if not condition:
                    errors.append(message)
            candidate = self.artifact(campaign, member["approved_candidate_path"], member["candidate_sha256"])
            baseline = self.artifact(campaign, member["backup"], member["baseline_sha256"])
            origin = self.artifact(campaign, member["retained_origin"], member["retained_origin_sha256"])
            for node in [candidate, baseline, origin]:
                member_require(self.get(node)["properties"]["materialization"] == "matches",
                               f"bound artifact unavailable or changed: {self.get(node)['path']}")
            member_require(member["retained_origin_sha256"] == member["baseline_sha256"],
                           "baseline origin digest mismatch")
            expected = member["candidate_sha256"]
            member_require(mapping.get(name, {}).get("draft_sha256") == expected and
                           mapping.get(name, {}).get("draft_path") == member["approved_candidate_path"],
                           "review mapping mismatch")
            member_require(mapping.get(name, {}).get("baseline_sha256") == member["baseline_sha256"],
                           "review baseline mismatch")
            member_require(check.get("candidate_sha256", {}).get(name) == expected,
                           "consistency candidate mismatch")
            member_require(manifest.get("candidates", {}).get(name, {}).get("sha256") == expected,
                           "manifest candidate mismatch")
            member_require(decisions.get("decisions", {}).get(name) == "approve", "not approved")
            member_require(sum(item["id"] == name for item in items.get("items", [])) == 1,
                           "missing/duplicate review card")
            matching = [m for m in receipt.get("members", []) if m.get("document") == name]
            receipt_pointer = "members"
            member_require(len(matching) == 1, "missing/duplicate application member")
            if len(matching) == 1:
                applied = matching[0]
                receipt_pointer += f"/{receipt['members'].index(applied)}"
                member_require(applied.get("approved_after_sha256") == expected and
                               applied.get("approved_origin") == member["approved_candidate_path"] and
                               applied.get("live_path") == member["live_path"] and
                               applied.get("before_sha256") == member["baseline_sha256"],
                               "application member mismatch")
            operation = self.node("delta", campaign, [bundle, name], bundle=bundle, document=name)
            self.edge(source_node, operation, "input_to", records["application_plan.json"], "source")
            self.edge(snapshot, operation, "input_to", records["application_plan.json"], "source/snapshot")
            self.edge(baseline, operation, "input_to", records["application_plan.json"], f"members/{member_index}/backup")
            self.edge(origin, baseline, "baseline_copy", records["application_plan.json"], f"members/{member_index}/retained_origin")
            self.edge(records["manifest.json"], operation, "describes", records["manifest.json"], f"candidates/{name}")
            for node in extra_nodes:
                self.edge(node, operation, "input_to", records["application_plan.json"], "extra_inputs")
            self.edge(operation, candidate, "proposed_candidate", records["manifest.json"], f"candidates/{name}")
            # A per-document check avoids contaminating unrelated candidates through a shared check record.
            check_node = self.node("consistency_binding", campaign, [bundle, name], bundle=bundle,
                                   document=name, overall=check["overall"])
            self.edge(candidate, check_node, "checked_by", records["runs/final_consistency.record.json"], f"candidate_sha256/{name}")
            for filename in ("runs/final_consistency.record.json", "final_consistency.json", "runs/consistency.record.json"):
                self.edge(records[filename], check_node, "check_record", records[filename], "overall")
            approval = self.node("approval_binding", campaign, [bundle, name], bundle=bundle,
                                 document=name, valid=not errors, errors=errors,
                                 current_source_matches=current_source_matches,
                                 scope="legacy-record-bindings; no native authority or semantic certification")
            self.edge(candidate, approval, "approved_candidate", records["review_mapping.json"], f"{name}/draft_sha256")
            self.edge(baseline, approval, "approved_baseline", records["review_mapping.json"], f"{name}/baseline_sha256")
            self.edge(check_node, approval, "review_check", records["runs/final_consistency.record.json"], f"candidate_sha256/{name}")
            for filename, field in (("application_plan.json", "application_plan_sha256"),
                                    ("review_mapping.json", "mapping_sha256"),
                                    ("decisions.json", "decision_sha256"),
                                    ("review_items.json", "review_items_sha256")):
                self.edge(records[filename], approval, "review_binding", records["application_manifest.json"], field)
            application = self.node("application_binding", campaign, [bundle, name], bundle=bundle,
                                    document=name, valid=not errors, errors=errors)
            self.edge(approval, application, "authorizes_recorded_application", records["application_manifest.json"], receipt_pointer)
            self.edge(records["application_manifest.json"], application, "application_receipt", records["application_manifest.json"], receipt_pointer)
            live = self.artifact(campaign, member["live_path"], expected)
            self.edge(application, live, "applied_as", records["application_manifest.json"], receipt_pointer)
            result.append({"document": name, "binding_valid": not errors, "errors": errors,
                           "current_source_matches": current_source_matches,
                           "reuse_status": ("invalid_bindings" if errors else
                                            "current" if current_source_matches else "stale_source"),
                           "live_matches_this_version": self.get(live)["properties"]["materialization"] == "matches",
                           "candidate_sha256": expected})
        return {"bundle": bundle, "members": result}

    def impact(self, campaign: str, path: str, sha: str | None = None):
        rows = self.db.execute("SELECT id FROM nodes WHERE campaign=? AND path=?" +
                               (" AND sha256=?" if sha else "") + " ORDER BY id",
                               (campaign, path, sha) if sha else (campaign, path)).fetchall()
        queue = deque((row[0], []) for row in rows)
        seen = set()
        targets = []
        while queue:
            node, chain = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            if chain:
                value = self.get(node)
                value["trace"] = chain
                targets.append(value)
            for edge in self.db.execute("SELECT * FROM edges WHERE src=? ORDER BY dst,predicate,evidence", (node,)):
                trace = {"src": node, "dst": edge["dst"], "predicate": edge["predicate"],
                         "evidence": json.loads(edge["evidence"])}
                queue.append((edge["dst"], chain + [trace]))
        return {"status": "tracked" if rows else "not_covered", "campaign": campaign,
                "path": path, "changed_versions": len(rows), "affected": targets,
                "coverage": "only explicit indexed dependencies; missing paths are unknown, not safe"}

    def resolve(self, campaign: str, name: str):
        rows = self.db.execute("""SELECT DISTINCT n.* FROM nodes s JOIN edges e ON s.id=e.src
            JOIN nodes n ON e.dst=n.id WHERE s.kind='surface' AND s.campaign=?
            AND json_extract(s.properties,'$.folded')=? AND e.predicate='explicit_name_of'
            ORDER BY n.id""", (campaign, name.strip().casefold())).fetchall()
        entities = [self.get(row["id"]) for row in rows]
        has_store = self.db.execute("SELECT 1 FROM nodes WHERE campaign=? AND kind='registry_binding' LIMIT 1", (campaign,)).fetchone()
        return {"status": ("resolved" if len(rows) == 1 else "ambiguous" if rows else
                           "not_found" if has_store else "no_store"), "entities": entities,
                "matching": "exact explicit name/alias with casefold; no fuzzy or first-token inference"}

    def graph_digest(self):
        nodes = [dict(row) for row in self.db.execute("SELECT * FROM nodes ORDER BY id")]
        edges = [dict(row) for row in self.db.execute("SELECT * FROM edges ORDER BY src,dst,predicate,evidence")]
        return digest(encoded({"nodes": nodes, "edges": edges}).encode())

    def finish(self):
        for key, sha in self.reads.items():
            campaign, path = key.split("/", 1)
            if digest(self.safe_path(campaign, path).read_bytes()) != sha:
                raise ValueError(f"input changed before index commit: {key}")
        if digest((self.workspace / "provenance.yaml").read_bytes()) != self.manifest_sha256:
            raise ValueError("classification manifest changed before index commit")
        self.db.commit()
        return {"nodes": self.db.execute("SELECT count(*) FROM nodes").fetchone()[0],
                "edges": self.db.execute("SELECT count(*) FROM edges").fetchone()[0],
                "graph_sha256": self.graph_digest(), "files_read": dict(sorted(self.reads.items())),
                "classification_manifest_sha256": self.manifest_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--workspace", type=Path, required=True)
    build.add_argument("--campaign", required=True)
    build.add_argument("--bundle", action="append", required=True)
    build.add_argument("--out", type=Path, required=True)
    for command in ("impact", "resolve"):
        sub = commands.add_parser(command)
        sub.add_argument("--db", type=Path, required=True)
        sub.add_argument("--campaign", required=True)
        sub.add_argument("value")
    args = parser.parse_args()
    if args.command == "build":
        graph = Index(args.out, args.workspace)
        result = {"registry": graph.import_registry(args.campaign),
                  "bundles": [graph.import_bundle(args.campaign, b) for b in args.bundle]}
        result.update(graph.finish())
    else:
        graph = Index(args.db)
        result = getattr(graph, args.command)(args.campaign, args.value)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
