# Phase 1: reading the TYTFS 2024 PSS/E cases

`psse.py` reads EirGrid's Ten Year Transmission Forecast Statement 2024 study
files — solved AC load-flow cases for the all-island system, PSS/E v35 raw
format — into pandas DataFrames. `test_psse.py` guards it.

**Twelve of the sixteen confirmed WP2024 figures reproduce exactly. Four do
not.** All four disagreements were traced to a definite cause; none of them is
a parser bug, and none of the expected figures has been adjusted to make the
parser look right. They are set out in full below, because three of them are
the kind of thing that would otherwise propagate into every number built on
top of this.

## Why a parser and not a dependency

PyPSA has no PSS/E importer, and the general-purpose readers that do exist
carry a solver or a whole network model behind them. The format is eight
sections of comma-separated records with one genuinely awkward record type,
so the dependency would cost more than it saves. This module returns the file
and nothing else — no per-unit conversion, no topology, no network object.

## The format, as verified against the four files

| | |
|---|---|
| Encoding | latin-1 |
| Line endings | CRLF |
| Section delimiter | a line beginning `0 /`, whose comment names the section that **follows** it: `0 / END OF BUS DATA, BEGIN LOAD DATA` |
| Column headers | one or more `@!` comment lines opening each section — five in the transformer section (one per record line), three in the two-terminal DC section |
| Records | comma-separated; character fields single- **or** double-quoted; anything after an unquoted `/` is a comment |
| Short records | trailing fields may be omitted, so a short record is padded, not rejected. A record *longer* than its layout raises — that means the layout is wrong |

Two record types span more than one line, and both are assembled into a
single flat row here so that every section comes back as a rectangle:

- **Transformer** — four lines when two-winding, five when three-winding.
  `K` non-zero on the first line is what says which. A two-winding record's
  impedance line carries three fields and its second winding is a two-field
  line; a three-winding record's impedance line carries all eleven and each
  winding gets a full 27-field line.
- **Two-terminal DC** — always three lines: link, rectifier, inverter. The
  converter columns are suffixed `R` and `I`.

The transformer assembly is checked by arithmetic rather than by eye. WP2024's
transformer section holds 5,349 data lines; the reader finds 1,201 two-winding
and 109 three-winding transformers, and `1201 × 4 + 109 × 5 = 5349` exactly.
Nothing is left over, which is the failure mode that matters: one mis-sized
record slides every record after it by a line, and the result still parses.

## Field layouts

Zero-indexed, as read from the `@!` headers and confirmed against the data.

| Section | Layout |
|---|---|
| Bus | 0 `I`, 1 `NAME`, **2 `BASKV`**, 3 `IDE`, 4 `AREA`, 5 `ZONE`, 6 `OWNER`, 7 `VM`, 8 `VA`, 9–12 `NVHI`/`NVLO`/`EVHI`/`EVLO` |
| Load | 0 `I`, 1 `ID`, **2 `STAT`**, 3 `AREA`, 4 `ZONE`, 5 `PL`, 6 `QL`, 7–10 `IP`/`IQ`/`YP`/`YQ`, 11 `OWNER`, 12 `SCALE`, 13 `INTRPT`, 14–16 `DGENP`/`DGENQ`/`DGENF`, 17 `LOADTYPE` |
| Generator | 0 `I`, 1 `ID`, **2 `PG`**, 3 `QG`, 4 `QT`, 5 `QB`, 6 `VS`, 7 `IREG`, 8 `NREG`, 9 `MBASE`, 10–14 `ZR`…`GTAP`, **15 `STAT`**, 16 `RMPCT`, **17 `PT`**, 18 `PB`, 19 `BASLOD`, 20–27 owners, 28 `WMOD`, 29 `WPF` |
| Branch | 0 `I`, 1 `J`, 2 `CKT`, 3 `R`, 4 `X`, 5 `B`, 6 `NAME`, 7–18 `RATE1`…`RATE12`, 19–22 `GI`/`BI`/`GJ`/`BJ`, 23 `STAT`, **24 `MET`**, **25 `LEN`**, 26–33 owners |
| Transformer | line 1: 0 `I`, 1 `J`, 2 `K`, 3 `CKT`, 4–6 `CW`/`CZ`/`CM`, 7–8 `MAG1`/`MAG2`, 9 `NMETR`, 10 `NAME`, 11 `STAT`, 12–19 owners, 20 `VECGRP`, 21 `ZCOD` |
| Two-terminal DC | line 1: 0 `NAME`, 1 `MDC`, 2 `RDC`, 3 `SETVL`, 4 `VSCHD`, …; lines 2–3: 0 `IPR`/`IPI`, 1 `NBR`/`NBI`, … |
| Area | 0 `I`, 1 `ISW`, 2 `PDES`, 3 `PTOL`, 4 `ARNAME` |
| Zone | 0 `I`, 1 `ZONAME` |

