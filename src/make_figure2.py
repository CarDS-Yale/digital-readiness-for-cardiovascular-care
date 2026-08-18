"""
Figure 2: burden-readiness decision space.

Every high-need tract is plotted by Digital Divide Index against cardiometabolic
burden. Dashed lines mark the two national anchors, so the four quadrants read
directly off the axes; the upper-left holds deployment-priority tracts and the
upper-right investment-priority tracts. Circles mark the 10 highest-ranked tracts
in each group, labeled once per county with leader lines to each member tract.
Label slots are assigned by pairwise swapping so that no leader line crosses a
label.

Kentucky and Pennsylvania are dropped from both the ranked circles and the
background cloud, since their burden rests on a single measure.

Output: outputs/fig2_v7/
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.textpath import TextPath

from build_master import (load_master, matrix_boxes, rank_eligible,
                              RANK_EXCLUDE_STATES)

PD_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PD_, "outputs", "figure2")
os.makedirs(OUT, exist_ok=True)
DPI = 300
TOPN = 10
INV, DEP = "#c1272d", "#1f5fa6"
GRID = "#9aa0a6"
XMAX = 88
YMIN, YMAX = -1.2, 4.3
LAB_FS = 7.5


def segs_cross(a0, a1, b0, b1):
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    return (((ccw(b0, b1, a0) > 0) != (ccw(b0, b1, a1) > 0))
            and ((ccw(a0, a1, b0) > 0) != (ccw(a0, a1, b1) > 0)))


def seg_hits_box(p0, p1, box):
    x0, x1, y0, y1 = box
    for p in (p0, p1):
        if x0 < p[0] < x1 and y0 < p[1] < y1:
            return True
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
    return any(segs_cross(p0, p1, e0, e1) for e0, e1 in edges)


def main():
    tracts, anchors = load_master()
    nat = anchors["nat_med_ddi"]
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv, dep = matrix_boxes(P, "ddi", nat)   # boxes/scores use the full pool
    inv, dep = rank_eligible(inv), rank_eligible(dep)  # KY/PA out of ranked lists
    ni, nd = inv.head(TOPN), dep.head(TOPN)

    # background cloud excludes KY/PA: their burden rests on a single measure
    # (short sleep), so it is not comparable on the 10-measure burden axis
    st_bg = P["fips_tract"].astype(str).str.zfill(11).str[:2]
    Pbg = P[~st_bg.isin(RANK_EXCLUDE_STATES)]

    fig, a = plt.subplots(figsize=(10, 7.0))
    a.scatter(Pbg["ddi"], Pbg["burden_z"], s=5, c="#b6bbc2", alpha=.55,
              linewidths=0, rasterized=True)
    a.axhline(0, ls="--", c="#111111", lw=1.2)
    a.axvline(nat, ls="--", c="#111111", lw=1.2)
    a.axhspan(0, YMAX, xmin=0, xmax=nat / XMAX, color=DEP, alpha=.06)
    a.axhspan(0, YMAX, xmin=nat / XMAX, xmax=1, color=INV, alpha=.06)
    a.set_xlim(0, XMAX); a.set_ylim(YMIN, YMAX)
    a.text(nat / 2, 4.10, "Deployment priority", color=DEP, ha="center",
           fontsize=9.5, va="top", weight="bold")
    a.text((nat + XMAX) / 2, 4.10, "Investment priority", color=INV,
           ha="center", fontsize=9.5, va="top", weight="bold")
    a.text(nat + 0.5, -1.06, f"national median DDI ({nat:.0f})",
           color="#111111", fontsize=8, zorder=4.6,
           bbox=dict(fc="white", ec="none", alpha=0.9, pad=1.2))
    a.text(56, 0.08, "national-average burden (z = 0)", color="#111111",
           fontsize=8, zorder=4.6,
           bbox=dict(fc="white", ec="none", alpha=0.9, pad=1.2))
    a.scatter(ni["ddi"], ni["burden_z"], s=110, marker="o", c=INV,
              edgecolors="white", linewidths=.7, label="Top 10 investment priority",
              zorder=5, alpha=.92)
    a.scatter(nd["ddi"], nd["burden_z"], s=110, marker="o", c=DEP,
              edgecolors="white", linewidths=.7, label="Top 10 deployment priority",
              zorder=5, alpha=.92)

    a.set_xlabel("Digital Divide Index (higher = lower readiness \u2192)")
    a.set_ylabel("Cardiometabolic burden (z-score, \u2191 = worse)")
    fig.tight_layout()
    fig.canvas.draw()
    ux = (a.transData.transform((1, 0)) - a.transData.transform((0, 0)))[0]
    uy = (a.transData.transform((0, 1)) - a.transData.transform((0, 0)))[1]
    pt_x = 72.0 / fig.dpi / ux          # data-x units per point
    pt_y = 72.0 / fig.dpi / uy          # data-y units per point

    def text_w(txt):
        return (TextPath((0, 0), txt, size=LAB_FS).get_extents().width
                + 3.0) * pt_x

    ROWH = (LAB_FS * 1.3 + 2.0) * pt_y

    all_dots = [(float(x), float(y)) for x, y in
                zip(list(ni["ddi"]) + list(nd["ddi"]),
                    list(ni["burden_z"]) + list(nd["burden_z"]))]

    def county_groups(df):
        d = df.head(TOPN).reset_index(drop=True)
        pts, order = {}, []
        for _, r in d.iterrows():
            key = r["county_state"]
            if key not in pts:
                pts[key] = []
                order.append(key)
            pts[key].append((float(r["ddi"]), float(r["burden_z"])))
        return [(k, pts[k]) for k in order]

    def stack_labels(df, x_lab, ha, color):
        rows = sorted(county_groups(df),
                      key=lambda t: -np.mean([p[1] for p in t[1]]))
        n_rows = len(rows)
        y_hi = 3.55
        spacing = min(0.5, (y_hi + 1.05) / max(n_rows - 1, 1))
        ys = [y_hi - spacing * k for k in range(n_rows)]
        widths = [text_w(f"{nm} ({len(p)})" if len(p) > 1 else nm)
                  for nm, p in rows]

        def geometry(o):
            boxes, segs, owner = [], [], []
            for slot, i in enumerate(o):
                w = widths[i]
                x0 = x_lab - w if ha == "right" else x_lab
                x1 = x_lab if ha == "right" else x_lab + w
                boxes.append((x0, x1, ys[slot] - ROWH / 2, ys[slot] + ROWH / 2))
            for slot, i in enumerate(o):
                edge = (boxes[slot][0] if ha == "right" else boxes[slot][1],
                        ys[slot])
                for p in rows[i][1]:
                    segs.append((edge, p))
                    owner.append(slot)
            return boxes, segs, owner

        def cost(o):
            boxes, segs, owner = geometry(o)
            hard = 0
            for (p0, p1), ow in zip(segs, owner):
                for bslot, b in enumerate(boxes):
                    if bslot != ow and seg_hits_box(p0, p1, b):
                        hard += 1
            for b in boxes:                      # labels must not cover dots
                for dx, dy in all_dots:
                    if b[0] - 0.4 < dx < b[1] + 0.4 and \
                       b[2] - 0.03 < dy < b[3] + 0.03:
                        hard += 1
            soft = sum(1 for u in range(len(segs))
                       for v in range(u + 1, len(segs))
                       if owner[u] != owner[v]
                       and segs_cross(*segs[u], *segs[v]))
            return hard * 1000 + soft

        order = list(range(n_rows))
        improved = True
        while improved:
            improved = False
            base = cost(order)
            for u in range(n_rows):
                for v in range(u + 1, n_rows):
                    order[u], order[v] = order[v], order[u]
                    c = cost(order)
                    if c < base:
                        base = c
                        improved = True
                    else:
                        order[u], order[v] = order[v], order[u]
        print(f"  {ha} stack: {len(rows)} labels, residual cost {cost(order)}")

        boxes, segs, owner = geometry(order)
        for (p0, p1) in segs:
            a.plot([p0[0], p1[0]], [p0[1], p1[1]], color=color,
                   lw=0.55, alpha=0.5, zorder=3.5, solid_capstyle="round")
        for slot, i in enumerate(order):
            nm, pts = rows[i]
            txt = f"{nm} ({len(pts)})" if len(pts) > 1 else nm
            a.text(x_lab, ys[slot], txt, ha=ha, va="center",
                   fontsize=LAB_FS, color="#3c4043", zorder=6,
                   bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.5))

    stack_labels(nd, 1.0, "left", DEP)
    stack_labels(ni, 87.0, "right", INV)

    a.legend(loc="lower center", bbox_to_anchor=(0.46, 0.02),
             frameon=True, framealpha=0.9, edgecolor="none", fontsize=10)
    fig.savefig(os.path.join(OUT, "figure2_decision_space.png"), dpi=DPI)
    plt.close(fig)
    print(f"figure2_decision_space.png -> {OUT}")


if __name__ == "__main__":
    main()
