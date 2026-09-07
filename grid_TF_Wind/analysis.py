"""Diagnostics: is OpenStreetMap's Irish network data usable, and at what voltage?

Five independent measurements, one per subcommand, each writing one artefact
into ``data/``.  The conclusions drawn from them are in FINDINGS.md; this
module only produces the numbers.

    areas            per-area coverage, bands, topology, snapping sweep
    national         island-wide graph, one voltage layer at a time
    subtransmission  per-area check of the 38 kV-and-above layer alone
    missing-cable    a lower bound on missing MV cable from OSM's own assets
    counties         all 26 counties of the Republic, density normalised by area

Run them with ``python analysis.py all``, or one at a time.
"""

from __future__ import annotations

import argparse
import json
import os

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import network

#: Voltage thresholds used below.  110 kV lives in ``network`` because it is
#: the distribution/transmission boundary and several modules need it.
MV_MIN_V = 1_000.0
SUBTX_MIN_V = 38_000.0
HV_220_V = 220_000.0


# --------------------------------------------------------------------------- #
# areas - coverage and topology, per analysis area
# --------------------------------------------------------------------------- #

AREAS_JSON = "data/analysis.json"
SNAP_SWEEP = (0.1, 1.0, 5.0, 25.0, 100.0)


def hist_buckets(sizes):
    """Bucket component sizes so the shape of the distribution is visible."""
    arr = np.asarray(sizes)
    edges = [(1, 1), (2, 2), (3, 5), (6, 10), (11, 25), (26, 50),
             (51, 100), (101, 500), (501, 10**9)]
    out = {}
    for lo, hi in edges:
        sel = (arr >= lo) & (arr <= hi)
        label = f"{lo}" if lo == hi else (f"{lo}+" if hi == 10**9 else f"{lo}-{hi}")
        out[label] = {"n_components": int(sel.sum()),
                      "n_nodes": int(arr[sel].sum())}
    return out


def analyse_area(key: str) -> dict:
    area = network.AREAS_BY_KEY[key]
    data = network.load_area(key)
    lines, nodes, polys = data["lines"], data["nodes"], data["areas"]

    area_km2 = (
        gpd.GeoSeries([data["boundary"]], crs=network.WGS84)
        .to_crs(network.ITM).area.iloc[0] / 1e6
    )

    res = {"key": key, "label": area.label, "osm_relation": area.osm_id,
           "admin_level": area.admin_level, "area_km2": round(float(area_km2), 1)}

    # --- counts by power tag -------------------------------------------- #
    res["line_counts_by_power"] = (
        lines["power"].value_counts().to_dict() if not lines.empty else {}
    )
    res["node_counts_by_power"] = (
        nodes["power"].value_counts().to_dict() if not nodes.empty else {}
    )
    res["area_counts_by_power"] = (
        polys["power"].value_counts().to_dict() if not polys.empty else {}
    )

    # --- voltage tagging ------------------------------------------------- #
    n_lines = len(lines)
    n_volt = int(lines["voltage_v"].notna().sum()) if n_lines else 0
    res["n_line_features"] = n_lines
    res["n_line_features_with_voltage"] = n_volt
    res["frac_lines_with_voltage"] = round(n_volt / n_lines, 4) if n_lines else None

    # Same, weighted by length rather than by feature - a fairer measure,
    # since untagged features are often short stubs.
    if n_lines:
        tagged_km = float(lines.loc[lines["voltage_v"].notna(), "length_km"].sum())
        total_km = float(lines["length_km"].sum())
        res["total_km"] = round(total_km, 1)
        res["frac_km_with_voltage"] = round(tagged_km / total_km, 4) if total_km else None
    else:
        res["total_km"] = 0.0
        res["frac_km_with_voltage"] = None

    # Voltage tagging split by power tag, so overhead vs underground is visible.
    by_tag = {}
    for tag in ("minor_line", "line", "cable"):
        sub = lines[lines["power"] == tag] if n_lines else lines
        if len(sub) == 0:
            continue
        by_tag[tag] = {
            "n": int(len(sub)),
            "km": round(float(sub["length_km"].sum()), 1),
            "frac_with_voltage": round(float(sub["voltage_v"].notna().mean()), 4),
        }
    res["by_power_tag"] = by_tag

    # --- counts and length by band --------------------------------------- #
    if n_lines:
        g = lines.groupby("band")
        res["km_by_band"] = {k: round(float(v), 1)
                             for k, v in g["length_km"].sum().items()}
        res["count_by_band"] = {k: int(v) for k, v in g.size().items()}
        res["km_by_band_per_1000km2"] = {
            k: round(float(v) / area_km2 * 1000, 1)
            for k, v in g["length_km"].sum().items()
        }
        res["distinct_voltages"] = {
            str(int(k)): int(v)
            for k, v in lines["voltage_v"].dropna().value_counts().head(15).items()
        }
    else:
        res["km_by_band"] = {}
        res["count_by_band"] = {}
        res["km_by_band_per_1000km2"] = {}
        res["distinct_voltages"] = {}

    # --- underground vs overhead ----------------------------------------- #
    cable = lines[lines["power"] == "cable"] if n_lines else lines
    minor = lines[lines["power"] == "minor_line"] if n_lines else lines
    res["cable_vs_minor_line"] = {
        "n_cable": int(len(cable)),
        "n_minor_line": int(len(minor)),
        "count_ratio": round(len(cable) / len(minor), 5) if len(minor) else None,
        "km_cable": round(float(cable["length_km"].sum()), 2) if len(cable) else 0.0,
        "km_minor_line": round(float(minor["length_km"].sum()), 1) if len(minor) else 0.0,
        "km_ratio": (round(float(cable["length_km"].sum())
                           / float(minor["length_km"].sum()), 5)
                     if len(minor) and float(minor["length_km"].sum()) else None),
    }
    # location=underground is the other way underground plant is tagged.
    if n_lines and "location" in lines.columns:
        loc = lines["location"].astype("object")
        res["location_tag_counts"] = {
            str(k): int(v) for k, v in loc.value_counts().head(8).items()
        }
        res["n_lines_location_underground"] = int((loc == "underground").sum())
    else:
        res["location_tag_counts"] = {}
        res["n_lines_location_underground"] = 0

    # --- graph ------------------------------------------------------------ #
    dist = network.distribution_only(lines)
    res["n_distribution_line_features"] = int(len(dist))
    res["distribution_km"] = round(float(dist["length_km"].sum()), 1) if len(dist) else 0.0

    for label, frame in (("all_lines", lines), ("distribution_only", dist)):
        g = network.to_graph(frame, snap_m=1.0)
        st = network.component_stats(g)
        st["histogram"] = hist_buckets(st["sizes"]) if st["sizes"] else {}
        st["top_10_sizes"] = st["sizes"][:10] if st["sizes"] else []
        st.pop("sizes", None)
        res[f"graph_{label}_snap1m"] = st

    return res


