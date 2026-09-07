# Phase 2: the TYTFS cases as PyPSA networks

`pypsa_net.py` turns each of the four PSS/E v35 cases `psse.py` reads into a
`pypsa.Network`, at a chosen voltage floor, exported in PyPSA's own CSV folder
format. `geocode.py` puts coordinates on the transmission buses from
OpenStreetMap. `test_pypsa_net.py` and `test_geocode.py` guard both.

Every conversion decision is below with the measurement it was made on. They
are written down because most of them are invisible afterwards: a per-unit
base out by a factor, a rating column chosen wrongly, a reference bus in the
wrong place — none of those stop a network from solving, and all of them move
every number built on top of it.

```bash
python geocode.py fetch                     # Overpass -> data/raw/
python geocode.py candidates                # -> data/osm_substations.csv
python geocode.py match data/TYTFS2024_studyfiles/*_V35.raw
python pypsa_net.py build                   # -> data/pypsa/<case>_<scope>/
python pypsa_net.py verify                  # connectivity, DC PF, LOPF
python -m pytest test_pypsa_net.py test_geocode.py
```

---

## 1. The per-unit base is 100 MVA, and it is read rather than assumed

**Confirmed.** Every one of the four cases opens with

```
0,  100.00, 35,     1,     1, 50.00     / PSS(R)E-35.6 ...
    ^SBASE  ^REV  ^XFRRAT ^NXFRAT ^BASFRQ
```

`SBASE = 100.00` MVA, `BASFRQ = 50` Hz. `pypsa_net.build()` asserts it against
`SYSTEM_MVA` and refuses a case on any other base, because a case on a 200 MVA
base would produce a network that solves and whose every impedance is out by
exactly two.

PSS/E branch `R`, `X` and `B` are per-unit on that base and on the bus's base
kV. PyPSA wants two different things, so there are two conversions and they
live in one function each:

| | PyPSA units | conversion |
|---|---|---|
| `Line.r`, `Line.x` | ohms | `R_pu × kV² / 100` |
| `Line.b` | siemens | `B_pu × 100 / kV²` |
| `Transformer.r`, `.x` | pu on the transformer's own `s_nom` | `X_pu × s_nom / 100` |

A 110 kV line with 0.01 pu of reactance is 1.21 Ω; a transformer's ohms are
unchanged by the rebase, which is what `test_transformer_impedance_survives_the_rebase`
checks.

Transformer records carry their own convention flags, and all four cases use
the same ones: `CW = 1` (winding ratios in pu of the bus base kV, so the tap
ratio is `WINDV1 / WINDV2` with no conversion), `CM = 1`, and `MAG1 = MAG2 = 0`
throughout, so there is no magnetising branch to carry. `CZ = 1` on all but two
records, which are `CZ = 2` — impedance on the winding's own MVA base — and are
rebased by `100 / SBASE1_2`. They are the East-West and Greenlink converter
transformers, both on a 582 MVA base. `CZ = 3` would be a load loss in watts
rather than an impedance; it does not occur, and it raises rather than being
guessed at.

**One nuance that is worth knowing and does not change anything here.**
`NXFRAT = 1` and `XFRRAT = 1` mean the ratings are "current expressed as MVA",
so the MVA limit at a bus voltage of *V* pu is `RATE × V` rather than `RATE`.
At 1.0 pu they are the same number, and PyPSA's `s_nom` is a fixed MVA limit
with no voltage in it, so `RATE1` is taken at face value. A study that cares
about the difference at 0.95 pu has to apply it itself.

---

## 2. `RATE1` is `s_nom`, and RATE1/2/3 are normal / LTE / STE

**RATE1, RATE2 and RATE3 are populated; RATE4–RATE12 are empty in all four
cases.** What they are is settled by two facts about the data:

- `RATE1 == RATE2` in **every one of the 1,129 branch records, in every
  case**. Not approximately — exactly.
