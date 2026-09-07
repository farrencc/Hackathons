"""Maps: one per analysis area, plus the national map of the whole network.

Everything is projected to EPSG:2157 (Irish Transverse Mercator) so distance on
the page is distance on the ground.

Colour
------
Two families, because the map carries two kinds of data and the reader has to
be able to tell them apart at a glance.

*Distribution* (sub-110 kV, from OpenStreetMap) takes a single-hue blue ordinal
ramp, light to dark with rising voltage.  Voltage is an ordered quantity, so a
ramp is right and a set of unrelated hues would be wrong - a rainbow would
imply the bands are unordered categories.  Untagged features are off that scale
entirely and take a neutral grey: they are an absence of data, not a voltage
class, and grey keeps them recessive.

*Transmission* (110 kV and above, from EirGrid) takes its own single-hue warm
ramp on the same principle.  The two ramps are far apart in hue, so provenance
reads as colour family and voltage reads as position within a family.

Both ramps were checked rather than eyeballed: monotone lightness, adjacent
lightness gap >= 0.06, hue spread within 5 degrees, light end clearing the
surface (blue 2.06:1, warm 4.70:1), and every cross-family pair above the
colour-vision-deficiency and normal-vision separation floors - the worst pair
being untagged grey against 110 kV at deltaE 10.9 simulated deutan, which line
weight and legend grouping separate further.  Line weight repeats the voltage
ordering in both families, so band is never carried by colour alone.
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")   # must precede the pyplot import: no display here
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import eirgrid
import network

OUT_DIR = "data"
DPI = 160

NATIONAL_PNG = "data/national_network.png"
NATIONAL_GPKG = "data/national_distribution.gpkg"

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
HAIRLINE = "#e1e0d9"
COAST = "#c3c2b7"

#: Distribution bands, keyed by ``network.Band.id`` rather than by label, so
#: rewording a legend string cannot quietly detach a layer from its style.
#: ``lw_area`` is for the per-area maps, ``lw_national`` for the national one,
#: which is drawn at roughly a tenth the scale.
BAND_STYLE = {
    "unknown": {"colour": "#898781", "lw_area": 0.35, "lw_national": 0.28,
                "short": "no voltage tag"},
    "lv":      {"colour": "#86b6ef", "lw_area": 0.45, "lw_national": 0.35,
                "short": "LV (<1 kV)"},
    "mv":      {"colour": "#3987e5", "lw_area": 0.55, "lw_national": 0.45,
                "short": "MV (1-38 kV)"},
    "kv38":    {"colour": "#1c5cab", "lw_area": 1.00, "lw_national": 0.85,
                "short": "38 kV"},
    "tx":      {"colour": "#0d366b", "lw_area": 1.50, "lw_national": 1.20,
                "short": "110 kV+ (OSM)"},
}

_unstyled = [b.id for b in network.ALL_BANDS if b.id not in BAND_STYLE]
if _unstyled:
    raise RuntimeError(f"no plot style for voltage band(s): {_unstyled}")

#: EirGrid transmission, keyed by kV.  Not keyed by ``band``: every EirGrid
#: feature falls in the single ">=110 kV" band, so band cannot distinguish
#: them - voltage level is a finer axis here than the OSM taxonomy has.
#: 275 kV carries no line features (it is Northern Ireland, outside this
#: dataset) and survives on one station; it is here so the guard below can be
#: total, and it is deliberately not part of the validated three-step ramp.
TX_STYLE = {
    110: {"colour": "#c44a24", "lw": 1.1},
    220: {"colour": "#9a2f16", "lw": 1.5},
    275: {"colour": "#83280f", "lw": 1.8},
    400: {"colour": "#67200f", "lw": 2.1},
}
TX_DRAW_ORDER = (110, 220, 275, 400)

# Asset type is a genuine category, not a magnitude, so these take hues off the
# voltage ramps: orange for transformers reads clearly against every blue step,
# substations take primary ink, and poles take the recessive baseline tone since
# there are tens of thousands of them and they are context, not subject.
POINT_STYLE = {
    "substation":  {"colour": "#0b0b0b", "marker": "s", "size": 24, "z": 6},
    "transformer": {"colour": "#eb6834", "marker": "^", "size": 15, "z": 5},
    "pole":        {"colour": "#c3c2b7", "marker": ".", "size": 0.8, "z": 3},
}


def _stringify(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cast object columns to str so GPKG will take them."""
    out = gdf.copy()
    for col in out.columns:
        if col != "geometry" and out[col].dtype == object:
            out[col] = out[col].astype(str)
    return out


