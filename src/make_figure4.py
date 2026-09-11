"""
Figure 4: neighborhood-level variation across five metropolitan areas.

Chicago, Dallas-Fort Worth, Washington, Boston and Philadelphia, each drawn as
the county containing the city center plus its neighbors. Saturated red and blue
mark investment- and deployment-priority tracts. Every other tract with data
carries a light tint by which side of the national median its readiness falls
on, so the background keeps its structure instead of flattening to gray.

Output: outputs/figure4/, 300 dpi
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

from build_master import load_master, matrix_boxes
from geo import county_polys, fetch_tracts, INV, DEP

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "figure4")
os.makedirs(OUT, exist_ok=True)
DPI = 300

# light background tints (fade toward white)
LIGHT_RED = np.array([0.936, 0.716, 0.664])   # not-ready lean, full tint
LIGHT_BLUE = np.array([0.640, 0.756, 0.888])  # ready lean, full tint
WHITE = np.array([1.0, 1.0, 1.0])
NO_DATA = "#f5f5f5"

# fname -> (title, city label, (lon, lat), main county, all counties, states)
METROS = {
    "figure4a_chicago": ("Chicago Metro", "Cook County", "Chicago",
        (-87.6298, 41.8781),
        "17031", ["17031", "17043", "17097", "17197", "17089", "17111",
                  "17093", "18089", "18127"], ["17", "18"]),
    "figure4b_dallas": ("Dallas-Fort Worth Metro", "Dallas County", "Dallas",
        (-96.7970, 32.7767),
        "48113", ["48113", "48439", "48085", "48121", "48397", "48139",
                  "48257", "48251"], ["48"]),
    "figure4c_washington_dc": ("Washington DC Metro", "The District of Columbia",
        "Washington DC", (-77.0369, 38.9072),
        "11001", ["11001", "24031", "24033", "51013", "51510", "51059",
                  "51600", "51610", "51107", "51153"], ["11", "24", "51"]),
    "figure4d_boston": ("Boston Metro", "Suffolk County", "Boston",
        (-71.0589, 42.3601),
        "25025", ["25025", "25017", "25021", "25009", "25023"], ["25"]),
    "figure4e_philadelphia": ("Philadelphia Metro", "Philadelphia County",
        "Philadelphia", (-75.1652, 39.9526),
        "42101", ["42101", "42045", "42091", "42017", "42029",
                  "34007", "34005", "34015", "10003"], ["42", "34", "10"]),
}


def tint(side_red, strength):
    """Background color: white -> light red/blue; floor keeps tints visible."""
    base = LIGHT_RED if side_red else LIGHT_BLUE
    s = 0.18 + 0.82 * min(1.0, strength)
    return tuple(WHITE + (base - WHITE) * s)


def main():
    tracts, anchors = load_master()
    nat = anchors["nat_med_ddi"]
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv, dep = matrix_boxes(P, "ddi", nat)
    lab = {f: "INV" for f in inv["fips_tract"]}
    lab.update({f: "DEP" for f in dep["fips_tract"]})

    t = tracts.drop_duplicates("fips_tract").set_index("fips_tract")
    ddi = t["ddi"]
    # tint strength: distance from the national median, saturating at p95
    span_hi = float(np.nanpercentile(ddi[ddi > nat] - nat, 95))
    span_lo = float(np.nanpercentile(nat - ddi[ddi <= nat], 95))
    cp = county_polys()

    import sys
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for fname, (title, core_name, city, (clon, clat), main_cty, counties, states) in METROS.items():
        if only and only not in fname:
            continue
        feats = [f for f in fetch_tracts(states)
                 if f["properties"]["GEOID"][:5] in counties]
        lat0 = np.mean([np.asarray(
            (f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon"
             else f["geometry"]["coordinates"][0][0]))[:, 1].mean() for f in feats])
        kx = np.cos(np.radians(lat0))

        fig, a = plt.subplots(figsize=(8.2, 8.2))
        verts, cols = [], []
        n_inv = n_dep = 0
        for ft in feats:
            geoid = ft["properties"]["GEOID"]
            L = lab.get(geoid)
            if L == "INV":
                col = INV; n_inv += 1
            elif L == "DEP":
                col = DEP; n_dep += 1
            else:
                d = ddi.get(geoid, np.nan)
                if isinstance(d, float) and np.isnan(d):
                    col = NO_DATA
                elif d > nat:
                    col = tint(True, min(1.0, (d - nat) / span_hi))
                else:
                    col = tint(False, min(1.0, (nat - d) / span_lo))
            g = ft["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for poly in polys:
                r = np.asarray(poly[0], dtype=float)
                verts.append(np.column_stack([r[:, 0] * kx, r[:, 1]]))
                cols.append(col)
        a.add_collection(PolyCollection(verts, facecolors=cols,
                                        edgecolors="white", linewidths=0.12))

        # county outlines: surrounding thin, main county dark and thick
        thin, thick = [], []
        for f5 in counties:
            for r in cp.get(f5, []):
                v = np.column_stack([r[:, 0] * kx, r[:, 1]])
                (thick if f5 == main_cty else thin).append(v)
        a.add_collection(PolyCollection(thin, facecolors="none",
                                        edgecolors="#8a8f98", linewidths=0.8))
        a.add_collection(PolyCollection(thick, facecolors="none",
                                        edgecolors="#1a1a1a", linewidths=2.4))

        # city center dot + label
        cxp, cyp = clon * kx, clat
        a.scatter([cxp], [cyp], s=55, c="black", zorder=6,
                  edgecolors="white", linewidths=1.0)
        a.annotate(city, xy=(cxp, cyp), xytext=(6, 6),
                   textcoords="offset points", fontsize=11.5, weight="bold",
                   color="black", zorder=6,
                   path_effects=[pe.withStroke(linewidth=3, foreground="white")])

        a.autoscale_view(); a.set_aspect("equal")
        a.set_xticks([]); a.set_yticks([])
        for s in a.spines.values():
            s.set_visible(False)
        fig.suptitle(title, fontsize=14, weight="bold", y=0.972)
        fig.text(0.5, 0.912, f"({core_name} and Surrounding Counties)",
                 ha="center", fontsize=10.5, color="#444444")
        fig.legend(handles=[
            Patch(facecolor=INV, label="Investment priority"),
            Patch(facecolor=DEP, label="Deployment priority"),
            Patch(facecolor=tint(True, 0.7), label="Lower readiness"),
            Patch(facecolor=tint(False, 0.7), label="Higher readiness"),
            Patch(facecolor=NO_DATA, label="No data"),
            Line2D([0], [0], marker="o", ls="", mfc="black", mec="white",
                   ms=8, label="City center")],
            loc="lower center", ncol=3, frameon=False, fontsize=9,
            bbox_to_anchor=(0.5, 0.005))
        fig.tight_layout(rect=[0, 0.075, 1, 0.9])
        fig.savefig(os.path.join(OUT, f"{fname}.png"), dpi=DPI)
        plt.close(fig)
        print(f"  {fname}.png done ({n_inv} INV, {n_dep} DEP)")

    print(f"\nmetro maps -> {OUT}")


if __name__ == "__main__":
    main()
