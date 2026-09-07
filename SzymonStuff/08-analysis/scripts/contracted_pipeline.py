"""
Where is new wind being connected, and is it landing on constrained nodes?

EirGrid publish the farms that hold a connection contract but are not yet
generating. Cross-referencing their connection nodes against the constraint
groups already defined on those nodes says whether the pipeline is being added
where the network is already tight.

This is a forward-looking check: today's constraint map against tomorrow's
capacity.

Output: contracted-pipeline-vs-constraints.csv
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

from pypdf import PdfReader

ROOT = ROOT
PDF = ROOT / "04-meteorology" / "data" / "TSO-Contracted-Wind-Report-2025-11-28.pdf"
WDT = ROOT / "03-network" / "script-output" / "constraint-groups-to-stations.csv"
CONNECTED = ROOT / "04-meteorology" / "script-output" / "wind-farms-with-coordinates.csv"
OUT = OUT_DIR / "contracted-pipeline-vs-constraints.csv"

# "Knockranny 110 kV TG443 Ardderroo Wind Farm Extension ECP-2.1 Wind 18.0 Feb 2022"
ROW = re.compile(
    r"^(?P<node>.+?)\s+(?P<kv>\d+)\s*kV\s+(?P<ref>T[GA]\d+)\s+(?P<name>.+?)\s+"
    r"(?P<batch>ECP[-\w.]*|Gate\s*\d+|\S*)\s+(?P<type>Wind|Solar)\s+"
    r"(?P<mec>\d+(?:\.\d+)?)\s+(?P<signed>[A-Z][a-z]{2}\s+\d{4})\s*$")


def norm(s):
    s = re.sub(r"\d+\s*kv", " ", str(s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # Constraint groups per station.
    groups = defaultdict(set)
    with open(WDT, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["station"]:
                groups[norm(r["station"])].add(r["group_id"])

    # Capacity already connected at each node.
    connected = defaultdict(float)
    with open(CONNECTED, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["node_110kv"]:
                connected[norm(r["node_110kv"])] += float(r["mec_mw"])

    # A few entries wrap onto a second line ("...Wind Farm (Formerly" then
    # "Other Name) ECP-1 Wind 25.0 Jan 2020"), so rejoin before parsing.
    raw = []
    for page in PdfReader(PDF).pages:
        for line in (page.extract_text() or "").split("\n"):
            line = re.sub(r"\s+", " ", line).strip()
            if line and not line.lower().startswith(("page ", "contracted", "node")):
                raw.append(line)

    START_OF_ROW = re.compile(r"\d+\s*kV\s+T[GA]\d+")
    lines, i = [], 0
    while i < len(raw):
        line = raw[i]
        while (START_OF_ROW.search(line) and not ROW.match(line)
               and i + 1 < len(raw) and not START_OF_ROW.search(raw[i + 1])):
            line = f"{line} {raw[i + 1]}"
            i += 1
        lines.append(line)
        i += 1

    rows, unparsed = [], 0
    for line in lines:
            m = ROW.match(line)
            if not m:
                if START_OF_ROW.search(line):
                    unparsed += 1
                    print(f"  UNPARSED: {line[:90]}")
                continue
            node = norm(m.group("node"))
            g = sorted(groups.get(node, ()))
            rows.append({
                "farm": m.group("name").strip(),
                "node": m.group("node").strip(),
                "kv": m.group("kv"),
                "ref": m.group("ref"),
                "batch": m.group("batch"),
                "mec_mw": float(m.group("mec")),
                "signed": m.group("signed"),
                "constraint_groups_at_node": ";".join(g),
                "n_groups_at_node": len(g),
                "connected_mw_at_node": round(connected.get(node, 0.0), 1),
            })

    rows.sort(key=lambda r: (-r["n_groups_at_node"], -r["mec_mw"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    tot = sum(r["mec_mw"] for r in rows)
    constrained = [r for r in rows if r["n_groups_at_node"] > 0]
    cmw = sum(r["mec_mw"] for r in constrained)
    print(f"contracted wind farms parsed : {len(rows)}  ({unparsed} lines unparsed)")
    print(f"total contracted capacity    : {tot:,.0f} MW")
    print(f"already-connected fleet      : 4,304 MW  -> pipeline is {100*tot/4304:.0f}% of it\n")
    print(f"landing on a node inside an existing constraint group:")
    print(f"  {len(constrained)} of {len(rows)} farms   {cmw:,.0f} MW  ({100*cmw/tot:.0f}% of the pipeline)\n")

    print("Largest additions at already-constrained nodes:")
    for r in constrained[:12]:
        print(f"  {r['mec_mw']:>6.1f} MW  {r['farm'][:32]:<32} {r['node'][:16]:<16} "
              f"{r['constraint_groups_at_node'][:26]}")

    by_node = defaultdict(float)
    for r in constrained:
        by_node[r["node"]] += r["mec_mw"]
    print("\nNodes taking the most new capacity (already constrained):")
    for n, mw in sorted(by_node.items(), key=lambda kv: -kv[1])[:8]:
        ex = connected.get(norm(n), 0.0)
        print(f"  {mw:>6.1f} MW new   {n[:20]:<20} (already carries {ex:>6.1f} MW)")
    print(f"\nwrote {OUT.name}")


if __name__ == "__main__":
    main()
