"""
Audit the farm-to-constraint-group join, and classify every disagreement.

Two independent routes reach a farm's constraint groups:
  route A  farm -> model generator -> prorata_groups   (Nayer's reconstruction)
  route B  farm -> SEAI node -> WDT station -> groups  (EirGrid's own document)

Where they differ, the interesting question is HOW. A genuine contradiction (two
different regional groups) would mean one source is wrong. A containment gap
(route A says nationwide only, route B adds a regional group) means route A is
merely incomplete -- a hole to fill, not an error to fix.

Output: join-coverage-gaps.csv
"""
import csv
import sys
from collections import Counter
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

SRC = ROOT / "03-network" / "script-output" / "farm-to-constraint-group-map.csv"
OUT = OUT_DIR / "join-coverage-gaps.csv"

NATIONWIDE = {"ROI/1", "ROI-ALL/1", "NI/4"}


def region_of(gid):
    return gid.split("/")[0]


def classify(model, wdt):
    """How do the two route answers relate?"""
    m, w = set(model), set(wdt)
    if not m or not w:
        return "one route missing"
    if m & w:
        return "agree"
    if m <= NATIONWIDE and (w - NATIONWIDE):
        return "model has nationwide only, WDT adds regional"
    if {region_of(g) for g in m} & {region_of(g) for g in w}:
        return "same region, different group"
    return "different regions - genuine conflict"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out, kinds = [], Counter()
    for r in rows:
        if r["matched"] != "yes" or not r["groups_via_wdt_station"]:
            continue
        model = [g for g in r["groups_via_model"].split(";") if g]
        wdt = [g for g in r["groups_via_wdt_station"].split(";") if g]
        kind = classify(model, wdt)
        kinds[kind] += 1
        if kind == "agree":
            continue
        missing = sorted(set(wdt) - set(model))
        out.append({
            "farm": r["farm"], "mec_mw": r["mec_mw"], "county": r["county"],
            "seai_node": r["seai_node"], "model_bus": r["model_bus"],
            "model_station": r["model_station"],
            "station_agrees": r["station_agrees"],
            "groups_via_model": r["groups_via_model"],
            "groups_via_wdt_station": r["groups_via_wdt_station"],
            "kind": kind,
            "groups_model_is_missing": ";".join(missing),
            "missing_regions": ";".join(sorted({region_of(g) for g in missing})),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    total = sum(kinds.values())
    print(f"farms with both routes: {total}\n")
    for k, n in kinds.most_common():
        print(f"  {n:>4}  ({100*n/total:>4.0f}%)  {k}")

    print(f"\nGenuine conflicts: "
          f"{kinds['different regions - genuine conflict'] + kinds['same region, different group']}")

    reg = Counter()
    mw = Counter()
    for r in out:
        for x in r["missing_regions"].split(";"):
            if x:
                reg[x] += 1
                mw[x] += float(r["mec_mw"])
    print("\nRegional groups the model never assigns:")
    for k, n in reg.most_common():
        print(f"  {k:<10} {n:>3} farms   {mw[k]:>7.1f} MW")
    print(f"\nwrote {OUT.name}")
    return out


if __name__ == "__main__":
    main()
