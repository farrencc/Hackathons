"""Build a self-contained interactive HTML map of the OSM power network for Ireland.

Consumes the caches written by ``extract_web_data.py`` and
``extract_web_base.py`` and emits one HTML file with every byte of geometry,
attribute and styling inlined, so it opens from a local path with no server
and no build step.  Leaflet itself is the only external request, and the
county outlines are carried as vector data so the map still reads as Ireland
if that request - or the tile server - is unavailable.

Two size decisions carry the file.  Geometry is simplified in Irish
Transverse Mercator at a tolerance chosen per layer (tight for the
transmission layers you will zoom into, looser for the untagged fragments you
will not) and then delta-encoded against a 1e-5 degree grid, which is finer
than the simplification and about a metre on the ground.  Attributes are
emitted as arrays of arrays against one shared string pool, so "ESB Networks"
is stored once rather than eleven thousand times.  Together those take the
payload from roughly 90 MB of GeoJSON to something a browser opens instantly.

The layer split follows FINDINGS.md.  110 kV and above is EirGrid
transmission and gets a warm ramp; 38 kV and below is ESB Networks
distribution and gets a blue ramp; the two are separated because the
conclusion of that document is that the data is trustworthy on one side of
that line and not on the other.  The default view is the layers that survived
scrutiny - 38 kV and above, plus the substations - with MV, LV and the
untagged remainder available but switched off, and the sidebar says why.
"""

from __future__ import annotations

import json
import os
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd

import network as m
from extract_web_data import COUNTS_CACHE, LINES_CACHE, SITES_CACHE
from extract_web_base import OUT as BASE_CACHE

warnings.filterwarnings("ignore")

OUT_HTML = "data/ireland_distribution_map.html"
TEMPLATE = "web/map_template.html"

#: Leaflet is inlined rather than pulled from a CDN.  The point of the file is
#: that it opens from a local path years from now, on a laptop that may be
#: offline or behind a policy that blocks third-party script hosts; a <script
#: src> would make all of that a coin toss for the sake of 150 kB against an
#: 11 MB payload.  BSD-2-Clause, see web/vendor/LEAFLET-LICENSE.
VENDOR_JS = "web/vendor/leaflet.js"
VENDOR_CSS = "web/vendor/leaflet.css"

#: Coordinate quantum for the delta encoding, in degrees.  1e-5 is ~1.1 m of
#: latitude and ~0.7 m of longitude at Irish latitudes - below the tightest
#: simplification tolerance used, so it never becomes the binding constraint
#: on shape.
PREC = 100_000

EXTRACT_DATE = "2026-09-03"
EXTRACT_MD5 = "fbfef4e91342bcf26a8a342d01f002a7"

# (key, label, predicate, simplify_m, weight, opacity, default_on)
LINE_LAYERS = [
    ("t220", "≥220 kV transmission",
     lambda L: L["voltage_v"] >= 220_000, 8.0, 2.0, 0.95, True),
    ("t110", "110 kV transmission",
     lambda L: (L["voltage_v"] >= 110_000) & (L["voltage_v"] < 220_000), 8.0, 1.5, 0.9, True),
    ("kv38", "38 kV sub-transmission",
     lambda L: (L["voltage_v"] >= 38_000) & (L["voltage_v"] < 110_000), 8.0, 1.3, 0.9, True),
    ("mv", "MV 1–38 kV",
     lambda L: (L["voltage_v"] >= 1_000) & (L["voltage_v"] < 38_000), 15.0, 0.9, 0.8, False),
    ("lv", "LV under 1 kV",
     lambda L: L["voltage_v"] < 1_000, 15.0, 0.9, 0.8, False),
    ("unk", "No voltage tag",
     lambda L: L["voltage_v"].isna(), 20.0, 0.7, 0.65, False),
]