def _write_layer(gdf: gpd.GeoDataFrame, path: str, layer: str,
                 replace: bool) -> None:
    if replace and os.path.exists(path):
        os.remove(path)
    _stringify(gdf).to_file(path, layer=layer, driver="GPKG")


# --------------------------------------------------------------------------- #
# Per-area maps
# --------------------------------------------------------------------------- #

def write_area_gpkg(data: dict, path: str) -> None:
    """Write ``lines`` and ``nodes`` layers for one area, in EPSG:2157."""
    drop = ("tags",)   # dict/JSON blob, not writable to GPKG

    lines = data["lines"]
    if not lines.empty:
        out = lines.drop(columns=[c for c in drop if c in lines.columns])
        _write_layer(out.to_crs(network.ITM), path, "lines", replace=True)

    nodes = network.as_points(data["nodes"], data["areas"])
    if not nodes.empty:
        nodes = nodes.drop(columns=[c for c in drop if c in nodes.columns])
        _write_layer(nodes.to_crs(network.ITM), path, "nodes",
                     replace=lines.empty)


def plot_area(key: str) -> None:
    """Draw one analysis area: lines by voltage band, plus point assets."""
    area = network.AREAS_BY_KEY[key]
    data = network.load_area(key)
    lines = data["lines"]

    boundary = gpd.GeoSeries([data["boundary"]],
                             crs=network.WGS84).to_crs(network.ITM)
    fig, ax = plt.subplots(figsize=(9.5, 10.5))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    boundary.boundary.plot(ax=ax, color=COAST, lw=0.8, zorder=1)
    boundary.plot(ax=ax, color=SURFACE, zorder=0)

    lines_itm = lines.to_crs(network.ITM) if not lines.empty else lines
    drawn = []
    for z, band in enumerate(network.ALL_BANDS):
        if lines_itm.empty:
            break
        sel = lines_itm[lines_itm["band"] == band.label]
        if len(sel) == 0:
            continue
        st = BAND_STYLE[band.id]
        sel.plot(ax=ax, color=st["colour"], lw=st["lw_area"], zorder=2 + z)
        drawn.append((band.label, st, float(sel["length_km"].sum()), len(sel)))

    points = network.as_points(data["nodes"], data["areas"])
    drawn_points = []
    if not points.empty:
        points = points.to_crs(network.ITM)
        for kind in ("pole", "transformer", "substation"):
            sel = points[points["power"] == kind]
            if len(sel) == 0:
                continue
            st = POINT_STYLE[kind]
            sel.plot(ax=ax, color=st["colour"], marker=st["marker"],
                     markersize=st["size"], zorder=st["z"],
                     linewidth=0.3 if kind == "substation" else 0)
            drawn_points.append((kind, st, len(sel)))

    handles = [Line2D([0], [0], color=st["colour"],
                      lw=max(st["lw_area"], 1.4),
                      label=f"{label}  -  {km:,.0f} km ({n:,})")
               for label, st, km, n in reversed(drawn)]
    handles += [Line2D([0], [0], color=st["colour"], marker=st["marker"], lw=0,
                       markersize=7 if kind != "pole" else 4,
                       label=f"{kind}  ({n:,})")
                for kind, st, n in reversed(drawn_points)]
    leg = ax.legend(handles=handles, loc="upper left", fontsize=7.5,
                    frameon=True, framealpha=0.95, edgecolor=HAIRLINE,
                    facecolor=SURFACE, labelcolor=INK_SECONDARY,
                    title="voltage band / asset", title_fontsize=8)
    leg.get_title().set_color(INK_MUTED)

    total_km = float(lines["length_km"].sum()) if not lines.empty else 0.0
    frac = float(lines["voltage_v"].notna().mean()) if not lines.empty else 0.0
    ax.set_title(
        f"{area.label}\n"
        f"OpenStreetMap power features - {len(lines):,} line features, "
        f"{total_km:,.0f} km, {frac:.0%} voltage-tagged\n"
        f"Geofabrik ireland-and-northern-ireland extract - EPSG:2157",
        fontsize=10.5, color=INK)
    ax.set_xlabel("ITM easting (m)", fontsize=8, color=INK_MUTED)
    ax.set_ylabel("ITM northing (m)", fontsize=8, color=INK_MUTED)
    ax.tick_params(labelsize=7, colors=INK_MUTED)
    for spine in ax.spines.values():
        spine.set_edgecolor(HAIRLINE)
    ax.set_aspect("equal")

    os.makedirs(OUT_DIR, exist_ok=True)
    png = os.path.join(OUT_DIR, f"{key}_power.png")
    fig.tight_layout()
    fig.savefig(png, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)

    gpkg = os.path.join(OUT_DIR, f"{key}_power.gpkg")
    write_area_gpkg(data, gpkg)
    print(f"  {png}  |  {gpkg}", flush=True)


