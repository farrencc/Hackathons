# TPSA & TFWind Hackathon 2026

Ireland's transmission network, as a PyPSA model, ready to load in one line.
Built for the **TPSA & TFWind Hackathon 2026**, whose subject is why 5–6% of
Irish renewable generation gets **constrained** off the grid every year — and
what a battery, a reconductored line, or a smarter dispatch rule could do
about it.

If you're here for the hackathon, you want [`participant-kit/`](participant-kit/).
Everything below is about that directory; the rest of the repository is the
pipeline that built it, and you shouldn't need it.

## 60 seconds to a plotted map

```bash
cd participant-kit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python examples/a_dc_power_flow.py
```

That's the whole quickstart. No API keys, no PSS/E reader, no download —
the networks are committed data. From a clean virtual environment it takes
about 42 seconds and ends in a figure under `participant-kit/figures/`.

## The problem, in one paragraph

In 2025, 12% of Ireland's renewable generation was dispatched down — wind and
solar turned off while the wind was blowing. Roughly half of that is
**curtailment**, a system-wide reduction (SNSP, inertia, not enough demand),
and the other half is **constraint**: specific lines and transformers running
out of headroom. This hackathon is about constraint. `WP2033`, the headline
scenario in this kit, is where it bites hardest: **42.6 GW of connected
capacity against an 8.8 GW peak**, and in the week modelled here, curtailment
happens in every hour studied.

## What's in the kit

Four TYTFS 2024 scenarios (`WP2024`, `SV2024`, `WP2033`, `SV2033`), each at
two scopes — the full **all-island** transmission network and the **North
West** region (EirGrid Constraint Groups 1–3: Donegal, Sligo, Mayo), each
carrying a real 168-hour week of weather-driven generation and demand.

| | |
|---|---|
| `networks/` | 4 scenarios × 2 scopes, as `.nc` (PyPSA) and as CSV folders you can edit in a spreadsheet |
| `gridkit.py` | load a network, add/remove lines, site a battery, reset, save |
| `flowmath.py` | PTDF, edge-to-edge susceptibility, shift factors — the linear algebra under everything below |
| `examples/` | six runnable scripts, `a` to `f`, each producing a figure |
| `test_kit.py` | ~20 checks, run this if you touch `flowmath.py` |

```python
import gridkit
n = gridkit.load("WP2033", "north-west")
gridkit.add_battery(n, "Letterkenny", p_nom=50, hours=4)
gridkit.solve(n)
print(gridkit.curtailment(n).head())
```

## Matching examples to the problem sheet

Each subproblem on the question sheet has a starting point already built and
already tested against a real power flow — you're extending these, not
starting from a blank file.

| Question sheet subproblem | Start here |
|---|---|
| **Analyse the North-West** — which lines constrain most, shift factor per wind farm | `f_shift_factors.py` (the WDT calculation itself), `d_ptdf.py` |
| **Battery siting** | `c_capacity_expansion.py` — extendable circuits and a battery at every renewable bus, solved together |
| **Constraint Group Generation** / non-local correlations | `e_braess_susceptibility.py` — the full edge-to-edge `dF_e/dB_e'` matrix; the off-diagonal terms *are* the non-local effect the sheet asks about |
| **Dispatch Down Strategy** / **Surplus** | `b_lopf_dispatch.py` — separates a week's dispatch-down into the part transmission actually caused and the part no network could have absorbed |
| Everything downstream | `a_dc_power_flow.py`, `d_ptdf.py` — if the flow picture here is wrong, nothing built on top of it is right |

```bash
python examples/f_shift_factors.py WP2033 north-west
python examples/e_braess_susceptibility.py WP2033 all-island
```

## Two things that will cost you an afternoon if you don't know them

**`n.lpf()` after `n.optimize()` gives you nonsense.** Optimise writes the
dispatch to `generators_t.p`; `n.lpf()` reads `generators_t.p_set`, a
different field the kit ships empty. Run `gridkit.freeze_dispatch(n)` between
the two, or you'll get a power flow with no generation in it and a circuit
reading 1600% of rating.

**A bus at 0°N 0°E is a bug, not a location.** PyPSA's netCDF writer turns a
missing coordinate into `0.0`, not `NaN`. Plot with `gridkit.placed_buses(n)`,
which filters those out, or Ireland ends up squashed into the corner of a
map that also shows the Gulf of Guinea.

## What this is, honestly

**This is a DC approximation of an AC model.** The source files are solved
AC load-flow cases with reactive power, tap changers and voltage magnitude;
this kit throws all of that away in exchange for linear flows you can invert
and differentiate. Good for shift factors and PTDF-based reasoning; not a
substitute for an AC study.

**A snapshot is not a time series.** Each TYTFS case is one solved hour. The
168 hours you're given are real weather-and-demand shapes fitted to that
anchor hour, not EirGrid's own dispatch — check `gridkit.load(...).meta` for
which scenario, scope, and hour is the real one, and say so in anything you
present.

**Line lengths, ratings, and thresholds are inputs, not verified facts.**
Where a number in these networks looks precise, it means the source file said
so — nothing here has been checked against the physical network. The 5% used
to define a constraint group in `f_shift_factors.py` is a working threshold,
not a standard; EirGrid draws its own groups by study and by judgement.

## Going deeper

- **`report.pdf`** — the full build report: every conversion decision, every
  source, every number's provenance. Read this if a result surprises you and
  you want to know whether that's the grid or the model.
- **`docs/PHASE2_PYPSA.md`, `PHASE3_NORTHWEST.md`, `PHASE4_PROFILES.md`,
  `SYNTHETIC_DATA.md`** — the working notes behind that report, including
  exactly what in the hourly profiles is real ERA5/Smart-Grid-Dashboard data
  and what is synthetic.
- **The question sheet** for this hackathon, and the [EirGrid Wind Dispatch
  Tool Constraint Group Overview](.), for what "constraint group" and "shift
  factor" mean outside this codebase.

None of that is required reading to start. Load a network, run an example,
break something, and go from there.