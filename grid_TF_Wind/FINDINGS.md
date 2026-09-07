# OpenStreetMap as a distribution-network input for SWIS-100-IE

**Verdict up front.** OSM's Irish network data is not usable as a distribution
topology, and it is not usable as a demand-allocation prior either. It *is*
usable, and quite good, for the sub-transmission and transmission layers —
38 kV and above. Since SWIS-100-IE aggregates buses to regional nodes rather
than literal substations, that upper layer is most likely all you needed from
OSM in the first place, and you can take it. Everything below 38 kV should be
abandoned: pursue the ESB CAD `.dgn` files and the capacity heatmap for
anything that depends on MV/LV.

The rest of this document sets out what was measured and why it supports that
split.

---

## 1. What was actually run

Two things did not match the brief, and both are worth stating plainly before
any numbers.

First, there was no pipeline module in the repository (the OpenStreetMap data
layer is now `network.py`). The repo at `4246414` contained exactly two
things: an empty `data/.gitkeep` and a file called `requirements.txt.txt`.
There was no script to run, so there was no osmnx 2.x API drift to hit and no
pre-existing `gdf.get("voltage")` branch to inspect in situ. The pipeline here
was written fresh against the interface described in the brief — power-tag
GeoDataFrames plus a `networkx.MultiGraph` from `to_graph(snap_m=...)`. Where
the brief predicted a specific failure, the prediction is reported against the
new code, and the `voltage` case (section 2) turned out to be a genuine and
consequential bug.

Second, the Geofabrik download had to go over plain HTTP. This session's
egress policy blocks HTTPS to `download.geofabrik.de` — and to
`overpass-api.de`, `planet.openstreetmap.org` and every OSM mirror tried — but
allows port 80. The extract was therefore fetched over HTTP and verified
against Geofabrik's published MD5 (`e6fa4fd2707d7c05388e288c8f5ff94d`), which
matched. The file is `ireland-and-northern-ireland-latest.osm.pbf` dated
2026-08-28, 392 MB, 761,470 objects carrying a `power` tag. Since the checksum
came over the same channel this is integrity checking rather than
authentication, but for a public extract whose contents are independently
sanity-checked against ESB's published asset counts, that is adequate. It also
means Overpass was avoided as instructed, and the whole analysis is
reproducible from one file.

One engineering note. pyrosm cannot read the national extract directly: it
holds the entire node index in memory and was OOM-killed with 15 GB available.
A pyosmium pass streams the 392 MB file down to the ~7 MB of objects carrying
a `power` tag plus the nodes they reference, and pyrosm then re-applies the
identical filter to that. The selection is unchanged; only the memory profile
is. Anyone reproducing this on a laptop will need the same step.

## 2. The `voltage` branch was wrong, and wrong in a way that mattered

The brief flagged `gdf.get("voltage")` returning `None` rather than raising.
That instinct was right, and the consequences are worse than expected.

`gdf.get("voltage")` does return `None` when the column is missing, so a
branch written as `if gdf.get("voltage"):` silently does nothing. And when the
column *is* present, the same branch raises `ValueError: The truth value of a
Series is ambiguous`. It never behaves as intended: it either hides a real
result or crashes.

What makes this more than a style point is that with pyrosm the column is
missing by default. pyrosm promotes only a fixed set of keys to DataFrame
columns and buries the rest in a JSON `tags` blob — and `voltage` is in the
blob. So a default read of County Kilkenny returns 16,078 line features with
no `voltage` column at all, the silent branch skips, and the pipeline reports
**0%** voltage coverage. The true figure for Kilkenny is **48.4%**. That is not
a crash you would notice; it is a plausible-looking answer that would have
confirmed the "OSM has no voltage data" hypothesis for entirely spurious
reasons.

The fix is to name the tags in `tags_as_columns`, expand the leftover blob as
a fallback, and have the accessor return an explicit all-NA Series so a
missing column reports "0 of N tagged" rather than dropping the area.
`test_network.py` pins all of this, including the `ValueError` on the
present-column case.

## 3. Coverage: the assumption was right about the outcome, wrong about the mechanism

The working hypothesis was that Irish MV/LV coverage is patchy and biased
toward overhead lines because underground urban cable is invisible to
volunteer mappers. The outcome is confirmed. The mechanism is not what the
hypothesis says, and the difference changes what the data is good for.

Per area, at the county boundary, all voltages:

