"""
Figure 1: county-level landscape of workforce, burden and digital readiness.

Five choropleths on an Albers projection with Alaska and Hawaii insets:
cardiologists per 100,000 residents, mean tract burden z-score, and the Digital
Divide Index with its infrastructure and socioeconomic subscores. Panels c-e
share one numeric scale so the three readiness measures can be compared.

Output: outputs/figure1/, 300 dpi
"""
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.cm import ScalarMappable

from build_master import load_master
from geo import albers, county_polys, region_of, PROJ, DPI

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "figure1")
os.makedirs(OUT, exist_ok=True)

GRAY_RED = LinearSegmentedColormap.from_list(
    "gray_red", ["#e4e4e4", "#e8b9a8", "#d6604d", "#8c1a1f"])
MISS = "#e9e9e9"


def draw_choropleth(values, title, cmap, norm, cbar_label, fname,
                    missing=MISS, extend="neither"):
    """values: dict fips -> value (np.nan allowed)."""
    cp = county_polys()
    fig = plt.figure(figsize=(8.2, 5.6))
    ax = fig.add_axes([0.01, 0.16, 0.98, 0.76])
    ax_ak = fig.add_axes([0.015, 0.155, 0.22, 0.24])
    ax_hi = fig.add_axes([0.25, 0.155, 0.14, 0.15])
    axes = {"conus": ax, "ak": ax_ak, "hi": ax_hi}
    polys = {k: ([], []) for k in axes}
    sm = ScalarMappable(norm=norm, cmap=cmap)
    for fips, rings in cp.items():
        reg = region_of(fips)
        if reg is None:
            continue
        v = values.get(fips, np.nan)
        col = missing if (v is None or (isinstance(v, float) and np.isnan(v))) \
            else sm.to_rgba(v)
        for r in rings:
            x, y = albers(r[:, 0], r[:, 1], *PROJ[reg])
            polys[reg][0].append(np.column_stack([x, y]))
            polys[reg][1].append(col)
    for reg, a in axes.items():
        verts, cols = polys[reg]
        a.add_collection(PolyCollection(verts, facecolors=cols,
                                        edgecolors="white", linewidths=0.12))
        a.autoscale_view()
        a.set_aspect("equal")
        a.set_xticks([]); a.set_yticks([])
        for s in a.spines.values():
            s.set_visible(False)
    ax.set_title(title, fontsize=12.5, weight="bold", pad=8)
    cax = fig.add_axes([0.44, 0.10, 0.36, 0.025])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal", extend=extend)
    cb.set_label(cbar_label, fontsize=8.5)
    cb.ax.tick_params(labelsize=7.5)
    cb.outline.set_visible(False)
    fig.savefig(os.path.join(OUT, fname), dpi=DPI)
    plt.close(fig)
    print(f"  {fname} done")


def figure1(tracts):
    wf = pd.read_csv(os.path.join(PD_, "outputs", "burden_workforce",
                                  "county_workforce_summary.csv"),
                     dtype={"fips_st_cnty": str})
    wf["fips_st_cnty"] = wf["fips_st_cnty"].str.zfill(5)
    rate = dict(zip(wf["fips_st_cnty"], wf["card_per_100k_last"]))
    cap = float(np.nanpercentile(list(rate.values()), 97))
    draw_choropleth(rate, "Cardiology workforce",
                    GRAY_RED, Normalize(0, cap),
                    f"Cardiologists per 100,000 residents (capped at {cap:.0f})",
                    "figure1a_workforce.png", extend="max")

    cb = (tracts.dropna(subset=["burden_z"])
                .groupby("fips_county")["burden_z"].mean())
    lim = float(np.nanpercentile(np.abs(cb.values), 98))
    draw_choropleth(cb.to_dict(), "Cardiometabolic disease burden",
                    GRAY_RED, Normalize(-lim, lim),
                    "Mean tract burden z-score (0 = national average)",
                    "figure1b_burden.png", extend="both")

    ddi = pd.read_excel(os.path.join(PD_, "DDI", "2022-2024 US DDI.xlsx"),
                        sheet_name="Counties 22", dtype={"FIPS_Cnty": str})
    ddi["FIPS_Cnty"] = ddi["FIPS_Cnty"].str.zfill(5)
    vmax = float(max(np.nanpercentile(ddi[c], 99) for c in ("DDI", "INFA", "SE")))
    for col, label, fname in [
            ("DDI", "Digital Divide Index (composite)", "figure1c_ddi.png"),
            ("INFA", "Infrastructure/adoption sub-score (INFA)", "figure1d_infrastructure.png"),
            ("SE", "Socioeconomic sub-score (SE)", "figure1e_socioeconomic.png")]:
        vals = dict(zip(ddi["FIPS_Cnty"], ddi[col]))
        draw_choropleth(vals, label, GRAY_RED, Normalize(0, vmax),
                        f"{col} score (higher = worse readiness; shared scale)",
                        fname, extend="max")


def main():
    tracts, _ = load_master()
    figure1(tracts)
    print(f"\nFigure 1 -> {OUT}")


if __name__ == "__main__":
    main()
