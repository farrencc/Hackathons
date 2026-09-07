# Phase 3: the North-West subnetwork, and the 15-node dataset

`northwest.py` extracts the North West — EirGrid's Wind Dispatch Tool
constraint groups 1–3 — from a TYTFS case in two views, and reconciles it
against the hand-built dataset in `data/handbuilt/`. `test_northwest.py`
guards it.

```bash
python northwest.py circuits     # the circuit table, both views
python northwest.py balance      # capacity, dispatch, demand, boundary flow
python northwest.py extract      # -> data/pypsa/northwest_<case>_<view>/
python northwest.py verify       # connectivity, DC PF, LOPF, agreement
python northwest.py windy        # the region with its wind running
```

The hand-built files are committed alongside, because everything below is a
comparison against them:

| file | what |
|---|---|
| `data/handbuilt/nodes.xlsx` | the node list, in two blocks: 24 nodes with generation as nodes of its own, then a "substation-only nodal representation" of 15 |
| `data/handbuilt/transmission.xlsx` | 14 of the 15 stations with empty Three Letter Code / Rating / Length columns — a template, not data |
| `data/handbuilt/nodes_24hr.xlsx` | a synthetic half-hourly day for the 15 nodes; its own README says it is fabricated, NumPy seed 42 |

---

## 1. The two views are both in `nodes.xlsx`, and they are 24 and 15

The file holds both, one under the other in a single sheet. That settles the
question Phase 3 opened with:

- **24 nodes** with generation as nodes of its own — Clady, Lenalea,
  Meentycat, Golagh, Mulreavy, Cathaleen's Fall, Cliff, Tawnaghmore, Garvagh,
  Cunghill — each carrying an "Assigned to which substation?" column.
- **15 nodes** with those ten folded into nine substations.

TYTFS-native is **24 stations** as well, and the correspondence is one-to-one
with a single substitution: **TYTFS has no Clady, and it splits Srananagh into
a 110 kV and a 220 kV busbar that `nodes.xlsx` has as one node.**

### The 15-node view

| station | kV | TYTFS buses | folds in |
|---|---|---|---|
| Ardnagappary | 110 | 1571 | *Clady — not in TYTFS* |
| Binbane | 110 | 1341 | |
| Cathaleen's Fall | 110 | 1701, 1761, 17010, 17061 | **Cliff** |
| Clogher | 110 | 2801, 2870, 2871, 4091, 28019, 28710, 28712 | **Golagh**, **Mulreavy** |
| Corderry | 110 | 1631, 2671 | **Garvagh** |
| Croaghonagh | 110 | 51911 | |
| Drumkeen | 110 | 2321, 4071 | **Meentycat** |
| Glenree | 110 | 4371 | |
| Letterkenny | 110 | 3581, 3591, 35861, 35862 | **Lenalea** |
| Moy | 110 | 4041, 5241, 5251, 40461, 40462 | **Tawnaghmore** |
| Sligo | 110 | 1931, 4981, 49861 | **Cunghill** |
| Sorne Hill | 110 | 4991 | |
| Srananagh 220 | 220 | 5041, 5042 | **Srananagh 110** |
| Tievebrack | 110 | 5191 | |
| Trillick | 110 | 5361 | |

Within a station, TYTFS's own busbars are joined by zero-impedance couplers
and are one place: Clogher is four 110 kV busbars, Cathaleen's Fall three,
Letterkenny three, Moy and Sligo two each.

---

## 2. The circuit table: 16 is right as a count of routes

**I agree there are 16 — as routes. TYTFS has 19 circuits on those 16
routes.** Three of them are double circuits, and in each case the two circuits
land on *different busbars* at one or both ends, which is exactly why they
collapse to one edge in a node-and-edge list.

### The 15-station view — 16 routes, 19 circuits