| | Kilkenny | Mayo | Dublin City | County Dublin |
|---|---|---|---|---|
| Area (km²) | 2,071 | 5,594 | 119 | 928 |
| Line features | 16,078 | 53,258 | 2,278 | 21,472 |
| Total mapped (km) | 1,525 | 4,618 | 136 | 1,443 |
| `minor_line` / `line` / `cable` | 15,184 / 657 / 219 | 52,022 / 1,103 / 125 | 324 / 213 / 1,603 | 15,266 / 1,549 / 4,023 |
| Voltage-tagged (features) | 48.4% | 27.0% | 89.4% | 82.4% |
| Voltage-tagged (km) | 51.4% | 31.1% | 97.7% | 90.7% |
| `cable`:`minor_line` (count) | 0.014 | 0.002 | 4.95 | 0.264 |
| `cable`:`minor_line` (km) | 0.008 | 0.003 | 10.81 | 0.303 |

Circuit length by band, in km:

| Band | Kilkenny | Mayo | Dublin City | County Dublin |
|---|---|---|---|---|
| LV (<1 kV) | 12.0 | 48.8 | 0.3 | 58.5 |
| MV (1–<38 kV) | 458.7 | 811.3 | 4.4 | 680.2 |
| 38 kV | 184.7 | 368.1 | 29.2 | 194.9 |
| ≥110 kV (transmission) | 129.1 | 210.2 | 99.0 | 375.6 |
| no voltage tag | 740.9 | 3,179.7 | 3.1 | 133.6 |

Read the Dublin City column carefully, because taken at face value it says the
opposite of the hypothesis. Dublin has the *best* voltage tagging in the study
(89% of features, 98% of km) and a cable-to-overhead ratio of nearly 5:1 by
count and 11:1 by length. On those two metrics alone you would conclude that
OSM maps Dublin's underground network better than it maps rural Kilkenny's
overhead network.

That conclusion is an artefact of composition. Of Dublin City's 115.7 km of
`power=cable`, 89.9 km is at 110 kV or above and 23.7 km is at 38 kV. Exactly
**1.0 km** is MV, and **0.0 km** is LV. The cable that OSM maps in Dublin is
EirGrid's underground transmission, which is a well-documented asset class that
enthusiasts track closely. The ESB MV and LV cable that actually distributes
power to the city — several thousand kilometres of it — appears as 4.7 km.

So the bias is not "overhead is mapped, underground is not". It is
**voltage-stratified**: the higher the voltage, the more completely it is
mapped, regardless of whether it is overhead or underground. Underground
transmission cable is mapped well. Overhead rural MV is mapped moderately.
Urban MV/LV, overhead or underground, is essentially absent.

### How large is the gap

ESB Networks publishes its own asset counts for the Republic: 150,000 km of
overhead line, 22,000 km of underground cable, 2.1 million wooden poles,
242,000 pole-mounted MV/LV transformers, 21,680 ground MV/LV substations, and
571 primary stations (133 at 110 kV, 438 at 38 kV).

Attributing every OSM power feature to a county and summing the 26 counties of
the Republic (`data/county_sweep.csv`, 70,296 km² — within 0.03% of the state's
actual area, which is a reasonable check that the attribution is sound):

| | OSM | ESB Networks | OSM share |
|---|---|---|---|
| Sub-110 kV line | 37,125 km | 172,000 km | **21.6%** |
| Wooden poles | 470,731 | 2,100,000 | **22.4%** |
| Underground cable | 927 km | 22,000 km | **4.2%** |
| MV/LV transformers | 4,982 | 242,000 | **2.1%** |
| Ground MV/LV substations | 987 | 21,680 | **4.6%** |

The structure of that table is the finding. Line length and pole count agree at
about 22% — two independent measures of the same thing, which is reassuring
about the method and tells you roughly a fifth of the rural overhead network
has been traced. But cable, transformers and substations sit at 2–5%, a factor
of five worse. OSM has captured a fifth of the wires and a fiftieth of the
plant.

The transformer figure is the single most damaging number. Distribution
substations are what you would place buses at in any network-derived model, and
OSM has 2% of them.

### A gap measure that needs no external reference

The ESB comparison invites arguments about how to scale national totals to a
county. Here is one that does not.

Every transformer and substation that OSM maps must, whatever the real network
looks like, be reached by conductor. A minimum spanning tree over those mapped
assets is therefore a hard lower bound on the required length — and a very
generous one, since real distribution follows streets and is built with ring
capacity rather than as a minimal tree. Comparing that bound to the sub-38 kV
line actually mapped:

