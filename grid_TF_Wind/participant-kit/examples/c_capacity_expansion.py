"""(c) Capacity expansion: let the optimiser decide what to build.

    python examples/c_capacity_expansion.py [SCENARIO] [SCOPE]

Runs the same LOPF as example (b), but with the option to reinforce circuits
and to build storage.  The optimiser trades the annualised cost of building
against the fuel and the unserved energy it avoids, and reports what it chose.
Writes ``figures/c_expansion_<scenario>_<scope>.png``.

The costs below are round numbers, not a price list.  They are here so the
model has a trade-off to make; a study whose conclusion depends on the third
significant figure of a capital cost should replace them.  What the example is
really for is the pattern: mark a component extendable, give it a capital
cost, solve, and read ``s_nom_opt`` back.
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

#: Annualised cost of one extra MVA of circuit capacity, EUR/MVA/year.  A
#: rough overhead-line reconductoring number: order 100 kEUR/MVA of capital at
#: a 40-year life and 7%, then per week rather than per year because that is
#: how long the model runs for.
LINE_COST_PER_MVA_YEAR = 7_500.0

#: Annualised cost of a 4-hour battery, EUR/MW/year, all-in.
BATTERY_COST_PER_MW_YEAR = 55_000.0

WEEKS_PER_YEAR = 52.18

#: How far a circuit may be reinforced, as a multiple of its present rating.
#: Uncapped, the optimiser will happily propose a 4 GVA 110 kV line.
MAX_REINFORCEMENT = 2.0

#: Where a battery may be built: any bus that already has a load or a
#: renewable generator.  A battery at a bus with neither has nothing to do.
BATTERY_CARRIERS = ("wind", "solar")


def main(scenario="WP2033", scope="all-island"):
    plotstyle.use()
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    print(gridkit.summary(n).to_string(), "\n")

    # The objective can come out negative: renewables bid at -1 EUR/MWh in
    # these networks, which is how a real support scheme makes a wind farm
    # willing to pay to stay on, and with 42 GW of it the fuel bill is
    # negative before anything else happens.  Only the *difference* between
    # two objectives means anything here, so that is what gets reported.
    base_cost = _solve(n, "baseline")
    base_down = _dispatch_down_gwh(n)
    base_short = gridkit.unserved(n).sum()
    hot = gridkit.binding(n)
    print(f"\nbaseline: {base_cost:,.0f} EUR of operating cost, "
          f"{base_down:,.1f} GWh dispatched down, "
          f"{len(hot)} circuits at their rating for at least one hour")

    m = gridkit.load(scenario, scope)
    candidates = _make_extendable(m, hot)
    batteries = _offer_batteries(m)
    print(f"offered: {len(candidates)} circuits to reinforce, "
          f"{len(batteries)} sites to build storage at\n")

    expanded_cost = _solve(m, "expansion")
    built_lines = _built_lines(m, candidates)
    built_storage = _built_storage(m, batteries)

    print("\ncircuits reinforced")
    print(built_lines.round(1).to_string() if len(built_lines)
          else "  none - reinforcement did not pay for itself")
    print("\nstorage built")
    print(built_storage.round(1).to_string() if len(built_storage)
          else "  none")

    invest = (built_lines["annual_cost_eur"].sum() if len(built_lines) else 0.0) \
        + (built_storage["annual_cost_eur"].sum() if len(built_storage) else 0.0)
    # PyPSA's objective already carries the capital term, so the expanded
    # objective is operating + build and the difference between the two
    # objectives is the *net* benefit.  Add the build cost back to recover the
    # operating saving on its own.
    net = (base_cost - expanded_cost) * WEEKS_PER_YEAR
    print(f"\nannualised build cost          {invest:15,.0f} EUR/year")
    print(f"operating cost avoided         {net + invest:15,.0f} EUR/year")
    print(f"net benefit                    {net:15,.0f} EUR/year")
    print("  (the optimiser minimised operating + build together, so the net "
          "is non-negative\n   by construction - what is worth reading is "
          "which projects it picked, and in what order)")
    print(f"\ndispatch-down {base_down:,.1f} -> "
          f"{_dispatch_down_gwh(m):,.1f} GWh over the week")
    if base_short > 1e-6:
        print(f"unserved energy {base_short:,.1f} -> "
              f"{gridkit.unserved(m).sum():,.1f} MWh")

    _draw(built_lines, built_storage, base_down, _dispatch_down_gwh(m),
          scenario, scope)
    return 0


def _solve(network, label):
    """Solve and return the operating cost over the week, in EUR."""
    gridkit.solve(network)
    if not len(network.generators_t.p.columns):
        raise RuntimeError(f"{label} solve failed")
    return float(network.objective)


def _make_extendable(network, hot):
    """Offer reinforcement on the circuits that actually bind.

    Making all 900 lines extendable is legal and slow, and it mostly proposes
    a megawatt here and there on circuits that were never the problem.  The
    ones that spend hours at their rating are the ones worth money.
    """
    names = [name for name in hot.index if name in network.lines.index]
    if not names:
        names = list(gridkit.line_loading(network).max()
                     .sort_values(ascending=False).head(10).index)
    weekly = LINE_COST_PER_MVA_YEAR / WEEKS_PER_YEAR
    network.lines.loc[names, "s_nom_extendable"] = True
    network.lines.loc[names, "s_nom_min"] = network.lines.loc[names, "s_nom"]
    network.lines.loc[names, "s_nom_max"] = (
        network.lines.loc[names, "s_nom"] * MAX_REINFORCEMENT)
    network.lines.loc[names, "capital_cost"] = weekly
    return names


def _offer_batteries(network):
    """Offer an extendable battery at every renewable bus."""
    buses = sorted(set(network.generators.loc[
        network.generators["carrier"].isin(BATTERY_CARRIERS), "bus"]))
    weekly = BATTERY_COST_PER_MW_YEAR / WEEKS_PER_YEAR
    if "battery" not in network.carriers.index:
        network.add("Carrier", "battery")
    names = []
    for bus in buses:
        name = f"battery {bus}"
        network.add("StorageUnit", name, bus=bus, p_nom=0.0,
                    p_nom_extendable=True, p_nom_max=500.0, max_hours=4.0,
                    efficiency_store=0.92 ** 0.5,
                    efficiency_dispatch=0.92 ** 0.5,
                    cyclic_state_of_charge=True, carrier="battery",
                    capital_cost=weekly, marginal_cost=0.5)
        names.append(name)
    return names


def _built_lines(network, names):
    frame = network.lines.loc[names]
    added = frame["s_nom_opt"] - frame["s_nom"]
    keep = added > 0.5
    return pd.DataFrame({
        "from_mva": frame.loc[keep, "s_nom"],
        "to_mva": frame.loc[keep, "s_nom_opt"],
        "added_mva": added[keep],
        "annual_cost_eur": added[keep] * LINE_COST_PER_MVA_YEAR,
    }).sort_values("added_mva", ascending=False)


def _built_storage(network, names):
    built = network.storage_units.loc[names, "p_nom_opt"]
    built = built[built > 0.5]
    return pd.DataFrame({
        "p_nom_mw": built,
        "energy_mwh": built * 4.0,
        "annual_cost_eur": built * BATTERY_COST_PER_MW_YEAR,
    }).sort_values("p_nom_mw", ascending=False)


def _dispatch_down_gwh(network):
    lost = gridkit.dispatch_down(network)
    return float(lost["dispatch_down_mwh"].sum() / 1000.0) if len(lost) else 0.0


def _draw(lines, storage, down_before, down_after, scenario, scope):
    os.makedirs(FIGURES, exist_ok=True)
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.0, 5.0),
                                      width_ratios=(1.7, 1.0))
    for ax in (left, right):
        ax.set_axisbelow(True)

    if len(lines) or len(storage):
        rows = pd.concat([
            lines["added_mva"].rename("MVA / MW").head(12).to_frame()
                .assign(kind="circuit reinforcement"),
            storage["p_nom_mw"].rename("MVA / MW").head(12).to_frame()
                .assign(kind="battery"),
        ]).sort_values("MVA / MW", ascending=True).tail(14)
        colours = [plotstyle.CATEGORICAL[0] if k == "circuit reinforcement"
                   else plotstyle.CARRIER_COLOURS["battery"]
                   for k in rows["kind"]]
        left.barh(range(len(rows)), rows["MVA / MW"].values, color=colours,
                  height=0.6)
        left.set_yticks(range(len(rows)), list(rows.index), fontsize=7)
        left.set_xlabel("capacity built (MVA for circuits, MW for batteries)")
        left.grid(axis="y", visible=False)
        # Patch proxies rather than zero-height bars, which would widen the
        # x-axis to fit a bar that is not there.
        from matplotlib.patches import Patch
        handles = [Patch(color=colour, label=kind)
                   for kind, colour in
                   (("circuit reinforcement", plotstyle.CATEGORICAL[0]),
                    ("battery", plotstyle.CARRIER_COLOURS["battery"]))
                   if (rows["kind"] == kind).any()]
        if len(handles) > 1:
            left.legend(handles=handles, loc="lower right")
    else:
        left.text(0.5, 0.5, "the optimiser built nothing:\nat these costs the "
                            "network is already worth what it costs",
                  ha="center", va="center", color=plotstyle.INK_SOFT)
        left.set_axis_off()
    left.set_title(f"{scenario} {scope}: what the optimiser built")

    values = [down_before, down_after]
    bars = right.bar(["baseline", "expanded"], values,
                     color=[plotstyle.INK_MUTED, plotstyle.CATEGORICAL[2]],
                     width=0.5)
    for bar, value in zip(bars, values):
        right.annotate(f"{value:,.1f} GWh",
                       (bar.get_x() + bar.get_width() / 2, value),
                       xytext=(0, 5), textcoords="offset points",
                       ha="center", fontsize=9, color=plotstyle.INK)
    right.set_ylabel("renewable energy dispatched down over the week (GWh)")
    right.set_ylim(0, max(values) * 1.25 + 0.01)
    right.set_title("dispatch-down avoided")
    right.grid(axis="x", visible=False)

    fig.tight_layout()
    path = os.path.join(FIGURES, f"c_expansion_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"\n-> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