| route | ckt | from bus | to bus | km | RATE1 | |
|---|---|---|---|---|---|---|
| Ardnagappary – Tievebrack | 1 | 1571 ARDNAGAPPARY | 5191 TIEVEBRACK | 35.00 | 91 | |
| Binbane – Cathaleen's Fall | 1 | 1341 BINBANE | 1701 CATH_FALL | 34.30 | 210 | |
| Binbane – Tievebrack | 1 | 1341 BINBANE | 5191 TIEVEBRACK | 23.20 | 159 | |
| Cathaleen's Fall – Clogher | 1 | 2870 CLOGHER | 17010 CATH FALL | 26.07 | 209 | **double** |
| Cathaleen's Fall – Clogher | 2 | 1701 CATH_FALL | 28712 CLOGHER | 25.74 | 210 | **double** |
| Cathaleen's Fall – Srananagh | 1 | 1701 CATH_FALL | 5041 SRANANAGH | 52.63 | 191 | **double** |
| Cathaleen's Fall – Srananagh | 2 | 5041 SRANANAGH | 17010 CATH FALL | 49.67 | 210 | **double** |
| Clogher – Croaghonagh | 1 | 28710 CLOGHER | 51911 CROAGHONAGH | 9.61 | 183 | |
| Clogher – Drumkeen | 1 | 2321 DRUMKEEN | 28710 CLOGHER | 27.00 | 123 | |
| Clogher – Letterkenny | 1 | 3581 LETTERKENNY | 28019 GOLAGH T | 38.40 | 121 | via the Golagh tee |
| Corderry – Srananagh | 1 | 1631 CORDERRY | 5041 SRANANAGH | 12.70 | 210 | |
| Drumkeen – Letterkenny | 1 | 2321 DRUMKEEN | 3581 LETTERKENNY | 8.35 | 123 | |
| Glenree – Moy | 1 | 4041 MOY | 4371 GLENREE | 13.96 | 123 | |
| Glenree – Sligo | 1 | 1931 CUNGHILL | 4371 GLENREE | 26.29 | 210 | through folded Cunghill |
| Letterkenny – Tievebrack | 1 | 3591 LENALEA | 5191 TIEVEBRACK | 33.13 | 159 | through folded Lenalea |
| Letterkenny – Trillick | 1 | 3581 LETTERKENNY | 5361 TRILLICK | 34.05 | 123 | |
| Sligo – Srananagh | 1 | 4981 SLIGO | 5041 SRANANAGH | 10.77 | 121 | **double** |
| Sligo – Srananagh | 2 | 4981 SLIGO | 5041 SRANANAGH | 11.19 | 121 | **double** |
| Sorne Hill – Trillick | 1 | 4991 SORNE HILL | 5361 TRILLICK | 4.40 | 123 | |

There is **no transformer** in this view: `nodes.xlsx` has one Srananagh node,
so the 250 MVA 220/110 kV transformer is inside it. §7 is about what that
costs.

### The 24-station view — 25 routes, 29 circuits

Unfolding adds Cathaleen's Fall–Cliff, Clogher–Golagh, Clogher–Mulreavy,
Drumkeen–Meentycat, Lenalea–Letterkenny, Corderry–Garvagh, Cunghill–Sligo,
Moy–Tawnaghmore and Srananagh 110–Srananagh 220, and splits
Letterkenny–Tievebrack and Glenree–Sligo back through Lenalea and Cunghill.
Moy–Tawnaghmore is a fourth double circuit. 28 lines and the transformer.

### Two things in that table worth knowing

**The double circuits land on different busbars.** Circuit 1 of the
Cathaleen's Fall–Clogher pair runs 2870 → 17010; circuit 2 runs 1701 → 28712.
The Srananagh pair is the same. Treating each station as one node is what
makes them parallel; in the case they are not, quite, which is why both views
are built from bus numbers rather than station names.

**Clogher–Letterkenny goes through the Golagh tee.** Bus 28019 `GOLAGH T` is a
tee point on the Letterkenny–Clogher line with Golagh's station hanging off
it — two circuits in the 24-node view, one in the 15-node view.

---

## 3. Cathaleen's Fall and Clady

