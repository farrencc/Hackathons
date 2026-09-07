"""PSS/E version 35 ``.raw`` load-flow case reader.

What this is
------------
A purpose-built reader for the solved AC load-flow cases EirGrid publishes
with its Ten Year Transmission Forecast Statement - the all-island Irish
transmission system in PSS/E v35 raw format.  It returns pandas DataFrames,
one per record section, and nothing else: no network object, no per-unit
conversion, no topology.  Everything downstream of the file is somebody
else's job.

Why not a library
-----------------
PyPSA, the model this feeds, has no PSS/E importer.  The general-purpose
readers that do exist carry a solver or a whole network model behind them,
and the raw format is small enough that a dependency costs more than it
saves: eight sections, one comma-separated record layout, one multi-line
record type.  The parts of the format this repo does not need - switched
shunts, FACTS devices, induction machines, impedance correction tables -
are skipped rather than half-read, and the section walker knows their names
so that skipping them is deliberate and not an accident of the file's order.

The format, as verified against the four TYTFS 2024 cases
---------------------------------------------------------
Sections are delimited by a line beginning ``0 /``, whose comment names the
section that *follows* it::

    0 / END OF BUS DATA, BEGIN LOAD DATA

Each section then opens with one or more ``@!`` comment lines carrying the
column headers (the transformer section has five, one per record line; the
two-terminal DC section has three).  Records are comma-separated, character
fields are single- or double-quoted, and anything after an unquoted ``/`` is
a comment.  Trailing fields may be omitted, so a record shorter than its
column list is padded rather than rejected.  Line endings are CRLF and the
encoding is latin-1.

Two record types span more than one line.  A transformer is four lines when
it is two-winding and five when three-winding (``K`` non-zero on the first
line says which); a two-terminal DC link is always three - link, rectifier,
inverter.  Both are assembled into one flat row here, with the continuation
lines' fields suffixed, so that every section comes back as a rectangle.

Two fields matter more than the rest
------------------------------------
``STAT`` on a generator record is the in-service flag, and the generator
section is a register of machines, not a dispatch: 597 records in WP2024, of
which 87 are actually running.  Summing ``PG`` without filtering on ``STAT``
gives a total several times the island's demand.  ``STAT`` on a branch is
the same thing for circuits.  Neither is filtered here - the reader reads -
but :func:`summary` and the module's own validation both apply them, and
they are the first thing to check when a total looks impossible.

Usage
-----
    import psse
    case = psse.read_raw("data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw")
    case.bus, case.load, case.generator, case.branch, case.transformer, ...

    python psse.py summary data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw
    python psse.py validate
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from dataclasses import dataclass, fields as dataclass_fields

import pandas as pd

# --------------------------------------------------------------------------- #
# Format constants
# --------------------------------------------------------------------------- #

#: PSS/E writes CRLF and non-ASCII station names in the Latin-1 range.
ENCODING = "latin-1"

#: The only raw revision whose field layouts are encoded below.  The v33
#: files shipped alongside these are a different shape and are refused.
REV = 35

#: A section delimiter: ``0 /`` followed by "END OF x DATA, BEGIN y DATA".
_DELIMITER = re.compile(r"^\s*0\s*/(.*)$")

#: The name of the section that follows a delimiter.
_BEGINS = re.compile(r"BEGIN\s+(.*?)\s+DATA", re.IGNORECASE)

#: The column-header comment that opens every section.
_COMMENT = "@!"

#: The all-island split: EirGrid's cases number the Republic's areas 1-12 and
#: Northern Ireland's 13-14 (their ARNAME fields read "IE AREA A".."NI WEST").
IE_AREAS = frozenset(range(1, 13))
NI_AREAS = frozenset((13, 14))

#: Transmission voltages in these cases.  Anything below 110 kV is the
#: distribution stub the transmission model carries to hang load off.
TRANSMISSION_KV = (380.0, 275.0, 220.0, 110.0)

# --------------------------------------------------------------------------- #
# Column layouts
#
# One list per record line, in file order, taken from the '@!' headers of the
# TYTFS 2024 v35 files and checked against the PSS/E 35 raw data format.
# Records may be short; they are never long, and a long one is an error.
# --------------------------------------------------------------------------- #

BUS_COLUMNS = [
    "I", "NAME", "BASKV", "IDE", "AREA", "ZONE", "OWNER",
    "VM", "VA", "NVHI", "NVLO", "EVHI", "EVLO",
]

LOAD_COLUMNS = [
    "I", "ID", "STAT", "AREA", "ZONE", "PL", "QL", "IP", "IQ", "YP", "YQ",
    "OWNER", "SCALE", "INTRPT", "DGENP", "DGENQ", "DGENF", "LOADTYPE",
]

GENERATOR_COLUMNS = [
    "I", "ID", "PG", "QG", "QT", "QB", "VS", "IREG", "NREG", "MBASE",
    "ZR", "ZX", "RT", "XT", "GTAP", "STAT", "RMPCT", "PT", "PB", "BASLOD",
    "O1", "F1", "O2", "F2", "O3", "F3", "O4", "F4", "WMOD", "WPF",
]

BRANCH_COLUMNS = (
    ["I", "J", "CKT", "R", "X", "B", "NAME"]
    + [f"RATE{n}" for n in range(1, 13)]
    + ["GI", "BI", "GJ", "BJ", "STAT", "MET", "LEN",
       "O1", "F1", "O2", "F2", "O3", "F3", "O4", "F4"]
)

#: Transformer line 1 - the transformer itself.
XFMR_COLUMNS_1 = [
    "I", "J", "K", "CKT", "CW", "CZ", "CM", "MAG1", "MAG2", "NMETR", "NAME",
    "STAT", "O1", "F1", "O2", "F2", "O3", "F3", "O4", "F4", "VECGRP", "ZCOD",
]

#: Transformer line 2 - impedances.  Two-winding records carry the first
#: three fields only; three-winding records carry all eleven.
XFMR_COLUMNS_2 = [
    "R1_2", "X1_2", "SBASE1_2",
    "R2_3", "X2_3", "SBASE2_3",
    "R3_1", "X3_1", "SBASE3_1",
    "VMSTAR", "ANSTAR",
]


def _winding_columns(n: int) -> list[str]:
    """Column names for winding-``n``'s record line."""
    return (
        [f"WINDV{n}", f"NOMV{n}", f"ANG{n}"]
        + [f"RATE{n}_{r}" for r in range(1, 13)]
        + [f"COD{n}", f"CONT{n}", f"NOD{n}", f"RMA{n}", f"RMI{n}",
           f"VMA{n}", f"VMI{n}", f"NTP{n}", f"TAB{n}",
           f"CR{n}", f"CX{n}", f"CNXA{n}"]
    )