- `RATE3 / RATE1` takes exactly two values: 1.0 and 1.1. (One summer-case
  circuit comes out at 1.10021, which is the rating having been rounded before
  the ratio was taken.) In WP2024, 963 branches are at 1.1 and 166 at 1.0.

That is the standard PSS/E RATEA/RATEB/RATEC triple — **normal, long-term
emergency, short-term emergency** — with the long-term emergency rating not
distinguished from the normal one, and the short-term emergency rating set at
110% of normal where it is distinguished at all. It is not a seasonal triple:
winter and summer ratings are never equal, and these two are.

The magnitudes corroborate it. Median `RATE1` by voltage in WP2024:

| kV | circuits | median RATE1 | implied current |
|---|---|---|---|
| 110 | 542 | 125.5 MVA | 659 A |
| 220 | 92 | 562 MVA | 1,475 A |
| 275 | 23 | 881 MVA | 1,850 A |
| 380 | 4 | 1,226 MVA | 1,862 A |

Those are continuous circuit ratings, not emergency ones.

**Decision: `s_nom = RATE1`.** `s_nom` is a continuous limit in every use PyPSA
puts it to — the LOPF binds on it at every snapshot — so it has to be the
continuous rating. A contingency study wanting the short-term rating should use
`s_max_pu = 1.1`, and the network is exported with `s_max_pu = 1.0` so that
doing so is a visible change rather than a default.

---

## 3. The unrated elements: 9999 and 0 both mean "no limit stated"

**18 AC branches at 110 kV and above carry no rating in WP2024: 9 at `RATE1 =
9999` and 9 at `RATE1 = 0`.** Both are PSS/E's ways of saying nothing, and 0 is
the more dangerous of the two because it looks like a number — put into `s_nom`
it makes the element unusable and the optimisation infeasible.

What they actually are settles the treatment. All 18:

```
 I     name            J      name           R      X       B    LEN
4961  SHANKILL      49662  MOB_CAP          0.0  0.0001   0.0   0.0
3934  MNYPG1         3944  MONEYPOINT       0.0  0.0001   0.0   0.0
4462  POOLBEG NORT  44661  PBEG REACTOR     0.0  0.0001   0.0   0.0
28710 CLOGHER       28712  CLOGHER          0.0  0.0001   0.0   0.0
74511 CAST1A        74512  CAST1B           0.0  0.0001   0.0   0.0
1661  CASTLEBAR     16662  CBAR_SVC         0.0  0.0100   0.0   0.0
 ... 12 more, all R = 0, |X| <= 0.01, B = 0, LEN = 0
```

Every one is a **station coupler**: a busbar section (CAST1A–CAST1B, the two
CLOGHER buses), a capacitor, reactor or SVC stub (MOB_CAP, PBEG REACTOR,
CBAR_SVC), or a generator terminal tie (MNYPG1–MONEYPOINT). Not one is a
circuit whose rating was forgotten. `test_the_eighteen_unrated_transmission_branches`
pins that, because if it ever stops being true the rule below is the wrong rule.

**Decision, in two parts.**

*A coupler is bounded by what is attached to it.* A busbar section can carry no
more than the weaker of the two sides it joins can deliver, so `s_nom` is the
smaller of the two ends' summed rated incident capacity. That is a real limit
rather than a number chosen to be large, and the case's own solved flows fit
inside it everywhere — `verify` reports `dc_pf_inferred_limits_exceeded`, which
is 0 for all four cases at both scopes.

*Everything else keeps the file's 9999.* Those are the sub-110 kV distribution
transformers, 1,164 of them, and there is no honest way to infer a rating for a
110/38 kV transformer from the feeders leaving the 38 kV bus — load taps off
that bus directly, so the feeders bound nothing. This rule was arrived at by
trying the other one: bounding them the same way produced limits that bind on
the case's own solved flows on 13 transformers, the worst at 156% of the bound
it had been given, and made the full network's LOPF infeasible.

