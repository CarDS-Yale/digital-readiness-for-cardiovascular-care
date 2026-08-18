"""
make_figure3.py
===============
Figure 3, replacement design: a national map of EVERY priority tract rather
than the top-10 county display (which was arbitrary and duplicated Tables
S1a,b).

Red = investment priority, blue = deployment priority, using the same colors
as Figures 2 and 4. Kentucky and Pennsylvania tracts are shown, because they
retain box membership; only the ranked lists excluded them.

Deployment tracts are urban and therefore small in area, so they are drawn
last and carry a same-color edge, which keeps dense metro clusters legible
against the much larger rural investment polygons.

Outputs: outputs/figure3/ (combined map and the three-panel version)
"""
import json
import os
import urllib.request

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import glob
import pandas as pd

from build_master import load_master, matrix_boxes
from geo import county_polys, albers, PROJ, region_of, INV, DEP

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "figure3")
os.makedirs(OUT, exist_ok=True)
GEO_DIR = os.path.join(PD_, "tract_geo")
os.makedirs(GEO_DIR, exist_ok=True)
TRACT_URL = ("https://raw.githubusercontent.com/loganpowell/census-geojson/"
             "master/GeoJSON/500k/2020/{st}/tract.json")
DPI = 300

STATES = [f"{s:02d}" for s in range(1, 57) if s not in (3, 7, 14, 43, 52)]
BASE_FILL, BASE_EDGE = "#f2f3f5", "white"


def state_features(st):
    """Tract features for one state; cached files are reused, temps removed."""
    cached = os.path.join(GEO_DIR, f"tract_{st}.json")
    if os.path.exists(cached):
        with open(cached) as fh:
            return json.load(fh)["features"], False
    tmp = os.path.join("/tmp", f"_tract_{st}.json")
    urllib.request.urlretrieve(TRACT_URL.format(st=st), tmp)
    with open(tmp) as fh:
        feats = json.load(fh)["features"]
    os.remove(tmp)
    return feats, True


def rings_of(geom, step):
    """Exterior rings as arrays, decimated for a national-scale render."""
    polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
             else geom["coordinates"])
    out = []
    for poly in polys:
        r = np.asarray(poly[0], dtype=float)
        if len(r) > 40:                       # thin dense coastlines
            keep = np.unique(np.r_[np.arange(0, len(r), step), len(r) - 1])
            r = r[keep]
        if len(r) >= 3:
            out.append(r)
    return out


def collect_cached(label_of):
    import pickle
    cache = os.path.join(OUT, "_rings.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as fh:
            print("using cached rings")
            return pickle.load(fh)
    b = collect(label_of)
    with open(cache, "wb") as fh:
        pickle.dump(b, fh)
    return b


def collect(label_of):
    """Walk every state once, keeping only priority-tract rings by region."""
    buckets = {("conus", "INV"): [], ("conus", "DEP"): [],
               ("ak", "INV"): [], ("ak", "DEP"): [],
               ("hi", "INV"): [], ("hi", "DEP"): []}
    for i, st in enumerate(STATES, 1):
        feats, fetched = state_features(st)
        reg = "ak" if st == "02" else "hi" if st == "15" else "conus"
        step = 3 if reg == "conus" else 2
        n = 0
        for ft in feats:
            gid = ft["properties"]["GEOID"]
            lab = label_of.get(gid)
            if lab is None:
                continue
            for r in rings_of(ft["geometry"], step):
                r[:, 0] = np.where(r[:, 0] > 0, r[:, 0] - 360, r[:, 0])
                x, y = albers(r[:, 0], r[:, 1], *PROJ[reg])
                buckets[(reg, lab)].append(np.column_stack([x, y]))
                n += 1
        print(f"  [{i:2}/{len(STATES)}] state {st}: {n:5} priority rings"
              f"{'  (downloaded)' if fetched else ''}")
    return buckets


def base_layer(ax, region, cp):
    verts = []
    for fips, rings in cp.items():
        if region_of(fips) != region:
            continue
        for r in rings:
            x, y = albers(r[:, 0], r[:, 1], *PROJ[region])
            verts.append(np.column_stack([x, y]))
    ax.add_collection(PolyCollection(verts, facecolors=BASE_FILL,
                                     edgecolors=BASE_EDGE, linewidths=0.15))


def draw_priority(ax, buckets, region, lw, only=None, dep_boost=4.0):
    """Investment first, deployment on top so urban clusters stay visible.

    Deployment tracts are urban and near-invisible at national scale, so their
    outline is widened, which dilates each polygon just enough to read.
    """
    for lab, colour in (("INV", INV), ("DEP", DEP)):
        if only and lab != only:
            continue
        v = buckets[(region, lab)]
        if v:
            ax.add_collection(PolyCollection(
                v, facecolors=colour, edgecolors=colour,
                linewidths=lw * (dep_boost if lab == "DEP" else 1.0),
                zorder=3 if lab == "INV" else 4))


def tidy(ax):
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def conus_map(ax, buckets, cp, only=None):
    base_layer(ax, "conus", cp)
    draw_priority(ax, buckets, "conus", lw=0.12, only=only)
    tidy(ax)


def add_insets(fig, buckets, cp, rects, only=None):
    for reg, rect in rects:
        ax = fig.add_axes(rect)
        base_layer(ax, reg, cp)
        draw_priority(ax, buckets, reg, lw=0.25, only=only)
        tidy(ax)
        ax.patch.set_alpha(0)



def tract_population():
    """ACS 5-year total tract population, the weights used for Table 1."""
    f = sorted(glob.glob(os.path.join(PD_, "ACS",
                                      "acs5_*_tract_ddi_components.csv")))[-1]
    a = pd.read_csv(f, dtype={"GEOID": str})
    a["GEOID"] = a["GEOID"].str.zfill(11)
    return a.set_index("GEOID")["age_65plus_denom"].astype(float)


def population_ribbon(ax, p_inv, p_dep, p_us):
    """One bar = the US population, split by priority group.

    Direct labels, no legend, no axis: the point is the relative width of the
    two priority groups against the country as a whole.
    """
    f_inv, f_dep = p_inv / p_us, p_dep / p_us
    y0, y1 = 0.46, 0.70
    segs = [(0.0, f_inv, INV), (f_inv, f_inv + f_dep, DEP),
            (f_inv + f_dep, 1.0, "#e3e5e8")]
    for x0, x1, c in segs:
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0,
                                   facecolor=c, edgecolor="none"))

    m = lambda v: f"{v / 1e6:.1f} million"
    ax.text(0.0, y0 - 0.16, "Investment priority", ha="left", va="top",
            fontsize=11, weight="bold", color=INV)
    ax.text(0.0, y0 - 0.46, f"{m(p_inv)}  ·  {100 * f_inv:.0f}%", ha="left",
            va="top", fontsize=10, color="#1e2021")
    ax.text(f_inv, y0 - 0.16, "Deployment priority", ha="left", va="top",
            fontsize=11, weight="bold", color=DEP)
    ax.text(f_inv, y0 - 0.46, f"{m(p_dep)}  ·  {100 * f_dep:.0f}%", ha="left",
            va="top", fontsize=10, color="#1e2021")
    ax.text(1.0, y0 - 0.16, "All other US residents", ha="right", va="top",
            fontsize=11, color="#2f3134")
    ax.text(1.0, y0 - 0.46,
            f"{m(p_us - p_inv - p_dep)}  ·  {100 * (1 - f_inv - f_dep):.0f}%",
            ha="right", va="top", fontsize=10, color="#2f3134")

    # bracket spanning the two priority groups
    yb = y1 + 0.20
    ax.plot([0.0, f_inv + f_dep], [yb, yb], color="#1e2021", lw=0.9)
    for x in (0.0, f_inv + f_dep):
        ax.plot([x, x], [yb, yb - 0.09], color="#1e2021", lw=0.9)
    ax.text(0.0, yb + 0.09,
            f"{m(p_inv + p_dep)} residents in priority tracts "
            f"({100 * (f_inv + f_dep):.0f}% of the US population)",
            ha="left", va="bottom", fontsize=10.5, color="#1e2021")

    ax.set_xlim(-0.005, 1.005); ax.set_ylim(-0.40, 1.45)
    ax.axis("off")