Your generator indices (2 `PG`, 15 `STAT`, 17 `PT`) and bus index 2 `BASKV`
are confirmed exactly. **The branch note needs one correction: `LEN` is index
25, not 24. Index 24 is `MET`.** The file settles it — over WP2024's 1,129
branches, index 23 takes only 0/1 (`STAT`, 50 out of service), index 24 takes
only 1/2 (`MET`, the metered end), and index 25 runs 0–208.5 with a median of
4.4, which is circuit length in km. Index 24 is almost certainly carried over
from the v33 layout, which has no branch `NAME` field and so shifts everything
after index 5 down by one. The v33 files sit in the same directory; the reader
refuses them by revision rather than reading them into misaligned columns.

## Validation against the confirmed WP2024 figures

`python psse.py validate`

| Check | Parsed | Expected | |
|---|---|---|---|
| Bus records | 2,025 | 2,026 | ✗ |
| Branch records | 1,129 | 1,130 | ✗ |
| Generator records | 597 | 597 | ✓ |
| Load records | 266 | 267 | ✗ |
| Buses at 380 kV | 7 | 7 | ✓ |
| Buses at 275 kV | 15 | 15 | ✓ |
| Buses at 220 kV | 69 | 69 | ✓ |
| Buses at 110 kV | 456 | 456 | ✓ |
| AC branches, both ends ≥110 kV | 679 | 679 | ✓ |
| …at 380 kV | 7 | 7 | ✓ |
| …at 275 kV | 23 | 23 | ✓ |
| …at 220 kV | 94 | 94 | ✓ |
| …at 110 kV | 555 | 555 | ✓ |
| Generators in service | 87 | 87 | ✓ |
| Dispatched PG | 7,412 MW | 7,412 MW | ✓ |
| Total load | 7,325 MW | 8,246 MW | ✗ |

Everything derived — every voltage count, the branch classification, the
generator dispatch — agrees to the unit. The four that do not are two
distinct causes.

### 1–3. The three record counts are each high by exactly one

2,026 − 2,025 = 1. 1,130 − 1,129 = 1. 267 − 266 = 1.

Each of those sections contains exactly one `@!` column-header comment line.
Counting the lines *between* the two `0 /` delimiters gives 2,026, 1,130 and
267 — your three figures precisely — and counting the data records inside
them gives 2,025, 1,129 and 266.

The generator figure is the tell. Generators came out right at 597, and the
generator section has one `@!` header too, so a header-inclusive count there
would have given 598. That is consistent with the generator count having been
taken from something that filtered records — as it must have been, to get 87
in service — while the other three were taken from a line span.

The verdict is one that has to come from you, not from the parser: I believe
these three expected figures are off by one header line each. I have not
changed them, and `psse.py validate` still reports them as failures.

### 4. Total load: 8,246 MW is the load register, not the case's demand

The 8,246 MW figure reproduces exactly — it is the sum of `PL` over all 266
load records. The parse agrees; what differs is which records to count.

Of the 266, **34 have `STAT = 0`** and total 921.9 MW. Every one of those 34
has `ID = 'MI'`, and **every one sits at a bus that already carries an
in-service load record**. They are an alternative representation of the same
demand, deliberately switched out. Summing them alongside the active records
double-counts 34 buses.