Both are listed for every element in `reports/rating_exceptions.csv` with which
rule applied and why.

**One thing this makes possible to say cleanly:** *every* transformer with both
ends at 110 kV and above carries a real rating — all 11 of them, in every case.
The 9999 placeholder does not reach the transmission network at all except
through generator step-up transformers, which are dead ends.

---

## 4. The sub-110 kV tail: a flag, and a reduction rather than a filter

`build(case, min_kv=...)`. `110` gives the transmission network, `0` gives the
case as it stands. Both are exported for every case.

**The measurement that decides how the floor works.** In WP2024:

| | at ≥110 kV | below 110 kV |
|---|---|---|
| in-service generation | 0 machines, 0 MW | 87 machines, 7,412 MW |
| in-service load | 2 records, 14 MW | 230 records, 7,310 MW |

**100% of generation and 99.8% of demand sits below 110 kV.** A transmission
network built by dropping those buses is empty. So the floor is a reduction:
sub-threshold buses go away and their machines and demand move to the retained
bus nearest them.

"Nearest" is the least total series reactance along a path that stays inside
the dropped part of the network. Paths through another retained bus do not
count — a load reached only by going through a second transmission station
belongs to that station. Where a dropped component touches more than one
retained bus (137 of WP2024's 518 sub-threshold components do, carrying 23% of
demand between them) the least-reactance one wins and the runner-up and the
ratio between them are both recorded, in `reports/aggregation.csv`, so the
arbitrariness is visible rather than averaged away.

**What the floor costs, measured.** Both scopes were built, a DC power flow run
on each, and the flows compared on the 645 circuits they share:

| | |
|---|---|
| shared circuits | 645 |
| mean absolute difference | 2.39 MW |
| circuits differing by more than 1 MW | 93 |
| worst | 53.5 MW, on the Ballylumford–Eden 110 kV circuit |

The reduction is exact wherever the sub-threshold network is radial, which is
most of it, and shifts flows by tens of MW where it is not. `compare_scopes()`
reproduces the table.

**What the transmission network comes out as.** 547 buses at the four
transmission voltages, plus the East-West (260 kV) and Greenlink (150 kV)
converter buses which are above the floor by base kV, less COLE1_CAP which
PSS/E marks isolated (`IDE = 4`) — **548 buses, 547 of them in one AC island**,
the 548th being SCOTLAND, which is joined to nothing but the Moyle DC link.
Add 95 star buses from the three-winding transformers and PyPSA sees 643 in the
main sub-network.

Three-winding transformers are the reason a naive filter would not have worked
even for topology. Only 11 two-winding transformers have both ends at ≥110 kV;
the 220/110 kV transformation is almost entirely in the **97 three-winding
transformers** whose first two windings are at transmission voltage and whose
tertiary is at 10.5–22 kV. Drop those and the 220 kV and 110 kV networks come
apart.

---

## 5. Three-winding transformers become a star bus and three legs

PyPSA has no three-winding transformer. Each record becomes the textbook star
equivalent — a new bus at the star point and one two-winding transformer per
winding — with

```
Z1 = (Z12 + Z31 - Z23) / 2
Z2 = (Z12 + Z23 - Z31) / 2
Z3 = (Z31 + Z23 - Z12) / 2
```

all on the system base. Winding 1's leg reactance comes out **negative in 24 of
WP2024's 109 records**, which is what an autotransformer's star equivalent
does, and it is carried through as it stands rather than clamped. The star bus
takes winding 1's base kV, which is what the record's `VMSTAR` is expressed on,
and the record's solved star voltage and angle are carried onto it.

A leg whose end bus is below the floor is dropped, which leaves the star as a
two-leg pass-through — the exact two-winding equivalent of the original
transformer between those two windings. A star with fewer than two surviving
legs is dropped entirely.

---

## 6. The DC links: Moyle, EWIC and Greenlink, all as PyPSA `Link`s

