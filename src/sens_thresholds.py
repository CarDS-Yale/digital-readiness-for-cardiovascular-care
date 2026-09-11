"""
sens_thresholds.py
==========================
Additional analysis D: stricter targeting thresholds.

The main analysis anchors at "above national-average burden" and "national
median DDI". A reviewer may ask how the target lists change when we demand
the top 25% or top 10% along either axis. All cutoffs are NATIONAL
percentiles over all US tracts.

Grid (3 burden cuts x 3 readiness cuts = 9 runs)
  burden : > mean (z>0, baseline) | >= p75 | >= p90 of national burden_z
  ready  : median split (baseline) | quartile split | decile split
           INVEST needs DDI above the upper cut; DEPLOY needs DDI at or
           below the lower cut. Stricter runs leave a middle band unassigned.

Because the priority scores are computed on the same pool in every run, a
stricter run keeps the baseline ranking and simply drops tracts that miss
the new cuts. The interesting outputs are box sizes, retention of the
baseline boxes, and survival of the baseline top-10 lists.

Outputs (outputs/master/)
  thresholds_grid.csv            one row per (burden_cut x ready_cut) combination
  thresholds_top10_survival.csv  baseline top-10 tracts, flagged per stricter run
"""
import os
import numpy as np
import pandas as pd

from build_master import load_master, matrix_boxes, tidy, OUT_DIR

BURDEN_CUTS = {"mean": None, "p75": 75, "p90": 90}     # None = baseline z>0
READY_CUTS  = {"median": (50, 50), "p25_p75": (25, 75), "p10_p90": (10, 90)}


def boxes_at(P, burden_cut, dep_cut, inv_cut):
    """2x2 with separate DEPLOY (ddi<=dep_cut) and INVEST (ddi>inv_cut) gates."""
    d = P.dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract").copy()
    hb = d["burden_z"] > burden_cut
    zb = (d["burden_z"] - d["burden_z"].mean()) / d["burden_z"].std()
    zr = (d["ddi"] - d["ddi"].mean()) / d["ddi"].std()
    d["deploy_score"] = zb - zr
    d["invest_score"] = zb + zr
    inv = (d[hb & (d["ddi"] > inv_cut)]
           .sort_values("invest_score", ascending=False).reset_index(drop=True))
    dep = (d[hb & (d["ddi"] <= dep_cut)]
           .sort_values("deploy_score", ascending=False).reset_index(drop=True))
    inv.insert(0, "rank", inv.index + 1)
    dep.insert(0, "rank", dep.index + 1)
    return inv, dep


def main():
    tracts, anchors = load_master()
    P = tracts[tracts["in_pool"]].copy()

    # national anchors over ALL US tracts
    nat_b = tracts["burden_z"].dropna()
    nat_d = tracts["ddi"].dropna()
    b_cuts = {"mean": 0.0,
              "p75": float(nat_b.quantile(0.75)),
              "p90": float(nat_b.quantile(0.90))}
    d_cuts = {}
    for name, (lo, hi) in READY_CUTS.items():
        d_cuts[name] = (float(nat_d.quantile(lo / 100)), float(nat_d.quantile(hi / 100)))
    # baseline median split uses the median for both gates
    inv_ref, dep_ref = matrix_boxes(P, "ddi", anchors["nat_med_ddi"])
    ref_inv10 = list(inv_ref["fips_tract"].head(10))
    ref_dep10 = list(dep_ref["fips_tract"].head(10))

    print("=" * 78)
    print("stricter national thresholds (top 25% / top 10% per axis)")
    print("=" * 78)
    print("burden cuts  :", {k: round(v, 3) for k, v in b_cuts.items()})
    print("DDI cuts     :", {k: (round(a, 1), round(b, 1)) for k, (a, b) in d_cuts.items()})

    rows, surv = [], []
    for bname, bcut in b_cuts.items():
        for rname, (lo_cut, hi_cut) in d_cuts.items():
            inv, dep = boxes_at(P, bcut, dep_cut=lo_cut, inv_cut=hi_cut)
            row = {
                "burden_cut": bname, "ready_cut": rname,
                "burden_z_cut": round(bcut, 3),
                "deploy_ddi_max": round(lo_cut, 1), "invest_ddi_min": round(hi_cut, 1),
                "n_invest": len(inv), "n_deploy": len(dep),
                "invest_vs_base_pct": round(
                    inv["fips_tract"].isin(inv_ref["fips_tract"]).mean() * 100, 1) if len(inv) else np.nan,
                "deploy_vs_base_pct": round(
                    dep["fips_tract"].isin(dep_ref["fips_tract"]).mean() * 100, 1) if len(dep) else np.nan,
                "base_inv_top10_surviving": int(pd.Series(ref_inv10).isin(inv["fips_tract"]).sum()),
                "base_dep_top10_surviving": int(pd.Series(ref_dep10).isin(dep["fips_tract"]).sum()),
            }
            rows.append(row)
            print(f"  [{bname:>4} x {rname:>7}] INVEST {len(inv):6,} "
                  f"DEPLOY {len(dep):5,} | base top10 surviving "
                  f"INV {row['base_inv_top10_surviving']}/10 DEP {row['base_dep_top10_surviving']}/10")
            if bname == "p90" and rname == "p10_p90":
                tidy(inv).head(10).to_csv(os.path.join(OUT_DIR, "thresholds_strictest_INVEST_top.csv"), index=False)
                tidy(dep).head(10).to_csv(os.path.join(OUT_DIR, "thresholds_strictest_DEPLOY_top.csv"), index=False)

            for bucket, ref10, box in [("INVEST", ref_inv10, inv), ("DEPLOY", ref_dep10, dep)]:
                for t in ref10:
                    surv.append({"bucket": bucket, "fips_tract": t,
                                 "run": f"{bname}_x_{rname}",
                                 "survives": bool(box["fips_tract"].isin([t]).any())})

    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "thresholds_grid.csv"), index=False)
    (pd.DataFrame(surv)
       .pivot_table(index=["bucket", "fips_tract"], columns="run",
                    values="survives", aggfunc="first")
       .reset_index()
       .to_csv(os.path.join(OUT_DIR, "thresholds_top10_survival.csv"), index=False))
    print(f"\nwritten -> {OUT_DIR}/thresholds_*")


if __name__ == "__main__":
    main()
