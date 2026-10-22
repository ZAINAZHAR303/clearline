"""Generate the corporate control graph the chain walk traverses.

    python scripts/gen_control_graph.py

Relationships are modelled on GLEIF Level 2, which records direct and ultimate
ACCOUNTING-CONSOLIDATING PARENT relationships. It does not publish ownership
percentages, so neither does Clearline: an indirect finding is reported as a
control relationship and flagged for human confirmation. See data/README.md.

The graph is synthetic, because the vendors are. Real LEIs resolve against the
live GLEIF API; these fictional vendors cannot, and inventing an LEI for them
would be worse than saying so. What is real is the shape: multi-hop chains,
shared intermediate holdcos, dead ends and a cycle.

Planted structure:
  - V0004 Nordvik Components GmbH -> two hops -> a REAL listed entity.
    Clean on its own name; only the chain finds it.
  - A 4-hop chain that terminates cleanly, to show depth without a hit.
  - A cycle, so termination is demonstrated rather than asserted.
  - Decoy branches, so the walk has to actually traverse rather than guess.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 42
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"

HOLDCO_NAMES = [
    "Baltic Holdings Oy", "Pellervo Invest AB", "Kronstadt Capital BV",
    "Vantaa Industrial Group", "Narva Partners SARL", "Aurora Beteiligungs GmbH",
    "Saaremaa Trading House", "Lahti Equity Partners", "Riga Industrial Holding",
]


def main() -> None:
    rng = random.Random(SEED)
    vendors = json.loads((SAMPLE / "vendor_master.json").read_text(encoding="utf-8"))
    sanctions = json.loads((SAMPLE / "sanctions_sample.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in sanctions["entities"]}
    anchors = [by_id[i] for i in sanctions["anchors"] if i in by_id]

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(key: str, name: str, country: str, kind: str, entity_id: str | None = None):
        nodes.setdefault(key, {"key": key, "name": name, "country": country,
                               "kind": kind, "entity_id": entity_id})
        return key

    def edge(child: str, parent: str, relation: str = "DIRECT_PARENT"):
        edges.append({"child": child, "parent": parent, "relation": relation})

    # Every vendor is a node, so the walk always has a starting point.
    for vendor in vendors["vendors"]:
        node(vendor["vendor_id"], vendor["legal_name"], vendor["country"], "vendor")

    # Listed entities that appear in the graph as parents.
    khaverim = next((a for a in anchors if "KHAVERIM" in a["caption"].upper()), anchors[0])
    shahid = next((a for a in anchors if "Shahid" in a["caption"]), anchors[-1])
    for entity in (khaverim, shahid):
        node(f"E:{entity['id']}", entity["caption"], entity["country"], "entity", entity["id"])

    # --- the planted indirect case: V0004, two hops to a listed entity --------
    node("H:baltic", "Baltic Holdings Oy", "FI", "holdco")
    edge("V0004", "H:baltic")
    edge("H:baltic", f"E:{khaverim['id']}", "ULTIMATE_PARENT")

    # --- a deep chain that terminates clean, to show depth without a hit -----
    chain = ["H:pellervo", "H:kronstadt", "H:vantaa", "H:narva"]
    for i, key in enumerate(chain):
        node(key, HOLDCO_NAMES[i + 1], rng.choice(["SE", "NL", "FI", "LU"]), "holdco")
    edge("V0007", chain[0])
    for a, b in zip(chain, chain[1:]):
        edge(a, b)

    # --- a cycle, so termination is demonstrated rather than claimed ---------
    node("H:loop_a", "Saaremaa Trading House", "EE", "holdco")
    node("H:loop_b", "Lahti Equity Partners", "FI", "holdco")
    edge("V0008", "H:loop_a")
    edge("H:loop_a", "H:loop_b")
    edge("H:loop_b", "H:loop_a")  # back-edge

    # --- a second, longer route to a listed entity via a shared holdco ------
    node("H:aurora", "Aurora Beteiligungs GmbH", "DE", "holdco")
    edge("H:aurora", f"E:{shahid['id']}", "ULTIMATE_PARENT")
    edge("V0010", "H:aurora")

    # --- decoys: ordinary one-hop parents that lead nowhere -----------------
    plain = [v["vendor_id"] for v in vendors["vendors"][20:60]]
    for i, vendor_id in enumerate(plain):
        key = f"H:plain{i}"
        node(key, f"{HOLDCO_NAMES[i % len(HOLDCO_NAMES)]} {i}",
             rng.choice(["GB", "DE", "NL", "US"]), "holdco")
        edge(vendor_id, key)

    out = {
        "provenance": {
            "synthetic": True,
            "modelled_on": "GLEIF Level 2 direct and ultimate accounting-consolidating parent relationships",
            "not_included": "ownership percentages -- GLEIF does not publish them, so no percentage is asserted anywhere",
            "listed_entities_are_real": "parent nodes of kind 'entity' are real OFAC SDN records from sanctions_sample.json",
        },
        "nodes": list(nodes.values()),
        "edges": edges,
    }
    target = SAMPLE / "control_graph.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {target.relative_to(ROOT)}  {len(nodes)} nodes, {len(edges)} edges, "
          f"{target.stat().st_size / 1024:.0f} KB")
    print("\nplanted routes:")
    print(f"  V0004 -> Baltic Holdings Oy -> {khaverim['caption']}  [LISTED]")
    print(f"  V0010 -> Aurora Beteiligungs GmbH -> {shahid['caption']}  [LISTED]")
    print(f"  V0007 -> 4-hop chain, terminates clean")
    print(f"  V0008 -> cycle (Saaremaa <-> Lahti), must terminate")


if __name__ == "__main__":
    main()