**Cathaleen's Fall is in TYTFS**, under a name the twelve-character field
cannot hold: bus 1701 `CATH_FALL`, bus 17010 `CATH FALL` and bus 17061
`CATH_CAP`, three busbars joined by zero-impedance couplers, with the machines
below at 10.5 kV (`HY_CATHG3`, `HY_CATHG4`) and 17.0 MW of 38 kV demand. In
OpenStreetMap it is *Cathleen's Fall 110kV Substation* — without the second
'a' — at 54.4988 N, 8.1770 W, which is how `geocode.py` places it.

`transmission.xlsx` lists 14 stations, and Cathaleen's Fall is the one it
leaves out. It is in `nodes.xlsx` twice — as a hydro node and as a substation.

**Clady is not in TYTFS at any voltage.** Three independent sources agree on
why:

- **OpenStreetMap** has *Clady 38kV Substation* (ESB Networks) and *Clady
  Hydroelectric Station* (ESB Generation), both at 55.0381 N, 8.2717 W in
  Gweedore, Co. Donegal, both tagged **38 kV**.
- **EirGrid's own asset register** — the 161-station 110 kV-and-above layer
  in `data/eirgrid_transmission.gpkg` — does not contain it.
- **TYTFS** has no bus whose name contains `CLAD`, at any voltage.

A 38 kV ESB Networks station is below the transmission model's floor. TYTFS
carries the sub-110 kV network only as the stub that load and small generation
hangs off.

`nodes.xlsx` assigns Clady to **Ardnagappary**, which is geographically right
— Ardnagappary 110 kV is 2.0 km north at 55.0565 N, 8.2692 W. But what
Ardnagappary carries in TYTFS is 9.67 MW of 38 kV demand and the **Cronalaght**
wind farm (three records, 22.94 MVA, all out of service in WP2024), and **no
hydro unit at all**. So the 38 MW `nodes.xlsx` puts at Ardnagappary is not in
TYTFS, there or anywhere.

*One near-miss, ruled out.* `HY_GLENTIES` (bus 13434, 38 kV under Binbane)
carries a 4.3 MW in-service machine, within 0.1 MW of Clady's real rating. It
is 7.4 km from Binbane's 38 kV busbar in the Glenties area, roughly 30 km from
Gweedore. Not it.

### And a question about that 38

`nodes.xlsx` gives **all three** of its hydro nodes a capacity of exactly 38
MW — Clady, Cliff and Cathaleen's Fall. None of the three matches:

| hydro node | nodes.xlsx | TYTFS | real |
|---|---|---|---|
| Cathaleen's Fall | 38 | 45.5 MVA (2 × 22.5/23.0) | 45 MW |
| Cliff | 38 | 20.0 MVA (2 × 10) | 20 MW |
| Clady | 38 | absent | 4.2 MW |

Meanwhile the file's **wind** figures are accurate to within 1% (§4). Three
identical values that match nothing, on the three plants that all connect at
**38 kV**, look like a connection voltage entered in a capacity column. I
cannot prove that from here, but it is worth checking before the 76 MW at
Cathaleen's Fall is used for anything.

---

## 4. The generation, plant by plant

This is where the reconciliation is most informative. `nodes.xlsx` names ten
generation nodes; **four of them agree with TYTFS to within 1%**.

| nodes.xlsx node | type | assigned to | nodes.xlsx MW | TYTFS station MW | ratio |
|---|---|---|---|---|---|
| Mulreavy | Wind | Clogher | 95 | **95.25** | 1.00 |
| Meentycat | Wind | Drumkeen | 85 | **84.96** | 1.00 |
| Cunghill | Wind | Sligo | 35 | **34.80** | 0.99 |
| Lenalea | Wind | Letterkenny | 30 | **30.50** | 1.02 |
| Golagh | Wind | Clogher | 48 | 15.00 | 0.31 |
| Garvagh | Wind | Corderry | 34 | 82.00 | 2.41 |
| Cathaleen's Fall | Hydro | Cathaleen's Fall | 38 | 63.00 | 1.66 |
| Cliff | Hydro | Cathaleen's Fall | 38 | 20.00 | 0.53 |
| Clady | Hydro | Ardnagappary | 38 | — | — |
| Tawnaghmore | Thermal | Moy | 19 | 183.60 | 9.66 |

