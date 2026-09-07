"""
Build every figure for the project from the data in folders 02, 03 and 04.

Colours come from a validated categorical palette (checked for colourblind
separation, lightness band and chroma floor). Three of its slots sit below 3:1
contrast on the light surface, so every chart carries visible labels or a legend
rather than relying on colour alone.

One rule worth stating because it is the most common charting error: no chart
here uses two y-axes. Where two measures have different scales they get two
panels, not two scales.

Output: one PNG per figure, in 07-figures/charts/.
"""
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# This script lives in 07-figures/scripts/. Charts are written to 07-figures/charts/,
# and every input comes from another folder's script-output.
FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
CHARTS = FOLDER / "charts"

ANA = ROOT / "08-analysis" / "script-output"
CURT = ROOT / "02-curtailment" / "script-output"
NET = ROOT / "03-network" / "script-output"
MET = ROOT / "04-meteorology" / "script-output"

# Validated categorical palette (light surface #fcfcfb).
C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100",
     "magenta": "#e87ba4", "green": "#008300", "violet": "#4a3aa7", "red": "#e34948"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e2e1dd"


def style(ax, title, xlabel="", ylabel=""):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=12.5, fontweight="600", loc="left", pad=12)
    ax.set_xlabel(xlabel, color=INK2, fontsize=10)
    ax.set_ylabel(ylabel, color=INK2, fontsize=10)
    ax.tick_params(colors=INK2, labelsize=9.5, length=0)
    ax.grid(True, color=GRID, linewidth=0.8, axis="y")
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def save(fig, name, note=""):
    if note:
        fig.text(0.01, 0.005, note, color=INK2, fontsize=8, va="bottom")
    fig.savefig(CHARTS / name, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"  wrote {name}")


def load_dd():
    with open(CURT / "dispatch-down-by-reason-monthly.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["is_month"] == "yes"]


def annual(dd, region, metric):
    out = {}
    for r in dd:
        if r["region"] == region and r["metric"] == metric:
            out[r["year"]] = out.get(r["year"], 0) + float(r["mwh"])
    return out


def fig_dispatch_down_trend(dd):
    """Change over time, three regions -> lines, each directly labelled."""
    fig, ax = plt.subplots(figsize=(9, 5))
    series = [("All Island Wind", "All-island", C["blue"]),
              ("Ireland Wind", "Ireland", C["orange"]),
              ("Northern Ireland Wind", "Northern Ireland", C["aqua"])]
    for region, label, colour in series:
        av = annual(dd, region, "Availability")
        ddn = annual(dd, region, "Dispatch Down")
        yrs = sorted(y for y in av if av[y] > 0)
        pct = [100 * ddn.get(y, 0) / av[y] for y in yrs]
        x = [int(y) for y in yrs]
        ax.plot(x, pct, color=colour, linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.2, label=label)
        ax.annotate(f"{label}  {pct[-1]:.1f}%", (x[-1], pct[-1]),
                    textcoords="offset points", xytext=(8, 0), va="center",
                    color=INK, fontsize=9.5, fontweight="600")
    style(ax, "Wind dispatch-down is rising, and Northern Ireland is worst hit",
          "", "% of available wind not used")
    ax.set_xlim(2015.6, 2028.6)
    ax.set_xticks(list(range(2016, 2027, 2)))   # no ticks past the data
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="upper left")
    save(fig, "01-dispatch-down-trend.png",
         "2026 is a partial year (Jan-Jul). Source: EirGrid DD Summary Report V21.")


def fig_roi_split(dd):
    """Composition over time -> stacked bars with a surface gap between segments."""
    av = annual(dd, "Ireland Wind", "Availability")
    con = annual(dd, "Ireland Wind", "Constraints")
    cur = annual(dd, "Ireland Wind", "Curtailments")
    yrs = sorted(y for y in av if av[y] > 0)
    x = np.arange(len(yrs))
    c = np.array([100 * con.get(y, 0) / av[y] for y in yrs])
    u = np.array([100 * cur.get(y, 0) / av[y] for y in yrs])

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x, c, width=0.62, color=C["blue"], label="Constraint (local network)")
    ax.bar(x, u, width=0.62, bottom=c + 0.06, color=C["orange"],
           label="Curtailment (system-wide)")
    for i in range(len(yrs)):
        ax.text(i, c[i] + u[i] + 0.35, f"{c[i] + u[i]:.1f}", ha="center",
                color=INK, fontsize=9, fontweight="600")
    style(ax, "In Ireland, local constraint overtook system-wide curtailment in 2025",
          "", "% of available wind")
    ax.set_xticks(x)
    ax.set_xticklabels(yrs)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="upper left")
    save(fig, "02-ireland-curtailment-vs-constraint.png",
         "2026 is a partial year (Jan-Jul). Source: EirGrid DD Summary Report V21.")


