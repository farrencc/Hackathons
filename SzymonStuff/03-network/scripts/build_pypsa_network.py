"""
Load the Ireland electricity system model into PyPSA.

The spreadsheet describes a grid; PyPSA turns that description into something
that obeys Kirchhoff's laws and can therefore tell you where power flows. This
script does the translation, then checks the result hard enough to trust it.

THE THREE CONVERSIONS THAT MATTER

1. Per-unit to physical. The workbook stores r, x and b as per-unit on a 100 MVA
   base (baseMVA sheet). PyPSA wants line reactance in OHMS, so
       x_ohm = x_pu * V_nom^2 / 100
   Transformers are different: PyPSA wants their reactance per-unit on the
   TRANSFORMER's own rating, so
       x_pypsa = x_pu * s_nom / 100
   Getting this wrong does not throw an error - it silently produces a network
   with the wrong impedances and therefore the wrong flows.

2. Status flags. `stat` marks whether a component is in service, but the value
   differs by sheet: branches use 1, transformers use 2, and 0 always means out
   of service. Out-of-service components are skipped.

3. The slack bus. One bus carries `type = 3`, the power-flow slack. PyPSA
   assigns its own slack per connected sub-network, so we record theirs for
   reference rather than forcing it.

Output: script-output/ireland-network.nc  (a PyPSA network, reloadable with
        pypsa.Network(path)) and a printed validation report.
"""
import sys
import warnings
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
DATA = FOLDER / "data"
OUT_DIR = FOLDER / "script-output"

import openpyxl
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
import pypsa

SRC = DATA / "ireland_case_july2025.xlsx"
OUT = OUT_DIR / "ireland-network.nc"

BASE_MVA = 100.0


def sheet(wb, name):
    """A sheet as a DataFrame, with blank rows dropped."""
    rows = list(wb[name].iter_rows(values_only=True))
    df = pd.DataFrame(rows[1:], columns=[str(c) for c in rows[0]])
    return df.dropna(how="all")


def num(s, default=0.0):
    """The workbook stores several numeric columns as text."""
    return pd.to_numeric(s, errors="coerce").fillna(default)


def build():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    bus = sheet(wb, "bus")
    branch = sheet(wb, "branch")
    trafo = sheet(wb, "transformer")
    gen = sheet(wb, "generator")
    dem = sheet(wb, "demand")
    wb.close()

    n = pypsa.Network()
    n.set_snapshots([0])

    # ---- buses ------------------------------------------------------------
    bus["baseKV"] = num(bus["baseKV"])
    n.add("Bus", bus["name"].astype(str).tolist(),
          v_nom=bus["baseKV"].tolist(),
          carrier="AC")
    kv = dict(zip(bus["name"].astype(str), bus["baseKV"]))
    slack = bus.loc[num(bus["type"]) == 3, "name"].astype(str).tolist()

    # ---- lines ------------------------------------------------------------
    branch = branch[num(branch["stat"], 0) == 1].copy()
    v = branch["from_busname"].astype(str).map(kv)
    z_base = v.pow(2) / BASE_MVA                      # ohms per per-unit
    s_nom = num(branch["ContinousRating"])
    n.add("Line", branch["name"].astype(str).tolist(),
          bus0=branch["from_busname"].astype(str).tolist(),
          bus1=branch["to_busname"].astype(str).tolist(),
          r=(num(branch["r"]) * z_base).tolist(),
          x=(num(branch["x"]) * z_base).tolist(),
          b=(num(branch["b"]) / z_base).tolist(),
          s_nom=s_nom.tolist())

    # ---- transformers -----------------------------------------------------
    trafo = trafo[num(trafo["stat"], 0) != 0].copy()
    t_s_nom = num(trafo["ContinousRating"]).replace(0, 100.0)
    n.add("Transformer", trafo["name"].astype(str).tolist(),
          bus0=trafo["from_busname"].astype(str).tolist(),
          bus1=trafo["to_busname"].astype(str).tolist(),
          # per-unit on the transformer's own rating, not on 100 MVA
          r=(num(trafo["r"]) * t_s_nom / BASE_MVA).tolist(),
          x=(num(trafo["x"]) * t_s_nom / BASE_MVA).tolist(),
          s_nom=t_s_nom.tolist())

    # ---- generators -------------------------------------------------------
    gen = gen[num(gen["stat"], 0) == 1].copy()
    n.add("Generator", gen["name"].astype(str).tolist(),
          bus=gen["busname"].astype(str).tolist(),
          p_nom=num(gen["PGUB"]).tolist(),
          p_min_pu=0.0,
          marginal_cost=num(gen["costc1"]).tolist(),
          carrier=gen["FuelType"].astype(str).tolist())

    # ---- loads ------------------------------------------------------------
    dem = dem[num(dem["stat"], 0) == 1].copy()
    n.add("Load", dem["name"].astype(str).tolist(),
          bus=dem["busname"].astype(str).tolist(),
          p_set=num(dem["real"]).tolist())

    return n, slack


def validate(n, slack):
    """Everything that would silently produce wrong answers if left unchecked."""
    print(f"{'buses':<22}{len(n.buses):>6}")
    print(f"{'lines':<22}{len(n.lines):>6}")
    print(f"{'transformers':<22}{len(n.transformers):>6}")
    print(f"{'generators':<22}{len(n.generators):>6}")
    print(f"{'loads':<22}{len(n.loads):>6}")

    problems = []

    bad_x = n.lines[n.lines.x <= 0]
    if len(bad_x):
        problems.append(f"{len(bad_x)} lines with non-positive reactance")
    bad_tx = n.transformers[n.transformers.x <= 0]
    if len(bad_tx):
        problems.append(f"{len(bad_tx)} transformers with non-positive reactance")
    zero_s = n.lines[n.lines.s_nom <= 0]
    if len(zero_s):
        problems.append(f"{len(zero_s)} lines with no thermal rating")

    # Connectivity: PTDF is only defined within a connected sub-network.
    n.determine_network_topology()
    subs = n.buses.sub_network.value_counts()
    print(f"\n{'sub-networks':<22}{len(subs):>6}")
    for name, count in subs.head(6).items():
        print(f"   sub-network {name:<8} {count:>5} buses")
    if len(subs) > 1:
        print(f"   -> the largest holds {100*subs.iloc[0]/len(n.buses):.1f}% of buses")

    isolated = [b for b in n.buses.index
                if b not in set(n.lines.bus0) | set(n.lines.bus1)
                | set(n.transformers.bus0) | set(n.transformers.bus1)]
    if isolated:
        problems.append(f"{len(isolated)} buses with no branch attached: {isolated[:5]}")

    total_gen = n.generators.p_nom.sum()
    total_load = n.loads.p_set.sum()
    print(f"\n{'generation capacity':<22}{total_gen:>8.0f} MW")
    print(f"{'peak load in sheet':<22}{total_load:>8.0f} MW")
    print(f"{'slack bus (type 3)':<22}{slack[0] if slack else 'none':>8}")

    print("\nchecks:")
    if problems:
        for p in problems:
            print(f"   PROBLEM  {p}")
    else:
        print("   all impedances positive, all lines rated, no isolated buses")
    return problems


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"loading {SRC.name}\n")
    n, slack = build()
    problems = validate(n, slack)

    OUT_DIR.mkdir(exist_ok=True)
    n.export_to_netcdf(str(OUT))
    print(f"\nwrote {OUT.name}  —  reload with pypsa.Network(path)")
    return n, problems


if __name__ == "__main__":
    main()