**Every wind figure is right; no hydro figure is.** Mulreavy is 95.25 MVA
across four machines, Meentycat 84.96 across three, Cunghill 34.80 across
three, Lenalea 30.50 — the hand-built numbers are the same numbers rounded.

The six that differ each have a reason:

- **Golagh 48 vs 15.** TYTFS's Golagh 22 kV bus carries `W_BS_GOLAGH`, two
  records totalling 15.0 MVA. Either the hand-built figure is a later
  extension, or it is a different site.
- **Garvagh 34 vs 82.** The hand-built 34 matches `W_DERRYSALLA` (34.0 MVA)
  exactly and misses the other two farms at that station, Garvagh Glebe
  (26.0) and Garvagh Tullinwar (22.0).
- **Cathaleen's Fall 63** is the station total: 45.5 MVA of hydro plus the
  17.5 MVA `W_ACRES` wind farm on its 38 kV busbar.
- **Tawnaghmore 19 vs 183.6.** TYTFS's Tawnaghmore busbars carry the
  Tawnaghmore peaking station (`TAW_PEAK`, 2 × 52.3 MVA), Mayo Renewable
  Power (`BIO_MAYO_REN`, 49.0 MVA) and Killala storage (30.0 MVA). Against
  the peaking plant alone, 19 MW is 5.5× low.

### One internal inconsistency in `nodes.xlsx`

The 24-node block's generation sums to **460 MW**. The 15-node block sums to
**425 MW**. The difference is exactly **35 MW — Cunghill**, which the 24-node
block assigns to Sligo and the 15-node block gives Sligo 0 supply for. One of
the two blocks has lost it.

---

## 5. Supply and demand, station by station

| station | nodes.xlsx supply | TYTFS capacity | Δ | nodes.xlsx demand | TYTFS demand | Δ |
|---|---|---|---|---|---|---|
| Ardnagappary | 38 | 22.9 | −15.1 | 5 | 9.7 | +4.7 |
| Binbane | 0 | **75.1** | +75.1 | 10 | 18.7 | +8.7 |
| Cathaleen's Fall | 76 | 83.0 | +7.0 | 0 | 17.0 | +17.0 |
| Clogher | 143 | 110.3 | −32.8 | 5 | 0.0 | −5.0 |
| Corderry | 34 | **145.3** | +111.3 | 5 | 0.0 | −5.0 |
| Croaghonagh | 0 | **139.2** | +139.2 | 10 | 0.0 | −10.0 |
| Drumkeen | 85 | 85.0 | −0.0 | 10 | 0.0 | −10.0 |
| Glenree | 0 | **77.3** | +77.3 | 10 | 0.0 | −10.0 |
| Letterkenny | 30 | 70.8 | +40.8 | 15 | **66.1** | +51.1 |
| Moy | 19 | **189.6** | +170.6 | 5 | 26.9 | +21.9 |
| Sligo | 0 | 48.5 | +48.5 | 20 | 54.2 | +34.2 |
| Sorne Hill | 0 | **63.3** | +63.3 | 5 | 0.0 | −5.0 |
| Srananagh | 0 | 0.0 | 0.0 | **50** | 0.0 | −50.0 |
| Tievebrack | 0 | 0.0 | 0.0 | 5 | 0.0 | −5.0 |
| Trillick | 0 | **44.7** | +44.7 | 5 | 20.1 | +15.1 |
| **total** | **425** | **1,154.8** | **+730** | **160** | **212.6** | **+53** |

### Supply: the hand-built set is a correct subset, not a wrong dataset

**TYTFS has 1,155 MW of connected capacity in these 15 stations against the
hand-built 425 MW — 2.7 times as much.** But it is not that the hand-built
figures are wrong; §4 shows four of them are exact. It is that the file names
ten generation sites and TYTFS has **85 machines**. The 730 MW gap is almost
entirely at stations the file gives zero supply:

- **Croaghonagh 139.2 MW** (two wind farms, 91.2 + 48.0) — the single largest
  omission, and Croaghonagh is one of the 15 nodes.
