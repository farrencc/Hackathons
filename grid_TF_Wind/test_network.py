"""Regression tests for the voltage-handling path.

The motivating bug: code that reached for the voltage column as

    v = gdf.get("voltage")
    if v:
        ...

is wrong in both directions.  With the column absent, ``gdf.get`` returns
``None`` and the branch is silently skipped, so an area with thousands of
voltage-tagged lines is reported as having none.  With the column present,
``if v:`` raises ``ValueError: The truth value of a Series is ambiguous``.

On top of that, pyrosm does not promote ``voltage`` to a DataFrame column
unless it is named in ``tags_as_columns`` - it leaves it inside a JSON ``tags``
blob.  So the "column absent" case is the *normal* case with a default pyrosm
read, not a rare edge case, and the silent-skip branch would have reported 0%
voltage coverage nationally.
"""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

import network as m


def _gdf(rows, with_voltage=True):
    data = {"power": [r[0] for r in rows],
            "geometry": [LineString([(0, i), (1, i)]) for i, _ in enumerate(rows)]}
    if with_voltage:
        data["voltage"] = [r[1] for r in rows]
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


def test_get_returns_none_when_column_missing():
    """Documents the trap itself: .get() does not raise, it returns None."""
    gdf = _gdf([("minor_line", "20000")], with_voltage=False)
    assert gdf.get("voltage") is None


def test_truthiness_of_present_column_raises():
    """The same branch blows up when the column *is* there."""
    gdf = _gdf([("minor_line", "20000")])
    with pytest.raises(ValueError):
        bool(gdf.get("voltage"))


def test_voltage_series_missing_column_is_all_na_not_none():
    gdf = _gdf([("minor_line", None), ("cable", None)], with_voltage=False)
    s = m.voltage_series(gdf)
    assert isinstance(s, pd.Series)
    assert len(s) == len(gdf)
    assert s.isna().all()


def test_voltage_series_present_column_passes_through():
    gdf = _gdf([("minor_line", "20000"), ("cable", "10000")])
    assert list(m.voltage_series(gdf)) == ["20000", "10000"]


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("nan", None), ("yes", None), ("-1", None),
    ("400", 400.0), ("20000", 20000.0), ("38000 V", 38000.0),
    ("10000;20000", 20000.0), ("110000;38000", 110000.0),
    ("0.4", 0.4),
])
def test_parse_voltage(raw, expected):
    assert m.parse_voltage(raw) == expected


@pytest.mark.parametrize("volts,band", [
    (None, m.UNKNOWN_BAND), (230.0, "LV (<1 kV)"), (400.0, "LV (<1 kV)"),
    (10_000.0, "MV (1-<38 kV)"), (20_000.0, "MV (1-<38 kV)"),
    (38_000.0, "38 kV"), (110_000.0, "HV >=110 kV (transmission)"),
    (400_000.0, "HV >=110 kV (transmission)"),
])
def test_voltage_band(volts, band):
    assert m.voltage_band(volts) == band


def test_expand_tags_recovers_voltage_from_blob():
    """The pyrosm-specific half of the bug."""
    gdf = _gdf([("minor_line", None), ("cable", None)], with_voltage=False)
    gdf["tags"] = ['{"voltage":"20000","location":"overhead"}',
                   '{"voltage":"10000","location":"underground"}']
    out = m.expand_tags(gdf)
    assert list(out["voltage"]) == ["20000", "10000"]
    assert list(out["location"]) == ["overhead", "underground"]


def test_expand_tags_does_not_clobber_existing_values():
    gdf = _gdf([("minor_line", "20000")])
    gdf["tags"] = ['{"voltage":"999"}']
    out = m.expand_tags(gdf)
    assert list(out["voltage"]) == ["20000"]


def test_to_graph_on_empty_frame_returns_empty_graph():
    empty = gpd.GeoDataFrame({"power": [], "geometry": []}, crs="EPSG:4326")
    g = m.to_graph(empty, snap_m=1.0)
    assert g.number_of_nodes() == 0


def test_to_graph_snapping_joins_near_endpoints():
    """Two lines 3 m apart: disconnected at 1 m tolerance, joined at 5 m."""
    lines = gpd.GeoDataFrame({
        "power": ["minor_line", "minor_line"],
        "geometry": [LineString([(0, 0), (0, 100)]),
                     LineString([(0, 103), (0, 200)])],
    }, crs=m.ITM).to_crs("EPSG:4326")
    assert m.component_stats(m.to_graph(lines, snap_m=1.0))["n_components"] == 2
    assert m.component_stats(m.to_graph(lines, snap_m=5.0))["n_components"] == 1


def test_to_graph_splits_at_t_junction():
    """A feeder ending mid-way along another line must connect, not orphan."""
    lines = gpd.GeoDataFrame({
        "power": ["minor_line", "minor_line"],
        "geometry": [LineString([(0, 0), (200, 0)]),
                     LineString([(100, 0), (100, 80)])],
    }, crs=m.ITM).to_crs("EPSG:4326")
    stats = m.component_stats(m.to_graph(lines, snap_m=0.1))
    assert stats["n_components"] == 1
    assert stats["n_nodes"] == 4


# --------------------------------------------------------------------------- #
# Guards on things that would move published numbers or silently drop a layer
# --------------------------------------------------------------------------- #

