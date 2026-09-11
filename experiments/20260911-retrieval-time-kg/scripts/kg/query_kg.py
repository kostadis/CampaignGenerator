from mempalace.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph(palace_path="/home/kostadis/cognee-local/mempalace-exp/palace")

def show(title, rows, keys=("sub_name","predicate","obj_name","valid_from","valid_to","current")):
    print(f"\n═══ {title}")
    for r in rows:
        print("   " + "  ".join(f"{str(r.get(k,'')):<14}"[:22] for k in keys))

print("### TEST 1 — current state: where is Glasstaff?")
for r in kg.query_entity("Glasstaff"):
    print(f"   {r['predicate']:<11} {r['object']:<36} from={r['valid_from']}  to={r['valid_to']}  current={r['current']}")

print("\n### TEST 2 — current state: the party")
for r in kg.query_entity("Party"):
    print(f"   {r['predicate']:<11} {r['object']:<20} from={r['valid_from']}  to={r['valid_to']}  current={r['current']}")

print("\n### TEST 3 — point in time: the party AS OF 2026-08-10 (between sessions 8 and 10)")
for r in kg.query_entity("Party", as_of="2026-08-10"):
    print(f"   {r['predicate']:<11} {r['object']:<20} from={r['valid_from']}  to={r['valid_to']}")

print("\n### TEST 4 — timeline order: Gundren (undated sessions 003a/004 present)")
for r in kg.timeline("Gundren"):
    print(f"   {r['object']:<14} valid_from={r['valid_from']}")
