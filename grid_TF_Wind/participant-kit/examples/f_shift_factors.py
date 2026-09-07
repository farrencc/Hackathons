"""(f) Shift factors per generator - the Wind Dispatch Tool calculation.

    python examples/f_shift_factors.py [SCENARIO] [SCOPE] [MONITORED_CIRCUIT]

For one monitored circuit, works out how much of each generator's output that
circuit actually carries, ranks the generators by it, and draws the constraint
group: the machines a dispatch instruction would have to act on to unload the
circuit.  Writes ``figures/f_shift_factors_<scenario>_<scope>.png``.

This is the arithmetic behind EirGrid's Wind Dispatch Tool.  The tool works on
*constraint groups*: a monitored circuit or corridor, and the set of wind farms
whose output it sees.  When the corridor is full the farms in the group get
dispatched down, in the order and proportion their factors imply, and farms
outside the group are untouched because turning them down would not help.

The one thing worth being careful about is the reference.  A shift factor is
"MW on the circuit per MW at the generator" - but a megawatt cannot appear on
its own, so the definition is incomplete until you say where the balancing
megawatt goes.  Three conventions are printed side by side below:

    load        spread over every load in proportion to its size.  This is
                what a system operator means, because that is what the rest
                of the system does when one machine backs off
    uniform     spread evenly over all buses - the pseudoinverse's own
                reference, and the one PTDF returns untouched
    a bus name  all of it at one bus, the textbook single-slack convention

The numbers differ.  The *ranking* barely does, which is why the method is
robust enough to run a real dispatch tool on.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flowmath
import gridkit
import plotstyle

FIGURES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "figures")

#: A generator is in the constraint group if the monitored circuit carries at
#: least this fraction of its output.  5% is a working threshold, not a
#: standard - EirGrid's own groups are drawn by study and by judgement.
GROUP_THRESHOLD = 0.05

#: Carriers a wind dispatch tool can actually instruct.
DISPATCHABLE_DOWN = ("wind", "solar")


def main(scenario="WP2033", scope="all-island", monitored=None):
    plotstyle.use()
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    loading = gridkit.line_loading(n)
    monitored = monitored or loading.max().idxmax()
    hours = int((loading[monitored] >= 0.999).sum())
    print(f"monitored circuit {monitored}: "
          f"{n.lines.at[monitored, 's_nom']:.0f} MVA, at its rating for "
          f"{hours} of {len(n.snapshots)} hours\n")

    frame = flowmath.branches(n)
    # The load-shedding generators are a modelling device, not plant, so they
    # are dropped before anything is ranked - a "generator" at every load bus
    # with a factor of 0.51 is noise in a constraint group.
    real = n.generators.index[n.generators["carrier"] != "load shedding"]
    factors = flowmath.shift_factors(n, monitored, reference="load",
                                     branch_frame=frame).reindex(real).dropna(
                                         subset=["shift_factor"])
    factors = factors.reindex(
        factors["shift_factor"].abs().sort_values(ascending=False).index)
    uniform = flowmath.shift_factors(n, monitored, reference="uniform",
                                     branch_frame=frame).reindex(real)
    biggest_load = n.loads.groupby("bus")["p_set"].sum().idxmax()
    single = flowmath.shift_factors(n, monitored, reference=biggest_load,
                                    branch_frame=frame).reindex(real)

    compare = pd.DataFrame({
        "load_weighted": factors["shift_factor"],
        "uniform": uniform["shift_factor"].reindex(factors.index),
        f"slack at {biggest_load}": single["shift_factor"].reindex(factors.index),
    })
    print("the same generators under three references")
    print(compare.head(10).round(4).to_string())
    ranks = compare.rank(ascending=False).corr(method="spearman")
    print(f"\nrank correlation between references: "
          f"{ranks.to_numpy()[np.triu_indices(3, 1)].min():.4f} at worst - "
          f"the values move, the ordering does not")

    group = factors[
        (factors["shift_factor"].abs() >= GROUP_THRESHOLD)
        & factors["carrier"].isin(DISPATCHABLE_DOWN)]
    print(f"\nconstraint group for {monitored}: {len(group)} instructable "
          f"generators at a {GROUP_THRESHOLD:.0%} threshold, "
          f"{group['p_nom'].sum():,.0f} MW of capacity")
    print(group.head(15)[["bus", "carrier", "p_nom", "shift_factor",
                          "mw_on_monitored_at_full_output"]]
          .round(3).to_string())

    # What the group is for: relieving the circuit by backing the group off.
    peak = loading[monitored].idxmax()
    flow = float(n.lines_t.p0.at[peak, monitored])
    rating = float(n.lines.at[monitored, "s_nom"])
    excess = abs(flow) - rating
    if excess > 0:
        print(f"\nat {peak} the circuit carries {flow:+,.1f} MW against a "
              f"{rating:,.0f} MVA rating - {excess:,.1f} MW to shed")
    else:
        print(f"\nat {peak} the circuit carries {flow:+,.1f} MW against a "
              f"{rating:,.0f} MVA rating; no reduction needed")
    output = n.generators_t.p.loc[peak].reindex(group.index).fillna(0.0)
    relief = (output * group["shift_factor"]).abs().sort_values(ascending=False)
    print("\nMW of relief available from each group member at this hour, "
          "if it were dispatched to zero")
    print(relief.head(10).round(2).to_string())
    print(f"total relief available from the group: {relief.sum():,.1f} MW")

    _draw(n, factors, group, compare, monitored, relief, scenario, scope)
    return 0


def _draw(network, factors, group, compare, monitored, relief,
          scenario, scope):
    os.makedirs(FIGURES, exist_ok=True)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.4, 6.0),
                                      width_ratios=(1.15, 1.0))
    for ax in (left, right):
        ax.set_axisbelow(True)

    # Left: the shift factor on the map, one dot per generator bus.  Signed,
    # so the diverging ramp: blue pushes power one way down the circuit, red
    # the other, and the pale middle is the part of the island the circuit
    # cannot feel at all.
    placed = gridkit.placed_buses(network)
    at_bus = (factors.groupby("bus")["shift_factor"].mean()
              .reindex(placed.index))
    have = at_bus.dropna()
    limit = float(np.nanpercentile(have.abs(), 98)) or 1e-6
    for _, line in network.lines.iterrows():
        if line["bus0"] in placed.index and line["bus1"] in placed.index:
            left.plot([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]],
                      [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]],
                      color="#e6e5e1", linewidth=0.6, zorder=1)
    capacity = (network.generators.groupby("bus")["p_nom"].sum()
                .reindex(have.index).fillna(0.0))
    order = have.abs().sort_values().index
    dots = left.scatter(placed.loc[order, "x"], placed.loc[order, "y"],
                        c=have[order], cmap=plotstyle.diverging_cmap,
                        vmin=-limit, vmax=limit,
                        s=8 + 42 * np.sqrt(capacity[order]
                                           / max(capacity.max(), 1e-9)),
                        zorder=3, linewidths=0.4,
                        edgecolors=plotstyle.SURFACE)
    line = network.lines.loc[monitored]
    if line["bus0"] in placed.index and line["bus1"] in placed.index:
        mx = np.mean([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]])
        my = np.mean([placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]])
        left.plot([placed.at[line["bus0"], "x"], placed.at[line["bus1"], "x"]],
                  [placed.at[line["bus0"], "y"], placed.at[line["bus1"], "y"]],
                  color=plotstyle.INK, linewidth=2.6, zorder=4)
        east = mx > 0.5 * (placed["x"].min() + placed["x"].max())
        left.annotate(monitored, (mx, my),
                      xytext=(-14 if east else 14, 22),
                      textcoords="offset points",
                      ha="right" if east else "left", fontsize=8,
                      color=plotstyle.INK,
                      arrowprops=dict(arrowstyle="-",
                                      color=plotstyle.INK_SOFT, linewidth=0.8))
    bar = fig.colorbar(dots, ax=left, orientation="horizontal",
                       fraction=0.045, pad=0.03, shrink=0.85)
    bar.set_label("shift factor, load-weighted reference",
                  color=plotstyle.INK_SOFT)
    bar.outline.set_visible(False)
    margin = 0.25
    left.set_xlim(placed["x"].min() - margin, placed["x"].max() + margin)
    left.set_ylim(placed["y"].min() - margin, placed["y"].max() + margin)
    left.set_aspect(1 / np.cos(np.radians(float(placed["y"].mean()))))
    left.set_xticks([]); left.set_yticks([]); left.grid(False)
    for spine in left.spines.values():
        spine.set_visible(False)
    left.set_title(f"{scenario} {scope}: who this circuit can feel\n"
                   f"(dot area is installed capacity at the bus)",
                   fontsize=10)

    # Right: the constraint group, ranked by the relief each member offers.
    top = relief[relief > 1e-6].head(14).iloc[::-1]
    if len(top):
        colours = [plotstyle.carrier_colour(
            group["carrier"].get(name, "unknown")) for name in top.index]
        right.barh(range(len(top)), top.values, color=colours, height=0.62)
        right.set_yticks(range(len(top)), list(top.index), fontsize=7)
        right.set_xlabel("MW taken off the monitored circuit if this "
                         "generator goes to zero")
        right.grid(axis="y", visible=False)
        # One series needs no legend box - the title names it.
        carriers = sorted(set(group["carrier"].reindex(top.index).dropna()))
        if len(carriers) > 1:
            from matplotlib.patches import Patch
            right.legend(handles=[Patch(color=plotstyle.carrier_colour(c),
                                        label=c) for c in carriers],
                         loc="lower right")
    else:
        right.text(0.5, 0.5, "nothing in the group was generating at this hour",
                   ha="center", va="center", color=plotstyle.INK_SOFT)
        right.set_axis_off()
    right.set_title(f"constraint group: {len(group)} generators above a "
                    f"{GROUP_THRESHOLD:.0%} factor", fontsize=10)

    fig.tight_layout()
    path = os.path.join(FIGURES, f"f_shift_factors_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n-> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
