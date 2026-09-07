"""
Join the four tables that describe Irish wind farms, and cross-check them.

    SEAI farms --node_110kv--> WDT stations --> constraint groups
         |                                            |
         +---- name ----> model generators --prorata_groups--+

Two independent routes reach a farm's constraint groups. Where both exist we can
compare them, which is the only way to check either one.

Nothing is silently merged. Every fuzzy name match carries its score, and the
output records which route produced which answer so any row can be audited by
hand against the source files.

Output: farm-to-constraint-group-map.csv
"""
import csv
import re
import sys
from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import openpyxl
from rapidfuzz import fuzz, process

ROOT = ROOT

MODEL = DATA / "ireland_case_july2025.xlsx"
WDT = OUT_DIR / "constraint-groups-to-stations.csv"
SEAI = ROOT / "04-meteorology" / "script-output" / "wind-farms-with-coordinates.csv"
OUT = OUT_DIR / "farm-to-constraint-group-map.csv"

# A name score alone is not enough: "Cappawhite A" scores 71 against
# "Cappawhite B" and they are different farms, while "Gortahile Wind Farm" and
# "gortahile ltd" score 82 and are the same one. So we use two independent
# signals -- the name, and whether the farm's SEAI connection node agrees with
# the station of the model generator's bus.
NAME_ONLY = 93      # accept on name alone only when it is near-identical
NAME_WITH_STATION = 80   # a weaker name is enough if the location corroborates


