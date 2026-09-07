# All-Island Grid Kit

A ready-to-run PyPSA model of the Irish and Northern Irish transmission
network, built from EirGrid's **Ten Year Transmission Forecast Statement 2024**
study files, with a week of hourly profiles attached and six worked examples.

Everything here is a plain file. There is no build step, no database, no
Snakemake, and nothing to download at run time: the networks are in
`networks/`, and the only external thing you need is a Python environment.

---

## Five-minute quickstart

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python examples/a_dc_power_flow.py
```

That is the whole thing. The last command loads the 2033 winter-peak
all-island network, solves a least-cost dispatch with HiGHS, runs a DC power
flow, prints the ten most loaded circuits, and writes a map of the island with
every circuit coloured by how full it is to
`figures/a_flow_map_WP2033_all-island.png`.

Expect under a minute, most of it in the solver. Measured from a clean
virtual environment: 42 s for the quickstart, 19 s for `test_kit.py`.

In Python:

```python
import gridkit

gridkit.quiet()                            # PyPSA and HiGHS are chatty by default

n = gridkit.load("WP2033", "all-island")   # or "north-west"
print(gridkit.summary(n))

gridkit.solve(n)                           # n.optimize, with the solver log off
print(gridkit.dispatch_down(n).head())     # what the dispatch refused to take
print(gridkit.binding(n).head())           # which circuits were full, and for how long
```

---

## What is in the box

```
networks/           8 networks: 4 scenarios x 2 scopes, as .nc and as CSV
gridkit.py          load, modify, reset, and read results back
test_kit.py         checks on all of the above - run it before you trust a result
flowmath.py         PTDF, susceptibility and shift factors from the Laplacian
plotstyle.py        one look for every chart
examples/           six scripts, a to f
figures/            where they write their output - one of each is committed,
                    so you can see what to expect before you run anything
requirements.txt    pip only
```

### The eight networks

Four TYTFS scenarios, at two scopes:

| scenario | what it is |
|---|---|
| `WP2024` | winter peak, 2024 network |
| `SV2024` | summer valley, 2024 network |
| `WP2033` | winter peak, 2033 network - **start here** |
| `SV2033` | summer valley, 2033 network |

| scope | what it is |
|---|---|
| `all-island` | the whole 110 kV-and-above transmission system, both jurisdictions: 639-754 buses, 640-755 circuits, 203-225 transformers, the Moyle, EWIC and Greenlink DC links |
| `north-west` | Donegal, Sligo and north Mayo folded to 15 station-level nodes - EirGrid Wind Dispatch Tool constraint groups 1 to 3, with the rest of the system pinned at the boundary. Small enough to reason about by hand |

`WP2033` is the interesting one: 42.6 GW of connected capacity against an
8.8 GW peak. That is where constraint and dispatch-down actually bite, and it
is the case the hackathon is about.

Each network carries **168 hourly snapshots** - one week, centred on the hour
that matches its own TYTFS state (winter peak or summer valley). `n.meta`
records which scenario, which scope, and which snapshot is the anchor.

### The CSVs

Every network is written twice: as `networks/WP2033_all-island.nc` (netCDF,
what `gridkit.load` reads) and as `networks/WP2033_all-island/` (a folder of
CSVs, one per component). The CSVs are the same data. Open `lines.csv` in a
spreadsheet, change a rating, and read the folder back with:

```python
import pypsa
n = pypsa.Network("networks/WP2033_all-island")   # the folder, not the .nc
```

`generators-p_max_pu.csv` and `loads-p_set.csv` are the time series - one
column per component, one row per hour.

---

## The loader

```python
import gridkit

gridkit.catalogue()                     # what is available, with sizes
n = gridkit.load("WP2033", "north-west")

gridkit.add_line(n, "Meentycat", "Srananagh 220", s_nom=200)   # a new circuit
gridkit.remove_line(n, "3581-89516-1")                          # take one out
gridkit.set_rating(n, "2781-4951-1", 200.0)                     # reconductor
gridkit.add_battery(n, "Letterkenny", p_nom=50, hours=4)        # 50 MW / 4 h