- **Moy 189.6 MW**, of which 183.6 is at Tawnaghmore.
- **Corderry 145.3 MW**, of which 82 is Garvagh and 63.3 is Corderry's own
  cluster (Tullynamoyle, Black Bank, Altagowlan, Geevagh, Moneenatie,
  Caranne Hill).
- **Binbane 75.1 MW** across 14 machines (Corkermore, Meenachullalan,
  Killybegs, Loughderryduff, Killin Hill, Burtonport, Meenadreen, Anarget,
  Clogheravaddy, Glenties hydro).
- **Glenree 77.3**, **Sorne Hill 63.3**, **Trillick 44.7**.

So the region is **more** export-dominated than the hand-built data says, not
less: 5.4 : 1 against 2.7 : 1.

### Demand: the totals nearly agree and the distribution does not

160 MW against 213 MW is agreement, for a nominal figure against a
winter-peak one. The distribution is not:

- **Nine of the fifteen nodes have demand in `nodes.xlsx` that TYTFS puts at
  zero** — Clogher, Corderry, Croaghonagh, Drumkeen, Glenree, Sorne Hill,
  Tievebrack, and Srananagh. These are transmission stations with no 38 kV
  load busbar under them.
- **Letterkenny carries 66.1 MW in TYTFS against 15 in `nodes.xlsx`** — more
  on its own than the hand-built model gives to any station. Sligo is 54.2
  against 20, Moy 26.9 against 5, Trillick 20.1 against 5, Cathaleen's Fall
  17.0 against 0.
- **Srananagh's 50 MW is the boundary, not demand.** `nodes.xlsx` gives the
  220 kV node 50 MW of "Est. Demand Capacity" and no supply; TYTFS has no load
  at either Srananagh busbar. That is the export modelled as a load, which is
  a reasonable thing for a 15-node model to do and is worth being explicit
  about, because it is the largest single demand entry in the file.

The pattern is a **nominal per-station allocation** — 5, 10, 15, 20 MW — where
TYTFS has the case's actual 38 kV load at the six stations that have one.

---

## 6. Srananagh, the boundary, and the export claim

### The transformer

```
5042 SRANANAGH 220 kV  --+
                          +-- 250 MVA, X = 0.064 pu on 100 MVA
5041 SRANANAGH 110 kV  --+
                          +-- 50421 SRANANAGH 10.5 kV, tertiary,
                              no generator and no load
```

One **three-winding** 220/110/10.5 kV unit, 250 MVA, idle tertiary. The
extraction keeps the 220/110 leg as a single two-winding transformer, which is
exact because nothing hangs on the tertiary. Slacking at the 220 kV busbar is
right — it is where the region's own model ends.

### The region is not radial behind it

Removing that transformer leaves every North-West bus still connected to the
220 kV network. There are **six** boundary ties in the 2024 cases:

| from | to | kV | km | RATE1 | into the region, WP2024 |
|---|---|---|---|---|---|
| Srananagh 220 | FLAGFORD 220 | 220 | 56.0 | 513 | **+92.9 MW** |
| Sligo | FLAGFORD | 110 | 50.5 | 121 | +24.4 MW |
| Moy | BELLACORICK | 110 | 27.0 | 210 | +20.5 MW |
| Corderry | ARIGNA_T | 110 | 13.7 | 210 | +17.9 MW |
| Cathaleen's Fall | CORRACLASSY | 110 | 61.3 | 210 | +8.2 MW |
| Letterkenny | STRA_PST (Strabane, NI) | 110 | 22.3 | 93 | −20.5 MW |

### None of the four cases runs the fleet

| case | capacity | dispatched | demand | net into the region | via Srananagh | machines running |
|---|---|---|---|---|---|---|
| WP2024 | 1,154.8 | 69.3 (6%) | 212.6 | **+143.3** | +92.9 | 6 of 85 |
| SV2024 | 1,057.8 | 96.0 (9%) | 73.2 | **−22.8** | +35.8 | 2 of 83 |
| WP2033 | 1,329.1 | 274.2 (21%) | 238.9 | **−35.3** | +43.3 | 89 of 94 |
| SV2033 | 1,329.1 | 40.0 (3%) | 73.0 | **+33.0** | +29.0 | 3 of 94 |

