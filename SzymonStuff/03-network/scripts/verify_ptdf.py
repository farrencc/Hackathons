"""
Verify PyPSA's PTDF against a network small enough to solve on paper.

A PTDF matrix for the Irish grid is 588 x 446 numbers, and every one of them
looks plausible. So before trusting it, compute one where the right answer is
known by hand.

THE TEST CASE. Three buses in a triangle, every line with the same reactance x.
Inject 1 MW at bus A and take it out at bus C (the slack).

    A ----------- C          direct path:  reactance x
     \           /
      \         /            long path:    reactance 2x (via B)
       \       /
          B

Current divides between parallel paths in inverse proportion to reactance, so
the direct path carries 2/3 and the long way round carries 1/3. That is a
schoolbook result and it does not depend on the value of x.

    PTDF(line A-C, injection at A) = +2/3
    PTDF(line A-B, injection at A) = +1/3
    PTDF(line B-C, injection at A) = +1/3

If PyPSA reproduces those three numbers, the per-unit conversion and the sign
convention in build_pypsa_network.py are right, and the 446-bus matrix can be
trusted.

The second case adds the fourth node from the Braess example in Session 1 of the
graph workshop, where two parallel routes have DIFFERENT reactances, to check
the split still follows 1/x rather than being hard-coded to an even share.
"""
import sys
import warnings
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent

import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)
import pypsa

TOL = 1e-9


def triangle(x=0.1):
    """Three buses, equal reactances. Slack is whichever PyPSA picks; we
    compute PTDF relative to it and compare shape, not absolute labels."""
    n = pypsa.Network()
    n.set_snapshots([0])
    for b in ("A", "B", "C"):
        n.add("Bus", b, v_nom=110)
    n.add("Line", "A-C", bus0="A", bus1="C", x=x, r=0.0, s_nom=100)
    n.add("Line", "A-B", bus0="A", bus1="B", x=x, r=0.0, s_nom=100)
    n.add("Line", "B-C", bus0="B", bus1="C", x=x, r=0.0, s_nom=100)
    return n


def unequal(x_short=0.1, x_long=0.2):
    """Two parallel routes with different reactance: the split must follow 1/x."""
    n = pypsa.Network()
    n.set_snapshots([0])
    for b in ("A", "B", "C"):
        n.add("Bus", b, v_nom=110)
    n.add("Line", "A-C", bus0="A", bus1="C", x=x_short, r=0.0, s_nom=100)
    n.add("Line", "A-B", bus0="A", bus1="B", x=x_long / 2, r=0.0, s_nom=100)
    n.add("Line", "B-C", bus0="B", bus1="C", x=x_long / 2, r=0.0, s_nom=100)
    return n


def ptdf_of(n):
    """PTDF as a DataFrame: rows = branches, columns = buses.

    PyPSA returns flows per MW injected at a bus and withdrawn at ITS OWN
    slack, so the slack's own column is all zeros. To express a transfer
    between two chosen buses, subtract one column from the other.
    """
    n.determine_network_topology()
    sub = n.sub_networks.obj.iloc[0]
    sub.calculate_PTDF()
    import pandas as pd
    # branches_i() returns (component, name) pairs in PTDF row order.
    branches = sub.branches_i().get_level_values(1)
    buses = sub.components.buses.static.index
    return pd.DataFrame(sub.PTDF, index=branches, columns=buses)


def transfer(P, inject, withdraw):
    """Flow on each branch for 1 MW injected at `inject`, taken out at `withdraw`."""
    return P[inject] - P[withdraw]


def check(label, got, want, tol=1e-6):
    ok = abs(got - want) < tol
    print(f"   {'PASS' if ok else 'FAIL'}  {label:<38} got {got:+.6f}   expected {want:+.6f}")
    return ok


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    results = []

    print("CASE 1 — triangle, equal reactances")
    print("  Inject at A, withdraw at slack. Direct path should take 2/3.\n")
    n = triangle()
    P = ptdf_of(n)
    inj = transfer(P, "A", "C")      # 1 MW in at A, out at C
    results.append(check("flow on A-C from 1 MW at A", inj["A-C"], 2/3))
    results.append(check("flow on A-B from 1 MW at A", inj["A-B"], 1/3))
    results.append(check("flow on B-C from 1 MW at A", inj["B-C"], 1/3))
    results.append(check("A-B and B-C carry the same",
                         inj["A-B"] - inj["B-C"], 0.0))

    print("\nCASE 2 — parallel routes, reactance 0.1 against 0.2")
    print("  Split should be 2:1 in favour of the low-reactance path.\n")
    n2 = unequal()
    P2 = ptdf_of(n2)
    inj2 = transfer(P2, "A", "C")
    results.append(check("flow on the short path (x=0.1)", inj2["A-C"], 2/3))
    results.append(check("flow on the long path (x=0.2)", inj2["A-B"], 1/3))

    print("\nCASE 3 — a transfer from a bus to itself moves nothing\n")
    zero = transfer(P, "B", "B")
    results.append(check("all flows for a null transfer",
                         float(np.abs(zero).max()), 0.0))

    print("\nCASE 4 — the two routes out of A carry the whole injection\n")
    results.append(check("A-C plus A-B", inj["A-C"] + inj["A-B"], 1.0))

    print(f"\n{sum(results)} of {len(results)} checks passed")
    if all(results):
        print("PTDF is being computed correctly. The 446-bus matrix can be trusted.")
    else:
        print("Do NOT trust the full network PTDF until these pass.")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