#: A two-winding transformer's fourth line is WINDV2, NOMV2 and stops there.
XFMR_COLUMNS_W2_SHORT = ["WINDV2", "NOMV2"]

#: Two-terminal DC line 1 - the link.
DC_COLUMNS_LINK = [
    "NAME", "MDC", "RDC", "SETVL", "VSCHD", "VCMOD", "RCOMP", "DELTI",
    "METER", "DCVMIN", "CCCITMX", "CCCACC",
]


def _converter_columns(end: str) -> list[str]:
    """Column names for a DC converter line, ``end`` being 'R' or 'I'."""
    return [
        f"IP{end}", f"NB{end}", f"ANMX{end}", f"ANMN{end}", f"RC{end}",
        f"XC{end}", f"EBAS{end}", f"TR{end}", f"TAP{end}", f"TMX{end}",
        f"TMN{end}", f"STP{end}", f"IC{end}", f"ND{end}", f"IF{end}",
        f"IT{end}", f"ID{end}", f"XCAP{end}",
    ]


AREA_COLUMNS = ["I", "ISW", "PDES", "PTOL", "ARNAME"]

ZONE_COLUMNS = ["I", "ZONAME"]

#: Sections read into DataFrames, keyed by the name the delimiter gives them.
WANTED = {
    "BUS": "bus",
    "LOAD": "load",
    "GENERATOR": "generator",
    "BRANCH": "branch",
    "TRANSFORMER": "transformer",
    "TWO-TERMINAL DC": "two_terminal_dc",
    "AREA": "area",
    "ZONE": "zone",
}