The solved case says the same thing. In-service generation is 7,411.6 MW and
in-service load is 7,324.5 MW — a gap of 87 MW, or 1.2%, which is
losses-shaped. Against the full 8,246 MW register, generation would fall
835 MW short, and a solved AC load flow does not fail to serve 10% of its
demand. The same holds across all four cases:

| Case | In-service PG | In-service PL | Gap | Load register | Gap vs register |
|---|---|---|---|---|---|
| WP2024 | 7,412 | 7,325 | +87 (1.2%) | 8,246 | −835 (−10.1%) |
| SV2024 | 3,424 | 3,402 | +22 (0.7%) | 4,283 | −858 (−20.0%) |
| WP2033 | 8,989 | 8,792 | +198 (2.3%) | 9,522 | −533 (−5.6%) |
| SV2033 | 4,104 | 4,111 | −7 (−0.2%) | 4,842 | −738 (−15.2%) |

Filtered, every case balances within a loss-sized band. (SV2033's small
negative gap is Turlough Hill pumping — its four units sit at −24.7 MW each,
so pumped storage load arrives as negative generation.) Unfiltered, every
case is short by between 5% and 20%.

So: **`STAT` is essential on loads as well as on generators**, and for the
same reason. `psse.loads()` and `psse.generators()` both filter by default;
`psse.summary()` reports the in-service total as `total_load_mw` and the
register total as `load_register_mw`, so both are visible and neither is
hidden.

## The generator `STAT` trap, quantified

Your warning is right, and larger than it sounds. WP2024's generator section
is a register of 597 machines totalling **18,158 MW** of `PG` — more than
twice the island's winter peak. Filtering on `STAT = 1` leaves 87 machines and
7,412 MW, which is a plausible winter-peak dispatch (Great Island 464 MW,
Aghada 456 MW, Whitegate 444 MW, Dublin Bay 404 MW, Moneypoint 3 × 234 MW).

The in-service fraction is not stable across scenarios, so this cannot be
approximated by a rule of thumb:

| Case | Records | In service | Fraction |
|---|---|---|---|
| WP2024 | 597 | 87 | 15% |
| SV2024 | 558 | 18 | 3% |
| WP2033 | 847 | 710 | 84% |
| SV2033 | 847 | 45 | 5% |

WP2033 keeps 84% of its machines in service, SV2024 keeps 3%. Anything
downstream must filter per case.

## What comes out

`read_raw()` returns a `Case` with eight DataFrames. WP2024:

| Frame | Rows |
|---|---|
| `bus` | 2,025 |
| `load` | 266 |
| `generator` | 597 |
| `branch` | 1,129 |
| `transformer` | 1,310 (1,201 two-winding, 109 three-winding) |
| `two_terminal_dc` | 2 |
| `area` | 14 |
| `zone` | 14 |

Numeric columns are coerced; identifier columns (`ID`, `CKT`, `NAME`,
`ARNAME`, `ZONAME`, `VECGRP`, `METER`, `IDR`, `IDI`) stay text, so a machine
id of `'1 '` keeps its fixed-width padding and does not become `1.0`.

Across all eight frames of WP2024, the only columns that come back entirely
empty are `branch.O2/F2/O3/F3/O4/F4` — every branch carries a single owner, so
the second through fourth owner fields are never written. That set is pinned
by a test, because an all-null column is otherwise exactly what a layout that
has slipped a field looks like.

## Skipped sections

Read: bus, load, generator, branch, transformer, two-terminal DC, area, zone.

Deliberately skipped, by name, so that skipping is a decision in the code
rather than an accident of the file's order: fixed shunt, system switching
device, VSC DC line, impedance correction, multi-terminal DC, multi-section
line, inter-area transfer, owner, FACTS device, switched shunt, GNE, induction
machine, substation. A section name the reader does not recognise raises,
rather than being silently dropped.

## The four scenarios