def fig_curtailment_causes(dd):
    """Which limit actually binds -> stacked shares of curtailment."""
    parts = [("High Freq / Min Gen", "Minimum units online (MUON)", C["blue"]),
             ("SNSP Issue", "SNSP limit", C["orange"]),
             ("ROCOF / Inertia", "RoCoF / inertia", C["aqua"])]
    tot = annual(dd, "All Island Wind", "Curtailments")
    yrs = sorted(y for y in tot if tot[y] > 0)
    x = np.arange(len(yrs))
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = np.zeros(len(yrs))
    for metric, label, colour in parts:
        v = annual(dd, "All Island Wind", metric)
        share = np.array([100 * v.get(y, 0) / tot[y] for y in yrs])
        ax.bar(x, share, width=0.62, bottom=bottom, color=colour, label=label)
        bottom += share + 0.06
    style(ax, "Minimum-units-online drives curtailment; the SNSP cap is a small share",
          "", "% of all-island curtailment")
    ax.set_xticks(x)
    ax.set_xticklabels(yrs)
    ax.set_ylim(0, 112)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="lower left", ncol=3)
    save(fig, "03-curtailment-causes.png",
         "Share of CURTAILMENT only, not of total dispatch-down. Source: EirGrid DD Summary Report V21.")


def fig_snsp():
    """One distribution -> histogram, single hue, limit marked."""
    with open(CURT / "system-state-15min-2026.csv", encoding="utf-8") as f:
        v = [float(r["SNSP"]) * 100 for r in csv.DictReader(f) if r["SNSP"]]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(v, bins=60, color=C["blue"], edgecolor=SURFACE, linewidth=0.5)
    top = ax.get_ylim()[1]
    ax.axvline(75, color=C["red"], linewidth=2)
    ax.annotate("75% operational limit", (75, top * 0.92), xytext=(-10, 0),
                textcoords="offset points", ha="right", color=C["red"],
                fontsize=9.5, fontweight="600")
    mean = float(np.mean(v))
    ax.axvline(mean, color=INK2, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.annotate(f"mean {mean:.1f}%", (mean, top * 0.72), xytext=(8, 0),
                textcoords="offset points", color=INK, fontsize=9.5, fontweight="600")
    style(ax, "The system runs well below its SNSP ceiling most of the time",
          "System Non-Synchronous Penetration (%)", "quarter-hours")
    save(fig, "04-snsp-distribution.png",
         "All-island, 15-min resolution, Jan-Jul 2026. Source: EirGrid System Data Qtr Hourly V7.")


def fig_correlation():
    """Two seasons -> two labelled series on one axis."""
    with open(MET / "wind-farm-row-order.csv", encoding="utf-8") as f:
        names = [r["farm"] for r in csv.DictReader(f)]
    with open(MET / "wind-farms-with-coordinates.csv", encoding="utf-8") as f:
        rows = {r["farm"]: r for r in csv.DictReader(f)}
    lat = np.radians([float(rows[n]["lat"]) for n in names])
    lon = np.radians([float(rows[n]["lon"]) for n in names])
    dla = lat[:, None] - lat[None, :]
    dlo = lon[:, None] - lon[None, :]
    a = np.sin(dla / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlo / 2) ** 2
    D = 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    iu = np.triu_indices(len(names), k=1)

    fig, ax = plt.subplots(figsize=(9, 5))
    bands = [(0, 10), (10, 25), (25, 50), (50, 100), (100, 150), (150, 200), (200, 400)]
    mids = [(lo + hi) / 2 for lo, hi in bands]
    for tag, label, colour in [("2025-07", "July 2025 (summer)", C["orange"]),
                               ("2025-01", "January 2025 (winter)", C["blue"])]:
        W = np.load(MET / f"wind-speed-100m-{tag}.npy")
        Cm = np.corrcoef(W)
        d, c = D[iu], Cm[iu]
        y = [float(c[(d >= lo) & (d < hi)].mean()) for lo, hi in bands]
        ax.plot(mids, y, color=colour, linewidth=2, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.2, label=label)
        ax.annotate(f"{label.split(' ')[0]}  {y[-1]:.2f}", (mids[-1], y[-1]),
                    textcoords="offset points", xytext=(9, 0), va="center",
                    color=INK, fontsize=9.5, fontweight="600")
    style(ax, "Irish wind stays correlated across the whole island, more so in winter",
          "distance between farms (km)", "correlation of hourly wind speed")
    ax.set_ylim(0.4, 1.02)
    ax.set_xlim(0, 340)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="lower left")
    save(fig, "05-wind-correlation-by-distance.png",
         "Pairs under 30 km share an ERA5 grid cell (~28 km), so their correlation is partly an artefact.")


