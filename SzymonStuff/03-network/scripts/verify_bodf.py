"""
Verify PyPSA's N-1 outage factors against networks solvable by hand.

BODF (Branch Outage Distribution Factor, elsewhere called LODF) answers: if line
k trips, what fraction of the flow it was carrying appears on line l?

    new_flow(l) = old_flow(l) + BODF[l, k] * old_flow(k)

This is what makes N-1 tractable. Rather than re-solving the power flow once per
contingency, one matrix gives every post-outage flow at once.

THE TEST CASES

1. Triangle, equal reactances. Outage A-B and its power must travel A -> C -> B,
   because there is exactly one alternative path. So the whole flow lands on the
   other two lines:

       BODF[A-C, A-B] = +1     power A->C runs WITH that line's orientation
       BODF[B-C, A-B] = -1     power C->B runs AGAINST it (bus0=B, bus1=C)
       BODF[A-B, A-B] = -1     the outaged line loses all of its own flow

   The signs are the whole point: get them backwards and every N-1 result
   silently reverses.

2. Two parallel paths of unequal reactance. Outage the short path and ALL of its
   flow must still go the long way - there is nowhere else. The magnitude stays
   1 regardless of reactance, which distinguishes a correct BODF from something
   that has quietly absorbed a PTDF-style impedance split.

3. Radial line. Outage a line that is the only connection to a bus and the
   network splits in two. BODF is then undefined - the flow cannot redistribute
   because there is no alternative path. A correct implementation must produce
   a non-finite value here, and the caller must detect and exclude it. This case
   exists because the real Irish network has many radial connections, and
   treating them as ordinary contingencies would produce nonsense.
"""
import sys
import warnings
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import pypsa


def bodf_of(n):
    """BODF as a DataFrame: rows = affected branch, columns = outaged branch."""
    n.determine_network_topology()
    sub = n.sub_networks.obj.iloc[0]
    sub.calculate_BODF()
    names = sub.branches_i().get_level_values(1)
    return pd.DataFrame(sub.BODF, index=names, columns=names)


def check(label, got, want, tol=1e-6):
    ok = abs(got - want) < tol
    print(f"   {'PASS' if ok else 'FAIL'}  {label:<44} got {got:+.6f}   expected {want:+.6f}")
    return ok


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    results = []

    print("CASE 1 — triangle, equal reactances")
    print("  Outage A-B; its flow must travel A -> C -> B.\n")
    n = pypsa.Network(); n.set_snapshots([0])
    for b in ("A", "B", "C"):
        n.add("Bus", b, v_nom=110)
    n.add("Line", "A-B", bus0="A", bus1="B", x=0.1, r=0.0, s_nom=100)
    n.add("Line", "B-C", bus0="B", bus1="C", x=0.1, r=0.0, s_nom=100)
    n.add("Line", "A-C", bus0="A", bus1="C", x=0.1, r=0.0, s_nom=100)
    B = bodf_of(n)
    results.append(check("A-C picks up A-B's flow", B.loc["A-C", "A-B"], +1.0))
    results.append(check("B-C picks it up, opposite sign", B.loc["B-C", "A-B"], -1.0))
    results.append(check("the outaged line loses its flow", B.loc["A-B", "A-B"], -1.0))

    print("\nCASE 2 — unequal reactances, one alternative path")
    print("  All the flow must reroute regardless of impedance.\n")
    n2 = pypsa.Network(); n2.set_snapshots([0])
    for b in ("A", "B", "C"):
        n2.add("Bus", b, v_nom=110)
    n2.add("Line", "A-C", bus0="A", bus1="C", x=0.05, r=0.0, s_nom=100)
    n2.add("Line", "A-B", bus0="A", bus1="B", x=0.30, r=0.0, s_nom=100)
    n2.add("Line", "B-C", bus0="B", bus1="C", x=0.30, r=0.0, s_nom=100)
    B2 = bodf_of(n2)
    results.append(check("long path takes all of the short path's flow",
                         abs(B2.loc["A-B", "A-C"]), 1.0))

    print("\nCASE 3 — radial line, network splits")
    print("  BODF must be non-finite: there is no alternative path.\n")
    n3 = pypsa.Network(); n3.set_snapshots([0])
    for b in ("A", "B", "C", "D"):
        n3.add("Bus", b, v_nom=110)
    n3.add("Line", "A-B", bus0="A", bus1="B", x=0.1, r=0.0, s_nom=100)
    n3.add("Line", "B-C", bus0="B", bus1="C", x=0.1, r=0.0, s_nom=100)
    n3.add("Line", "A-C", bus0="A", bus1="C", x=0.1, r=0.0, s_nom=100)
    n3.add("Line", "C-D", bus0="C", bus1="D", x=0.1, r=0.0, s_nom=100)  # radial stub
    B3 = bodf_of(n3)
    col = B3["C-D"]
    non_finite = not np.isfinite(col).all()
    print(f"   {'PASS' if non_finite else 'FAIL'}  radial outage flagged as undefined"
          f"           column has non-finite values: {non_finite}")
    results.append(non_finite)
    print(f"          (loop lines stay finite: "
          f"{np.isfinite(B3.loc[['A-B', 'B-C', 'A-C'], 'A-B']).all()})")

    print(f"\n{sum(results)} of {len(results)} checks passed")
    if all(results):
        print("BODF is correct, including its behaviour on radial lines.")
        print("N-1 effectiveness built on this can be trusted.")
    else:
        print("Do NOT build N-1 results on this until these pass.")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