Two of the four export — by 23 and 35 MW, against more than a gigawatt of
connected capacity. **Between 3% and 21% of the fleet is dispatched in any
case**, because these are peak and valley security studies and a security
study does not credit wind. So the answer to "confirm the TYTFS boundary flows
are consistent with export dominance" is: **the capacity is, emphatically; the
flows in the published cases are not, because none of the four is a high-wind
case.** The export the Wind Dispatch Tool exists to manage does not appear in
any of them.

---

## 7. What happens when the wind blows, and where it goes

`python northwest.py windy --capacity-factor X` puts the region's connected
capacity to work at *X* of `PT` and re-solves, on the **whole** transmission
network. Not on the extract: the region has six ties, and an extract that
holds five of them where the case put them sends every extra megawatt out
through Srananagh and produces an answer that is both large and meaningless.

It is a what-if. Nothing outside the region is re-dispatched, so it says where
the region's power would *try* to go.

| capacity factor | net export | worst boundary tie | Srananagh out | worst internal circuit |
|---|---|---|---|---|
| 10% | −97 MW (importing) | Letterkenny–Strabane 0.36× | −85 MW (in) | 0.40× |
| 20% | 18 MW | Letterkenny–Strabane 0.71× | −62 MW (in) | 0.48× |
| **30%** | **134 MW** | **Letterkenny–Strabane 1.05×** | −39 MW (in) | 0.56× |
| 60% | 480 MW | Letterkenny–Strabane 2.09× | +31 MW | 0.80× |
| 100% | 942 MW | Letterkenny–Strabane 3.48× | +123 MW | **1.11×** |

**The binding constraint is the Letterkenny–Strabane 110 kV tie into Northern
Ireland, 93 MVA, and it binds at about 29% of connected capacity.** Srananagh
does not even reverse into export until about 45%, and at full output carries
123 MW — 0.24× of its 513 MVA 220 kV circuit and 0.49× of the 250 MVA
transformer. The first internal circuit to bind is Drumkeen–Letterkenny, at
about 90%.

So Srananagh 220 is the right place to **slack** the extraction and the wrong
place to look for the constraint. Caveats, both real: nothing outside the
region is re-dispatched, and the system reference is Turlough Hill, far away.
A study that cares should redo this with the Northern Ireland network
dispatched rather than fixed.

---

## 8. What the 15-node topology costs, and the one node to add

`python northwest.py extract` writes both views to
`data/pypsa/northwest_<case>_<view>/` as PyPSA CSV folders, with `reports/`
carrying `stations.csv`, `circuits.csv`, `routes.csv`, `balance.csv`,
`boundary.csv` and `agreement_with_full.csv`.

Every boundary tie but Srananagh is pinned at the MW the full network's DC
solve puts on it — by its bounds and not only by `p_set`, so it stays pinned
in an optimisation, where PyPSA releases `p_set`. Srananagh is left free.

### The verification

Same impedances, same injections, a different reference bus: a DC flow has to
put the same MW on every circuit as the full network does.

| view | worst disagreement, WP2024 |
|---|---|
| 24-station native | **0.0099 MW** |
| 15-station folded | **21.59 MW** |

The native extraction is exact to a hundredth of a megawatt; the residual is
the zero-impedance couplers merged to make a station one bus.

### Almost all of the 21.59 MW is one fold

| what is folded | worst disagreement |
|---|---|
| all nine | 21.59 MW |
| all but Srananagh 110 | **1.74 MW** |
| all but Lenalea | 21.59 MW |
| all but Cunghill | 21.59 MW |
| all but Srananagh 110, Lenalea and Cunghill | 0.15 MW |

**Merging Srananagh's two busbars short-circuits the 250 MVA transformer**,
whose 0.064 pu of reactance is a large fraction of the region's total. It
redistributes the two Cathaleen's Fall–Srananagh circuits by 21.6 MW each —
one goes from −35.2 to −13.6 MW and the other from +39.4 to +60.9. Folding
Lenalea costs 1.74 MW (it sits between Letterkenny and Tievebrack, so folding
it loses 12.2 km of impedance from that triangle); folding Cunghill costs
0.15; the other six folds are radial spurs and cost nothing measurable.