The case models the island's three interconnectors in **two different ways**,
and anything that looks only at the two-terminal DC section sees one of them.

**Moyle** is the DC section, twice — one record per pole, both from bus 86221
SCOTLAND to bus 86220 BALLYCRO, `MDC = 1` (power control), `SETVL = 40` MW
each, `VSCHD = 250` kV, `RDC = 2.0956` Ω. SCOTLAND has **no AC branch and no
transformer**: it is an island of one bus tied to the network only by the link,
and it carries `IDE = 3`, so it is the swing bus that supplies whatever Moyle
draws.

**East-West** (bus 54630, `EASTWEST`, 260 kV) and **Greenlink** (bus 36671,
`GREENLINK`, 150 kV) are PV buses with a generator record and no far terminal
at all. Their generator records are `STAT = 0` in WP2024 — 954 MW of idle
import capacity between them.

**Decision: all three become `Link`s.** An interconnector is a controllable flow
on a branch, not a machine, and modelling it as a generator loses the fact that
it can run backwards. Ratings come from the case's own generator record at the
converter bus: `PT` for import, `|PB|` for export.

| link | bus0 | bus1 | p_nom | p_min_pu | p_max_pu | efficiency | p_set |
|---|---|---|---|---|---|---|---|
| Moyle pole 1 | 86221 SCOTLAND | 86220 BALLYCRO | 250 MW | −1 | 1 | 0.9916 | 40 MW |
| Moyle pole 2 | 86221 SCOTLAND | 86220 BALLYCRO | 250 MW | −1 | 1 | 0.9916 | 40 MW |
| EWIC | GB_EWIC | 54630 EASTWEST | 530 MW | −1 | 0.943 | 1.0 | 0 |
| Greenlink | GB_GREENLINK | 36671 GREENLINK | 530 MW | −1 | 0.951 | 1.0 | 0 |

Moyle's efficiency is the DC line's own `I²R` loss at rated power, 0.84% per
pole, computed from `RDC` and `VSCHD`. It is optimistic: converter losses are
not in the record and are not invented, so it is short by roughly 0.7% per
station. EWIC and Greenlink have no loss data at all and are left lossless,
which is stated rather than hidden.

The two missing far terminals are **created** — `GB_EWIC` and `GB_GREENLINK` —
because a link needs two buses. Each far terminal carries two components rather
than one bidirectional machine: an **import generator** priced above every
domestic carrier, and an **export sink** (`sign = -1`) that buys at
`export_price`, default zero. One bidirectional generator would be simpler and
wrong: a machine with a positive marginal cost and a negative output is *paid*
to run backwards, and the first version of this exported 1,223 MW in the LOPF
for exactly that reason.

---

## 7. The reference bus

**The case names its own.** Five buses carry `IDE = 3`: the four Turlough Hill
machine terminals (52071–52074, 10.5 kV) and SCOTLAND (86221, 275 kV).

The rule is: honour them where they survive the voltage floor; where a swing
bus has been aggregated away, the role goes to whatever absorbed it; where a
sub-network keeps no `IDE = 3` bus at all, the bus carrying the most in-service
generation takes it. Every choice, and which of the three rules made it, is in
`reports/slack.csv`.

That gives one reference per AC sub-network — four of them, because SCOTLAND
and the two created far terminals are each their own AC island by construction.
In the transmission network the Turlough Hill reference moves to bus 5202,
TURLOUGH HIL 220 kV, which is where its machines aggregate to.

**This one is not cosmetic, and it took a bug to find out.** Determining the
topology makes PyPSA choose a slack of its own — the first generator in each
sub-network — and in WP2033 that is a 21 MW hydro unit at Ardnacrusha sitting
behind its own step-up transformer. A lossless DC flow has nowhere to put the
case's 198 MW generation-minus-demand gap except the reference, so that one
machine absorbed the lot: 856 MW through a 21 MW step-up, an angle of 172°
across it, and the whole network's angles thrown out by up to 100°. Assigning
the reference as a whole column, after the topology has been determined, is
what fixes it. Before: angle correlation against the case's own solved angles
of 0.90. After: 0.99.

