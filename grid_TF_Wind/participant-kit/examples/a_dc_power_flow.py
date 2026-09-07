"""(a) DC power flow, and a map of where the power goes.

    python examples/a_dc_power_flow.py [SCENARIO] [SCOPE]

Runs PyPSA's linear power flow over the week the network ships with, and draws
the transmission map with each circuit coloured by how loaded it is.  Writes
``figures/a_flow_map_<scenario>_<scope>.png``.

A DC power flow does not optimise anything - it takes the dispatch as given and
tells you where the flow ends up.  That is what makes it the right first thing
to run: if the picture is wrong here, nothing downstream will be right.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gridkit
import plotstyle

FIGURES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "figures")


def main(scenario="WP2033", scope="all-island"):
    plotstyle.use()
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    print(gridkit.summary(n).to_string(), "\n")

    # A power flow needs a dispatch.  Get one from the optimisation, freeze it
    # into p_set, then flow it - freeze_dispatch explains why that middle step
    # is not optional and what it looks like when you skip it.
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    loading = gridkit.line_loading(n)
    peak = n.loads_t.p_set.sum(axis=1).idxmax()
    print(f"peak demand at {peak}: "
          f"{n.loads_t.p_set.loc[peak].sum():,.0f} MW")

    worst = loading.max().sort_values(ascending=False)
    print("\nmost loaded circuits, over the week")
    table = pd.DataFrame({
        "max_loading": worst.head(10).round(3),
        "s_nom_mva": n.lines.loc[worst.head(10).index, "s_nom"].round(0),
        "hours_at_rating": (loading[worst.head(10).index] >= 0.999).sum(),
    })
    print(table.to_string())

    _draw(n, loading.loc[peak], scenario, scope, peak)
    return 0


def _draw(n, loading, scenario, scope, snapshot):
    """The map: circuits coloured by loading, overloads also drawn heavier."""
    os.makedirs(FIGURES, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 8.4))

    placed = gridkit.placed_buses(n)
    drawn = skipped = 0
    order = loading.sort_values().index          # heaviest drawn last, on top
    for name in order:
        line = n.lines.loc[name]
        if line["bus0"] not in placed.index or line["bus1"] not in placed.index:
            skipped += 1
            continue
        x = [placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]]
        y = [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]]
        value = float(loading.get(name, 0.0))
        over = value >= 0.999
        ax.plot(x, y,
                color=(plotstyle.STATUS["critical"] if over
                       else plotstyle.loading_colour(value)),
                linewidth=3.0 if over else 0.7 + 1.6 * min(value, 1.0),
                solid_capstyle="round", zorder=2 + value)
        if over:
            # Several circuits join buses a few hundred metres apart, so a
            # stroke alone can be invisible at this scale.  A ring at the
            # midpoint makes every overload findable however short it is.
            ax.plot(np.mean(x), np.mean(y), marker="o", markersize=9,
                    markerfacecolor="none", markeredgewidth=1.8,
                    color=plotstyle.STATUS["critical"], zorder=6)
        drawn += 1

    ax.scatter(placed["x"], placed["y"], s=3, color=plotstyle.INK_MUTED,
               zorder=1, linewidths=0)

    hottest = loading.idxmax()
    if hottest in n.lines.index:
        line = n.lines.loc[hottest]
        if line["bus0"] in placed.index and line["bus1"] in placed.index:
            mx = np.mean([placed.at[line["bus0"], "x"],
                          placed.at[line["bus1"], "x"]])
            my = np.mean([placed.at[line["bus0"], "y"],
                          placed.at[line["bus1"], "y"]])
            # Label away from the nearer edge, so it cannot run under the
            # colorbar or off the frame.
            east = mx > 0.5 * (placed["x"].min() + placed["x"].max())
            ax.annotate(f"{hottest}\n{loading.max():.0%} of rating",
                        (mx, my), xytext=(-14 if east else 14, 14),
                        textcoords="offset points", fontsize=8,
                        ha="right" if east else "left",
                        color=plotstyle.INK,
                        arrowprops=dict(arrowstyle="-", color=plotstyle.INK_SOFT,
                                        linewidth=0.8))

    bar = fig.colorbar(
        plt.cm.ScalarMappable(cmap=plotstyle.sequential_cmap,
                              norm=plt.Normalize(0, 1)),
        ax=ax, fraction=0.035, pad=0.02, shrink=0.55)
    bar.set_label("circuit loading (flow / rating)", color=plotstyle.INK_SOFT)
    bar.outline.set_visible(False)
    ax.plot([], [], color=plotstyle.STATUS["critical"], linewidth=3.0,
            marker="o", markersize=9, markerfacecolor="none",
            markeredgewidth=1.8, label="at or above rating")
    ax.legend(loc="upper left")

    ax.set_title(f"{scenario} {scope}: circuit loading at peak demand")
    note = f"{snapshot:%Y-%m-%d %H:%M} · DC power flow · synthetic profiles"
    if skipped:
        note += f" · {skipped} circuits not drawn (no coordinates)"
    ax.set_xlabel(note)
    margin = 0.25
    ax.set_xlim(placed["x"].min() - margin, placed["x"].max() + margin)
    ax.set_ylim(placed["y"].min() - margin, placed["y"].max() + margin)
    ax.set_aspect(1 / np.cos(np.radians(float(placed["y"].mean()))))
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()

    path = os.path.join(FIGURES, f"a_flow_map_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n{drawn} circuits drawn -> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
