"""EirGrid transmission network (110 kV and above) for the Republic of Ireland.

Data source
-----------
EirGrid publishes its Transmission Development Plan web map as an anonymously
queryable ArcGIS feature service under its own ArcGIS Online organisation
(``eirgrid-ie.maps.arcgis.com``).  Three layers are read here: existing
overhead lines, existing underground cables, and existing stations.

This is the transmission system operator's own asset register, not a
redrawing of it.  The check that it is: summing the geometry gives 5,348 km of
overhead line and 774 km of cable, 6,122 km in total, against EirGrid's
published "6,500 km of overhead line and underground cable".

One documented gap, because the aggregate agreement hides it.  The 400 kV
layer holds a single overhead circuit, MONEYPOINT-OLDSTREET, 103 km spanning
longitude -9.42 to -8.27 - the western leg only.  Ireland's 400 kV network
continues east from Oldstreet to Dunstown in Kildare and on to Woodland in
Meath (EirGrid's own "Dunstown-Moneypoint 400 kV Refurbishment" names the
full route), and no circuit for those legs exists in this service at any
voltage.  400 kV is a small share of the total, so this barely moves the
headline figure, but anything that depends on the 400 kV backbone being whole
should not use this layer alone.  ``summary`` prints the warning.

The service is native EPSG:2157 - the same Irish Transverse Mercator the
OpenStreetMap side of this repo uses - so nothing is reprojected.

Why this module is separate from ``network.py``
-----------------------------------------------
Provenance.  ``network.py`` reads crowd-sourced OpenStreetMap data and its
whole job is to measure how incomplete that is.  This module reads utility
data that is complete by construction.  Keeping them apart keeps the two
kinds of claim apart, and the national map draws them in two deliberately
different colour families for the same reason.
"""

from __future__ import annotations

import argparse
import os
import re

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely.geometry import shape

import network

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #

#: EirGrid's public Transmission Development Plan 2024 web map.
TDP_BASE = (
    "https://services-eu1.arcgis.com/1VGs4Se8lewgdzfE/arcgis/rest/services"
    "/TDP_2024_Web_Map_PUBLIC/FeatureServer"
)

#: Line layers, mapped to the ``category`` value written to the output.
LINE_LAYERS = {40: "Overhead Line", 39: "Underground Cable"}
STATION_LAYER = 38

#: The layers do not share a schema - layer 38 has no CATEGORY, CIRCUIT,
#: STATE or LENGTH - so each gets its own field list.
LINE_FIELDS = ("OBJECTID", "VOLTAGE", "CATEGORY", "CSECT_NAME", "CIRCUIT",
               "TYPE", "STATE", "LENGTH")
STATION_FIELDS = ("OBJECTID", "VOLTAGE", "ST_NAME", "ST_NUMBER")

#: ArcGIS caps a single response; the service reports maxRecordCount 2000.
PAGE = 2000

#: Esri Ireland's public copy of the Ordnance Survey Ireland statutory county
#: boundaries.  Requested generalised: the national map draws these at about
#: 1:1,500,000, where 250 m of simplification is invisible and full coastline
#: detail is 39 MB of vertices nobody can see.
COUNTY_URL = (
    "https://services6.arcgis.com/MmUrOQU5v1he9gfS/arcgis/rest/services"
    "/Counties_OSi_Ireland/FeatureServer/0"
)
COUNTY_TOLERANCE_M = 250

CACHE = "data/eirgrid_transmission.gpkg"
COUNTY_CACHE = "data/counties_osi.gpkg"

TIMEOUT = 120

#: EirGrid line voltages, ascending.  Read from the data rather than from the
#: service's renderer: the renderer declares a 275 kV class on all three
#: layers, but no line feature carries it (275 kV is Northern Ireland, which
#: this dataset does not cover).  It survives on exactly one of the 161
#: stations.
LINE_KV = (110, 220, 400)
STATION_KV = (110, 220, 275, 400)


# --------------------------------------------------------------------------- #
# Voltage
# --------------------------------------------------------------------------- #

_KV = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*kV\s*$", re.IGNORECASE)


def parse_kv(raw) -> float:
    """Parse an EirGrid ``VOLTAGE`` string such as ``"110 kV"`` into volts.

    Deliberately strict, and deliberately *not* ``network.parse_voltage``.
    That function reads OpenStreetMap tags, where the unit is conventionally
    omitted and the value is plain volts, so it takes the first number it
    finds and ignores any suffix - it returns ``110.0`` for ``"110 kV"``.
    Teaching it a kV suffix to serve this module would silently re-band every
    OSM tag written with a unit (``"20 kV"`` currently parses to 20 V and
    lands in the LV band), changing published figures for a cosmetic reason.
    So the strict parser lives here and raises rather than guessing.
    """
    if raw is None:
        raise ValueError("no voltage")
    m = _KV.match(str(raw))
    if not m:
        raise ValueError(f"not an EirGrid voltage string: {raw!r}")
    return float(m.group(1)) * 1_000.0


