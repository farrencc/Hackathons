"""(b) Least-cost dispatch, and what it throws away.

    python examples/b_lopf_dispatch.py [SCENARIO] [SCOPE]

Solves the linear optimal power flow over the shipped week and reports two
things: who generated, and how much wind and solar the network refused to
take.  Writes ``figures/b_dispatch_<scenario>_<scope>.png``.

Dispatch-down is the number to watch.  A generator that is offered and not
taken is either uneconomic or unreachable: surplus-based dispatch-down when
the demand cannot absorb it in that hour, constraint-based when the
transmission between the wind and the demand is full.  Separating the two is
the problem the rest of the kit is about.  Note that neither is curtailment in
the SEM/EirGrid sense - there is no SNSP constraint in this model; see
``gridkit.dispatch_down``.
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

#: Carriers drawn in this order, bottom to top: must-run under flexible under
#: the fuel that fills the gap.  Fixed, so two scenarios stack alike.
STACK_ORDER = ("wind", "solar", "hydro", "biomass", "gas", "unknown",
               "import", "battery", "load shedding")


def main(scenario="WP2033", scope="all-island"):
    plotstyle.use()
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    print(gridkit.summary(n).to_string(), "\n")

    gridkit.solve(n)

    dispatch = by_carrier(n)
    served = n.loads_t.p_set.sum(axis=1)
    print("energy over the week, GWh")
    energy = (dispatch.sum() / 1000.0).sort_values(ascending=False)
    share = 100.0 * energy / energy.sum()
    print(pd.DataFrame({"GWh": energy.round(1),
                        "share_pct": share.round(1)}).to_string())
    print(f"\ndemand served: {served.sum() / 1000.0:,.1f} GWh"
          f" · peak {served.max():,.0f} MW")

    lost = gridkit.dispatch_down(n)
    if len(lost):
        by_kind = lost.groupby("carrier")[
            ["offered_mwh", "dispatched_mwh", "dispatch_down_mwh"]].sum()
        by_kind["dispatch_down_pct"] = (100.0 * by_kind["dispatch_down_mwh"]
                                        / by_kind["offered_mwh"])
        print("\ndispatch-down by carrier")
        print(by_kind.round(1).to_string())
        print("\nworst ten generators by energy dispatched down")
        print(lost.head(10)[["carrier", "offered_mwh", "dispatch_down_mwh",
                             "dispatch_down_pct"]].round(1).to_string())

    congestion = _congestion_share(scenario, scope, lost)

    short = gridkit.unserved(n)
    if len(short):
        print(f"\nunserved energy at {len(short)} buses, "
              f"{short.sum():,.1f} MWh total - the network could not reach "
              f"this demand at any price:")
        print(short.head(10).round(1).to_string())
    else:
        print("\nno unserved energy: every MW of demand was reachable.")

    _draw(n, dispatch, served, lost, congestion, scenario, scope)
    return 0


def _congestion_share(scenario, scope, lost):
    """How much of the dispatch-down is the network's fault, in GWh.

    A large dispatch-down total on its own does not mean the transmission is
    the problem.  WP2033 carries 42 GW of plant against an 8.8 GW peak, so
    most of the wind offered in any hour has nowhere to go whatever the
    network looks like - that is surplus-based dispatch-down, not
    constraint-based, and building a line does not recover a megawatt of it.

    The separation is one extra solve.  Lift every branch rating to something
    that cannot bind and optimise again: what is still withheld is
    surplus-based, and the difference is constraint-based - what the network
    cost.  It is a copper plate with the real topology, which is the cleanest
    counterfactual available here.
    """
    if not len(lost):
        return {"total": 0.0, "surplus": 0.0, "network": 0.0}
    m = gridkit.load(scenario, scope)
    m.lines["s_nom"] = m.lines["s_nom"] * 1000.0
    if len(m.transformers):
        m.transformers["s_nom"] = m.transformers["s_nom"] * 1000.0
    gridkit.solve(m)
    free = gridkit.dispatch_down(m)
    total = float(lost["dispatch_down_mwh"].sum()) / 1000.0
    surplus = (float(free["dispatch_down_mwh"].sum()) / 1000.0
               if len(free) else 0.0)
    network = max(total - surplus, 0.0)
    print(f"\ndispatch-down split, over the week")
    print(f"  {total:8,.1f} GWh dispatched down in the real network")
    print(f"  {surplus:8,.1f} GWh still withheld with every rating lifted"
          f"  - surplus-based, no network can take it")
    print(f"  {network:8,.1f} GWh recovered by the lift"
          f"  - constraint-based, this is what the transmission costs"
          f" ({100.0 * network / max(total, 1e-9):.1f}% of the dispatch-down)")
    return {"total": total, "surplus": surplus, "network": network}


def by_carrier(network) -> pd.DataFrame:
    """Generation per carrier per snapshot, MW, including storage discharge."""
    frame = (network.generators_t.p.T
             .groupby(network.generators["carrier"]).sum().T)
    if "export" in frame.columns:                # a sink, not a source
        frame = frame.drop(columns="export")
    if len(network.storage_units_t.p.columns):
        frame["battery"] = network.storage_units_t.p.clip(lower=0.0).sum(axis=1)
    shed = [g for g in network.generators.index if str(g).startswith("shed ")]
    if shed:
        frame["load shedding"] = network.generators_t.p[shed].sum(axis=1)
        for carrier in set(network.generators.loc[shed, "carrier"]):
            if carrier in frame.columns and carrier != "load shedding":
                frame[carrier] -= network.generators_t.p[
                    [g for g in shed
                     if network.generators.at[g, "carrier"] == carrier]
                ].sum(axis=1)
    frame = frame.loc[:, frame.abs().sum() > 1e-6]
    ordered = [c for c in STACK_ORDER if c in frame.columns]
    return frame[ordered + [c for c in frame.columns if c not in ordered]]


def _draw(network, dispatch, served, lost, congestion, scenario, scope):
    os.makedirs(FIGURES, exist_ok=True)
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(9.2, 6.8), height_ratios=(2.6, 1.0))
    for ax in (top, bottom):
        ax.set_axisbelow(True)          # grid under the fills, not over them

    hours = np.arange(len(dispatch))
    colours = [plotstyle.carrier_colour(c) for c in dispatch.columns]
    # A 2px surface gap between segments: stack the areas, then redraw each
    # boundary in the surface colour so neighbouring fills never touch.
    top.stackplot(hours, dispatch.T.values, colors=colours,
                  labels=list(dispatch.columns), linewidth=0)
    cumulative = dispatch.cumsum(axis=1)
    for column in cumulative.columns[:-1]:
        top.plot(hours, cumulative[column].values,
                 color=plotstyle.SURFACE, linewidth=2.0, zorder=3)
    top.plot(hours, served.values, color=plotstyle.INK, linewidth=1.6,
             linestyle=(0, (4, 2)), label="demand", zorder=4)

    top.set_title(f"{scenario} {scope}: least-cost dispatch over the week")
    top.set_ylabel("MW")
    top.set_xlim(0, len(dispatch) - 1)
    top.set_ylim(0, None)
    _day_ticks(top, dispatch.index)
    handles, labels = top.get_legend_handles_labels()
    top.legend(handles[::-1], labels[::-1], loc="upper left", ncol=4,
               columnspacing=1.4)

    if congestion["total"] > 0:
        # Two stacked segments of one bar, because the parts are shares of a
        # whole and the question is which part is bigger.  A 2px surface gap
        # keeps the segments from reading as one block.
        parts = [("surplus-based - no network could take it",
                  congestion["surplus"], plotstyle.INK_MUTED),
                 ("constraint-based - the transmission refused it",
                  congestion["network"], plotstyle.STATUS["serious"])]
        left = 0.0
        for label, value, colour in parts:
            bottom.barh([0], [value], left=left, color=colour, height=0.42,
                        label=label)
            if value > 0:
                bottom.annotate(f"{value:,.0f} GWh",
                                (left + value / 2, 0), ha="center",
                                va="center", fontsize=9,
                                color=plotstyle.SURFACE
                                if value / congestion["total"] > 0.12
                                else plotstyle.INK_SOFT)
            left += value
        bottom.set_ylim(-0.45, 0.75)
        bottom.set_yticks([])
        bottom.set_xlim(0, congestion["total"] * 1.02)
        bottom.set_xlabel(
            "renewable energy dispatched down over the week (GWh)")
        bottom.set_title("why it was dispatched down")
        bottom.legend(loc="upper left", ncol=2)
        bottom.grid(axis="y", visible=False)
    else:
        bottom.text(0.5, 0.5, "nothing dispatched down in this scenario",
                    ha="center", va="center", color=plotstyle.INK_SOFT)
        bottom.set_axis_off()

    fig.tight_layout()
    path = os.path.join(FIGURES, f"b_dispatch_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n-> {path}")


def _day_ticks(ax, index):
    """One tick per midnight, labelled with the date - 168 hourly ticks is
    unreadable and the reader only needs to find the days."""
    marks = [i for i, stamp in enumerate(index) if stamp.hour == 0]
    ax.set_xticks(marks, [index[i].strftime("%a %d") for i in marks])


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
