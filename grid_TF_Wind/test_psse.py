"""Regression tests for the PSS/E v35 raw reader.

Two classes of thing are guarded here.

The lexer and the multi-line records are tested on synthetic input, because
those are where a raw parser goes wrong silently: a quoted field containing
a comma, a record that stops early because its trailing owner fields were
omitted, a three-winding transformer read as two-winding and every record
after it shifted by one line.  None of those raise - they produce a
plausible-looking DataFrame with the wrong numbers in it.

The headline figures are tested against the real WP2024 case, because the
whole point of this module is that those numbers come out right.  The one
that matters most is the generator STAT filter: the WP2024 register holds
597 machines totalling 18,158 MW of PG, of which 87 totalling 7,412 MW are
actually running.  A parser that loses STAT still parses.
"""

import os

import pandas as pd
import pytest

import psse as m

WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"

needs_case = pytest.mark.skipif(
    not os.path.exists(WP2024), reason="TYTFS study files not present"
)


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    return m.read_raw(WP2024)


# --------------------------------------------------------------------------- #
# Lexing
# --------------------------------------------------------------------------- #

def test_split_fields_strips_quotes_and_whitespace():
    assert m.split_fields("  10,'F_M         ',  38.0000,1") == [
        "10", "F_M         ", "38.0000", "1"]


def test_split_fields_keeps_padding_inside_quotes():
    """A circuit id is fixed-width: '1 ' is not '1'."""
    assert m.split_fields("11, 42404,'1 ', 3.6E-03")[2] == "1 "


def test_split_fields_protects_commas_inside_quotes():
    assert m.split_fields("1,'A, B',2") == ["1", "A, B", "2"]


def test_split_fields_handles_double_quotes():
    """The two-terminal DC section quotes its name with " and not '."""
    assert m.split_fields('"1           ",1,   2.0956')[0] == "1           "


def test_split_fields_drops_trailing_comment():
    assert m.split_fields("0,  100.00, 35 / PSS(R)E-35.6  TUE") == [
        "0", "100.00", "35"]


def test_short_record_is_padded_not_rejected():
    row = m._row(["1", "2"], ["A", "B", "C"], "ctx")
    assert row == {"A": "1", "B": "2", "C": None}


def test_long_record_raises():
    """Too many fields means the layout is wrong, and silence would hide it."""
    with pytest.raises(ValueError, match="fields for"):
        m._row(["1", "2", "3", "4"], ["A", "B", "C"], "ctx")


# --------------------------------------------------------------------------- #
# Section walking
# --------------------------------------------------------------------------- #

RAW_STUB = "\r\n".join([
    "@!IC,SBASE,REV,XFRRAT,NXFRAT,BASFRQ",
    "0,  100.00, 35,     1,     1, 50.00     / PSS(R)E-35.6",
    "/ CASE: a test",
    "0 / END OF SYSTEM-WIDE DATA, BEGIN BUS DATA",
    "@!   I,'NAME        ', BASKV, IDE,AREA,ZONE,OWNER, VM,        VA",
    "    10,'F_M         ',  38.0000,1,  11,  11,   1,1.06540, -10.9636",
    "  5464,'WOODLAND    ', 380.0000,1,  11,  11,   1,1.02000,  -1.0000",
    "0 / END OF BUS DATA, BEGIN LOAD DATA",
    "@!   I,'ID',STAT,AREA,ZONE,      PL,        QL",
    "    10,'LD',   1,  11,   1,    76.210,     1.870",
    "    10,'MI',   0,  11,   1,    50.000,     1.000",
    "0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA",
    "@! I,'ID',STAT,GL,BL",
    "  1101,'1 ',1, 0.000, 12.000",
    "0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA",
    "0 / END OF GENERATOR DATA, BEGIN BRANCH DATA",
    "0 / END OF BRANCH DATA, BEGIN SYSTEM SWITCHING DEVICE DATA",
    "0 / END OF SYSTEM SWITCHING DEVICE DATA, BEGIN TRANSFORMER DATA",
    "0 / END OF TRANSFORMER DATA, BEGIN AREA DATA",
    "0 / END OF AREA DATA, BEGIN TWO-TERMINAL DC DATA",
    "0 / END OF TWO-TERMINAL DC DATA, BEGIN ZONE DATA",
    "0 / END OF ZONE DATA, BEGIN OWNER DATA",
    "0 / END OF OWNER DATA",
    "Q",
    "",
])


def test_sections_are_named_by_the_delimiter_that_precedes_them():
    names = [name for name, _ in m.iter_sections(RAW_STUB)]
    assert names[:4] == ["HEADER", "BUS", "LOAD", "FIXED SHUNT"]