**A consequence worth stating.** The reference still absorbs the case's whole
imbalance — 87 MW in WP2024, 198 MW in WP2033 — because that gap is AC losses
and a lossless model has no losses to spend it on. `verify` reports it as
`dc_pf_slack_mw`. The reference machine's own terminal angle is therefore not
comparable with the case's, which is why the angle check centres on the median
rather than the mean.

---

## 8. What is not carried

**Shunts.** `psse.py` skips the fixed shunt and switched shunt sections, so
this network has no reactive compensation. A full AC power flow will not
reproduce the case's voltages. DC power flow and LOPF ignore reactive power
entirely and are unaffected. The capacitor and reactor buses are still there
as dead ends carrying no injection, which is harmless in a linear flow and is
where their coordinates come from in the geocoding.

**Out-of-service elements.** The network is built from in-service records only
— branch `STAT = 1`, transformer `STAT ≠ 0`, generator and load `STAT = 1`.
WP2024's branch register holds 1,129 circuits of which 50 are out; its
generator register holds 597 machines of which 87 are running. The counts of
what was dropped are in the reports.

**Costs and carriers.** The raw format has neither. Carriers are inferred from
the file's own naming convention — `W_` for wind, `PV_` for solar, `HY_` for
hydro, `CCGT`/`OCGT` for gas — which reaches 29 of WP2024's 87 in-service
machines and leaves the rest as `unknown`. Marginal costs are placeholders that
exist so an LOPF is a well-posed problem with a merit order in roughly the
right order. They are written into the exported CSVs so that whatever a study
does with them, it is doing it to numbers it can see.

**`p_set` is a constraint in PyPSA 1.x.** The network carries the case's own
dispatch — `p_set` on each generator is that machine's `PG` — because that is
what makes `n.lpf()` reproduce the case rather than invent a new one. But
`optimize()` turns a non-null `p_set` into an equality that pins the variable,
so an optimisation run straight off this network is the case's dispatch,
asserted, and it is infeasible for the good reason that the case's dispatch is
an AC solution carrying 87 MW of losses that a lossless model has nowhere to
put. `for_optimisation(n)` returns a copy with the dispatch released; `verify`
uses it, and `test_releasing_the_dispatch_is_what_makes_an_optimisation_possible`
pins both halves.

---

## 9. Verification

`python pypsa_net.py verify` — all four cases, both scopes, all pass.

| | connected | DC PF | overloads | angle corr | angle sd | LOPF |
|---|---|---|---|---|---|---|
| WP2024 transmission | yes | solved | 0 | 0.9961 | 0.93° | optimal |
| WP2024 full | yes | solved | 1 | 0.9915 | 1.19° | optimal |
| SV2024 transmission | yes | solved | 0 | 0.9987 | 0.36° | optimal |
| SV2024 full | yes | solved | 0 | 0.9963 | 0.61° | optimal |
| WP2033 transmission | yes | solved | 4 | 0.9907 | 1.94° | optimal |
| WP2033 full | yes | solved | 6 | 0.9048 | 4.35° | optimal |
| SV2033 transmission | yes | solved | 0 | 0.9977 | 0.25° | optimal |
| SV2033 full | yes | solved | 1 | 0.9939 | 0.40° | optimal |

**Connectivity.** One AC island of 547 transmission buses, plus SCOTLAND and
the two created far terminals, each of which is its own AC island because a DC
link never joins two synchronous areas. Counting links as edges, every network
is one connected graph.

**The angle check is the real verification of the conversion.** The raw file
records the solved voltage angle at every bus, so the conversion can be checked
against the case rather than against itself: if the reactances, the star
equivalents or the phase-shift signs were wrong, a linear flow's angles would
not track them. Measured over the transmission buses, with the reference offset
removed at the median, the correlation is 0.99 or better in seven of the eight
networks and the spread is under 2°. That is a DC flow against an AC solution,
so exact agreement is not the expectation — tracking is.