All four V35 files parse. Both 2033 files share a topology (same bus, branch
and transformer counts) but differ in dispatch, voltages and load; they are
not duplicates.

| Case | Buses | Branches | AC ≥110 kV | Transformers | Gens | In svc | PG (MW) | Loads | In svc | PL (MW) | Register (MW) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WP2024 | 2,025 | 1,129 | 679 | 1,310 | 597 | 87 | 7,412 | 266 | 232 | 7,325 | 8,246 |
| SV2024 | 1,979 | 1,120 | 672 | 1,272 | 558 | 18 | 3,424 | 264 | 231 | 3,402 | 4,283 |
| WP2033 | 2,457 | 1,296 | 792 | 1,617 | 847 | 710 | 8,989 | 285 | 246 | 8,792 | 9,522 |
| SV2033 | 2,457 | 1,296 | 792 | 1,617 | 847 | 45 | 4,104 | 285 | 246 | 4,111 | 4,842 |

Bus counts by voltage:

| Case | 380 kV | 275 kV | 220 kV | 110 kV |
|---|---|---|---|---|
| WP2024 | 7 | 15 | 69 | 456 |
| SV2024 | 7 | 15 | 68 | 450 |
| WP2033 | 17 | 17 | 90 | 519 |
| SV2033 | 17 | 17 | 90 | 519 |

The 2033 cases roughly triple the 380 kV bus count (7 → 17) and add 96
transmission buses overall — the reinforcement the forecast statement is for.

## Notes for what comes next

**Branch counts are unfiltered.** The 679 figure counts every AC circuit whose
two ends are both at ≥110 kV, in service or not; 645 of the 679 have
`STAT = 1`. Both are defensible — a planning case's branch register is the
network on paper, and `STAT` is a scenario choice about it — so
`psse.ac_branches()` keeps out-of-service circuits by default and takes
`in_service=True` to drop them. Your 679 matches the unfiltered count, and the
per-voltage split matches unfiltered too. Whichever a downstream model wants,
it should say which.

**AC branches never change voltage.** Every one of the 679 joins two buses at
the same base kV, so classifying a circuit by voltage is unambiguous.
Transformation is entirely in the transformer section. A test pins this.

**Interconnectors are not all in the DC section.** The two two-terminal DC
records are both Scotland → Ballycronan, i.e. Moyle, and in WP2024 the
converter machine at the Scotland boundary bus is out of service. East-West
(bus 54630, `EASTWEST`, 260 kV) and Greenlink (bus 36671, `GREENLINK`,
150 kV) are modelled as PV buses with generator records instead. All three
carry a generator record with `STAT = 0` in WP2024 — 475, 475 and 479 MW of
`PG` between them, 1,429 MW of idle import capacity that is part of why the
unfiltered register reaches 18 GW. Anything that needs the island's
cross-border exchange has to look at all three places, not just
`two_terminal_dc`.

**One observation to check in a later phase, not a conclusion.** Summing
branch `LEN` over the 679 transmission circuits gives 9,862 km, against the
6,122 km of line and cable geometry this repo measures from EirGrid's ArcGIS
asset register (see `FINDINGS.md`). The two are not comparable as they stand:
`LEN` is circuit length, and a double-circuit tower line carries two circuits
over one route. The ratio is plausible for that, but nothing here has checked
it, and the two sources should not be reconciled on this number alone.

## Running it

```
python psse.py summary                 # all four V35 cases
python psse.py summary <file.raw>      # one case
python psse.py validate                # the table above; exits 1 on any failure
python -m pytest test_psse.py          # 30 tests
```

```python
import psse

case = psse.read_raw("data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw")
case.bus, case.branch, case.generator, ...    # DataFrames

psse.generators(case)          # STAT == 1 only
psse.loads(case)               # STAT == 1 only
psse.ac_branches(case)         # both ends >= 110 kV, with KV_I/KV_J/BASKV joined on
psse.summary(case)             # the headline figures
psse.read_all()                # all four, keyed by scenario name
```