def norm(s):
    """Lowercase, strip punctuation, voltage suffixes and generic words.

    'Sliabh Bawn Wind Farm' and 'Sliabh Bawn Windfarm' must collide; so must
    'Golagh 110 kV' and 'Golagh'. Generic words carry no identifying
    information here, since every row is a wind or solar farm.
    """
    s = str(s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\d+\s*kv", " ", s)                    # voltage suffixes
    s = re.sub(r"\bwind\s*farm\b|\bwindfarm\b|\bsolar\s*farm\b|\bwind\b|\bsolar\b|\bfarm\b", " ", s)
    # Alias clauses: "Carrigdangan (formerly Barnadivane)". The old name is not
    # part of the identity and drags the score down, so drop the whole bracket.
    s = re.sub(r"\((?:[^()]*\b(?:formerly|prev\.?|previously|temp|merged?|merge)\b[^()]*)\)", " ", s)
    # Phase / unit markers: "Dromada (1)", "Athea (1a)", "Killala (Phase 1)".
    s = re.sub(r"\(\s*(?:phase|gate|temp)?\s*\d+[a-z]?\s*\)", " ", s)
    # Corporate and plant suffixes carried by the model's descriptions.
    s = re.sub(r"\b(ltd|limited|plc|gen|genco|wfps|wf|plant|power)\b", " ", s)
    s = re.sub(r"\b(extension|ext|phase|gate|generator|generatot|unit|the|of)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def nospace(s):
    """'grouse lodge' and 'grouselodge' name the same place."""
    return s.replace(" ", "")


def station_from_bus_desc(desc):
    """'Ardnacrusha_110kV' -> 'Ardnacrusha'."""
    d = re.sub(r"_\d+kv.*$", "", str(desc or ""), flags=re.I)
    return re.sub(r"[_\s]+", " ", d).strip()


def load_model():
    """Wind and solar generators, with their groups and their bus's station."""
    wb = openpyxl.load_workbook(MODEL, read_only=True, data_only=True)

    rows = list(wb["bus"].iter_rows(values_only=True))
    bh = list(rows[0])
    bus_station = {r[bh.index("name")]: station_from_bus_desc(r[bh.index("description")])
                   for r in rows[1:]}

    rows = list(wb["generator"].iter_rows(values_only=True))
    gh = list(rows[0])
    idx = {k: gh.index(k) for k in
           ("name", "description", "busname", "FuelType", "prorata_groups", "PGUB")}
    gens = []
    for r in rows[1:]:
        if str(r[idx["FuelType"]]).lower() not in ("wind", "solar"):
            continue
        groups = [g.strip() for g in str(r[idx["prorata_groups"]] or "").split(",") if g.strip()]
        gens.append({
            "gen_id": str(r[idx["name"]] or "").strip(),
            # descriptions contain stray tabs
            "gen_desc": re.sub(r"\s+", " ", str(r[idx["description"]] or "")).strip(),
            "bus": str(r[idx["busname"]] or "").strip(),
            "station": bus_station.get(r[idx["busname"]], ""),
            "fuel": str(r[idx["FuelType"]]).lower(),
            # a farm can appear in the same group twice in the source data
            "groups": sorted(set(groups)),
        })
    wb.close()
    return gens


def load_wdt():
    """station (normalised) -> set of group ids."""
    out = {}
    with open(WDT, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["station"]:
                out.setdefault(norm(r["station"]), set()).add(r["group_id"])
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(SEAI, encoding="utf-8") as f:
        farms = list(csv.DictReader(f))
    gens = load_model()
    wdt = load_wdt()

    # Fuzzy-match SEAI farm names against model generator descriptions.
    gen_keys = {g["gen_desc"]: norm(g["gen_desc"]) for g in gens}
    choices = {k: v for k, v in gen_keys.items() if v}
    by_desc = {g["gen_desc"]: g for g in gens}

    rows, matched, group_agree, group_disagree, both = [], 0, 0, 0, 0
    for fm in farms:
        key = norm(fm["farm"])
        best = process.extractOne(key, choices, scorer=fuzz.token_sort_ratio)
        alt = process.extractOne(nospace(key), {k: nospace(v) for k, v in choices.items()},
                                 scorer=fuzz.token_sort_ratio)
        if alt and (not best or alt[1] > best[1]):
            best = alt
        gen, score, station_ok = None, 0, ""
        if best:
            score = best[1]
            cand = by_desc[best[2]]
            station_ok = "yes" if norm(fm["node_110kv"]) and                 norm(fm["node_110kv"]) == norm(cand["station"]) else "no"
            if score >= NAME_ONLY or (score >= NAME_WITH_STATION and station_ok == "yes"):
                gen = cand
                matched += 1

        # Route 1: SEAI node -> WDT station -> groups
        via_wdt = sorted(wdt.get(norm(fm["node_110kv"]), set()))
        # Route 2: model generator -> prorata_groups
        via_model = gen["groups"] if gen else []

        if via_wdt and via_model:
            both += 1
            if set(via_wdt) & set(via_model):
                group_agree += 1
            else:
                group_disagree += 1

        rows.append({
            "farm": fm["farm"],
            "county": fm["county"],
            "mec_mw": fm["mec_mw"],
            "lat": fm["lat"], "lon": fm["lon"],
            "seai_node": fm["node_110kv"],
            "model_gen_id": gen["gen_id"] if gen else "",
            "model_gen_desc": best[0] if best else "",
            "match_score": round(score, 1),
            "station_agrees": station_ok,
            "matched": "yes" if gen else "no",
            "model_bus": gen["bus"] if gen else "",
            "model_station": gen["station"] if gen else "",
            "groups_via_model": ";".join(via_model),
            "groups_via_wdt_station": ";".join(via_wdt),
            "routes_overlap": ("n/a" if not (via_wdt and via_model)
                               else "yes" if set(via_wdt) & set(via_model) else "no"),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    print(f"SEAI farms                        : {n}")
    corrob = sum(1 for r in rows if r["matched"] == "yes" and r["station_agrees"] == "yes")
    print(f"matched to a model generator      : {matched} ({100*matched/n:.0f}%)")
    print(f"   of which location corroborates : {corrob}")
    print(f"groups via WDT station route      : {sum(1 for r in rows if r['groups_via_wdt_station'])}")
    print(f"groups via model prorata route    : {sum(1 for r in rows if r['groups_via_model'])}")
    print(f"farms with BOTH routes            : {both}")
    if both:
        print(f"   routes share >=1 group         : {group_agree} ({100*group_agree/both:.0f}%)")
        print(f"   routes share NO group          : {group_disagree}")
    print(f"\nwrote {OUT.name}")
    return rows


if __name__ == "__main__":
    main()