def sweep_snapping(key: str) -> list:
    """How much of the fragmentation is the graph builder's tolerance?"""
    data = network.load_area(key)
    dist = network.distribution_only(data["lines"])
    rows = []
    for snap in SNAP_SWEEP:
        g = network.to_graph(dist, snap_m=snap)
        st = network.component_stats(g)
        sizes = st.pop("sizes", [])
        st["snap_m"] = snap
        st["top_5_sizes"] = sizes[:5]
        rows.append(st)
    return rows


def run_areas() -> None:
    """Per-area coverage, bands, topology and snapping sweep."""
    results = {}
    for area in network.AREAS:
        print(f"... {area.label}", flush=True)
        results[area.key] = analyse_area(area.key)
    print("... snapping sweep (Kilkenny)", flush=True)
    results["_snap_sweep_kilkenny"] = sweep_snapping("kilkenny")
    print("... snapping sweep (Dublin City)", flush=True)
    results["_snap_sweep_dublin_city"] = sweep_snapping("dublin_city")
    _write_json(results, AREAS_JSON)


# --------------------------------------------------------------------------- #
# national - island-wide graph, one voltage layer at a time
# --------------------------------------------------------------------------- #

NATIONAL_JSON = "data/national.json"

#: A finer cut than ``network.VOLTAGE_BANDS``: this needs a 220 kV split and
#: two overlapping roll-ups that the band taxonomy does not have.  Each entry
#: is ``(name, lo, hi)`` in volts, ``hi`` exclusive, with ``None`` meaning
#: unbounded; ``untagged`` and ``all_sub110kV`` are special-cased because they
#: are about the *absence* of a tag.  These names are keys in the output.
LAYERS = (
    ("ge_220kV", HV_220_V, None),
    ("110kV", network.DISTRIBUTION_MAX_V, HV_220_V),
    ("38kV", SUBTX_MIN_V, network.DISTRIBUTION_MAX_V),
    ("ge_38kV_all", SUBTX_MIN_V, None),
    ("MV_1to38kV", MV_MIN_V, SUBTX_MIN_V),
    ("LV_lt1kV", None, MV_MIN_V),
    ("untagged", None, None),
    ("all_sub110kV", None, network.DISTRIBUTION_MAX_V),
)