n = gridkit.reset(n)                    # back to the shipped baseline
gridkit.save(n, "my_network.nc")        # or a folder name, for CSVs
```

`add_line` wants a reactance. Give it `x` in ohms if you have one, or `length`
in km and it will use 0.4 ohms/km - a rule of thumb for a 110 kV double
circuit, and nothing more. With neither, it takes the great-circle distance
between the two buses. Say which you used in anything you present.

Reading results back, after `n.optimize(...)`:

| | |
|---|---|
| `gridkit.line_loading(n)` | \|flow\| / rating, every circuit, every hour |
| `gridkit.binding(n)` | how many hours each circuit spent at its rating |
| `gridkit.dispatch_down(n)` | wind and solar offered, taken, and withheld |
| `gridkit.unserved(n)` | demand the network could not reach, per bus |
| `gridkit.freeze_dispatch(n)` | **read this one before you run `n.lpf()`** |
| `gridkit.solve(n)` | `n.optimize` with the solver log off |
| `gridkit.quiet()` | turns down PyPSA's and linopy's logging and warnings |

### Two traps, both already sprung

**`freeze_dispatch`.** `n.optimize()` writes its answer to `generators_t.p`.
`n.lpf()` reads `generators_t.p_set`, which is a different thing and which the
kit ships empty. Run `lpf` straight after `optimize` and you get a power flow
with no generation in it: the reference bus silently supplies the whole
island, and you will see a circuit at 1600% of its rating and wonder what you
broke. `gridkit.freeze_dispatch(n)` copies one into the other. Call it between
the two.

**Buses at 0 N 0 E.** PyPSA's netCDF writer turns a missing coordinate into
`0.0` rather than `NaN`, and 0 N 0 E is in the Gulf of Guinea. Plot the raw
`n.buses` and Ireland is squashed into a corner of an Atlantic-to-equator map.
Use `gridkit.placed_buses(n)`, which drops those and respects the
`coordinate_source` column.

---

## The six examples

Each runs standalone, takes `SCENARIO` and `SCOPE` on the command line, and
writes a figure.

```bash
python examples/a_dc_power_flow.py            WP2033 all-island
python examples/b_lopf_dispatch.py            WP2033 all-island
python examples/c_capacity_expansion.py       WP2033 north-west
python examples/d_ptdf.py                     WP2033 all-island
python examples/e_braess_susceptibility.py    WP2033 all-island
python examples/f_shift_factors.py            WP2033 all-island
```

**(a) DC power flow.** Dispatch, freeze, flow, and map it. Nothing is
optimised about the flow itself - the power divides between paths in inverse
proportion to reactance, and nothing consults the ratings. If the picture is
wrong here, nothing downstream is right.

**(b) LOPF, dispatch and dispatch-down.** Least-cost dispatch over the week,
generation by carrier, and the energy that was offered and refused. It then
separates the dispatch-down into two parts with one extra solve: lift every
rating out of the way and re-optimise, and whatever is *still* withheld is
**surplus-based** - more supply than the demand can absorb, which no network
could have taken. The difference is **constraint-based**, and it is what the
transmission actually cost. A large dispatch-down total on its own does not
mean the network is the problem, and in WP2033 most of it is not.

**(c) Capacity expansion.** Marks the binding circuits extendable, offers a
battery at every renewable bus, gives both an annualised cost, and lets the
optimiser trade building against dispatching down. The costs are round
numbers, not a price list - the point is the pattern.

**(d) PTDF from the pseudoinverse.** Builds `L = K B Kᵀ`, inverts it with the
Moore-Penrose pseudoinverse, and reads `PTDF = B Kᵀ L⁺` off it. Then checks
the result against a PyPSA power flow, branch by branch, and plots the two
against each other. A PTDF that has not been checked against a flow is a
matrix of plausible numbers - this one agrees to 1e-10 MW over 980 branches.

The check is what caught the network's two **phase-shifting transformers**,
one of them at 17°. A shifter imposes an angle of its own, so the flow on it
is `b(θᵢ − θⱼ − φ)` and the bus equation picks up a `K B φ` term - it behaves
exactly like a pair of equal and opposite injections. The PTDF is unaffected;
the flows are not. Ignore them and the reconstruction is out by 79 MW.

Why the pseudoinverse rather than deleting a slack row: `L` is singular
because adding a constant to every angle changes nothing. Deleting a row works
but writes the arbitrary slack into every number that comes out. `L⁺` returns
the solution orthogonal to that nullspace, which is the one where the
balancing megawatt is spread evenly - the choice has not disappeared, it has
become explicit, and `flowmath.shift_factors` lets you change it.

**(e) Edge-to-edge susceptibility, `dF_e/dB_e'`.** The full matrix of how each
circuit's flow responds to each circuit's susceptance:

