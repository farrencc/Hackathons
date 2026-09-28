"""Tests for the inertia model and the reference incident.

The first test is the one to read: it pins the units.  At the published
23,000 MWs floor, a 500 MW infeed loss must give 0.543 Hz/s.  A factor-of-two
slip between H and 2H, or between MWs and GWs, fails it immediately, and every
downstream number would be out by the same factor.
"""

import glob
import os
import re

import numpy as np
import pandas as pd
import pytest

import inertia as m

HERE = os.path.dirname(os.path.abspath(__file__))


def _fleet():
    return pd.DataFrame({
        "technology": ["CCGT", "OCGT", "steam", "hydro", "pumped_storage"],
        "mbase": [500.0, 400.0, 350.0, 30.0, 87.5],
    }, index=["ccgt", "ocgt", "coal", "hyd", "ps"])


def test_initial_rocof_at_the_floor():
    """0.543 Hz/s at 23,000 MWs and 500 MW - the floor and the limit agree."""
    rocof = m.initial_rocof(500.0, m.OPERATIONAL_INERTIA_FLOOR_MWS)
    assert rocof == pytest.approx(0.543, abs=0.001)
    assert rocof > 0.5


def test_energy_is_h_times_mva_for_synchronised_machines_only():
    units = _fleet()
    online = pd.Series([True, False, True, False, True], index=units.index)
    e = m.system_energy(units, online)
    assert e["E_mws"] == pytest.approx(6.0 * 500 + 4.0 * 350 + 3.0 * 87.5)
    assert e["components"]["ocgt"] == 0.0


def test_converter_coupled_plant_has_no_inertia():
    for tech in ("wind", "solar", "battery", "hvdc"):
        assert m.machine_h(tech) == 0.0


def test_an_unknown_synchronous_technology_is_refused():
    """A machine with no H must not quietly count as zero."""
    with pytest.raises(KeyError):
        m.machine_h("gas_engine")


def test_condensers_add_their_mws():
    units = _fleet()
    off = pd.Series(False, index=units.index)
    e = m.system_energy(units, off, condensers=3)
    assert e["E_mws"] == pytest.approx(3 * m.SYNC_CONDENSER_MWS)


def test_unit_trip_removes_its_kinetic_energy():
    units = _fleet()
    online = pd.Series(True, index=units.index)
    e = m.system_energy(units, online)
    post = m.post_trip_energy(e["E_mws"], e["components"], "ccgt", "unit")
    assert post < e["E_mws"]
    assert e["E_mws"] - post == pytest.approx(6.0 * 500.0)


def test_hvdc_trip_removes_none():
    units = _fleet()
    online = pd.Series(True, index=units.index)
    e = m.system_energy(units, online)
    assert m.post_trip_energy(e["E_mws"], e["components"], "EWIC",
                              "hvdc") == e["E_mws"]


def test_same_dp_gives_higher_rocof_for_a_unit_than_for_hvdc():
    """Why the incident type has to stay in the output."""
    units = _fleet()
    online = pd.Series(True, index=units.index)
    e = m.system_energy(units, online)
    unit = m.initial_rocof(450.0, m.post_trip_energy(
        e["E_mws"], e["components"], "ccgt", "unit"))
    hvdc = m.initial_rocof(450.0, m.post_trip_energy(
        e["E_mws"], e["components"], "EWIC", "hvdc"))
    assert unit > hvdc


def test_reference_incident_is_the_largest_infeed_either_kind():
    out = pd.Series({"a": 300.0, "b": 440.0})
    unit = m.reference_incident(out, {"EWIC": 400.0, "Moyle": -200.0})
    assert (unit["incident_element"], unit["incident_type"]) == ("b", "unit")
    assert unit["lsi_mw"] == 440.0
    hvdc = m.reference_incident(out, {"EWIC": 504.0, "Moyle": -200.0})
    assert (hvdc["incident_element"], hvdc["incident_type"]) == ("EWIC",
                                                                "hvdc")


def test_exports_are_not_infeeds_but_are_the_negative_incident():
    out = pd.Series({"a": 300.0})
    ri = m.reference_incident(out, {"EWIC": -526.0},
                              pump_load=pd.Series({"ps1": 87.5}))
    assert ri["lsi_mw"] == 300.0
    assert ri["ri_minus_mw"] == 526.0 and ri["ri_minus_type"] == "hvdc"


def test_c_loss_is_added_to_the_lsi():
    ri = m.reference_incident(pd.Series({"a": 400.0}), {}, c_loss_fraction=0.1)
    assert ri["ri_plus_mw"] == pytest.approx(440.0)


def test_rocof_is_vectorised():
    got = m.initial_rocof(np.array([500.0, 250.0]), np.array([23e3, 23e3]))
    assert got[0] == pytest.approx(2 * got[1])


def test_no_other_module_carries_an_inertia_number():
    """One table, one place.

    Scans the study's other modules for a definition that looks like an
    inertia constant or a MWs figure.  It is a coarse check, but the failure
    it is aimed at - someone pasting ``H = 6.0`` into a second file - is a
    coarse mistake.
    """
    pattern = re.compile(r"^\s*(H_[A-Z_]*|[A-Z_]*_MWS|[A-Z_]*INERTIA[A-Z_]*)"
                         r"\s*=\s*[-\d{]", re.MULTILINE)
    for name in ("ensemble.py", "frequency.py", "compare.py", "validate.py",
                 "testcase.py"):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            found = pattern.findall(fh.read())
        assert not found, f"{name} defines {found}; move it to inertia.py"