#: Sections deliberately not read.  Listed so that an unknown section name is
#: distinguishable from a known-but-skipped one, and so the skip is a
#: decision recorded in the code rather than a gap.
SKIPPED = {
    "FIXED SHUNT", "SYSTEM SWITCHING DEVICE", "VSC DC LINE",
    "IMPEDANCE CORRECTION", "MULTI-TERMINAL DC", "MULTI-SECTION LINE",
    "INTER-AREA TRANSFER", "OWNER", "FACTS DEVICE", "SWITCHED SHUNT",
    "GNE", "INDUCTION MACHINE", "SUBSTATION",
}

#: Columns whose values are identifiers, not quantities: kept as text so that
#: a circuit id of '1 ' and a machine id of '1 ' survive intact.
_TEXT_COLUMNS = frozenset({
    "NAME", "ID", "CKT", "ARNAME", "ZONAME", "LOADTYPE", "VECGRP",
    "METER", "IDR", "IDI",
})


# --------------------------------------------------------------------------- #
# Lexing
# --------------------------------------------------------------------------- #

def split_fields(line: str) -> list[str]:
    """Split one raw-format record into its fields.

    Commas separate, single or double quotes protect, and an unquoted ``/``
    begins a trailing comment.  Quotes are stripped; surrounding whitespace
    is stripped from unquoted fields only, because a quoted field's padding
    is part of a fixed-width identifier.
    """
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    quoted = False
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "'\"":
            quote = ch
            quoted = True
        elif ch == "/":
            break
        elif ch == ",":
            out.append("".join(buf) if quoted else "".join(buf).strip())
            buf, quoted = [], False
        else:
            buf.append(ch)
    out.append("".join(buf) if quoted else "".join(buf).strip())
    return out


def _row(values: list[str], columns: list[str], context: str) -> dict:
    """Map a record's fields onto ``columns``, padding a short record."""
    if len(values) > len(columns):
        raise ValueError(
            f"{context}: {len(values)} fields for {len(columns)} columns: "
            f"{values!r}"
        )
    row = dict(zip(columns, values))
    for missing in columns[len(values):]:
        row[missing] = None
    return row