```
dF_e/dB_e'  =  δ(e,e') · Δθ_e  −  B_e · (k_eᵀ L⁺ k_e') · Δθ_e'
```

The off-diagonal term is where **Braess's paradox** lives: a positive entry
means that strengthening `e'` puts *more* power on `e`. The script picks the
strongest such candidate, actually doubles that branch's susceptance,
re-solves the flow, and prints what happened - the derivative is a claim and
the script tests it.

**(f) Shift factors, the Wind Dispatch Tool calculation.** For one monitored
circuit, how much of each generator's output that circuit carries; the
constraint group that follows from ranking them; and the MW of relief each
member could offer. Printed under three references - load-weighted, uniform,
and single-bus - because a shift factor is undefined until you say where the
balancing megawatt goes. The values differ. The ranking barely does, which is
why the method is robust enough to run a real dispatch tool on.

---

## Checking it still works

```bash
python test_kit.py        # about 20 seconds; pytest works too, if you have it
```

Twenty checks on the eight networks, the loader and the linear algebra.
Two of them are the ones that matter: the PTDF is rebuilt into branch flows
and compared against PyPSA's own power flow, and the susceptibility matrix is
compared against finite differences on a perturbed susceptance. Both agree to
better than 1e-6. If you change anything in `flowmath.py`, run this.

---

## Limitations

Read this section before you present anything.

**This is a DC approximation of an AC model.** The TYTFS files are full AC
load-flow cases with reactive power, voltage magnitudes, tap changers and
shunt compensation. Everything here throws that away: flows are linear in
angle differences, voltages are 1.0 pu everywhere, and losses are zero. That
is the standard approximation for network-constraint work at transmission
voltages and it is good to a few percent on real flows, but it cannot tell you
anything about voltage, reactive support, or stability - and a "solution" that
depends on those is not supported by anything in this kit.

**Line lengths are placeholders.** The TYTFS raw files carry a `LEN` field
that is zero or nominal for most branches. Lengths in `lines.csv` are
therefore not survey distances, and neither are any per-km costs or
great-circle estimates derived from them. Impedances are real - they come from
the file, in per-unit on a 100 MVA base - and it is the impedances, not the
lengths, that determine the flows.

**Ratings are TYTFS `RATE1` values, not operational limits.** `s_nom` is the
`RATE1` column, which is the continuous rating. A real control room works to
seasonal, weather-dependent and often dynamic limits that are not in these
files, and it runs circuits above `RATE1` for defined periods under `RATE2`
and `RATE3`. Eighteen transmission branches carry a 9999 MVA placeholder in
the file rather than a rating; those are shipped as-is except where a branch
is a zero-impedance busbar coupler, where a bound was inferred from the
elements it connects. A circuit at "100% of rating" here means 100% of a
planning number.