# --------------------------------------------------------------------------- #
# National map
# --------------------------------------------------------------------------- #

def national_distribution(counties: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Sub-110 kV OSM lines for the Republic, in EPSG:2157.

    Read from the GeoPackage if it is there, and rebuilt from the OSM extract
    if it is not.  The GeoPackage is committed, so the usual case is that this
    map can be redrawn without the 392 MB download - and, because Geofabrik
    republishes the extract continuously, redrawing from the cache is also what
    keeps the figures on this map equal to the ones in FINDINGS.md.
    """
    if os.path.exists(NATIONAL_GPKG):
        return gpd.read_file(NATIONAL_GPKG, layer="lines").to_crs(network.ITM)

    network.ensure_prepared()   # only the rebuild path needs the OSM extract
    lines = network.national_lines().to_crs(network.ITM)
    dist = network.distribution_only(lines)
    # Midpoint containment, not clipping: keeps whole features and avoids
    # slicing every line that crosses a county edge.
    mids = gpd.GeoDataFrame(
        geometry=dist.geometry.interpolate(0.5, normalized=True),
        crs=network.ITM)
    inside = gpd.sjoin(mids, counties[["geometry"]], how="inner",
                       predicate="within")
    dist = dist.loc[dist.index.isin(inside.index)].copy()
    os.makedirs(OUT_DIR, exist_ok=True)
    _write_layer(dist, NATIONAL_GPKG, "lines", replace=True)
    return dist


def plot_national(with_eirgrid: bool = True) -> None:
    """Draw the national map: OSM distribution under EirGrid transmission.

    Scope is the Republic throughout.  ESB Networks is the distribution system
    operator for the Republic and EirGrid the transmission system operator for
    the same area; Northern Ireland is NIE Networks and SONI, and is a
    different dataset with different coverage.
    """
    counties = eirgrid.fetch_counties()
    dist = national_distribution(counties)
    # buffer(0) drops the handful of degenerate LineString slivers the
    # generalised boundaries dissolve into, leaving a clean coastline.
    roi = counties.union_all().buffer(0)

    tx = eirgrid.fetch_transmission() if with_eirgrid else None
    if tx is not None:
        unstyled = sorted(set(tx["kv"]) - set(TX_STYLE))
        if unstyled:
            raise RuntimeError(
                f"EirGrid voltage level(s) with no plot style: {unstyled} kV")

    fig, ax = plt.subplots(figsize=(10.5, 11.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    counties.boundary.plot(ax=ax, color=HAIRLINE, lw=0.5, zorder=1)
    gpd.GeoSeries([roi], crs=network.ITM).boundary.plot(
        ax=ax, color=COAST, lw=0.7, zorder=2)

    # Distribution first, untagged underneath and voltage ascending upward.
    dist_handles = []
    for z, band in enumerate(network.ALL_BANDS):
        sel = dist[dist["band"] == band.label]
        if len(sel) == 0:
            continue
        st = BAND_STYLE[band.id]
        sel.plot(ax=ax, color=st["colour"], lw=st["lw_national"], zorder=3 + z)
        dist_handles.append(Line2D(
            [0], [0], color=st["colour"], lw=2.2,
            label=f"{st['short']}   {sel['length_km'].sum():,.0f} km"))

    # Transmission on top: it is the sparse layer and the authoritative one.
    tx_handles = []
    if tx is not None:
        for z, kv in enumerate(TX_DRAW_ORDER):
            sel = tx[tx["kv"] == kv]
            if len(sel) == 0:
                continue
            st = TX_STYLE[kv]
            for category, dash in (("Overhead Line", None),
                                   ("Underground Cable", (0, (2.2, 1.4)))):
                part = sel[sel["category"] == category]
                if len(part) == 0:
                    continue
                part.plot(ax=ax, color=st["colour"], lw=st["lw"],
                          linestyle="solid" if dash is None else dash,
                          zorder=20 + z)
            tx_handles.append(Line2D(
                [0], [0], color=st["colour"], lw=max(st["lw"], 2.2),
                label=f"{kv} kV   {sel['length_km'].sum():,.0f} km"))
        # Highest voltage reads first, and the dash key sits under the levels
        # it qualifies rather than above them.
        tx_handles.reverse()
        if (tx["category"] == "Underground Cable").any():
            tx_handles.append(Line2D(
                [0], [0], color=INK_SECONDARY, lw=1.6,
                linestyle=(0, (2.2, 1.4)), label="dashed = underground cable"))

    # Two legend blocks, because the two families differ in provenance as well
    # as voltage and that is the more important distinction on this map.
    first = ax.legend(handles=tx_handles, loc="upper left",
                      bbox_to_anchor=(0.0, 1.0), fontsize=8.5, frameon=False,
                      labelcolor=INK_SECONDARY,
                      title="EirGrid transmission  (operator data)",
                      title_fontsize=8.5,
                      handlelength=1.7, borderpad=0.5, labelspacing=0.5)
    first.get_title().set_color(INK_MUTED)
    second = ax.legend(handles=dist_handles[::-1], loc="upper left",
                       bbox_to_anchor=(0.0, 0.845), fontsize=8.5,
                       frameon=False, labelcolor=INK_SECONDARY,
                       title="OpenStreetMap distribution  (crowd-sourced)",
                       title_fontsize=8.5,
                       handlelength=1.7, borderpad=0.5, labelspacing=0.5)
    second.get_title().set_color(INK_MUTED)
    ax.add_artist(first)

    dist_km = float(dist["length_km"].sum())
    tx_km = float(tx["length_km"].sum()) if tx is not None else 0.0
    ax.set_title("Ireland's electricity network\nRepublic of Ireland",
                 fontsize=15, color=INK, loc="left", pad=16)
    ax.text(0.0, 1.005,
            f"EirGrid transmission, 110 kV and above: {tx_km:,.0f} km in "
            "service  ·  "
            f"OpenStreetMap distribution, below 110 kV: {dist_km:,.0f} km "
            "mapped",
            transform=ax.transAxes, fontsize=9, color=INK_SECONDARY,
            va="bottom")
    ax.text(0.0, -0.018,
            "The two layers are not comparable in kind. The transmission "
            "network is EirGrid's own asset register; the distribution network "
            "is crowd-sourced, so its\nblank areas are unmapped, not unserved "
            "- every part of the state is served, and OpenStreetMap holds "
            "about a fifth of what ESB Networks\nreports as 172,000 km of "
            "distribution network. One gap on the EirGrid side: its 400 kV "
            "layer carries only the Moneypoint-Oldstreet leg, so the\n400 kV "
            "backbone east of Oldstreet, to Dunstown and Woodland, is missing "
            "from the published service and therefore from this map.",
            transform=ax.transAxes, fontsize=9, color=INK_SECONDARY, va="top")
    ax.text(0.0, -0.106,
            "EirGrid Transmission Development Plan 2024 web map  ·  "
            "Geofabrik ireland-and-northern-ireland extract  ·  "
            "Ordnance Survey Ireland county boundaries  ·  "
            "EPSG:2157 Irish Transverse Mercator",
            transform=ax.transAxes, fontsize=8, color=INK_MUTED, va="top")

    ax.set_aspect("equal")
    ax.set_axis_off()

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.tight_layout()
    fig.savefig(NATIONAL_PNG, dpi=DPI, facecolor=SURFACE, bbox_inches="tight",
                pad_inches=0.35)
    plt.close(fig)

    print(f"{NATIONAL_PNG}  |  {NATIONAL_GPKG}  |  {eirgrid.CACHE}")
    print(dist.groupby("band")["length_km"].agg(["size", "sum"])
          .round(1).to_string())
    if tx is not None:
        print(tx.groupby(["kv", "category"])["length_km"].agg(["size", "sum"])
              .round(1).to_string())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def run_areas(area: str | None = None) -> None:
    """Draw a map and GeoPackage for each analysis area."""
    keys = [area] if area else [a.key for a in network.AREAS]
    for key in keys:
        print(network.AREAS_BY_KEY[key].label, flush=True)
        plot_area(key)


def run_national(with_eirgrid: bool = True) -> None:
    """Draw the national map of the whole network."""
    plot_national(with_eirgrid=with_eirgrid)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("areas", help=run_areas.__doc__.splitlines()[0])
    a.add_argument("--area", choices=[x.key for x in network.AREAS],
                   help="draw only this area")
    n = sub.add_parser("national", help=run_national.__doc__.splitlines()[0])
    n.add_argument("--no-eirgrid", action="store_true",
                   help="omit the transmission overlay")
    sub.add_parser("all", help="draw every map")
    args = p.parse_args(argv)

    network.quiet()
    if args.cmd == "areas":
        network.ensure_prepared()
        run_areas(args.area)
    elif args.cmd == "national":
        run_national(with_eirgrid=not args.no_eirgrid)
    else:
        network.ensure_prepared()
        run_areas()
        run_national()


if __name__ == "__main__":
    main()