**The overloads are a finding, not a failure.** WP2033's own dispatch,
evaluated as a lossless DC flow, exceeds `RATE1` on four transmission circuits,
the worst at 2.0× on Killonan–Singland 110 kV. All four are `RATE1`-rated
circuits, not elements this module gave a bound to — `dc_pf_inferred_limits_exceeded`
is 0 everywhere. Two things separate a DC flow from the case's AC one here: the
reference bus absorbing 196 MW at one point, and the 110% short-term rating the
case may be dispatching against. Neither is checked here, and the numbers are
reported rather than tuned away.

**LOPF** solves to optimality with HiGHS on all eight, on the dispatch-released
copy. In WP2024 it lands on total generation exactly equal to demand (7,324.5
MW, lossless) with zero net exchange, because no network constraint binds and
the problem reduces to a merit-order dispatch.

---

## 10. Geocoding: 87% of buses placed, and every failure named

Bus records have no coordinates, and the only thing to join on is a
twelve-character name. `geocode.py` downloads every named `power=substation`
and `power=plant` on the island from Overpass — 1,705 named objects, of which
367 substations carry a voltage tag of 110 kV or more — and matches them
against the station names of the buses at 110 kV and above.

**Nothing is interpolated, averaged or guessed.** A station this cannot match
gets no coordinate, and is reported by name with the candidate it rejected and
why.

Buses are grouped into stations first, by `pypsa_net.station_of()`, because a
station's busbar sections are one place.

### The result, WP2024

431 stations, 549 buses. **370 stations (85.8%) and 479 buses (87.2%) placed.**

| method | stations | buses | what it means |
|---|---|---|---|
| `exact` | 239 | 309 | normalised names equal, voltage tag agrees |
| `coupled` | 48 | 53 | joined to a placed bus by a coupler or the station's own transformer |
| `ni-code` | 36 | 60 | Northern Ireland contraction resolved by subsequence |
| `truncated` | 15 | 19 | the twelve-character name is a prefix of exactly one candidate |
| `fuzzy` | 12 | 13 | token-sort score ≥ 92 with ≥ 6 points over the runner-up |
| `prefix` | 9 | 10 | ≥ 6-character prefix of exactly one candidate, voltage agrees |
| `alias` | 6 | 6 | resolved by hand, with the reasoning recorded |
| `ni-site` | 3 | 6 | the same NIE site at its other voltage class |
| `exact-name` | 2 | 3 | names equal, candidate carries no voltage tag |
| **failed** | **61** | **70** | see below |

Voltage is corroboration, not a key: OSM's `voltage` tag is present on 367 of
the island's named substations and absent on the rest, so a voltage that agrees
raises confidence, a missing one does not lower it, and a contradicting one
rejects the match. 303 of the placed stations have a voltage tag that agrees.

### The cross-check: 134 stations, median separation 14 metres

The matching has one source and one join key, so it can be confidently wrong.
EirGrid publishes its own station layer with names and coordinates and this
repo already holds it — 161 stations at 110 kV and above in
`data/eirgrid_transmission.gpkg`. 134 of the placed stations are in it too:

| | |
|---|---|
| median separation | **0.014 km** |
| 95th percentile | 0.25 km |
| more than 5 km apart | **1** |

The one disagreement is TANDRAGEE, at 36.3 km, and it is EirGrid's: its
register puts the station at the Republic's end of the Louth–Tandragee 275 kV
interconnector, in Co. Louth, while the substation itself is in Co. Armagh
where OSM has it.

### The three hard cases