def test_band_labels_are_frozen():
    """These strings are keys in data/analysis.json and text in map legends.

    Renaming one rewrites an artefact, so the rename has to be deliberate
    enough to come here and change this list too.
    """
    assert [b.label for b in m.ALL_BANDS] == [
        "unknown (no voltage tag)",
        "LV (<1 kV)",
        "MV (1-<38 kV)",
        "38 kV",
        "HV >=110 kV (transmission)",
    ]


def test_every_band_has_a_plot_style():
    """A new voltage band must not be able to vanish from a map unnoticed.

    ``plots`` keys its palette on ``Band.id`` and raises at import if a band
    has no style, which is why this test is just an import plus a set check.
    """
    import plots

    assert {b.id for b in m.ALL_BANDS} <= set(plots.BAND_STYLE)


def test_parse_voltage_does_not_interpret_kv_suffix():
    """``parse_voltage`` reads OSM tags, where the value is plain volts.

    ``"110 kV"`` giving 110.0 is correct here, not a bug: OSM convention omits
    the unit, so the first number *is* the voltage. Teaching this function a
    kV suffix would silently re-band every OSM tag written with a unit and move
    figures in data/analysis.json and data/national.json. EirGrid's strict
    parser lives in eirgrid.parse_kv instead.
    """
    assert m.parse_voltage("110 kV") == 110.0
    assert m.parse_voltage("20 kV") == 20.0


def test_eirgrid_parse_kv_is_strict():
    import eirgrid

    assert eirgrid.parse_kv("110 kV") == 110_000.0
    assert eirgrid.parse_kv("275 kV") == 275_000.0
    assert eirgrid.parse_kv("400 kv") == 400_000.0
    for bad in ("110", "", None, "110000", "kV"):
        with pytest.raises(ValueError):
            eirgrid.parse_kv(bad)


def test_annotate_does_not_mutate_caller_on_empty_frame():
    empty = gpd.GeoDataFrame({"power": [], "geometry": []}, crs="EPSG:4326")
    m.annotate(empty)
    assert "band" not in empty.columns


def test_load_lines_keeps_non_conductor_power_values(monkeypatch):
    """The per-area path must not filter lines to conductor ``power`` values.

    data/analysis.json records 18 ``power=portal`` linestrings in Kilkenny. If
    ``load_lines`` defaulted to conductors only, those would disappear and
    n_line_features, total_km, every by-band figure, both graph blocks and the
    missing-cable ratio would all move.
    """
    raw = gpd.GeoDataFrame({
        "power": ["minor_line", "portal"],
        "voltage": ["20000", None],
        "geometry": [LineString([(0, 0), (0, 1)]),
                     LineString([(1, 0), (1, 1)])],
    }, crs="EPSG:4326")
    monkeypatch.setattr(m, "read_power_features", lambda *a, **k: raw)

    kept = m.load_lines()["lines"]
    assert sorted(kept["power"]) == ["minor_line", "portal"]

    conductors = m.load_lines(line_power_only=True)["lines"]
    assert list(conductors["power"]) == ["minor_line"]


def test_eirgrid_paging_assembles_all_pages(monkeypatch):
    """Paging must cover the whole layer and refuse to truncate silently.

    In GeoJSON mode ArcGIS reports truncation under ``properties``, not at the
    top level, so a caller watching the wrong key pages once and loses the rest
    of the network without an error.
    """
    import eirgrid

    total, page = 5, 2
    calls = []

    def fake(url, params):
        calls.append((url, dict(params)))
        if params.get("returnCountOnly") == "true":
            return {"count": total}
        offset = params["resultOffset"]
        n = min(page, total - offset)
        return {"features": [{"properties": {"OBJECTID": offset + i},
                              "geometry": None} for i in range(n)],
                "properties": {"exceededTransferLimit": offset + n < total}}

    monkeypatch.setattr(eirgrid, "_get_json", fake)
    got = eirgrid.query_paged(40, ("OBJECTID",), page=page)

    assert len(got) == total
    queries = [p for _, p in calls if "resultOffset" in p]
    assert [p["resultOffset"] for p in queries] == [0, 2, 4]
    assert all(p["orderByFields"] == "OBJECTID" for p in queries)
    assert all(p["outSR"] == 2157 for p in queries)


def test_eirgrid_paging_raises_on_an_empty_page(monkeypatch):
    import eirgrid

    def fake(url, params):
        if params.get("returnCountOnly") == "true":
            return {"count": 10}
        return {"features": []}

    monkeypatch.setattr(eirgrid, "_get_json", fake)
    with pytest.raises(RuntimeError, match="empty page"):
        eirgrid.query_paged(40, ("OBJECTID",))


def test_no_two_modules_name_the_same_cache_path():
    """A cache path may be written by one module and imported by others.

    The bug this guards against: plot_national.py re-typed
    "data/raw/counties.gpkg", a path only county_sweep.py wrote, so the
    national map crashed on a fresh clone unless another script had run first.
    Two modules naming the same path is that bug; one module owning a path and
    others importing the constant - as build_web_map does from
    extract_web_data - is the fix, so this checks for re-typing rather than
    for the literal.
    """
    import collections
    import pathlib
    import re

    here = pathlib.Path(__file__).parent
    owners = collections.defaultdict(set)
    for path in sorted(here.glob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        for hit in re.findall(r'"(data/raw/[^"]+)"', path.read_text()):
            owners[hit].add(path.name)

    shared = {path: sorted(mods) for path, mods in owners.items()
              if len(mods) > 1}
    assert shared == {}, f"cache paths named in more than one module: {shared}"