def test_header_comments_are_not_records():
    sections = dict(m.iter_sections(RAW_STUB))
    assert len(sections["BUS"]) == 2
    assert not any(line.startswith("@!") for line in sections["BUS"])


def test_read_raw_on_a_stub(tmp_path):
    p = tmp_path / "stub.raw"
    p.write_bytes(RAW_STUB.encode("latin-1"))
    case = m.read_raw(str(p))
    assert case.sbase == 100.0
    assert case.title == ("CASE: a test",)
    assert len(case.bus) == 2
    assert case.bus["BASKV"].tolist() == [38.0, 380.0]
    assert case.bus["NAME"].tolist() == ["F_M         ", "WOODLAND    "]
    assert len(case.load) == 2
    assert case.generator.empty and case.branch.empty


def test_unknown_section_raises(tmp_path):
    p = tmp_path / "odd.raw"
    p.write_bytes(RAW_STUB.replace("BEGIN LOAD DATA",
                                   "BEGIN PARTICLE ACCELERATOR DATA")
                  .encode("latin-1"))
    with pytest.raises(ValueError, match="unknown section"):
        m.read_raw(str(p))


@needs_case
def test_v33_file_is_refused():
    """The v33 files sit in the same directory and are a different shape."""
    v33 = WP2024.replace("_V35.raw", "_V33.raw")
    if not os.path.exists(v33):
        pytest.skip("v33 file not present")
    with pytest.raises(ValueError, match="revision 33"):
        m.read_raw(v33)


# --------------------------------------------------------------------------- #
# Multi-line records
# --------------------------------------------------------------------------- #

def _xfmr_stub(*bodies):
    lines = ["0 / END OF SYSTEM-WIDE DATA, BEGIN TRANSFORMER DATA"]
    lines += list(bodies)
    lines += ["0 / END OF TRANSFORMER DATA, BEGIN AREA DATA",
              "0 / END OF AREA DATA"]
    return "\r\n".join(lines)


TWO_WINDING = [
    "  2561,    10,     0,'2 ', 1, 1, 1, 0.0, 0.0,2,' 2561 - 10 - 2',1,   2,1.0",
    " 8.19800E-03, 2.98180E-01,9999.00",
    "0.97748,  0.000,  0.000, 9999.00",
    "1.00000,   0.00",
]

THREE_WINDING = [
    " 30001, 30002, 30003,'1 ', 1, 1, 1, 0.0, 0.0,2,' three winding',1,   2,1.0",
    " 1.0E-03, 2.0E-01,100.00, 3.0E-03, 4.0E-01,100.00, 5.0E-03, 6.0E-01,100.00,1.01,0.5",
    "1.00000,  380.0,  0.000, 500.00",
    "1.00000,  110.0,  0.000, 400.00",
    "1.00000,   20.0,  0.000, 300.00",
]


def test_two_winding_transformer_is_four_lines():
    df = m._parse_transformers(TWO_WINDING)
    assert len(df) == 1
    assert df.loc[0, "WINDINGS"] == 2
    assert df.loc[0, "R1_2"] == pytest.approx(8.198e-03)
    assert df.loc[0, "WINDV2"] == pytest.approx(1.0)
    assert pd.isna(df.loc[0, "VMSTAR"])


def test_three_winding_transformer_is_five_lines():
    df = m._parse_transformers(THREE_WINDING)
    assert len(df) == 1
    assert df.loc[0, "WINDINGS"] == 3
    assert df.loc[0, "K"] == 30003
    assert df.loc[0, "VMSTAR"] == pytest.approx(1.01)
    assert df.loc[0, "NOMV3"] == pytest.approx(20.0)


def test_mixed_transformers_do_not_shift():
    """The failure mode: one mis-sized record slides every record after it."""
    df = m._parse_transformers(
        TWO_WINDING + THREE_WINDING + TWO_WINDING)
    assert df["WINDINGS"].tolist() == [2, 3, 2]
    assert df["I"].tolist() == [2561, 30001, 2561]


def test_truncated_transformer_raises():
    with pytest.raises(ValueError, match="wants 4 lines"):
        m._parse_transformers(TWO_WINDING[:-1])


def test_two_terminal_dc_is_three_lines():
    df = m._parse_two_terminal_dc([
        '"1           ",1,   2.0956,    40.00,   250.00',
        " 86221,  2, 16.500, 13.500, 0.2156",
        " 86220,  2, 25.000, 15.000, 0.2156",
    ])
    assert len(df) == 1
    assert df.loc[0, "IPR"] == 86221 and df.loc[0, "IPI"] == 86220
    assert df.loc[0, "SETVL"] == pytest.approx(40.0)


def test_ragged_two_terminal_dc_raises():
    with pytest.raises(ValueError, match="multiple of 3"):
        m._parse_two_terminal_dc(["a", "b"])