#: Column order matters for size, not just readability.  Rows are emitted as
#: plain arrays and every trailing null is dropped, so the columns almost
#: everything carries go first and the ones only a well-tagged minority
#: carries go last.  Most OSM power features are tagged with three or four
#: keys out of the dozen offered, so the tail is usually empty: this alone is
#: worth about a third of the payload.
LINE_COLS = ["id", "osm_type", "power", "length_km", "voltage_v",
             "name", "operator", "ref", "location", "cables", "circuits"]
LINE_STR_COLS = {"osm_type", "power", "name", "operator", "ref", "location",
                 "cables", "circuits"}

#: Position is stored first so the tail stays trimmable.
SITE_COLS = ["_lat", "_lon", "id", "osm_type", "power", "generator:source",
             "substation", "voltage_v", "name", "operator", "ref",
             "plant:source", "generator:output:electricity",
             "plant:output:electricity", "generator:method", "start_date",
             "area_m2"]
SITE_STR_COLS = {"osm_type", "power", "substation", "name", "operator", "ref",
                 "generator:source", "plant:source",
                 "generator:output:electricity", "plant:output:electricity",
                 "generator:method", "start_date"}


def trim(row: list) -> list:
    """Drop trailing nulls; the reader treats a short row as null-padded."""
    end = len(row)
    while end and row[end - 1] is None:
        end -= 1
    return row[:end]

# (key, label, singular, predicate, radius, default_on)
SITE_LAYERS = [
    ("substation", "Substations", "substation",
     lambda S: S["power"] == "substation", 4.5, True),
    ("transformer", "Transformers", "transformer",
     lambda S: S["power"] == "transformer", 2.6, True),
    ("plant", "Generating stations", "generating station",
     lambda S: S["power"] == "plant", 4.5, True),
    ("wind", "Wind turbines", "wind turbine",
     lambda S: (S["power"] == "generator") & (S["source_clean"] == "wind"), 2.4, False),
    ("othergen", "Other generation", "generator",
     lambda S: (S["power"] == "generator")
               & (~S["source_clean"].isin(["wind", "solar"])), 3.0, True),
    ("solar", "Solar PV", "solar installation",
     lambda S: (S["power"] == "generator") & (S["source_clean"] == "solar"), 1.8, False),
    ("switch", "Switchgear and other plant", "switching equipment",
     lambda S: S["power"].isin(["switch", "switchgear", "compensator", "converter"]), 3.0, True),
]


class Pool:
    """Intern strings so repeated operators and tag values are stored once."""

    def __init__(self):
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, value) -> int | None:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            return None
        if text not in self.index:
            self.index[text] = len(self.items)
            self.items.append(text)
        return self.index[text]


def encode_line(geom, prec: int = PREC) -> list[int]:
    """Delta-encode a LineString as [x0, y0, dx1, dy1, ...] of quantised ints."""
    xs, ys = geom.coords.xy
    x = np.rint(np.asarray(xs) * prec).astype(np.int64)
    y = np.rint(np.asarray(ys) * prec).astype(np.int64)
    # Quantisation can collapse neighbouring vertices onto the same cell; a
    # zero-length step is pure payload with no effect on the drawn shape.
    keep = np.ones(len(x), dtype=bool)
    keep[1:] = (np.diff(x) != 0) | (np.diff(y) != 0)
    x, y = x[keep], y[keep]
    if len(x) < 2:
        return []
    out = [int(x[0]), int(y[0])]
    dx, dy = np.diff(x), np.diff(y)
    for a, b in zip(dx.tolist(), dy.tolist()):
        out.append(a)
        out.append(b)
    return out