**The recommendation is one node.** Split Srananagh back into 110 and 220 and
put the transformer between them — 16 nodes instead of 15 — and the flow error
falls from 21.6 MW to 1.7 MW. Add Lenalea back too and it falls to 0.15 MW.

### Both views solve

| case | view | connected | DC PF | LOPF (HiGHS) | agreement |
|---|---|---|---|---|---|
| WP2024 | native | yes | solved | optimal | 0.0099 MW |
| WP2024 | folded | yes | solved | optimal | 21.59 MW |
| SV2024 | native | yes | solved | optimal | 0.50 MW |
| SV2024 | folded | yes | solved | optimal | 21.78 MW |

---

## 9. The 15-node region is a 2024 region

In **both 2033 cases the region is disconnected**, and it is not a modelling
artefact: EirGrid's 2033 network rebuilds the Mayo 110 kV system.

- The **Glenree–Moy** circuit does not exist in 2033 — not out of service, no
  branch record at all.
- A new station, **FIRLOUGH** (bus 2601), sits between them instead:
  Glenree–Firlough 5.7 km and Moy–Firlough 15.9 km.
- Moy gains ties to **Laghtanvack** (3691) and **Tonroe** (5341) and loses the
  one to Bellacorick; Garvagh gains one to **Aghaleague** (2661).

Firlough is not in the 15-node set, so **Moy and Tawnaghmore fall out of the
region**: the 2033 extract has two components, one of 14 stations and one of
Moy alone. `northwest.py verify` reports this as a failure, which is the right
answer — the node set no longer describes a connected subnetwork.

Adding Firlough, and probably Laghtanvack and Aghaleague, is what a 2033
version of the hand-built dataset would need.

---

## 10. Summary

| # | claim | verdict |
|---|---|---|
| 1 | **16 circuits among 15 stations** | Agreed as **routes**. TYTFS has **19 circuits** on those 16 routes — three are double circuits landing on different busbars. |
| 2 | **15 nodes** | Reproduced exactly, and `nodes.xlsx`'s own 24-node block matches the TYTFS-native 24 stations one-for-one, with Clady replaced by Srananagh's second busbar. |
| 3 | **Cathaleen's Fall missing** | It is there — `CATH_FALL`, `CATH FALL`, `CATH_CAP`. `transmission.xlsx` is the file that omits it. |
| 4 | **Clady missing** | Genuinely absent at every voltage: a 38 kV station, below the model's floor. The 38 MW `nodes.xlsx` puts at Ardnagappary is not in TYTFS. |
| 5 | **the hydro capacities** | All three are exactly 38 and none matches TYTFS. All three plants connect at 38 kV. Worth checking. |
| 6 | **the wind capacities** | Four of four agree to within 1% — Mulreavy, Meentycat, Cunghill, Lenalea. |
| 7 | **~425 MW supply** | TYTFS has **1,155 MW** — 2.7×. The gap is stations the file gives zero supply, above all **Croaghonagh at 139 MW**. |
| 8 | **~160 MW demand** | TYTFS has **213 MW** — but nine of the fifteen nodes have hand-built demand that TYTFS puts at zero, and Letterkenny alone carries 66 MW. |
| 9 | **Srananagh as the export path** | Right place to slack. Six boundary ties, and **Letterkenny–Strabane binds first, at ~29% capacity factor**, while Srananagh is still importing. |
| 10 | **export-dominated** | True of capacity, and more so than the hand-built data says (5.4 : 1 against 2.7 : 1). False of all four cases' flows. |
| 11 | **the 15-node topology** | Costs **21.6 MW** of circuit flow, of which 21.6 is the Srananagh merge alone. Splitting that one node back recovers all but 1.7 MW. |
| 12 | **`nodes.xlsx` internally** | The 24-node block sums to 460 MW of supply, the 15-node block to 425. The missing 35 MW is Cunghill. |
| 13 | **2033** | The 15-node region is disconnected in both 2033 cases: Glenree–Moy is replaced by a new station, Firlough, that the node set does not have. |