# --------------------------------------------------------------------------- #
# The WP2024 case itself
# --------------------------------------------------------------------------- #

@needs_case
def test_section_record_counts(case):
    assert len(case.bus) == 2025
    assert len(case.load) == 266
    assert len(case.generator) == 597
    assert len(case.branch) == 1129
    assert len(case.transformer) == 1310
    assert len(case.two_terminal_dc) == 2
    assert len(case.area) == 14
    assert len(case.zone) == 14


@needs_case
def test_transformer_lines_account_for_the_whole_section(case):
    """4 lines per two-winding, 5 per three-winding, and nothing left over.

    This is the arithmetic that would fail first if the reader had lost
    sync: the section holds 5,349 data lines, and 1,201 * 4 + 109 * 5 is
    exactly that.
    """
    counts = case.transformer["WINDINGS"].value_counts()
    assert counts[2] * 4 + counts[3] * 5 == 5349


@needs_case
def test_bus_counts_by_voltage(case):
    counts = case.bus["BASKV"].value_counts()
    assert [counts[kv] for kv in (380.0, 275.0, 220.0, 110.0)] == [7, 15, 69, 456]


@needs_case
def test_ac_branch_counts_by_voltage(case):
    ac = m.ac_branches(case)
    assert len(ac) == 679
    counts = ac["BASKV"].value_counts()
    assert [counts[kv] for kv in (380.0, 275.0, 220.0, 110.0)] == [7, 23, 94, 555]


@needs_case
def test_every_transmission_ac_branch_joins_equal_voltages(case):
    """Voltage transformation is the transformer section's job, not a branch's."""
    ac = m.ac_branches(case)
    assert (ac["KV_I"] == ac["KV_J"]).all()


@needs_case
def test_generator_stat_is_the_difference_between_possible_and_absurd(case):
    """597 machines on the register, 87 running.  Ignoring STAT gives 18 GW."""
    assert len(case.generator) == 597
    assert case.generator["PG"].sum() == pytest.approx(18157.8, abs=0.5)
    running = m.generators(case)
    assert len(running) == 87
    assert running["PG"].sum() == pytest.approx(7411.6, abs=0.5)


@needs_case
def test_dispatch_covers_demand(case):
    """A solved case balances; the load register does not.

    In-service generation exceeds in-service load by a loss-sized margin.
    Against the whole load register - which double-counts 34 buses through
    deactivated 'MI' records - generation would fall 800 MW short, which no
    solved case does.
    """
    pg = m.generators(case)["PG"].sum()
    served = m.loads(case)["PL"].sum()
    register = case.load["PL"].sum()
    assert 0 < pg - served < 0.03 * served
    assert register - pg > 800


@needs_case
def test_deactivated_loads_shadow_active_ones(case):
    """Every STAT=0 load sits at a bus that already has an in-service load."""
    off = case.load[case.load["STAT"] == 0]
    on = case.load[case.load["STAT"] == 1]
    assert len(off) == 34
    assert off["ID"].str.strip().eq("MI").all()
    assert off["I"].isin(on["I"]).all()


@needs_case
def test_areas_split_into_two_jurisdictions(case):
    names = dict(zip(case.area["I"], case.area["ARNAME"].str.strip()))
    assert all(names[a].startswith("IE") for a in m.IE_AREAS)
    assert all(names[a].startswith("NI") for a in m.NI_AREAS)
    assert set(names) == m.IE_AREAS | m.NI_AREAS


@needs_case
def test_identifier_columns_stay_text(case):
    """Machine and circuit ids are labels; '1 ' must not become 1.0."""
    assert not pd.api.types.is_numeric_dtype(case.generator["ID"])
    assert not pd.api.types.is_numeric_dtype(case.branch["CKT"])
    assert isinstance(case.branch["CKT"].iloc[0], str)
    assert "1 " in set(case.branch["CKT"])


#: The only columns WP2024 leaves empty: branches carry one owner, so the
#: second through fourth owner and fraction fields are never written.  Pinned
#: rather than waved through, because an all-null column is otherwise exactly
#: what a layout that slipped a field looks like.
UNSUPPLIED = {("branch", c) for c in ("O2", "F2", "O3", "F3", "O4", "F4")}


@needs_case
def test_only_the_known_columns_are_empty(case):
    """A column of NaN is the signature of a layout that slipped a field."""
    empty = {
        (name, col)
        for name, df in case.frames().items() if not df.empty
        for col in df.columns if df[col].isna().all()
    }
    assert empty == UNSUPPLIED


@needs_case
def test_every_v35_case_parses():
    cases = m.read_all()
    assert len(cases) == 4
    for name, case in cases.items():
        assert len(case.bus) > 1900, name
        assert m.generators(case)["PG"].sum() > 3000, name