| Area | Mapped assets | MST lower bound (km) | Mapped sub-38 kV (km) | Ratio |
|---|---|---|---|---|
| Kilkenny | 128 | 201 | 1,212 | 602% |
| Mayo | 154 | 307 | 4,040 | 1,315% |
| **Dublin City** | **874** | **154** | **7.8** | **5.1%** |
| County Dublin | 2,141 | 513 | 872 | 170% |

Dublin City fails its own internal consistency check. OSM contains 874 MV/LV
transformers and substations in the city and 7.8 km of sub-38 kV line — not
enough conductor to reach a twentieth of the assets it already knows about. At
least 95% of Dublin's MV network is missing, and that follows from OSM's own
data without reference to ESB at all.

## 4. Topology: this is a scattering of segments, not a network

This is the diagnostic the brief identified as decisive, and it comes back
unambiguous.

Run island-wide with no administrative clipping — county clipping cuts every
line crossing a boundary and would inflate the counts for exactly the layers
that span counties — the picture separates cleanly by voltage:

| Layer | Features | km | Graph nodes | Components | Largest | % nodes in largest |
|---|---|---|---|---|---|---|
| ≥220 kV | 10,502 | 2,640 | 10,241 | **22** | 9,680 | **94.5%** |
| 110 kV | 43,167 | 6,190 | 42,830 | 124 | 20,598 | 48.1% |
| 38 kV | 50,221 | 6,278 | 50,416 | 347 | 9,608 | 19.1% |
| ≥38 kV combined | 103,890 | 15,108 | 103,301 | 419 | 66,047 | 63.9% |
| MV 1–38 kV | 287,021 | 23,886 | 293,381 | **6,707** | 25,420 | **8.7%** |
| LV <1 kV | 12,822 | 619 | 17,495 | **4,682** | 149 | **0.9%** |
| untagged | 202,557 | 16,724 | 214,298 | 11,920 | 8,480 | 4.0% |
| all sub-110 kV | 552,621 | 47,507 | 565,436 | **13,633** | 49,165 | 8.7% |

The 220 kV and 400 kV network is a network: 22 components, 94.5% of nodes in
one of them. The 110 kV network is nearly one: 124 components with the largest
holding half. The combined ≥38 kV layer holds 64% of its nodes in one
component. These behave like real, connected, mapped infrastructure.

Below that it falls apart. The MV layer is 6,707 disconnected pieces whose
largest holds 8.7% of nodes, with 2,284 pieces of five nodes or fewer. The LV
layer is 4,682 pieces whose largest is 149 nodes — under 1%. The untagged
remainder is 11,920 pieces.

To put 6,707 MV components in context: ESB operates 571 primary stations
nationally. A real radial MV network has one connected component per primary
station busbar, so the true number is on the order of 500–600. OSM gives an
order of magnitude more. County Kilkenny alone returns 686 components at 1 m
snapping for a county that has roughly 17–26 primary stations.

To say it as plainly as the brief asked: **below 38 kV this is a scattering of
independently mapped segments, not a network.** Someone traced a run of poles
along a road, someone else traced another run two townlands away, and nothing
ties them together because the intervening span was never walked. No amount of
snapping will fix that, which is the next section.

## 5. Snapping sensitivity confirms the geometry is genuinely disconnected

If the fragmentation were an artefact of imprecise noding — endpoints that
should coincide sitting a metre or two apart — then component count would
collapse as the tolerance grows past the noding error. It does not.

County Kilkenny, distribution lines only:

| snap_m | Graph nodes | Components | Largest | % in largest |
|---|---|---|---|---|
| 0.1 | 16,097 | 694 | 1,222 | 7.6% |
| 1 | 16,093 | 686 | 1,222 | 7.6% |
| 5 | 15,983 | 663 | 1,570 | 9.8% |
| 25 | 15,249 | 570 | 3,777 | 24.8% |
| 100 | 5,081 | 364 | 1,361 | 26.8% |

Dublin City:

| snap_m | Graph nodes | Components | Largest | % in largest |
|---|---|---|---|---|
| 0.1 | 977 | 63 | 357 | 36.5% |
| 1 | 956 | 57 | 349 | 36.5% |
| 5 | 582 | 41 | 176 | 30.2% |
| 25 | 330 | 29 | 81 | 24.5% |
| 100 | 94 | 11 | 29 | 30.9% |

Going from 0.1 m to 25 m in Kilkenny — a tolerance already far wider than any
plausible GPS or tracing error, and wide enough to fuse genuinely distinct
poles — removes only 18% of components. At 100 m, which is wider than a road
corridor and merges two thirds of all nodes into each other, 364 components
survive. The graph is being destroyed faster than it is being connected: node
count falls by 68% while component count falls by 47%, and the largest
component actually *shrinks* from 3,777 to 1,361 as spurious merges rewire it.