# --------------------------------------------------------------------------- #
# Paged query
# --------------------------------------------------------------------------- #

def _get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(f"ArcGIS error from {url}: {payload['error']}")
    return payload


def feature_count(layer: int, where: str = "1=1") -> int:
    """Number of features the layer will return for ``where``."""
    got = _get_json(f"{TDP_BASE}/{layer}/query",
                    {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(got["count"])


def query_paged(layer: int, fields, where: str = "1=1",
                page: int = PAGE) -> list:
    """Return every GeoJSON feature of ``layer``, paging through the record cap.

    The count is fetched first and the accumulated total checked against it.
    That matters: in GeoJSON mode ArcGIS reports truncation as
    ``properties.exceededTransferLimit`` rather than at the top level, so a
    caller watching the wrong key pages once, believes it is done, and loses
    the rest of the network without any error.  Here a short page raises.
    """
    expected = feature_count(layer, where)
    out = []
    offset = 0
    while offset < expected:
        got = _get_json(f"{TDP_BASE}/{layer}/query", {
            "where": where,
            "outFields": ",".join(fields),
            "orderByFields": "OBJECTID",     # paging without an order is undefined
            "resultOffset": offset,
            "resultRecordCount": page,
            "outSR": 2157,
            "f": "geojson",
        })
        batch = got.get("features") or []
        if not batch:
            raise RuntimeError(
                f"layer {layer} returned an empty page at offset {offset} "
                f"with {len(out)} of {expected} features collected")
        out.extend(batch)
        offset += len(batch)
    if len(out) != expected:
        raise RuntimeError(f"layer {layer}: collected {len(out)} features, "
                           f"service reported {expected}")
    return out


def _to_gdf(features: list) -> gpd.GeoDataFrame:
    """GeoJSON features to a GeoDataFrame, with the CRS asserted not inferred.

    ``outSR=2157`` does put a ``crs`` member on the response, but that member
    is not part of RFC 7946 and readers are free to ignore it, so the CRS is
    set from what was asked for.
    """
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs=network.ITM)
    return gpd.GeoDataFrame(
        pd.DataFrame([f["properties"] for f in features]),
        geometry=[shape(f["geometry"]) for f in features],
        crs=network.ITM,
    )


# --------------------------------------------------------------------------- #
# Layers
# --------------------------------------------------------------------------- #

def _annotate_voltage(gdf: gpd.GeoDataFrame,
                      allowed: tuple) -> gpd.GeoDataFrame:
    """Add ``voltage_v``, ``kv`` and ``band``, refusing unknown voltages.

    ``band`` is ``network.voltage_band``'s label, so these rows are directly
    comparable with the OSM ones - but every EirGrid feature lands in the
    single ">=110 kV" band, which is why the map's palette keys on ``kv``.
    The two are different axes, not a duplicated taxonomy.
    """
    gdf = gdf.copy()
    gdf["voltage_v"] = [parse_kv(v) for v in gdf["VOLTAGE"]]
    gdf["kv"] = (gdf["voltage_v"] / 1_000.0).round().astype(int)
    gdf["band"] = [network.voltage_band(v) for v in gdf["voltage_v"]]
    unknown = sorted(set(gdf["kv"]) - set(allowed))
    if unknown:
        raise RuntimeError(f"unexpected EirGrid voltage level(s) {unknown} kV; "
                           f"expected {list(allowed)}")
    return gdf


def fetch_transmission(force: bool = False,
                       state: str | None = "In Operation") -> gpd.GeoDataFrame:
    """Existing transmission lines, 110 kV and above, in EPSG:2157.

    Every row is cached, including the 212 segments that are abandoned or out
    of service, so ``state`` stays a reversible view rather than a decision
    baked into the cache.  ``state=None`` returns all of them.
    """
    if not force and _has_layer(CACHE, "lines"):
        lines = gpd.read_file(CACHE, layer="lines")
    else:
        parts = []
        for layer, category in LINE_LAYERS.items():
            gdf = _to_gdf(query_paged(layer, LINE_FIELDS))
            gdf["category"] = category
            parts.append(gdf)
        lines = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True),
                                 geometry="geometry", crs=network.ITM)
        lines = _annotate_voltage(lines, LINE_KV)
        lines = lines.rename(columns={
            "CSECT_NAME": "section", "CIRCUIT": "circuit", "TYPE": "conductor",
            "STATE": "state", "LENGTH": "section_length_m",
        })
        # Measured from the geometry, as every other length in this repo is,
        # rather than trusting the recorded section length.
        lines["length_km"] = lines.geometry.length / 1000.0
        lines = lines[["kv", "voltage_v", "band", "category", "circuit",
                       "section", "conductor", "state", "length_km",
                       "section_length_m", "geometry"]]
        _write_gpkg(lines, CACHE, "lines", replace=True)

    if state is not None:
        lines = lines[lines["state"] == state].copy()
    return lines