def _frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Build a DataFrame with numeric columns coerced, text columns left."""
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        if col in _TEXT_COLUMNS:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# Section walking
# --------------------------------------------------------------------------- #

def iter_sections(text: str):
    """Yield ``(name, records)`` for each section of a raw file.

    ``records`` are the section's data lines with the ``@!`` header comments
    and blank lines removed.  The case-identification block before the first
    delimiter is yielded as the section named ``HEADER``.
    """
    name = "HEADER"
    records: list[str] = []
    for line in text.splitlines():
        delimiter = _DELIMITER.match(line)
        if delimiter:
            yield name, records
            begins = _BEGINS.search(delimiter.group(1))
            name = begins.group(1).upper() if begins else "END"
            records = []
            continue
        if line.startswith(_COMMENT) or not line.strip():
            continue
        records.append(line)
    yield name, records


# --------------------------------------------------------------------------- #
# Per-section parsers
# --------------------------------------------------------------------------- #

def _parse_flat(records: list[str], columns: list[str], name: str) -> pd.DataFrame:
    """Parse a section whose records are one line each."""
    rows = [
        _row(split_fields(line), columns, f"{name} record {n}")
        for n, line in enumerate(records, 1)
    ]
    return _frame(rows, columns)


def _parse_transformers(records: list[str]) -> pd.DataFrame:
    """Parse the transformer section, four or five lines per transformer.

    ``K`` non-zero on the first line marks a three-winding transformer: its
    impedance line carries all eleven fields and each of its three windings
    gets a full record line.  A two-winding transformer's impedance line
    carries three fields and its second winding is a two-field line.
    """
    columns = (
        XFMR_COLUMNS_1 + XFMR_COLUMNS_2
        + _winding_columns(1) + _winding_columns(2) + _winding_columns(3)
    )
    rows = []
    i = 0
    while i < len(records):
        first = _row(split_fields(records[i]), XFMR_COLUMNS_1,
                     f"transformer record at line {i}")
        three_winding = int(float(first["K"] or 0)) != 0
        lines = 5 if three_winding else 4
        if i + lines > len(records):
            raise ValueError(
                f"transformer record at line {i} wants {lines} lines, "
                f"{len(records) - i} left"
            )
        row = dict(first)
        row.update(_row(split_fields(records[i + 1]), XFMR_COLUMNS_2,
                        "transformer impedances"))
        row.update(_row(split_fields(records[i + 2]), _winding_columns(1),
                        "transformer winding 1"))
        if three_winding:
            row.update(_row(split_fields(records[i + 3]), _winding_columns(2),
                            "transformer winding 2"))
            row.update(_row(split_fields(records[i + 4]), _winding_columns(3),
                            "transformer winding 3"))
        else:
            row.update(_row(split_fields(records[i + 3]),
                            XFMR_COLUMNS_W2_SHORT, "transformer winding 2"))
        row["WINDINGS"] = 3 if three_winding else 2
        rows.append(row)
        i += lines
    return _frame(rows, columns + ["WINDINGS"])


def _parse_two_terminal_dc(records: list[str]) -> pd.DataFrame:
    """Parse the two-terminal DC section, three lines per link."""
    columns = (
        DC_COLUMNS_LINK + _converter_columns("R") + _converter_columns("I")
    )
    if len(records) % 3:
        raise ValueError(
            f"two-terminal DC section has {len(records)} lines, not a "
            "multiple of 3"
        )
    rows = []
    for i in range(0, len(records), 3):
        row = _row(split_fields(records[i]), DC_COLUMNS_LINK, "DC link")
        row.update(_row(split_fields(records[i + 1]),
                        _converter_columns("R"), "DC rectifier"))
        row.update(_row(split_fields(records[i + 2]),
                        _converter_columns("I"), "DC inverter"))
        rows.append(row)
    return _frame(rows, columns)


# --------------------------------------------------------------------------- #
# The case
# --------------------------------------------------------------------------- #

@dataclass
class Case:
    """One solved load-flow case, section by section."""

    path: str
    title: tuple[str, ...]
    sbase: float
    bus: pd.DataFrame
    load: pd.DataFrame
    generator: pd.DataFrame
    branch: pd.DataFrame
    transformer: pd.DataFrame
    two_terminal_dc: pd.DataFrame
    area: pd.DataFrame
    zone: pd.DataFrame

    @property
    def name(self) -> str:
        """The scenario name, e.g. ``TYTFS2024_WP2024_V35``."""
        return os.path.splitext(os.path.basename(self.path))[0]

    def frames(self) -> dict[str, pd.DataFrame]:
        """The DataFrames, keyed by section name."""
        return {
            f.name: getattr(self, f.name)
            for f in dataclass_fields(self)
            if f.type == "pd.DataFrame"
        }

    def __repr__(self) -> str:
        counts = ", ".join(f"{k}={len(v)}" for k, v in self.frames().items())
        return f"Case({self.name}: {counts})"


def read_raw(path: str) -> Case:
    """Read a PSS/E v35 ``.raw`` file into a :class:`Case` of DataFrames.

    Sections outside :data:`WANTED` are skipped.  An unrecognised section
    name raises, because a v35 file this reader has not seen the shape of is
    more likely a format surprise than a section worth ignoring silently.
    """
    with open(path, encoding=ENCODING, newline="") as fh:
        text = fh.read()

    parsed: dict[str, pd.DataFrame] = {}
    title: tuple[str, ...] = ()
    sbase = float("nan")

    for name, records in iter_sections(text):
        if name == "HEADER":
            first = split_fields(records[0]) if records else []
            if len(first) > 2:
                sbase = float(first[1])
                rev = int(float(first[2]))
                if rev != REV:
                    raise ValueError(
                        f"{path}: raw format revision {rev}, not {REV}. The "
                        "field layouts here are v35's; the v33 files beside "
                        "these have fewer branch ratings and no branch name, "
                        "so reading them with this parser would silently "
                        "misalign columns."
                    )
            title = tuple(
                line.lstrip("/ ").rstrip()
                for line in records[1:] if line.startswith("/")
            )
            continue
        if name == "END" or name in SKIPPED:
            continue
        if name not in WANTED:
            raise ValueError(f"{path}: unknown section {name!r}")
        key = WANTED[name]
        if key == "transformer":
            parsed[key] = _parse_transformers(records)
        elif key == "two_terminal_dc":
            parsed[key] = _parse_two_terminal_dc(records)
        else:
            columns = {
                "bus": BUS_COLUMNS, "load": LOAD_COLUMNS,
                "generator": GENERATOR_COLUMNS, "branch": BRANCH_COLUMNS,
                "area": AREA_COLUMNS, "zone": ZONE_COLUMNS,
            }[key]
            parsed[key] = _parse_flat(records, columns, key)

    missing = set(WANTED.values()) - set(parsed)
    for key in missing:
        parsed[key] = pd.DataFrame()

    return Case(path=path, title=title, sbase=sbase, **parsed)


def read_all(pattern: str = "data/TYTFS2024_studyfiles/*_V35.raw") -> dict[str, Case]:
    """Read every case matching ``pattern``, keyed by scenario name."""
    cases = [read_raw(p) for p in sorted(glob.glob(pattern))]
    return {c.name: c for c in cases}


# --------------------------------------------------------------------------- #
# Derived views
#
# The reader returns the file.  These turn it into the handful of quantities
# anything downstream asks for first, and they are where the in-service
# filters live.
# --------------------------------------------------------------------------- #

def bus_voltages(case: Case) -> pd.Series:
    """Bus count by base kV, highest first."""
    return case.bus["BASKV"].value_counts().sort_index(ascending=False)


def ac_branches(case: Case, min_kv: float = 110.0,
                in_service: bool = False) -> pd.DataFrame:
    """AC branches with both ends at or above ``min_kv``.

    Transformers are a separate section and are not included: this is the
    line-and-cable network.  ``KV_I``/``KV_J`` are joined on from the bus
    section, and ``BASKV`` is their maximum - equal for every circuit in
    these cases, so it is simply the circuit's voltage.  Out-of-service
    circuits are kept by default, because a planning case's branch register
    is the network on paper and ``STAT`` is a scenario choice about it.
    """
    kv = case.bus.set_index("I")["BASKV"]
    df = case.branch.copy()
    df["KV_I"] = df["I"].map(kv)
    df["KV_J"] = df["J"].map(kv)
    df["BASKV"] = df[["KV_I", "KV_J"]].max(axis=1)
    keep = (df["KV_I"] >= min_kv) & (df["KV_J"] >= min_kv)
    if in_service:
        keep &= df["STAT"] == 1
    return df[keep]


def generators(case: Case, in_service: bool = True) -> pd.DataFrame:
    """Generator records, in-service only by default.

    ``STAT`` is the flag that matters.  The section is a register of every
    machine the model knows about; the scenario's dispatch is the subset
    with ``STAT == 1``, and summing ``PG`` over the register instead gives a
    total the island could not physically produce.
    """
    df = case.generator
    return df[df["STAT"] == 1] if in_service else df


def loads(case: Case, in_service: bool = True) -> pd.DataFrame:
    """Load records, in-service only by default."""
    df = case.load
    return df[df["STAT"] == 1] if in_service else df


def jurisdiction(area: pd.Series) -> pd.Series:
    """Map area numbers onto 'IE' / 'NI'."""
    return pd.Series(
        ["IE" if a in IE_AREAS else "NI" if a in NI_AREAS else "??"
         for a in area],
        index=area.index,
    )


def summary(case: Case) -> dict:
    """The headline figures for one case."""
    gen = generators(case)
    ld = loads(case)
    ac = ac_branches(case)
    return {
        "buses": len(case.bus),
        "branches": len(case.branch),
        "transformers": len(case.transformer),
        "generator_records": len(case.generator),
        "generators_in_service": len(gen),
        "loads": len(case.load),
        "dispatched_pg_mw": float(gen["PG"].sum()),
        "total_load_mw": float(ld["PL"].sum()),
        "load_register_mw": float(case.load["PL"].sum()),
        "loads_in_service": len(ld),
        "dc_links": len(case.two_terminal_dc),
        "bus_kv": {kv: int((case.bus["BASKV"] == kv).sum())
                   for kv in TRANSMISSION_KV},
        "ac_branch_kv": {kv: int((ac["BASKV"] == kv).sum())
                         for kv in TRANSMISSION_KV},
        "ac_branches_110_plus": len(ac),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

#: The WP2024 figures confirmed independently of this parser.  ``validate``
#: checks against them; they are not adjusted to whatever the parser says.
WP2024_EXPECTED = {
    "buses": 2026,
    "branches": 1130,
    "generator_records": 597,
    "loads": 267,
    "bus_kv": {380.0: 7, 275.0: 15, 220.0: 69, 110.0: 456},
    "ac_branches_110_plus": 679,
    "ac_branch_kv": {380.0: 7, 275.0: 23, 220.0: 94, 110.0: 555},
    "generators_in_service": 87,
    "dispatched_pg_mw": 7412,
    "total_load_mw": 8246,
}


#: Why a check fails, where the cause is understood.  These explain the
#: disagreement; they do not excuse it, and nothing above is tuned to make
#: any of them go away.
DISAGREEMENT_NOTES = {
    "buses": "expected count is the 2,025 records plus the section's one "
             "'@!' header line",
    "branches": "expected count is the 1,129 records plus the section's one "
                "'@!' header line",
    "loads": "expected count is the 266 records plus the section's one "
             "'@!' header line",
    "total_load_mw": "8,246 MW is the whole load register; 34 records with "
                     "STAT=0 and ID='MI', worth 922 MW, sit at buses that "
                     "already carry an in-service load, so counting them "
                     "double-counts those buses",
}


def run_summary(paths: list[str]) -> None:
    """Print the headline figures for each case."""
    for path in paths:
        case = read_raw(path)
        s = summary(case)
        print(f"\n{case.name}")
        print("-" * len(case.name))
        for line in case.title:
            print(f"  {line}")
        print(f"  buses            {s['buses']:>8,}   "
              + "  ".join(f"{kv:g}kV={s['bus_kv'][kv]}"
                          for kv in TRANSMISSION_KV))
        print(f"  AC branches      {s['branches']:>8,}   "
              f">=110kV both ends={s['ac_branches_110_plus']}  ("
              + "  ".join(f"{kv:g}kV={s['ac_branch_kv'][kv]}"
                          for kv in TRANSMISSION_KV) + ")")
        print(f"  transformers     {s['transformers']:>8,}")
        print(f"  generators       {s['generator_records']:>8,}   "
              f"in service={s['generators_in_service']}  "
              f"PG={s['dispatched_pg_mw']:,.0f} MW")
        print(f"  loads            {s['loads']:>8,}   "
              f"in service={s['loads_in_service']}  "
              f"PL={s['total_load_mw']:,.0f} MW  "
              f"(whole register {s['load_register_mw']:,.0f} MW)")
        print(f"  two-terminal DC  {s['dc_links']:>8,}")


def run_validate(path: str) -> int:
    """Check the WP2024 case against the independently confirmed figures."""
    case = read_raw(path)
    s = summary(case)
    checks: list[tuple[str, object, object]] = []
    for key, want in WP2024_EXPECTED.items():
        if isinstance(want, dict):
            for kv, n in want.items():
                checks.append((f"{key} {kv:g}kV", s[key][kv], n))
        elif key in ("dispatched_pg_mw", "total_load_mw"):
            checks.append((key, round(s[key]), want))
        else:
            checks.append((key, s[key], want))
    width = max(len(name) for name, _, _ in checks)
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:<{width}}  "
              f"parsed={got!s:>8}  expected={want!s:>8}")
    print(f"\n{len(checks) - bad}/{len(checks)} checks pass")
    for name, got, want in checks:
        if got != want and name in DISAGREEMENT_NOTES:
            print(f"\n  {name}: {DISAGREEMENT_NOTES[name]}.")
    return 1 if bad else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help=run_summary.__doc__.splitlines()[0])
    s.add_argument("paths", nargs="*",
                   default=sorted(glob.glob(
                       "data/TYTFS2024_studyfiles/*_V35.raw")))
    v = sub.add_parser("validate", help=run_validate.__doc__.splitlines()[0])
    v.add_argument("path", nargs="?",
                   default="data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw")
    args = p.parse_args(argv)
    if args.cmd == "summary":
        run_summary(args.paths)
        return 0
    return run_validate(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