def fig_power_curve():
    """A transfer function -> single line, regions annotated."""
    sys.path.insert(0, str(ROOT / "04-meteorology" / "scripts"))
    from wind_power import power_curve
    v = np.linspace(0, 30, 600)
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.plot(v, power_curve(v) * 100, color=C["blue"], linewidth=2)
    for x, lab in [(3, "cut-in 3 m/s"), (12, "rated 12 m/s"), (25, "cut-out 25 m/s")]:
        ax.axvline(x, color=GRID, linewidth=1.2)
        ax.annotate(lab, (x, 105), ha="center", color=INK2, fontsize=9)
    ax.annotate("output rises as v³", (7.0, 36), color=INK, fontsize=9.5, fontweight="600")
    style(ax, "The power curve: a small wind change is a large power change",
          "wind speed at hub height (m/s)", "% of rated capacity")
    ax.set_ylim(0, 118)
    ax.set_xlim(0, 30)
    save(fig, "06-turbine-power-curve.png",
         "Generic IEC-style curve, not the real turbine at each site.")


def fig_farm_map():
    """Geography -> one map, marker area encodes capacity."""
    with open(NET / "farm-to-constraint-group-map.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fig, ax = plt.subplots(figsize=(7.4, 8.4))
    for matched, colour, label in [("no", "#b7d3f6", "not matched to model"),
                                   ("yes", C["blue"], "matched to network model")]:
        s = [r for r in rows if r["matched"] == matched]
        ax.scatter([float(r["lon"]) for r in s], [float(r["lat"]) for r in s],
                   s=[max(float(r["mec_mw"]), 1) * 2.2 for r in s],
                   c=colour, alpha=0.82, edgecolors=SURFACE, linewidths=0.7,
                   label=f"{label} ({len(s)})")
    style(ax, "313 connected wind farms, sized by capacity",
          "longitude", "latitude")
    ax.grid(True, color=GRID, linewidth=0.8, axis="both")
    ax.set_aspect(1 / np.cos(np.radians(53.4)))
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="upper left",
              scatterpoints=1)
    save(fig, "07-wind-farm-map.png",
         "Locations are SEAI connection substations, not turbine sites. Source: SEAI, CC BY 4.0.")


