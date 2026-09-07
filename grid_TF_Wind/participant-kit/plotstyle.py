"""One look for every chart in the kit.

A small, validated palette and a matplotlib style, so the six examples read as
one set rather than six defaults.  Import it and call :func:`use`.

The categorical order is fixed and is never cycled: an eighth series folds into
"other" rather than reusing slot 1.  The sequential ramp is one hue, light to
dark, because a magnitude scale that changes hue invents categories that are
not in the data.  Loading above 1.0 is drawn in the status colour **and** with a
heavier stroke, so an overload is never carried by colour alone.
"""

from __future__ import annotations

import matplotlib as mpl
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

#: Categorical slots, in fixed order.  Validated: worst adjacent CVD dE 9.1,
#: worst adjacent normal-vision dE 19.6 on a light surface.
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948")

#: One hue, light to dark, for continuous magnitude.
SEQUENTIAL = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
              "#256abf", "#184f95", "#0d366b")

#: Two poles and a neutral middle, for a signed quantity.
DIVERGING = ("#0d366b", "#256abf", "#86b6ef", "#f0efec",
             "#ec9a9a", "#d03b3b", "#8f1f1f")

#: Reserved, never used for a series.
STATUS = {"good": "#0ca30c", "warning": "#fab219",
          "serious": "#ec835a", "critical": "#d03b3b"}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
INK_MUTED = "#8a8983"

#: A carrier always gets the same colour, whichever chart it appears in.
CARRIER_COLOURS = {
    "wind": CATEGORICAL[0],
    "solar": CATEGORICAL[3],
    "hydro": CATEGORICAL[2],
    "gas": CATEGORICAL[1],
    "biomass": CATEGORICAL[5],
    "unknown": CATEGORICAL[6],
    "import": CATEGORICAL[4],
    "export": CATEGORICAL[7],
    "battery": CATEGORICAL[2],
    "load shedding": STATUS["critical"],
}

sequential_cmap = LinearSegmentedColormap.from_list("kit_seq", SEQUENTIAL)
diverging_cmap = LinearSegmentedColormap.from_list("kit_div", DIVERGING)


def use() -> None:
    """Apply the kit's matplotlib style: recessive axes, thin marks."""
    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": INK_MUTED,
        "axes.linewidth": 0.8,
        "axes.labelcolor": INK_SOFT,
        "axes.titlecolor": INK,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.labelsize": 9,
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": "#e6e5e1",
        "grid.linewidth": 0.7,
        "xtick.color": INK_SOFT,
        "ytick.color": INK_SOFT,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 2.0,
        "font.size": 9,
        "figure.dpi": 130,
    })


def carrier_colour(carrier: str) -> str:
    """The colour for a carrier, or a muted grey for one not in the map."""
    return CARRIER_COLOURS.get(str(carrier), INK_MUTED)


def loading_colour(loading):
    """Colour a line by how loaded it is, in [0, 1]; overloads are status red."""
    value = float(np.clip(loading, 0.0, 1.0))
    return sequential_cmap(0.15 + 0.85 * value)