def layer_mask(lines: gpd.GeoDataFrame, name: str, lo, hi) -> pd.Series:
    """Boolean mask for one voltage layer.

    ``untagged`` is the rows with no voltage at all; ``all_sub110kV`` is
    everything that is not known to be transmission, so it deliberately
    *includes* the untagged rows.  Every other layer is a numeric window and
    excludes them - which is why the comparison result has to be filled with
    False rather than left as NA.
    """
    volts = lines["voltage_v"]
    if name == "untagged":
        return volts.isna()
    if name == "all_sub110kV":
        return volts.isna() | (volts < hi)
    mask = pd.Series(True, index=lines.index)
    if lo is not None:
        mask &= volts >= lo
    if hi is not None:
        mask &= volts < hi
    return mask.fillna(False)


def run_national() -> None:
    """Island-wide graph by voltage layer, with no administrative clipping.

    Clipping to a county cuts every line that crosses the boundary and inflates
    the component count for exactly the layers that span counties - the 110 kV
    and 38 kV networks.  Running the whole island at once removes that
    artefact, so these component counts are the fair test of whether each
    voltage layer is a network or a scattering.
    """
    L = network.national_lines()
    print(f"island-wide line features: {len(L):,}  "
          f"total {L['length_km'].sum():,.0f} km")
    print(L["power"].value_counts().to_dict())
    print(f"voltage-tagged: {L['voltage_v'].notna().mean():.1%} of features, "
          f"{L.loc[L['voltage_v'].notna(),'length_km'].sum()/L['length_km'].sum():.1%} of km")

    res = {"n_features": int(len(L)),
           "total_km": round(float(L["length_km"].sum()), 1)}
    print(f"\n{'layer':<14} {'feats':>8} {'km':>10} {'nodes':>8} {'comps':>7} "
          f"{'largest':>9} {'largest%':>9} {'comps<=5':>9}")
    for name, lo, hi in LAYERS:
        sel = L[layer_mask(L, name, lo, hi)]
        g = network.to_graph(sel, snap_m=1.0)
        st = network.component_stats(g)
        sizes = st.pop("sizes", [])
        st["n_features"] = int(len(sel))
        st["km"] = round(float(sel["length_km"].sum()), 1)
        st["top_5_sizes"] = sizes[:5]
        res[name] = st
        if st["n_nodes"]:
            print(f"{name:<14} {len(sel):>8,} {st['km']:>10,.0f} {st['n_nodes']:>8,} "
                  f"{st['n_components']:>7,} {st['largest']:>9,} "
                  f"{st['largest_share']:>8.1%} {st['n_size_le_5']:>9,}")
        else:
            print(f"{name:<14} {len(sel):>8,} {st['km']:>10,.0f} {'-':>8} {'-':>7}")

    _write_json(res, NATIONAL_JSON)


# --------------------------------------------------------------------------- #
# subtransmission - is the 38 kV-and-above layer usable on its own?
# --------------------------------------------------------------------------- #

SUBTX_JSON = "data/subtransmission.json"


def run_subtransmission() -> None:
    """Per-area check of the 38 kV-and-above layer alone.

    SWIS-100-IE aggregates buses to regional nodes, so it does not need MV
    feeders.  The question that actually decides the OSM-vs-ESB choice is
    narrower: is the sub-transmission layer mapped completely and connectedly
    enough to place regional nodes and constrain inter-node transfer?
    """
    res = {}
    for area in network.AREAS:
        L = network.load_area(area.key)["lines"]
        volts = L["voltage_v"]
        row = {"label": area.label}
        for name, sel in (
            ("ge_38kV", L[volts.notna() & (volts >= SUBTX_MIN_V)]),
            ("ge_110kV", L[volts.notna() & (volts >= network.DISTRIBUTION_MAX_V)]),
            ("mv_only", L[volts.notna() & (volts >= MV_MIN_V)
                          & (volts < SUBTX_MIN_V)]),
            ("untagged", L[volts.isna()]),
        ):
            g = network.to_graph(sel, snap_m=1.0)
            st = network.component_stats(g)
            sizes = st.pop("sizes", [])
            st["km"] = round(float(sel["length_km"].sum()), 1) if len(sel) else 0.0
            st["n_features"] = int(len(sel))
            st["top_5_sizes"] = sizes[:5]
            row[name] = st
        res[area.key] = row

        print(f"\n{area.label}")
        print(f"  {'layer':<10} {'feats':>7} {'km':>9} {'nodes':>7} {'comps':>7} "
              f"{'largest':>8} {'largest%':>9}")
        for name in ("ge_110kV", "ge_38kV", "mv_only", "untagged"):
            s = row[name]
            if s["n_nodes"] == 0:
                print(f"  {name:<10} {s['n_features']:>7} {s['km']:>9} "
                      f"{'-':>7} {'-':>7} {'-':>8} {'-':>9}")
                continue
            print(f"  {name:<10} {s['n_features']:>7,} {s['km']:>9,.1f} "
                  f"{s['n_nodes']:>7,} {s['n_components']:>7,} "
                  f"{s['largest']:>8,} {s['largest_share']:>8.1%}")

    _write_json(res, SUBTX_JSON)