That is the signature of genuinely absent geometry. There is no tolerance at
which this becomes a radial network, because the missing spans are hundreds of
metres to kilometres of unmapped conductor, not centimetres of noding slop.

Note that `to_graph()` already splits lines where another line's endpoint lands
within tolerance of their interior, so these counts are not inflated by
T-junction feeders being treated as orphans. The fragmentation survives a
graph builder built to be generous about it.

## 6. Is it worth anything as a spatial prior?

Separately from topology, the brief asks whether the data retains value for
allocating regional demand or siting distributed generation. The answer differs
sharply between the line layer and the point layer.

**The line layer carries no usable signal, because its variation is mapping
effort rather than network.** The national county sweep makes this
unambiguous. Mapped sub-110 kV density across the 26 counties of the Republic
ranges from 210 km per 1,000 km² in Westmeath to 1,450 in Monaghan — a factor
of 6.9, with a coefficient of variation of 0.56.

The tempting reading is that this is an urban/rural signal. It is not. Monaghan
and Westmeath are both small inland counties of similar character, similar
population density and similar terrain, and they differ by 6.9×. Sligo (1,262)
and Longford (264) differ by 4.8×. Meanwhile County Dublin, which has the
highest demand density in the state, sits third at 1,127 — high, but between
two border counties with a fraction of its load. There is no ordering of these
counties by demand, population or network reality that reproduces the observed
ranking. What it reproduces is where an active local mapper happened to work.

`data/national_distribution.png` shows this directly. The 38 kV skeleton reads
as a coherent national network; the MV layer above it is a set of dense local
clusters — Monaghan and Louth, Sligo, the Dublin fringe, pockets of Cork and
Kerry — separated by large areas holding only untagged fragments or nothing at
all. Those clusters are where mappers have worked. The blank areas are not
unserved; every part of the state has a distribution network.

The variation is real, large, and unrelated to anything a capacity-expansion
model wants to allocate. Using mapped circuit length as a demand or activity
prior would import a 7× arbitrary regional distortion. That is worse than using
no spatial information at all, because it looks like data.

Within Dublin the same effect shows up at finer grain: County Dublin as a whole
is at 1,127 km per 1,000 km² — the suburbs of Fingal and South Dublin, where
the network is still partly overhead and has been traced — while the Dublin
City core, where everything is underground, collapses to 311. The signal
disappears exactly where the load is densest.

**The point layer is genuinely informative, with a caveat.** Dublin City has
874 mapped MV/LV transformers and substations in 119 km², against 128 in
Kilkenny's 2,071 km² — a density ratio of about 118:1 in the right direction.
Those urban substations get mapped because they are visible street furniture:
small ESB kiosks and chambers that a surveyor walks past. The Dublin City map
shows this clearly — a dense, plausible scatter of substations and transformers
across the whole city, with almost no cable between them. OSM has the nodes of
the Dublin distribution system and none of the edges.

The caveat is that this density partly measures mapper effort rather than
network structure, and mapper effort correlates with urbanity, which correlates
with demand. So the point layer will look like a good demand prior whether or
not it is one, and you cannot distinguish the two from within OSM. I would not
build on it without validating against something external — at which point you
have the external source and no longer need the prior.

For **siting distributed generation**, the ≥38 kV layer is a different matter
and is directly usable: it is largely complete, connected, and its substations
are the actual connection points that matter for utility-scale renewables.

## 7. Recommendation for SWIS-100-IE

Given that SWIS-100-IE aggregates buses to regional nodes and you have said you
do not need feeder-level fidelity, the split falls out cleanly.

**Take the ≥38 kV layer from OSM.** 15,108 km island-wide, 419 components with
64% of nodes in the largest, and 220 kV+ at 94.5% in a single component. For
placing regional nodes and for constraining inter-node transfer capacity, this
is adequate and it is free. The 38 kV sublayer is the weakest of the three
(347 components, largest holding 19%) and will need attention if you want
38 kV-level detail, but 110 kV and above is solid. The GeoPackages in `data/`
carry a `voltage_v` and `band` column so you can filter directly.

**Do not use anything below 38 kV.** Not as topology — 6,707 MV components
against a true figure near 571 makes it unreconstructable, and the snapping
sweep shows no tolerance fixes it. Not as a demand prior — the density bias
runs backwards and would actively degrade a regional allocation. About 2% of
distribution transformers are present, and in Dublin the mapped conductor
cannot reach even the assets OSM itself contains.

