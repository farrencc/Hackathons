"""Figures for the LaTeX report that the six kit examples do not already draw.

    python docs/report_figures.py

Three of them:

  g_geocoding   where the 110 kV-and-above buses ended up, coloured by how
                each one was matched, with the failures marked
  h_correlation the measured wind correlation against distance, against the
                exponential the field was built with - the single check that
                says the synthetic profiles are not independent noise
  i_northwest   the 15-node North-West region as a graph, with the boundary

Everything else in the report is a kit figure, drawn by examples/a..f.
"""

from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "participant-kit"))
import plotstyle                                          # noqa: E402
import psse                                               # noqa: E402
import pypsa_net                                          # noqa: E402
import synthetic                                          # noqa: E402
import northwest                                          # noqa: E402
import gridkit                                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures")
CASE = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"

#: How each match was made, in decreasing confidence.  Grouped, because ten
#: categorical slots is more than a reader can hold and the distinctions
#: between "prefix" and "truncated" are not the point of the picture.
METHOD_GROUPS = (
    ("exact name", ("exact", "exact-name"), plotstyle.CATEGORICAL[0]),
    ("name contraction", ("ni-code", "ni-site", "truncated", "prefix"),
     plotstyle.CATEGORICAL[2]),
    ("fuzzy or by hand", ("fuzzy", "alias"), plotstyle.CATEGORICAL[3]),
    ("placed via a coupler", ("coupled",), plotstyle.CATEGORICAL[6]),
)


def geocoding():
    """Where the buses landed, and how each was matched."""
    # One row per bus at 110 kV and above; `station` repeats across a
    # station's busbar sections, which is why the cross-check dedupes on it.
    frame = pd.read_csv("data/pypsa/geocoding/TYTFS2024_WP2024_V35.csv")
    placed = frame[frame["lat"].notna()]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.6, 5.6),
                                      width_ratios=(1.25, 1.0))
    for ax in (left, right):
        ax.set_axisbelow(True)

    for label, methods, colour in METHOD_GROUPS:
        block = placed[placed["method"].isin(methods)]
        left.scatter(block["lon"], block["lat"], s=22, color=colour,
                     linewidths=0.4, edgecolors=plotstyle.SURFACE,
                     label=f"{label} ({len(block)})", zorder=3)
    left.set_aspect(1 / np.cos(np.radians(float(placed["lat"].mean()))))
    left.set_xticks([]); left.set_yticks([]); left.grid(False)
    for spine in left.spines.values():
        spine.set_visible(False)
    left.legend(loc="upper left", fontsize=7)
    left.set_title(f"{len(placed)} of {len(frame)} buses placed "
                   f"({len(placed) / len(frame):.0%}), "
                   f"{placed['station'].nunique()} of "
                   f"{frame['station'].nunique()} stations", fontsize=10)

    # The cross-check, as a distribution rather than three numbers.
    check = _crosscheck(placed)
    if check is not None and len(check):
        metres = np.sort(check * 1000.0)
        share = np.arange(1, len(metres) + 1) / len(metres) * 100.0
        right.step(metres, share, where="post",
                   color=plotstyle.CATEGORICAL[0], linewidth=2.0)
        right.set_xscale("log")
        median = float(np.median(metres))
        right.axvline(median, color=plotstyle.INK_MUTED, linewidth=1.0,
                      linestyle=(0, (4, 2)))
        right.annotate(f"median {median:,.0f} m", (median, 8),
                       xytext=(8, 0), textcoords="offset points",
                       fontsize=8, color=plotstyle.INK)
        right.set_xlabel("distance from EirGrid's own register (metres, log)")
        right.set_ylabel("% of the cross-checked stations within")
        right.set_ylim(0, 101)
        right.set_title(f"cross-check against EirGrid's own register: "
                        f"{len(metres)} stations", fontsize=10)
    else:
        right.set_axis_off()

    fig.tight_layout()
    return _save(fig, "g_geocoding")


def _crosscheck(placed: pd.DataFrame):
    """Great-circle distance to EirGrid's own station layer.

    Reuses ``geocode.crosscheck`` rather than reimplementing the join - the
    report should be measuring the same thing the code measures.
    """
    try:
        import geocode
        one_per_station = placed.drop_duplicates("station")
        return geocode.crosscheck(one_per_station)["distance_km"].to_numpy()
    except Exception as problem:                             # noqa: BLE001
        print(f"    cross-check unavailable: {problem}")
        return None


def _km(lat0, lon0, lat1, lon1):
    radius, degree = 6371.0088, np.pi / 180.0
    dlat, dlon = (lat1 - lat0) * degree, (lon1 - lon0) * degree
    h = (np.sin(dlat / 2) ** 2 + np.cos(lat0 * degree) * np.cos(lat1 * degree)
         * np.sin(dlon / 2) ** 2)
    return float(2 * radius * np.arcsin(np.sqrt(np.clip(h, 0, 1))))