def num(value):
    """JSON-safe number, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(f):
        return None
    return round(f, 4) if f % 1 else int(f)


def build_line_layers(lines: gpd.GeoDataFrame, pool: Pool) -> dict:
    itm = lines.to_crs(m.ITM)
    out = {}
    for key, label, pred, tol, weight, opacity, on in LINE_LAYERS:
        mask = pred(lines)
        mask = mask.fillna(False) if mask.dtype != bool else mask
        sel = lines[mask]
        if sel.empty:
            continue
        simple = itm.loc[sel.index].geometry.simplify(tol)
        simple = gpd.GeoSeries(simple, crs=m.ITM).to_crs(m.WGS84)

        geom, rows = [], []
        for idx, g in zip(sel.index, simple.values):
            if g is None or g.is_empty:
                continue
            enc = encode_line(g)
            if not enc:
                continue
            rec = sel.loc[idx]
            row = [pool.add(rec.get(c)) if c in LINE_STR_COLS else num(rec.get(c))
                   for c in LINE_COLS]
            geom.append(enc)
            rows.append(trim(row))

        out[key] = {
            "label": label, "weight": weight, "opacity": opacity, "on": on,
            "km": round(float(sel["length_km"].sum()), 1),
            "n": len(geom),
            "cols": LINE_COLS,
            "strCols": [c in LINE_STR_COLS for c in LINE_COLS],
            "geom": geom, "rows": rows,
        }
        print(f"  {key:<6} {len(geom):>7,} features  {out[key]['km']:>9,.0f} km  "
              f"{sum(len(g) for g in geom) // 2:>9,} vertices")
    return out


def build_site_layers(sites: gpd.GeoDataFrame, pool: Pool) -> dict:
    src = sites["generator:source"].fillna(sites["plant:source"])
    sites = sites.copy()
    sites["source_clean"] = (src.astype("object").where(src.notna(), "")
                             .astype(str).str.split(";").str[0].str.strip().str.lower())

    sites.loc[sites["area_m2"] == 0, "area_m2"] = np.nan

    lon = np.rint(sites.geometry.x.values * PREC).astype(np.int64)
    lat = np.rint(sites.geometry.y.values * PREC).astype(np.int64)

    out = {}
    for key, label, singular, pred, radius, on in SITE_LAYERS:
        mask = pred(sites)
        mask = mask.fillna(False) if mask.dtype != bool else mask
        sel = sites[mask]
        if sel.empty:
            continue
        pos = np.flatnonzero(mask.values)
        rows = []
        for row_i, (_, rec) in zip(pos, sel.iterrows()):
            row = []
            for col in SITE_COLS:
                if col == "_lat":
                    row.append(int(lat[row_i]))
                elif col == "_lon":
                    row.append(int(lon[row_i]))
                elif col in SITE_STR_COLS:
                    row.append(pool.add(rec.get(col)))
                else:
                    row.append(num(rec.get(col)))
            rows.append(trim(row))

        out[key] = {
            "label": label, "singular": singular, "radius": radius, "on": on,
            "cols": SITE_COLS,
            "strCols": [c in SITE_STR_COLS for c in SITE_COLS],
            "lat": SITE_COLS.index("_lat"), "lon": SITE_COLS.index("_lon"),
            "rows": rows,
        }
        print(f"  {key:<12} {len(rows):>7,} sites")
    return out


def build_base() -> dict:
    base = gpd.read_file(BASE_CACHE)
    gj = json.loads(base[["name", "kind", "geometry"]].to_json())

    # 4 decimals is ~11 m - an order of magnitude below the 150 m the outlines
    # were already simplified at, so it costs no visible shape and halves the
    # size of the base geometry.
    def trim(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], 4), round(coords[1], 4)]
        return [trim(c) for c in coords]
    for feat in gj["features"]:
        feat["geometry"]["coordinates"] = trim(feat["geometry"]["coordinates"])
        feat.pop("id", None)
    return gj


def notes(line_layers: dict, site_layers: dict, structural: dict) -> list[str]:
    sub110 = sum(line_layers[k]["km"] for k in ("kv38", "mv", "lv", "unk") if k in line_layers)
    mv_km = line_layers.get("mv", {}).get("km", 0)
    n_sub = len(site_layers.get("substation", {}).get("rows", []))
    n_tx = len(site_layers.get("transformer", {}).get("rows", []))
    poles = structural.get("pole", 0)
    return [
        "<b>The top three layers are the trustworthy ones.</b> At 38 kV and above "
        "OpenStreetMap holds a genuine, connected network: 220 kV and up resolves to "
        "22 components with 94% of nodes in one of them, and the combined ≥38 kV layer "
        "holds 64% in one. That is usable for siting and for inter-regional transfer.",

        f"<b>Below 38 kV it is a scattering, not a network.</b> The MV layer is "
        f"{mv_km:,.0f} km in 6,707 disconnected pieces whose largest holds 8.7% of nodes, "
        "against roughly 571 primary stations nationally — an order of magnitude too "
        "many. No snapping tolerance fixes it, because the missing spans are kilometres "
        "of unmapped conductor, not centimetres of noding slop.",

        f"<b>Blank areas are unmapped, not unserved.</b> Every part of the island has a "
        f"distribution network. OpenStreetMap has about 22% of the line length and "
        f"{poles:,} of ESB's 2.1 million poles, but only ~4% of the underground cable "
        f"and ~2% of the MV/LV transformers — {n_tx:,} against 242,000. Mapped density "
        "tracks where a volunteer has worked, not where load is.",

        f"<b>Sites carry what the mapper typed.</b> Of {n_sub:,} substations, most have "
        "no voltage tag and many have no name; the popup shows the raw OSM tags rather "
        "than anything inferred. Solar PV is mostly individual rooftop panels and is off "
        "by default.",

        "<b>Northern Ireland is included</b> because the extract covers the island, but "
        "NIE Networks is the DSO there and none of the ESB comparisons above apply to it.",
    ]


def main():
    lines = gpd.read_file(LINES_CACHE)
    sites = gpd.read_file(SITES_CACHE)
    with open(COUNTS_CACHE) as fh:
        structural = json.load(fh)["structural"]

    print(f"lines {len(lines):,}  sites {len(sites):,}")
    pool = Pool()

    print("line layers:")
    line_layers = build_line_layers(lines, pool)
    print("site layers:")
    site_layers = build_site_layers(sites, pool)

    base = build_base()
    total_km = float(lines["length_km"].sum())

    payload = {
        "meta": {
            "title": "Ireland’s electricity network as mapped in OpenStreetMap",
            "subtitle": (
                f"{len(lines):,} conductor runs, {total_km:,.0f} km, and "
                f"{len(sites):,} sites extracted from a single Geofabrik extract. "
                "Click anything for its tags."
            ),
            "notes": notes(line_layers, site_layers, structural),
            "footer": (
                f"Source: Geofabrik <code>ireland-and-northern-ireland</code> extract, "
                f"{EXTRACT_DATE}, MD5 <code>{EXTRACT_MD5}</code>. Lengths measured in "
                f"EPSG:2157. Poles ({structural.get('pole', 0):,}) and towers "
                f"({structural.get('tower', 0):,}) are counted but not drawn. "
                "Method and caveats: FINDINGS.md."
            ),
        },
        "bounds": [[51.35, -10.75], [55.45, -5.35]],
        "lineOrder": [k for k, *_ in LINE_LAYERS if k in line_layers],
        "siteOrder": [k for k, *_ in SITE_LAYERS if k in site_layers],
        "lines": line_layers,
        "sites": site_layers,
        "base": base,
        "strings": pool.items,
    }

    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    with open(TEMPLATE) as fh:
        html = fh.read()
    with open(VENDOR_CSS) as fh:
        html = html.replace("/*__LEAFLET_CSS__*/", fh.read())
    with open(VENDOR_JS) as fh:
        html = html.replace("/*__LEAFLET_JS__*/", fh.read())
    html = html.replace("/*__DATA__*/null", blob)

    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, "w") as fh:
        fh.write(html)
    print(f"\n{OUT_HTML}  {os.path.getsize(OUT_HTML) / 1e6:.1f} MB  "
          f"(payload {len(blob) / 1e6:.1f} MB, {len(pool.items):,} interned strings)")


if __name__ == "__main__":
    main()