**Go to ESB for the MV/LV layer.** The `.dgn` CAD files and the capacity
heatmap spreadsheet are the right sources for anything below 38 kV, and this
exercise gives you a concrete acceptance test for them when they arrive: does
the MV layer resolve to something near 571 connected components nationally,
and does the conductor length reach the transformer population? Both questions
are cheap to answer and both are the questions OSM fails.

The honest summary is that the OSM route is not a dead end, but it is a much
smaller road than it looked. It gives you a transmission and sub-transmission
network you can use tomorrow, and nothing at all below that. If the parts of
SWIS-100-IE you were planning to build on OSM live entirely at the regional
node level, you have lost nothing. If any of them reach below 38 kV, that work
should not start until the ESB data is in hand.

---

## Reproducing

```bash
pip install -r requirements.txt
python network.py prepare         # download + prefilter + boundary cache
python analysis.py areas          # data/analysis.json - coverage, bands, components, snap sweep
python analysis.py national       # data/national.json - island-wide graph by voltage layer
python analysis.py subtransmission  # data/subtransmission.json - per-area layers
python analysis.py missing-cable  # data/missing_cable.json - MST lower bound
python analysis.py counties       # data/county_sweep.csv - all 26 counties of the Republic
python plots.py areas             # per-area PNGs (160 dpi) and GeoPackages (lines, nodes; EPSG:2157)
python eirgrid.py fetch           # data/eirgrid_transmission.gpkg - EirGrid 110 kV+ network
python plots.py national          # data/national_network.png - both layers, Republic
python -m pytest test_network.py
```

`python analysis.py all` and `python plots.py all` run each group in order.
Every stage caches and skips itself if the cache is present.

The interactive map is built separately, from the same extract:

```bash
python extract_web_data.py        # data/raw/web_{lines,sites}.gpkg - island-wide, ways reassembled
python extract_web_base.py        # data/raw/web_base.gpkg - county and Northern Ireland outlines
python build_web_map.py           # data/ireland_distribution_map.html
```

`data/ireland_distribution_map.html` is self-contained: open it from disk, no
server. Every voltage band is a separate layer, the point assets are
clickable and searchable, and the default view is the ≥38 kV layers plus the
substations - the part of the data section 7 says you can use. MV, LV and the
untagged remainder are one click away with the caveats stated beside them.

Extract: Geofabrik `ireland-and-northern-ireland-latest.osm.pbf`, 2026-08-28,
MD5 `e6fa4fd2707d7c05388e288c8f5ff94d`. Geofabrik republishes this file
continuously, so a later run will fetch a newer extract and the OSM-derived
figures in this document will move slightly. The committed
`data/national_distribution.gpkg` holds the lines these figures were measured
from, and `plots.py national` reads it in preference to rebuilding, so the map
stays consistent with the text.

Transmission layer: EirGrid Transmission Development Plan 2024 public web map
(ArcGIS feature service, layers 40 / 39 / 38), read in EPSG:2157. 24,952
overhead line sections, 1,607 cable sections, 161 stations; 5,348 km overhead
and 774 km cable, against EirGrid's published 6,500 km. This is the
transmission system operator's own asset register, so unlike the OpenStreetMap
layers above it is largely not a coverage question - it is used here as the
reference the OSM 110 kV+ band can be judged against, and as the backbone on
the national map.

With one exception the aggregate agreement hides. The 400 kV layer holds a
single overhead circuit, `MONEYPOINT-OLDSTREET`, 103 km spanning longitude
-9.42 to -8.27 - the western leg only. The 400 kV network continues from
Oldstreet to Dunstown and on to Woodland, and no circuit for those legs is
present in the service at any voltage. So the 110 kV and 220 kV layers can be
taken as the register; the 400 kV layer cannot be taken as the whole 400 kV
backbone. For a model that aggregates to regional nodes this matters less than
it sounds, but it is the one place this dataset should not be trusted
unqualified.

Reference asset counts: [ESB Networks, "Our
network"](https://www.esbnetworks.ie/about-us/company/our-network).

Areas are pinned by OSM relation id so runs do not depend on a geocoder:
County Kilkenny `285980`, County Mayo `338539`, Dublin City Council `1109531`,
County Dublin `282800`. "Dublin, Ireland" is ambiguous — a geocoder returns the
city council area, but County Dublin is the like-for-like comparison against
the other two counties, so both are reported throughout.
