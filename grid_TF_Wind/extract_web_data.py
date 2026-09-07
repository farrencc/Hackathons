"""Extract the island-wide OSM power network into a compact cache for the web map.

Reads the prefiltered ``ireland-power.osm.pbf`` once and writes two GeoPackages
that the HTML builder consumes:

* ``data/raw/web_lines.gpkg``  - conductor runs, reassembled per OSM way.
  pyrosm hands back each way split into two-point segments, which is fine for
  graph work but triples the coordinate count of anything drawn on a map.
  ``linemerge`` over the segments of one way puts the way back together, so a
  110 kV circuit is one clickable feature carrying its own name and operator
  rather than four hundred anonymous stubs.
* ``data/raw/web_sites.gpkg`` - point assets.  Substations mapped as polygons
  are reduced to their centroid with the footprint area kept as an attribute,
  so a site is one marker however it happens to have been drawn.

Poles, towers, catenary masts, insulators and bare connections are counted but
not carried through: there are half a million of them, they have no attributes
worth reading, and they would swamp both the file and the browser.
"""

from __future__ import annotations

import os
import warnings

import geopandas as gpd
import pandas as pd
from shapely.ops import linemerge, unary_union

import network as m

warnings.filterwarnings("ignore")

LINES_CACHE = "data/raw/web_lines.gpkg"
SITES_CACHE = "data/raw/web_sites.gpkg"
COUNTS_CACHE = "data/raw/web_counts.json"

#: Point assets worth a marker and a popup.  Everything else tagged ``power``
#: is structural hardware; see the module docstring.
SITE_POWER_VALUES = (
    "substation", "transformer", "generator", "plant", "switch",
    "converter", "compensator", "switchgear",
)

STRUCTURAL_POWER_VALUES = (
    "pole", "tower", "catenary_mast", "insulator", "connection",
    "terminal", "portal",
)

#: Tags pyrosm leaves in its JSON blob that the popups want as real columns.
#: ``generator:source`` is the one that matters most - it is the difference
#: between "a generator" and "a 3 MW wind turbine", and it is the attribute
#: that makes the point layer worth anything for siting distributed
#: generation, which FINDINGS.md identifies as the one distribution-side use
#: the OSM data does support.
EXTRA_TAGS = (
    "generator:source", "generator:output:electricity", "generator:method",
    "plant:source", "plant:output:electricity", "substation", "building",
    "man_made", "start_date", "note",
)

KEEP = ["id", "osm_type", "power", "voltage_v", "band", "name", "operator",
        "ref", "substation", "location", "cables", "circuits", "frequency",
        "generator:source", "generator:output:electricity", "generator:method",
        "plant:source", "plant:output:electricity", "start_date"]


def load_raw() -> gpd.GeoDataFrame:
    from pyrosm import OSM

    osm = OSM(m.POWER_PBF_PATH)
    raw = osm.get_data_by_custom_criteria(
        custom_filter={"power": True}, filter_type="keep",
        tags_as_columns=list(m.TAGS_AS_COLUMNS),
        keep_nodes=True, keep_ways=True, keep_relations=True,
    ).set_crs(m.WGS84, allow_override=True)
    raw = raw[~raw.geometry.is_empty & raw.geometry.notna()].copy()
    raw = m.expand_tags(raw, keys=tuple(m.TAGS_AS_COLUMNS) + EXTRA_TAGS)
    raw["voltage_v"] = [m.parse_voltage(v) for v in m.voltage_series(raw)]
    raw["band"] = [m.voltage_band(v) for v in raw["voltage_v"]]
    for col in KEEP:
        if col not in raw.columns:
            raw[col] = None
    return raw


def build_lines(raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gt = raw.geometry.geom_type
    lines = raw[gt.isin(["LineString", "MultiLineString"])].copy()
    lines = lines[lines["power"].isin(m.LINE_POWER_VALUES)].copy()
    lines = lines.explode(index_parts=False, ignore_index=True)
    lines = lines[lines.geometry.geom_type == "LineString"].copy()

    # Reassemble each OSM way from its segments.  Attributes are constant
    # within a way, so taking the first row of the group is exact, not a
    # summary.  A way that self-intersects or doubles back comes out of
    # linemerge as a MultiLineString; exploding keeps every part.
    rows = []
    for osm_id, grp in lines.groupby("id", sort=False):
        first = grp.iloc[0]
        geom = grp.geometry.iloc[0] if len(grp) == 1 else linemerge(unary_union(grp.geometry.values))
        rec = {c: first.get(c) for c in KEEP}
        rec["id"] = osm_id
        rec["geometry"] = geom
        rows.append(rec)

    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=m.WGS84)
    out = out.explode(index_parts=False, ignore_index=True)
    out = out[out.geometry.geom_type == "LineString"].copy()
    out["length_km"] = out.to_crs(m.ITM).geometry.length / 1000.0
    return out[out["length_km"] > 0].reset_index(drop=True)


def build_sites(raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gt = raw.geometry.geom_type
    sel = raw[raw["power"].isin(SITE_POWER_VALUES)].copy()
    gt = sel.geometry.geom_type

    pts = sel[gt == "Point"].copy()
    pts["area_m2"] = 0.0

    polys = sel[gt.isin(["Polygon", "MultiPolygon"])].copy()
    if not polys.empty:
        polys["area_m2"] = polys.to_crs(m.ITM).geometry.area
        polys["geometry"] = polys.to_crs(m.ITM).geometry.representative_point().to_crs(m.WGS84)

    # A few substations are mapped as an unclosed way; keep them via centroid.
    other = sel[gt.isin(["LineString", "MultiLineString"])].copy()
    if not other.empty:
        other["area_m2"] = 0.0
        other["geometry"] = other.geometry.centroid

    out = gpd.GeoDataFrame(pd.concat([pts, polys, other], ignore_index=True),
                           geometry="geometry", crs=m.WGS84)
    cols = KEEP + ["area_m2", "geometry"]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)


def main():
    import json

    raw = load_raw()
    print(f"raw power objects: {len(raw):,}")

    lines = build_lines(raw)
    print(f"line ways: {len(lines):,}  {lines['length_km'].sum():,.0f} km")
    print(lines["band"].value_counts().to_dict())

    sites = build_sites(raw)
    print(f"sites: {len(sites):,}")
    print(sites["power"].value_counts().to_dict())

    structural = raw[raw["power"].isin(STRUCTURAL_POWER_VALUES)]
    counts = structural["power"].value_counts().to_dict()
    counts = {str(k): int(v) for k, v in counts.items()}
    print(f"structural (not mapped): {counts}")

    os.makedirs(m.RAW_DIR, exist_ok=True)
    lines.to_file(LINES_CACHE, driver="GPKG")
    sites.to_file(SITES_CACHE, driver="GPKG")
    with open(COUNTS_CACHE, "w") as fh:
        json.dump({"structural": counts}, fh, indent=1)


if __name__ == "__main__":
    main()