**Cathaleen's Fall** *is* in TYTFS — as `CATH_FALL` and `CATH FALL`, because
the name does not fit in twelve characters, plus `CATH_CAP` for its capacitor.
It is in OSM too, spelled **Cathleen's Fall**, without the second 'a'. Neither
spelling reaches the other by truncation or by fuzzy matching, so it is in the
alias table with that reasoning written beside it, and `CATH_CAP` is placed
from it through the coupler that joins them. ESB's own spelling is Cathaleen's
Fall; OSM's is Cathleen's Fall; the station is one station either way.

**Clady** is not in TYTFS under any name, and this is not a naming problem.
OSM has it as *Clady 38kV Substation* alongside *Clady Hydroelectric Station*,
both at 55.038 N, 8.272 W in Gweedore, Co. Donegal, and both at **38 kV**. A
38 kV ESB Networks station is below the transmission model's floor: TYTFS
carries the sub-110 kV network only as the stub that load and small generation
hangs off, and Clady's four megawatts do not earn a bus of their own. It is
absent because it is distribution.

**Clogher** is four 110 kV buses in TYTFS — 2870, 2871, 28710 and 28712 — and
one substation in OSM, *Clogher 110kV Substation*, in Co. Donegal at 54.687 N,
7.995 W. The four are busbar sections of the same site, which is exactly what
the 28710–28712 zero-impedance coupler in the branch section says: split
busbars are an electrical arrangement, not four places. All four get the same
coordinate. EirGrid's own register corroborates it, with a CLOGHER station at
110 kV.

### Two rules that are worth stating on their own