def fig_groups_by_region():
    """Counts by category -> horizontal bars, values labelled."""
    with open(NET / "constraint-groups-to-stations.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    order = ["ROI-SW", "ROI-W", "ROI-NW", "NI", "ROI-SE", "ROI-NE", "ROI-ALL"]
    names = {"ROI-SW": "South West", "ROI-W": "West", "ROI-NW": "North West",
             "NI": "Northern Ireland", "ROI-SE": "South East",
             "ROI-NE": "North East", "ROI-ALL": "Nationwide"}
    groups, stations = {}, {}
    for r in rows:
        groups.setdefault(r["region"], set()).add(r["group_id"])
        if r["station"]:
            stations.setdefault(r["region"], set()).add(r["station"])
    y = np.arange(len(order))
    n = [len(groups.get(k, ())) for k in order]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(y, n, height=0.6, color=C["blue"])
    for i, k in enumerate(order):
        ax.text(n[i] + 0.2, i, f"{n[i]} groups, {len(stations.get(k, ()))} stations",
                va="center", color=INK, fontsize=9.5)
    style(ax, "Constraint groups cluster in the windy, weakly connected west",
          "number of constraint groups", "")
    ax.set_yticks(y)
    ax.set_yticklabels([names[k] for k in order])
    ax.invert_yaxis()
    ax.grid(True, color=GRID, linewidth=0.8, axis="x")
    ax.set_xlim(0, max(n) * 1.75)
    save(fig, "08-constraint-groups-by-region.png",
         "41 sections = 39 numbered groups (South West group 3 splits into 3a/3b/3c). Source: EirGrid WDT Overview, 1 Feb 2024.")


def fig_forecast():
    """A single series over time -> filled line."""
    with open(MET / "wind-forecast-7day.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    mw = [float(r["fleet_mw"]) for r in rows]
    x = np.arange(len(mw))
    fig, ax = plt.subplots(figsize=(9.4, 4.6))
    ax.fill_between(x, mw, color=C["blue"], alpha=0.18)
    ax.plot(x, mw, color=C["blue"], linewidth=2)
    style(ax, "Forecast wind output for the hackathon week",
          "date (UTC)", "fleet output (MW)")
    ticks = list(range(0, len(mw), 24))
    ax.set_xticks(ticks)
    ax.set_xticklabels([rows[i]["time_utc"][5:10] for i in ticks])
    ax.set_xlim(0, len(mw) - 1)
    ax.annotate(f"peak {max(mw):.0f} MW", (int(np.argmax(mw)), max(mw)),
                textcoords="offset points", xytext=(0, 8), ha="center",
                color=INK, fontsize=9.5, fontweight="600")
    save(fig, "09-wind-forecast-7day.png",
         "A real forecast, not reanalysis. Generic power curve, so treat the shape as the signal. Source: Open-Meteo.")


def fig_duration_curve():
    """Two measures in the same units -> one axis, two sorted series."""
    with open(CURT / "system-state-15min-2026.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r["AI Wind Availability"] and r["AI Wind Generation"]]
    av = np.sort(np.array([float(r["AI Wind Availability"]) for r in rows]))[::-1]
    gen = np.sort(np.array([float(r["AI Wind Generation"]) for r in rows]))[::-1]
    x = 100 * np.arange(len(av)) / len(av)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(x, av, color=C["blue"], linewidth=2, label="wind available")
    ax.plot(x, gen, color=C["orange"], linewidth=2, label="wind actually generated")
    ax.fill_between(x, gen, av, color=C["orange"], alpha=0.16)
    lost = (av.sum() - gen.sum()) / av.sum() * 100
    ax.annotate(f"the gap is dispatch-down:\n{lost:.1f}% of available wind",
                (22, (av[len(av) // 6] + gen[len(gen) // 6]) / 2),
                color=INK, fontsize=10, fontweight="600")
    style(ax, "Duration curve: available wind against what the system actually took",
          "% of time at or above this level", "all-island wind (MW)")
    ax.set_xlim(0, 100)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="upper right")
    save(fig, "10-wind-duration-curve.png",
         "Both curves sorted independently, so this shows the volume gap, not paired hours. Jan-Jul 2026.")


def fig_validation():
    """Model against observation -> scatter plus a 1:1 line, one hue."""
    with open(MET / "model-vs-eirgrid-hourly-2026.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    mod = np.array([float(r["modelled_mw"]) for r in rows])
    act = np.array([float(r["eirgrid_observed_mw"]) for r in rows])
    r = float(np.corrcoef(mod, act)[0, 1])

    fig, ax = plt.subplots(figsize=(7.6, 7.4))
    ax.scatter(act, mod, s=5, c=C["blue"], alpha=0.13, edgecolors="none")
    lim = max(act.max(), mod.max()) * 1.04
    ax.plot([0, lim], [0, lim], color=INK2, linewidth=1.4, linestyle=(0, (5, 4)))
    ax.annotate("perfect agreement", (lim * 0.72, lim * 0.75), rotation=39,
                color=INK2, fontsize=9.5, ha="center")
    ax.annotate(f"r² = {r**2:.3f}\n{len(rows):,} hours\nbias −3.8%",
                (lim * 0.06, lim * 0.84), color=INK, fontsize=11, fontweight="600")
    style(ax, "ERA5 wind plus a generic power curve reproduces EirGrid's own data",
          "EirGrid measured availability (MW)", "our modelled availability (MW)")
    ax.grid(True, color=GRID, linewidth=0.8, axis="both")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_aspect("equal")
    save(fig, "11-model-vs-eirgrid-measured.png",
         "Hourly, Ireland only, Jan-Jul 2026. Availability (pre-curtailment), so this tests the weather-to-power model alone.")


def fig_groups_vs_weather():
    """Two comparable measures, same units -> paired bars per group."""
    with open(ANA / "groups-vs-weather-test.csv", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: float(r["mean_distance_km"]))
    lab = [r["group_id"] for r in rows]
    obs = np.array([float(r["observed_corr"]) for r in rows])
    pred = np.array([float(r["predicted_from_distance"]) for r in rows])
    y = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.barh(y - 0.19, pred, height=0.34, color="#b7d3f6",
            label="predicted from distance alone")
    ax.barh(y + 0.19, obs, height=0.34, color=C["blue"],
            label="observed within the group")
    for i, r in enumerate(rows):
        ax.text(obs[i] + 0.008, i + 0.19, f"{obs[i]:.3f}", va="center",
                color=INK, fontsize=8.5)
    style(ax, "Constraint groups are no more wind-correlated than distance predicts",
          "mean pairwise wind correlation", "")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{l}  ({r['n_farms']} farms)" for l, r in zip(lab, rows)])
    ax.invert_yaxis()
    ax.grid(True, color=GRID, linewidth=0.8, axis="x")
    ax.set_xlim(0.6, 1.06)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="lower right")
    save(fig, "12-groups-vs-weather-test.png",
         "Groups ordered by how spread out they are. Mean residual -0.019: the grouping adds no weather information beyond proximity.")


def fig_weather_vs_effectiveness():
    """Two tests of the same groups -> paired bars, one axis, same statistic scale."""
    with open(ANA / "groups-vs-effectiveness-test.csv", encoding="utf-8") as f:
        eff = {r["group_id"]: r for r in csv.DictReader(f)}
    with open(ANA / "groups-vs-weather-test.csv", encoding="utf-8") as f:
        wea = {r["group_id"]: r for r in csv.DictReader(f)}
    ids = [g for g in eff if g in wea]
    ids.sort(key=lambda g: -float(eff[g]["excess"]))

    e = np.array([float(eff[g]["excess"]) for g in ids])
    w = np.array([float(wea[g]["residual"]) for g in ids])
    y = np.arange(len(ids))

    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.barh(y - 0.19, w, height=0.34, color="#b7d3f6",
            label="weather: excess over a distance-only prediction")
    ax.barh(y + 0.19, e, height=0.34, color=C["blue"],
            label="effectiveness: excess over random farm sets")
    for i in range(len(ids)):
        ax.text(e[i] + 0.012, i + 0.19, f"{e[i]:+.2f}", va="center",
                color=INK, fontsize=8.5)
    ax.axvline(0, color=INK2, linewidth=1.2)
    style(ax, "Constraint groups encode electrical effectiveness, not weather",
          "how much more alike group members are than the null", "")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{g}  ({eff[g]['n_farms']} farms)" for g in ids])
    ax.invert_yaxis()
    ax.grid(True, color=GRID, linewidth=0.8, axis="x")
    ax.set_xlim(-0.12, 1.12)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="lower right")
    save(fig, "13-weather-vs-effectiveness.png",
         "Same groups, same null-model method, two different properties. 11 of 12 groups are significantly coherent in effectiveness; 1 of 12 in weather.")


def fig_clustering_options():
    """Two metrics, same scale, three methods -> grouped bars plus a reference line."""
    with open(ANA / "clustering-options-scores.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    lab = [r["method"] for r in rows]
    om = np.array([float(r["omega_index"]) for r in rows])
    f1 = np.array([float(r["best_match_f1"]) for r in rows])
    x = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    ax.bar(x - 0.19, f1, width=0.34, color=C["blue"],
           label="best-match F1: are individual groups found?")
    ax.bar(x + 0.19, om, width=0.34, color=C["orange"],
           label="omega index: is the overlap structure reproduced?")
    for i in range(len(rows)):
        ax.text(i - 0.19, f1[i] + 0.015, f"{f1[i]:.2f}", ha="center",
                color=INK, fontsize=9, fontweight="600")
        ax.text(i + 0.19, max(om[i], 0) + 0.015, f"{om[i]:.2f}", ha="center",
                color=INK, fontsize=9, fontweight="600")
    ax.axhline(1.0, color=INK2, linewidth=1.4, linestyle=(0, (5, 4)))
    ax.annotate("the real answer scores 1.0 on both", (len(rows) - 0.5, 1.0),
                xytext=(0, 6), textcoords="offset points", ha="right",
                color=INK2, fontsize=9)
    style(ax, "Groups are electrically coherent, but not yet reconstructable",
          "", "score against EirGrid's real groups")
    ax.set_xticks(x)
    ax.set_xticklabels([l.replace(" (", "\n(") for l in lab], fontsize=9)
    ax.set_ylim(-0.12, 1.16)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9.5, loc="upper left")
    save(fig, "14-clustering-options.png",
         "F1 finds groups moderately well; omega near zero says the overlap structure is not captured. Decisions D1 and D2 remain open.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    dd = load_dd()
    print("building figures:")
    fig_dispatch_down_trend(dd)
    fig_roi_split(dd)
    fig_curtailment_causes(dd)
    fig_snsp()
    fig_correlation()
    fig_power_curve()
    fig_farm_map()
    fig_groups_by_region()
    fig_forecast()
    fig_duration_curve()
    fig_validation()
    fig_groups_vs_weather()
    fig_weather_vs_effectiveness()
    fig_clustering_options()
    print("done")


if __name__ == "__main__":
    main()