**Every time series is synthetic.** TYTFS gives four snapshots, not time
series. The 168 hourly profiles in these networks were generated: spatially
correlated wind from a Gaussian random field with an exponential correlation
decay, a documented panel model for solar, and a winter-weekday demand shape
scaled per bus by that bus's TYTFS load. They are anchored so that each
network's own scenario hour reproduces the TYTFS state, and the spatial
correlation is measured back off the output rather than assumed. They are
*not* a historical year, they are not a forecast, and no individual hour in
them ever happened. Wind and solar generators without a geocoded site of their
own borrow the nearest profile of the same carrier, which makes those pairs
perfectly correlated when they should not be.

**Dispatch-down is not curtailment.** `gridkit.dispatch_down` reports wind and
solar that was offered and not taken. That is plain economic dispatch-down,
and it splits into **constraint-based** (stranded behind a binding line rating)
and **surplus-based** (more supply than the demand can absorb). It is *not*
curtailment in the SEM/EirGrid sense: real curtailment is a system-wide,
pro-rata reduction ordered to respect an SNSP or an inertia limit, and this
model carries no SNSP constraint, no inertia constraint and no unit
commitment. Nothing in the kit reproduces EirGrid's curtailment mechanism, so
do not compare a number from here against a published curtailment figure.

**Costs are placeholders, and renewables bid negative.** Marginal costs are
per-carrier round numbers, not a fuel price stack: gas 90, biomass 40, hydro 1,
imports 150 EUR/MWh, and wind and solar at **−1 EUR/MWh**. The negative bid is
deliberate - it is how a support scheme makes a wind farm willing to pay to
stay on, and it is what makes dispatch-down a last resort in the optimisation
rather than a free choice. It also makes the objective come out negative, so
only *differences* between two objectives mean anything.

**About a fifth of the generation carries the carrier `unknown`.** Carriers are
inferred from the bus name - `W_` for wind, `PV_` for solar, `HY_` for hydro,
and a keyword list for the rest - and the TYTFS files do not label plant by
technology. What lands in `unknown` is mostly conventional thermal. Treat any
result that turns on the split between `gas` and `unknown` as unsupported.

**Coordinates are matched, not authoritative.** Bus locations were matched
against OpenStreetMap substations by name. About 87% of transmission buses
matched and carry `coordinate_source = "geocoded"`; three-winding transformer
star points sit at their own station; the rest were placed at the mean of
their neighbours **for drawing only** and have `has_coordinates = False`.
Check that column before using a coordinate for anything but a picture.

**The DC links are simplified.** Moyle, EWIC and Greenlink are PyPSA `Link`
components with a fixed efficiency and no ramp limits, no minimum stable
export, and no market coupling. Interconnector flow in these results is what
the cost assumptions make of it, not what the day-ahead market would do.

**The TYTFS data is EirGrid's, and is provided by EirGrid for reference
purposes only.** It describes a planning forecast, not the operational system,
and EirGrid publishes it without warranty as to accuracy or fitness for any
particular purpose. Nothing in this kit is an EirGrid product, an EirGrid
position, or a statement about how the transmission system will actually be
built or operated. Anything you conclude here is yours.

---

## If something goes wrong

**`FileNotFoundError` on a network.** The kit ships eight; if one is missing
the download is incomplete. `gridkit.catalogue()` lists what should be there.

**The solver says infeasible.** Every load bus carries a `shed <bus>`
generator at a Value of Lost Load of 10,000 EUR/MWh, so a shortfall shows up
as expensive unserved energy rather than as a failed solve. If you still get
infeasible, you have added a constraint that no dispatch satisfies - a
`p_min_pu` above a `p_max_pu` is the usual one. Check
`gridkit.unserved(n)` first.

**A circuit at 1600% of its rating.** See `freeze_dispatch`, above.

**A map of the Atlantic with Ireland in the corner.** See `placed_buses`,
above.

**`solver_name="highs"` not found.** `pip install highspy`. Note that the PyPI
package called `highs` is something else.