**The NIE contraction.** Northern Ireland's transmission buses are named with a
four- or five-letter contraction and a digit: `ANTR1A`, `BAFD2-`, `MAGF2-`,
`KILL1-CL`. The letters are a *subsequence* of the station's name rather than a
prefix — BAME is Bally**me**na, BNCH is Bally**n**a**ch**inch, MAGF is
**Mag**hera**f**elt — so no amount of fuzzy string matching reaches them. They
are matched by subsequence instead, resolved by how tightly the letters sit
(LARN is Larne's first four letters and is scattered over nine of Lisnabreeny),
and **the digit is the voltage class**: 1 is 110 kV and 2 is 275 kV, which
holds for every pair the cases contain — BAFD1/BAFD2, CAST1/CAST2, COOL1/COOL2,
KELS1/KELS2, HANA1/HANA2. That gives 36 stations by name and 3 more from their
own other voltage level, where OSM maps only one of the two.

**Coupling.** A capacitor, reactor, SVC or phase-shifter bus carries a name of
its own — `MOB_CAP`, `CATH_CAP`, `PBEG REACTOR`, `ENNK_PST`, `CBAR_SVC` —
which no name match will ever reach, because it is not the name of a place. Two
connections put two buses inside the same fence and neither is a name: a
zero-impedance branch, which is a coupler or a device stub; and a transformer
between two buses both at 110 kV or above, which is the station's own
transformer standing in its yard. Together they place 48 stations that no
amount of string matching would have.

### The 61 failures

Every one is in `data/pypsa/geocoding/<case>.csv` with its method, its best
rejected candidate and the score, and `python geocode.py report` prints them
all. By kind:

- **55 `weak`** — nothing scored above 92. Most are genuinely not in OSM:
  Fassaroe East and West, Finglas B5, Inch City and Inch Country, Seal Rock,
  Yellowmeadow. OSM has 367 substations tagged at ≥110 kV against TYTFS's 431
  stations, so a residue is expected.
- **3 `ambiguous`** — two candidates that cannot be separated. DRUM1 sits
  equally tightly in *Drumnakelly* and *Drumlins Park Wind Farm*; GLEN1 in
  *Glenconway* and *Glengormley*.
- **2 `voltage-contradicts`** — the only name match is at the wrong voltage
  class. COOLNANOONAG's only OSM namesake is tagged 33 kV.
- **1 `deliberately-unplaced`** — SCOTLAND, the GB end of Moyle. It is a
  boundary bus, not a place in Ireland, and it is left without a coordinate
  rather than being put at Auchencrosh.

The 2033 cases place 78% rather than 87%, and the difference is the
reinforcement the forecast statement is for: stations that do not exist yet are
not in OpenStreetMap.

---

## 11. The CSV schema

One directory per case per scope, `data/pypsa/<case>_<scope>/`, in **PyPSA's own
CSV folder format** — `pypsa.Network(<directory>)` reads it straight back with
nothing lost and no reader of its own.

### The network

| file | rows (WP2024 transmission) | columns beyond PyPSA's own |
|---|---|---|
| `network.csv` | 1 | — |
| `snapshots.csv` | 1 | — |
| `buses.csv` | 646 | `psse_name`, `station`, `psse_type`, `area`, `zone`, `jurisdiction`, `v_ang_psse`, `geocode_method`; `x`/`y` are longitude and latitude |
| `lines.csv` | 645 | `s_nom_source`, `psse_ckt` |
| `transformers.csv` | 203 | `s_nom_source`, `psse_ckt` |
| `links.csv` | 4 | — |
| `generators.csv` | 93 | `psse_bus`, `psse_bus_name`, `aggregated` |
| `loads.csv` | 232 | `psse_bus`, `psse_bus_name`, `aggregated` |
| `carriers.csv` | 8 | — |
| `sub_networks.csv` | 4 | — |

Names are the PSS/E bus number for a bus (`1701`), `I-J-CKT` for a line
(`1021-2121-1`), `T` plus the same for a transformer, `star:I-J-K-CKT` for a
three-winding star bus and `-w1`/`-w2`/`-w3` for its legs, and `I-ID` for a
generator or load. Every one is traceable back to the record it came from, and
`psse_name` carries the human name the number stands for.

`s_nom_source` says where each limit came from: `RATE1`, `station coupler,
bounded by the weaker end`, or `no rating in the file and none inferable; kept
the file's 9999`. `aggregated` says whether a machine or a load was moved by
the voltage floor. `v_ang_psse` is the case's own solved bus angle, kept so
that the angle check can be redone at any time.

### The reports

`reports/README.csv` lists them, with what each one answers.

| file | rows | answers |
|---|---|---|
| `aggregation.csv` | 1,488 | every bus below the floor, the retained bus its load and generation moved to, the reactance to it, the runner-up and the margin |
| `rating_exceptions.csv` | 1,334 | every element the file left unrated, what it actually is, and the bound it was given |
| `severed.csv` | 1,758 | every element dropped because an end is below the floor |
| `slack.csv` | 4 | the reference bus of each AC sub-network and why |
| `links.csv` | 4 | the interconnectors, their ratings, and which representation each came from |
| `orphans.csv` | 0 | records whose bus survived neither the floor nor the aggregation |
| `geocoding.csv` | 549 | one row per bus: the match, its method and confidence, and a reason for every failure |

### Alongside

| file | what |
|---|---|
| `data/osm_substations.csv` | the 1,705 named OSM objects the matching runs against, committed so the matching is reproducible without a network round-trip |
| `data/pypsa/geocoding/<case>.csv` | the per-bus geocoding result |
| `data/pypsa/geocoding/<case>_crosscheck.csv` | the comparison against EirGrid's own station coordinates |

---

## 12. What a downstream model should know

- **Say which scope you are using.** The two differ by up to 53 MW on shared
  circuits, and the transmission one has had 23% of demand assigned to a
  station by a rule rather than by the file.
- **`p_set` pins the dispatch.** Release it before optimising, or you are
  asserting the case's answer rather than solving for one.
- **Costs are placeholders.** They are in the CSVs. Replace them.
- **There is no reactive compensation.** Do not run a full AC power flow and
  expect the case's voltages.
- **70 buses have no coordinate.** They are named in the geocoding report. Do
  not fill them in by interpolation without saying so.
- **`s_nom` is the continuous rating.** The short-term emergency rating is 1.1×
  it, and applying it is `s_max_pu`, not a different `s_nom`.
