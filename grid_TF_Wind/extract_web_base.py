"""Extract the administrative outlines the web map draws itself on.

The map has to stay legible with no tile server - offline, or behind a policy
that blocks third-party image hosts - so the coastline and county lines are
carried as vector data inside the file rather than borrowed from a raster
basemap.  Republic counties come from admin_level 6.  Northern Ireland comes from its
eleven district councils at admin_level 7 rather than from the admin_level 4
region: the region relation follows the maritime limit and encloses 19,300 km2
against Northern Ireland's 14,100 km2 of land, which would draw a coastline
several kilometres out to sea.  The districts follow the shore.  It is drawn
because the extract covers the island, but NIE Networks is the DSO there and
none of the ESB comparisons in FINDINGS.md apply to it.

The areas are assembled with pyosmium's multipolygon assembler rather than
``pyrosm.get_boundaries()``.  The pyrosm route re-parses every administrative
relation on the island and takes the better part of ten minutes for the thirty
polygons wanted here; osmium's assembler, given a boundary-only prefilter,
does the same job in seconds.

Outlines are simplified to 150 m, which is invisible at any zoom this map
opens at and cuts the embedded geometry by an order of magnitude.
"""

from __future__ import annotations

import json
import os
import warnings

import geopandas as gpd
import osmium
import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

import network as m

warnings.filterwarnings("ignore")

OUT = "data/raw/web_base.gpkg"
SIMPLIFY_M = 150.0
MIN_AREA_KM2 = 100.0

#: Five Republic counties whose OSM name has no "County " prefix.
ROI_EXTRA = {"Dublin", "Cork", "Galway", "Limerick", "Waterford"}

#: The eleven Northern Ireland district councils, named as OSM has them.
#: Listed explicitly rather than pattern-matched because "District" also
#: appears in Republic municipal-district names at the same admin level.
NI_DISTRICTS = {
    "Antrim and Newtownabbey District",
    "Ards and North Down District Council",
    "Armagh City, Banbridge and Craigavon District Council",
    "Belfast City District",
    "Causeway Coast and Glens District",
    "Derry and Strabane District",
    "Fermanagh and Omagh District",
    "Lisburn and Castlereagh District",
    "Mid and East Antrim District",
    "Mid-Ulster District Council",
    "Newry, Mourne and Down District Council",
}


def wanted(tags) -> tuple[str, str] | None:
    """Return (display name, kind) for the boundaries the map draws, else None."""
    if tags.get("boundary") != "administrative":
        return None
    name = tags.get("name")
    level = tags.get("admin_level")
    if not name:
        return None
    if level == "6" and (name.startswith("County ") or name in ROI_EXTRA):
        return name, "county"
    if level == "7" and name in NI_DISTRICTS:
        return name, "district"
    return None


def main():
    factory = osmium.geom.GeoJSONFactory()
    fp = (osmium.FileProcessor(m.BOUNDS_PBF_PATH)
          .with_areas()
          .with_filter(osmium.filter.KeyFilter("boundary")))

    parts: dict[tuple[str, str], list] = {}
    for obj in fp:
        if not isinstance(obj, osmium.osm.Area):
            continue
        hit = wanted(obj.tags)
        if hit is None:
            continue
        geom = shape(json.loads(factory.create_multipolygon(obj)))
        if geom.is_empty:
            continue
        parts.setdefault(hit, []).append(geom)

    rows = [{"name": name, "kind": kind, "geometry": unary_union(geoms)}
            for (name, kind), geoms in parts.items()]
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=m.WGS84)
    out["area_km2"] = out.to_crs(m.ITM).area / 1e6
    out = out[out["area_km2"] > MIN_AREA_KM2].reset_index(drop=True)

    itm = out.to_crs(m.ITM)
    itm["geometry"] = itm.geometry.simplify(SIMPLIFY_M).buffer(0)
    out = itm.to_crs(m.WGS84)

    missing = NI_DISTRICTS - set(out["name"])
    if missing:
        raise RuntimeError(f"Northern Ireland districts not assembled: {sorted(missing)}")

    # One dissolved outline for the shore itself, so the map can draw the
    # coast a shade heavier than the internal county lines.
    coast = itm.geometry.union_all().buffer(0)
    coast = gpd.GeoDataFrame(
        [{"name": "Ireland", "kind": "coast", "area_km2": coast.area / 1e6}],
        geometry=[coast], crs=m.ITM).to_crs(m.WGS84)
    out = gpd.GeoDataFrame(pd.concat([out, coast], ignore_index=True),
                           geometry="geometry", crs=m.WGS84)

    os.makedirs(m.RAW_DIR, exist_ok=True)
    out.to_file(OUT, driver="GPKG")
    print(out[["name", "kind", "area_km2"]].sort_values(["kind", "name"]).to_string(index=False))
    print(f"\n{len(out)} outlines -> {OUT}")


if __name__ == "__main__":
    main()