def correlation():
    """Measured wind correlation against distance, versus the target."""
    case = psse.read_raw(CASE)
    result = synthetic.build(case, year=2030, seed=synthetic.SEED)
    table = synthetic.spatial_check(result)

    sites = result["sites"]
    wind = sites[(sites["cell"] != "") & (sites["carrier"] == "wind")]
    cells = wind.drop_duplicates("cell").reset_index(drop=True)
    values = result["p_max_pu"][cells["generator"].to_numpy()].to_numpy()
    r = np.corrcoef(values, rowvar=False)
    d = synthetic.distance_matrix(cells["lat"].to_numpy(),
                                  cells["lon"].to_numpy())
    upper = np.triu_indices(len(cells), k=1)

    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    ax.set_axisbelow(True)
    ax.scatter(d[upper], r[upper], s=3, color=plotstyle.CATEGORICAL[0],
               alpha=0.10, linewidths=0, label=f"{len(upper[0]):,} site pairs")
    grid = np.linspace(0, float(d[upper].max()), 200)
    ax.plot(grid, np.exp(-grid / synthetic.WIND_CORRELATION_KM),
            color=plotstyle.INK, linewidth=2.0,
            label=f"exp(-d / {synthetic.WIND_CORRELATION_KM:.0f} km), "
                  f"the field it was built from")
    middle = 0.5 * (table["km_from"] + table["km_to"])
    ax.plot(middle, table["measured_correlation"], marker="o", markersize=7,
            color=plotstyle.STATUS["serious"], linewidth=2.0,
            label="measured, binned")
    ax.set_xlabel("distance between sites (km)")
    ax.set_ylabel("correlation of hourly capacity factor")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(0, float(d[upper].max()))
    ax.legend(loc="upper right")
    ax.set_title("Synthetic wind: correlation falls with distance, as built")
    fig.tight_layout()
    return _save(fig, "h_correlation")


def north_west():
    """The 15-node region, its circuits, and where the power leaves."""
    n = gridkit.load("WP2033", "north-west")
    placed = gridkit.placed_buses(n)
    generation = n.generators[
        ~n.generators["carrier"].isin(("boundary", "load shedding"))]
    capacity = generation.groupby("bus")["p_nom"].sum().reindex(
        placed.index).fillna(0.0)
    demand = n.loads.groupby("bus")["p_set"].sum().reindex(
        placed.index).fillna(0.0)

    fig, ax = plt.subplots(figsize=(7.6, 7.2))
    for _, line in n.lines.iterrows():
        if line["bus0"] in placed.index and line["bus1"] in placed.index:
            ax.plot([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]],
                    [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]],
                    color=plotstyle.INK_MUTED, linewidth=1.0, zorder=1)
    ax.scatter(placed["x"], placed["y"],
               s=30 + 260 * capacity / max(capacity.max(), 1e-9),
               color=plotstyle.CARRIER_COLOURS["wind"], zorder=3,
               linewidths=0.6, edgecolors=plotstyle.SURFACE,
               label="generation capacity")
    with_load = demand[demand > 0].index
    ax.scatter(placed.loc[with_load, "x"], placed.loc[with_load, "y"],
               s=18 + 160 * demand[with_load] / max(demand.max(), 1e-9),
               facecolors="none", edgecolors=plotstyle.STATUS["serious"],
               linewidths=1.6, zorder=4, label="demand")
    slack = northwest.SLACK_STATION
    if slack in placed.index:
        ax.scatter([placed.at[slack, "x"]], [placed.at[slack, "y"]],
                   marker="s", s=120, color=plotstyle.INK, zorder=5,
                   label=f"boundary / reference ({slack})")
    _label_without_collisions(fig, ax, placed)

    ax.set_aspect(1 / np.cos(np.radians(float(placed["y"].mean()))))
    margin = 0.30
    ax.set_xlim(placed["x"].min() - margin, placed["x"].max() + margin)
    ax.set_ylim(placed["y"].min() - margin, placed["y"].max() + margin)
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title(f"The North-West region: {len(placed)} nodes, "
                 f"{len(n.lines)} circuits\n"
                 f"{capacity.sum():,.0f} MW of plant against "
                 f"{demand.sum():,.0f} MW of demand - it exports",
                 fontsize=11)
    fig.tight_layout()
    return _save(fig, "i_northwest")


