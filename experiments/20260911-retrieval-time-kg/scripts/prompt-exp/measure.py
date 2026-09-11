#!/usr/bin/env python3
"""Measure generated volume + check the three known fabrications.  usage: measure.py A|B"""
import asyncio, os, re, sys
ARM = sys.argv[1]
os.chdir(f"/home/kostadis/cognee-local/prompt-exp/{ARM}")
import cognee  # noqa: E402
from cognee.infrastructure.databases.graph import get_graph_engine  # noqa: E402

CHECKS = [("Voss paraphrase drift", r"dangerous location"),
          ("Droop knows the castle", r"droop.{0,120}(cragmaw castle|neverwinter wood)"),
          ("Iarno == Black Spider",  r"iarno[^.]{0,40}the black spider")]


async def main():
    ge = await get_graph_engine()
    nodes, edges = await ge.get_graph_data()
    edge_chars = with_desc = 0
    blob = []
    for e in edges:
        p = e[3] if len(e) > 3 else {}
        t = p.get("edge_text")
        if isinstance(t, str) and t.strip():
            edge_chars += len(t); with_desc += 1; blob.append(t)
    node_chars = 0
    for nid, p in nodes:
        if (p.get("type") or p.get("__type__")) != "DocumentChunk":
            node_chars += len(str(p.get("description") or "")) + len(str(p.get("text") or ""))
            blob.append(str(p.get("description") or ""))
    all_text = "\n".join(blob)
    print(f"ARM {ARM}")
    print(f"  nodes={len(nodes)}  edges={len(edges)}  edges_with_description={with_desc}")
    print(f"  edge description chars : {edge_chars:>9,}")
    print(f"  node generated chars   : {node_chars:>9,}")
    print(f"  TOTAL GENERATED        : {edge_chars+node_chars:>9,}")
    for label, pat in CHECKS:
        print(f"  {'FABRICATED' if re.search(pat, all_text, re.I|re.S) else 'clean     '}  {label}")

asyncio.run(main())