# --------------------------------------------------------------------------- #
# missing-cable - a lower bound derived only from OSM's own data
# --------------------------------------------------------------------------- #

MISSING_JSON = "data/missing_cable.json"
MST_ASSET_KINDS = ("transformer", "substation")


def mst_km(xy: np.ndarray, k: int = 12) -> float:
    """MST length in km over points, via a k-nearest-neighbour candidate graph."""
    n = len(xy)
    if n < 2:
        return 0.0
    k = min(k, n - 1)
    tree = cKDTree(xy)
    dist, idx = tree.query(xy, k=k + 1)
    g = nx.Graph()
    g.add_nodes_from(range(n))
    for i in range(n):
        for j, d in zip(idx[i][1:], dist[i][1:]):
            g.add_edge(i, int(j), weight=float(d))
    # If kNN left the graph disconnected, bridge components by nearest pair so
    # the bound stays valid rather than silently dropping assets.
    while not nx.is_connected(g):
        comps = list(nx.connected_components(g))
        base = comps[0]
        rest = [i for c in comps[1:] for i in c]
        bt = cKDTree(xy[rest])
        d, j = bt.query(xy[list(base)], k=1)
        a = list(base)[int(np.argmin(d))]
        b = rest[int(j[int(np.argmin(d))])]
        g.add_edge(a, b, weight=float(np.min(d)))
    return float(sum(d["weight"] for _, _, d in
                     nx.minimum_spanning_tree(g).edges(data=True)) / 1000.0)


def run_missing_cable() -> None:
    """A lower bound on missing MV cable, derived only from OSM's own data.

    No external reference is needed.  OSM maps a certain number of MV/LV
    transformers and substations in each area, and whatever the real network
    looks like, every one of those has to be reached by cable.  The minimum
    spanning tree over the mapped point assets is therefore a hard lower bound
    on the conductor length needed to connect just the assets OSM itself
    believes exist - and a very generous one, since a real distribution network
    is longer than an MST: it follows streets, and it is built with open points
    and ring capacity rather than as a minimal tree.

    Comparing that bound with the sub-38 kV length actually mapped gives a
    completeness figure that cannot be argued away as a disagreement about
    ESB's published statistics.
    """
    res = {}
    print(f"{'area':<38} {'assets':>7} {'MST km':>8} {'mapped':>8} {'ratio':>7}")
    for area in network.AREAS:
        d = network.load_area(area.key)
        assets = network.as_points(d["nodes"], d["areas"],
                                   kinds=MST_ASSET_KINDS)
        if assets.empty:
            continue
        assets = assets.to_crs(network.ITM)
        xy = np.column_stack([assets.geometry.x.values, assets.geometry.y.values])
        need = mst_km(xy)

        L = d["lines"]
        mapped = float(L.loc[L["voltage_v"].isna()
                             | (L["voltage_v"] < SUBTX_MIN_V),
                             "length_km"].sum())
        ratio = mapped / need if need else None
        res[area.key] = {
            "label": area.label, "n_assets": int(len(assets)),
            "mst_lower_bound_km": round(need, 1),
            "mapped_sub38kV_km": round(mapped, 1),
            "mapped_over_lower_bound": round(ratio, 3) if ratio else None,
        }
        print(f"{area.label:<38} {len(assets):>7,} {need:>8,.1f} "
              f"{mapped:>8,.1f} {ratio:>6.1%}")

    _write_json(res, MISSING_JSON)
    print("\nratio > 1 means more line is mapped than the bare minimum needed to")
    print("reach the mapped assets; ratio < 1 means the mapped network cannot")
    print("even reach the assets OSM itself contains.")