def _label_without_collisions(fig, ax, points, fontsize=7):
    """Place one label per point, taking the first offset that does not clash.

    Fifteen labels on a graph this tight collide if they all sit above their
    node, and pushing them away from the centroid is not enough where two
    nodes are neighbours - Clogher and Croaghonagh land on top of each other
    either way.  So each label tries eight positions around its node and keeps
    the first whose drawn box misses every label already placed.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    offsets = [(0, 12), (0, -12), (14, 0), (-14, 0),
               (11, 9), (-11, 9), (11, -9), (-11, -9)]
    # Seed with the nodes themselves, so a label never lands on a marker.
    taken = []
    for _, row in points.iterrows():
        x, y = ax.transData.transform((row["x"], row["y"]))
        taken.append(Bbox.from_bounds(x - 9, y - 9, 18, 18))
    for name, row in points.iterrows():
        for dx, dy in offsets:
            text = ax.annotate(
                name, (row["x"], row["y"]), xytext=(dx, dy),
                textcoords="offset points", fontsize=fontsize,
                ha="left" if dx > 0 else ("right" if dx < 0 else "center"),
                va="bottom" if dy > 0 else ("top" if dy < 0 else "center"),
                color=plotstyle.INK_SOFT)
            box = text.get_window_extent(renderer=renderer).expanded(1.05, 1.15)
            if not any(box.overlaps(other) for other in taken):
                taken.append(box)
                break
            text.remove()
        else:                       # nowhere clear - put it back on top
            taken.append(ax.annotate(
                name, (row["x"], row["y"]), xytext=(0, 12),
                textcoords="offset points", fontsize=fontsize, ha="center",
                color=plotstyle.INK_SOFT).get_window_extent(renderer=renderer))


def lengths():
    """Are the TYTFS line lengths real?  Check them against the geocoding.

    This figure exists because the first draft of the report asserted that the
    lengths were placeholders.  They are not: 83% of transmission branches
    carry one, and where both ends are independently geocoded the stated
    length tracks the great-circle distance closely.  Two datasets that share
    no source agreeing is the strongest evidence available here - and it
    checks the geocoding as much as it checks the lengths.
    """
    geo = pd.read_csv("data/pypsa/geocoding/TYTFS2024_WP2024_V35.csv")
    geo = geo[geo["lat"].notna()]
    lat = dict(zip(geo["bus"].astype(int), geo["lat"]))
    lon = dict(zip(geo["bus"].astype(int), geo["lon"]))

    case = psse.read_raw(CASE)
    kv = dict(zip(case.bus["I"].astype(int), case.bus["BASKV"]))
    branch = case.branch.copy()
    branch["kv0"] = branch["I"].astype(int).map(kv)
    branch["kv1"] = branch["J"].astype(int).map(kv)
    branch = branch[(branch["kv0"] >= 110) & (branch["kv1"] >= 110)
                    & (branch["LEN"] > 0)]

    rows = []
    for _, r in branch.iterrows():
        i, j = int(r["I"]), int(r["J"])
        if i in lat and j in lat:
            d = _km(lat[i], lon[i], lat[j], lon[j])
            if d > 0.5:                       # same-site pairs say nothing
                rows.append({"stated": float(r["LEN"]), "straight": d,
                             "kv": float(r["kv0"]),
                             "ohm_per_km": pypsa_net._ohms(float(r["X"]),
                                                           float(r["kv0"]))
                             / float(r["LEN"])})
    frame = pd.DataFrame(rows)

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.8))
    for ax in (left, right):
        ax.set_axisbelow(True)

    left.scatter(frame["straight"], frame["stated"], s=14,
                 color=plotstyle.CATEGORICAL[0], alpha=0.6, linewidths=0)
    top = float(max(frame["straight"].max(), frame["stated"].max())) * 1.05
    left.plot([0, top], [0, top], color=plotstyle.INK_MUTED, linewidth=1.0,
              linestyle=(0, (4, 2)), zorder=0)
    left.set_xlim(0, top); left.set_ylim(0, top)
    left.set_xlabel("great-circle distance between the geocoded ends (km)")
    left.set_ylabel("length stated in the TYTFS file (km)")
    left.set_title(f"{len(frame)} circuits: r = "
                   f"{frame['stated'].corr(frame['straight']):.3f}", fontsize=10)
    left.annotate("dashed line is a perfectly straight route;\n"
                  "real circuits sit above it",
                  (0.04, 0.95), xycoords="axes fraction", va="top",
                  fontsize=8, color=plotstyle.INK_SOFT)

    per_km = frame[frame["kv"] == 110.0]["ohm_per_km"]
    right.hist(per_km, bins=np.linspace(0, 0.8, 41),
               color=plotstyle.CATEGORICAL[0])
    median = float(per_km.median())
    right.axvline(median, color=plotstyle.STATUS["serious"], linewidth=1.8)
    right.annotate(f"median {median:.3f} $\\Omega$/km",
                   (median, right.get_ylim()[1] * 0.92), xytext=(8, 0),
                   textcoords="offset points", fontsize=9,
                   color=plotstyle.INK)
    right.set_xlabel("reactance per km of stated length, 110 kV circuits "
                     "($\\Omega$/km)")
    right.set_ylabel("circuits")
    right.set_title("impedance and length are consistent with each other",
                    fontsize=10)

    fig.tight_layout()
    return _save(fig, "j_lengths")


def _save(fig, stem):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{stem}.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"-> {path}")
    return path


def main() -> int:
    plotstyle.use()
    gridkit.quiet()
    geocoding()
    lengths()
    correlation()
    north_west()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