HANDLES = [Patch(facecolor=INV, label="Investment priority"),
           Patch(facecolor=DEP, label="Deployment priority")]


def main():
    tracts, anchors = load_master()
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv, dep = matrix_boxes(P, "ddi", anchors["nat_med_ddi"])
    print(f"investment tracts {len(inv):,} | deployment tracts {len(dep):,}")

    label_of = {}
    for f in inv["fips_tract"]:
        label_of[str(f).zfill(11)] = "INV"
    for f in dep["fips_tract"]:
        label_of[str(f).zfill(11)] = "DEP"

    buckets = collect_cached(label_of)
    print("rings drawn:", {k: len(v) for k, v in buckets.items() if v})
    cp = county_polys()

    # ── A. combined national map ────────────────────────────────────────────
    fig, a = plt.subplots(figsize=(11.5, 7.6))
    conus_map(a, buckets, cp)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.09)
    add_insets(fig, buckets, cp,
               [("ak", [0.035, 0.10, 0.17, 0.20]),
                ("hi", [0.195, 0.10, 0.10, 0.12])])
    fig.legend(handles=HANDLES, loc="lower center", ncol=2, frameon=False,
               fontsize=13, bbox_to_anchor=(0.55, 0.015))
    out = os.path.join(OUT, "figure3_priority_tracts.png")
    fig.savefig(out, dpi=DPI); plt.close(fig); print("->", out)

    # ── B. two-panel version, one geography per strategy ────────────────────
    pop = tract_population()
    p_inv = float(inv["fips_tract"].map(pop).sum())
    p_dep = float(dep["fips_tract"].map(pop).sum())
    p_us = float(pop.sum())
    print(f"population: investment {p_inv:,.0f} | deployment {p_dep:,.0f} "
          f"| US {p_us:,.0f}")

    fig = plt.figure(figsize=(14.0, 6.9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 0.34],
                          left=0.012, right=0.988, top=0.94, bottom=0.04,
                          wspace=0.02, hspace=0.16)
    axes = [fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])]
    for ax, only, title, colour in (
            (axes[0], "INV", "Investment priority", INV),
            (axes[1], "DEP", "Deployment priority", DEP)):
        conus_map(ax, buckets, cp, only=only)
        ax.set_title(title, fontsize=13, weight="bold", color=colour, pad=6)
    for k, only in ((0, "INV"), (1, "DEP")):
        x0 = 0.03 + 0.49 * k
        add_insets(fig, buckets, cp,
                   [("ak", [x0, 0.32, 0.10, 0.13]),
                    ("hi", [x0 + 0.095, 0.32, 0.058, 0.075])], only=only)
    for k, lab in ((0, "a"), (1, "b")):
        fig.text(0.015 + 0.49 * k, 0.955, lab, fontsize=15, weight="bold")

    axb = fig.add_subplot(gs[1, :])
    population_ribbon(axb, p_inv, p_dep, p_us)
    fig.text(0.015, 0.255, "c", fontsize=15, weight="bold")

    out2 = os.path.join(OUT, "figure3_priority_tracts_panels.png")
    fig.savefig(out2, dpi=DPI); plt.close(fig); print("->", out2)


if __name__ == "__main__":
    main()