def _has_layer(path: str, layer: str) -> bool:
    if not os.path.exists(path):
        return False
    return layer in set(gpd.list_layers(path)["name"])


def fetch_stations(force: bool = False) -> gpd.GeoDataFrame:
    """Existing transmission stations, in EPSG:2157."""
    if not force and _has_layer(CACHE, "stations"):
        return gpd.read_file(CACHE, layer="stations")
    st = _to_gdf(query_paged(STATION_LAYER, STATION_FIELDS))
    st = _annotate_voltage(st, STATION_KV)
    st = st.rename(columns={"ST_NAME": "name", "ST_NUMBER": "number"})
    st = st[["kv", "voltage_v", "band", "name", "number", "geometry"]]
    _write_gpkg(st, CACHE, "stations", replace=False)
    return st


def fetch_counties(force: bool = False) -> gpd.GeoDataFrame:
    """The 26 Republic of Ireland counties, generalised, in EPSG:2157.

    Used only for drawing and for the point-in-polygon containment test on the
    national map.  The county *analysis* uses OpenStreetMap boundaries
    (``network.load_counties``) because its published per-county figures are
    keyed to those polygons and their names.
    """
    if not force and os.path.exists(COUNTY_CACHE):
        return gpd.read_file(COUNTY_CACHE)
    got = _get_json(f"{COUNTY_URL}/query", {
        "where": "1=1",
        "outFields": "ENGLISH,PROVINCE,CO_ID",
        "outSR": 2157,
        "maxAllowableOffset": COUNTY_TOLERANCE_M,
        "f": "geojson",
    })
    counties = _to_gdf(got["features"])
    counties = counties.rename(columns={"ENGLISH": "name",
                                        "PROVINCE": "province"})
    counties["name"] = counties["name"].str.title()
    # Server-side generalisation can leave a ring touching itself, which is
    # enough to make a later dissolve raise a topology error. Repair once,
    # here, so the cached polygons are valid for every consumer.
    counties["geometry"] = shapely.make_valid(counties.geometry.values)
    counties = counties[["name", "province", "geometry"]]
    _write_gpkg(counties, COUNTY_CACHE, "counties", replace=True)
    return counties


def _write_gpkg(gdf: gpd.GeoDataFrame, path: str, layer: str,
                replace: bool) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if replace and os.path.exists(path):
        os.remove(path)
    gdf.to_file(path, layer=layer, driver="GPKG")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def run_fetch(force: bool = False) -> None:
    """Download the transmission lines, stations and county boundaries."""
    lines = fetch_transmission(force=force, state=None)
    stations = fetch_stations(force=force)
    counties = fetch_counties(force=force)
    print(f"{CACHE}: {len(lines):,} lines, {len(stations):,} stations")
    print(f"{COUNTY_CACHE}: {len(counties):,} counties")


def run_summary() -> None:
    """Print circuit length by voltage and construction, and check the total."""
    everything = fetch_transmission(state=None)
    in_service = everything[everything["state"] == "In Operation"]

    table = (everything.groupby(["category", "kv"])["length_km"]
             .agg(["size", "sum"]).round(0).astype(int)
             .rename(columns={"size": "features", "sum": "km"}))
    print(table.to_string())
    print()
    for category, km in everything.groupby("category")["length_km"].sum().items():
        print(f"  {category:<20} {km:>9,.0f} km")
    print(f"  {'total':<20} {float(everything['length_km'].sum()):>9,.0f} km"
          f"   ({len(everything):,} features)")
    print(f"  {'of which in service':<20} "
          f"{float(in_service['length_km'].sum()):>9,.0f} km"
          f"   ({len(in_service):,} features)")
    print()
    print("EirGrid publishes 6,500 km of overhead line and underground cable.")
    print("The total above is measured from the geometry of its own published")
    print("Transmission Development Plan service, so agreement to within a few")
    print("per cent is the check that this is the asset register and not a")
    print("schematic. The national map draws the in-service subset.")

    ohl400 = everything[(everything["kv"] == 400)
                        & (everything["category"] == "Overhead Line")]
    circuits = sorted(ohl400["circuit"].dropna().unique())
    if len(circuits) <= 1:
        print()
        print(f"WARNING: the 400 kV overhead layer holds {len(circuits)} circuit "
              f"({', '.join(circuits) or 'none'}),")
        print(f"{float(ohl400['length_km'].sum()):,.0f} km. Ireland's 400 kV "
              "network continues from Oldstreet to Dunstown")
        print("and Woodland, and those legs are absent from this service. Do not "
              "treat the")
        print("400 kV layer as the whole 400 kV backbone.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help=run_fetch.__doc__.splitlines()[0])
    f.add_argument("--refresh", action="store_true",
                   help="re-download even if the cache exists")
    sub.add_parser("summary", help=run_summary.__doc__.splitlines()[0])
    args = p.parse_args(argv)
    if args.cmd == "fetch":
        run_fetch(force=args.refresh)
    else:
        run_summary()


if __name__ == "__main__":
    main()