# --------------------------------------------------------------------------- #
# counties - is mapped density a usable spatial prior?
# --------------------------------------------------------------------------- #

COUNTIES_CSV = "data/county_sweep.csv"


def run_counties() -> None:
    """County-level national sweep: is mapped density a usable spatial prior?

    Attributes every power feature on the island to a Republic of Ireland
    county (OSM ``admin_level=6``) and reports mapped sub-110 kV circuit
    length, pole count and MV/LV transformer count per county, normalised by
    area.  The question is not "is the topology right" (it is not - see the
    ``areas`` subcommand) but "does the *density* of what has been mapped track
    anything a capacity-expansion model would want to allocate, such as
    demand?"
    """
    data = network.island_features()
    lines, pts, polys = data["lines"], data["nodes"], data["areas"]
    counties = network.load_counties()

    # A single spatial join, not a per-county clip loop. Clipping every line
    # against every county polygon in turn ran for over 40 minutes; this runs
    # in seconds. Lines are attributed to the county containing their
    # midpoint - at county scale the few features straddling a boundary move
    # none of these numbers.
    lines_itm = lines.to_crs(network.ITM).reset_index(drop=True)
    lines_itm["km"] = lines_itm.geometry.length / 1000.0
    mids = gpd.GeoDataFrame(
        {"km": lines_itm["km"], "power": lines_itm["power"],
         "voltage_v": lines_itm["voltage_v"]},
        geometry=lines_itm.geometry.interpolate(0.5, normalized=True),
        crs=network.ITM,
    )
    cty_itm = counties.to_crs(network.ITM).reset_index(drop=True)
    # County outlines carry full coastline detail, which makes a
    # point-in-polygon join against 650k points far slower than it needs to
    # be. 100 m simplification is well below the scale of any question here.
    cty_itm["geometry"] = cty_itm.geometry.simplify(100).buffer(0)

    def tag(gdf):
        return gpd.sjoin(gdf, cty_itm[["name", "geometry"]], how="inner",
                         predicate="within")

    lj = network.distribution_only(tag(mids))
    pj = tag(pts.to_crs(network.ITM)[["power", "geometry"]])
    qj = tag(gpd.GeoDataFrame(
        polys[["power"]].reset_index(drop=True),
        geometry=polys.to_crs(network.ITM).geometry.representative_point().values,
        crs=network.ITM))

    recs = []
    for _, cty in cty_itm.iterrows():
        name = cty["name"]
        d = lj[lj["name"] == name]
        p = pj[pj["name"] == name]
        q = qj[qj["name"] == name]
        km = float(d["km"].sum())
        recs.append({
            "county": name,
            "area_km2": round(float(cty["area_km2"]), 1),
            "dist_km": round(km, 1),
            "dist_km_per_1000km2": round(km / cty["area_km2"] * 1000, 1),
            "minor_line_km": round(float(d.loc[d["power"] == "minor_line", "km"].sum()), 1),
            "cable_km": round(float(d.loc[d["power"] == "cable", "km"].sum()), 1),
            "frac_km_with_voltage": round(
                float(d.loc[d["voltage_v"].notna(), "km"].sum()) / max(km, 1e-9), 3),
            "n_poles": int((p["power"] == "pole").sum()),
            "poles_per_km2": round(float((p["power"] == "pole").sum()) / cty["area_km2"], 2),
            "n_transformers": int((p["power"] == "transformer").sum()
                                  + (q["power"] == "transformer").sum()),
            "n_substations": int((p["power"] == "substation").sum()
                                 + (q["power"] == "substation").sum()),
        })

    df = pd.DataFrame(recs).sort_values("dist_km_per_1000km2", ascending=False)
    os.makedirs("data", exist_ok=True)
    df.to_csv(COUNTIES_CSV, index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))
    print(f"\nwrote {COUNTIES_CSV}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _write_json(payload, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print(f"wrote {path}")


COMMANDS = {
    "areas": run_areas,
    "national": run_national,
    "subtransmission": run_subtransmission,
    "missing-cable": run_missing_cable,
    "counties": run_counties,
}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in COMMANDS.items():
        sub.add_parser(name, help=fn.__doc__.splitlines()[0])
    sub.add_parser("all", help="run every measurement, in order")
    args = p.parse_args(argv)

    network.quiet()
    network.ensure_prepared()
    for name in (COMMANDS if args.cmd == "all" else [args.cmd]):
        COMMANDS[name]()


if __name__ == "__main__":
    main()
