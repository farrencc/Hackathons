"""
Turn SEAI's connected-wind-farm list into a lat/lon table.

The SEAI file carries substation coordinates as 6-digit Irish National Grid
eastings/northings (EPSG:29903, TM75), not ITM. We reproject to WGS84 so the
farms can be joined to weather data.

Output: wind-farms-with-coordinates.csv
"""

from pathlib import Path

# This script lives in <folder>/scripts/. Paths are built from the folder above
# it, so the script runs correctly from any working directory.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"
import csv
import re

from pyproj import Transformer

SRC = str(DATA / "WindFarmsConnectedJune2022.csv")
OUT = str(OUT_DIR / "wind-farms-with-coordinates.csv")

# EPSG:29903 = TM75 / Irish Grid. always_xy -> (easting, northing) in, (lon, lat) out.
TF = Transformer.from_crs("EPSG:29903", "EPSG:4326", always_xy=True)

# Rough bounding box for the island, used only to catch bad coordinates.
LAT_RANGE, LON_RANGE = (51.2, 55.5), (-11.0, -5.3)


def main():
    out, skipped = [], []
    with open(SRC, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            e, n = r.get("Nat_Grid_E__substation_"), r.get("Nat_Grid_N__substation_")
            try:
                e, n = float(e), float(n)
            except (TypeError, ValueError):
                skipped.append((r["Windfarm_Name"], "no coordinates"))
                continue
            lon, lat = TF.transform(e, n)
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                skipped.append((r["Windfarm_Name"], f"off-island {lat:.2f},{lon:.2f}"))
                continue
            # MEC (maximum export capacity) is the grid-relevant number and is
            # populated far more often than installed capacity.
            try:
                mec = float(r.get("MEC__MW_") or 0)
            except ValueError:
                mec = 0.0
            out.append({
                # 21 names in the SEAI file contain embedded newlines.
                "farm": re.sub(r"\s+", " ", r["Windfarm_Name"]).strip(),
                "county": r.get("County", "").strip(),
                "node_110kv": r.get("F110kV_Node_Name", "").strip(),
                "dso_tso": r.get("DSO_TSO", "").strip(),
                "mec_mw": round(mec, 3),
                "status": r.get("Present_Status", "").strip(),
                "year": r.get("Year_of_Connection", "").strip(),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
            })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(f"wrote {OUT}: {len(out)} farms, {sum(r['mec_mw'] for r in out):.0f} MW MEC total")
    print(f"skipped: {len(skipped)}")
    for s in skipped[:8]:
        print("   ", s)
    print("\nsanity check (should be recognisable Irish locations):")
    for r in out[:3] + out[-2:]:
        print(f"    {r['farm'][:30]:<30} {r['county']:<10} {r['lat']:.4f}, {r['lon']:.4f}")
    return out


if __name__ == "__main__":
    main()
