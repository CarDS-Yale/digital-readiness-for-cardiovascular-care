"""
sens_readiness_subscores.py
=========================
Additional analysis B: rerun the classification with the DDI's two
SUB-SCORES as the readiness axis, one at a time.

  INFA : infrastructure/adoption sub-score (broadband, devices, speeds)
  SE   : socioeconomic sub-score (age, education, poverty, disability, IIR)

Each run anchors readiness at that sub-score's own national median, mirroring how the composite uses its national median.

Questions answered
  - Do the boxes move when readiness means only infrastructure, or only
    socioeconomic capacity?
  - Which sub-score drives the composite's INVEST/DEPLOY split?

Outputs (outputs/master/)
  readiness_subscores_comparison.csv          one row per sub-score vs composite baseline
  readiness_subscores_<sub>_INVEST_top.csv / _DEPLOY_top.csv
  readiness_subscores_state_shift.csv         state mix of INVEST/DEPLOY under each axis
"""
import os
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              state_mix, tidy, OUT_DIR)

TOP_N = 10
SUBS = {"INFA": ("infa", "nat_med_infa"),
        "SE":   ("se",   "nat_med_se")}


def main():
    tracts, anchors = load_master()
    P = tracts[tracts["in_pool"]].copy()
    inv_ref, dep_ref = matrix_boxes(P, "ddi", anchors["nat_med_ddi"])

    rows, mixes = [], []
    for lab, box in [("DDI_INVEST", inv_ref), ("DDI_DEPLOY", dep_ref)]:
        m = state_mix(box).head(8)
        mixes.append(m.rename_axis("state").reset_index().assign(run=lab))

    print("=" * 78)
    print("readiness = INFA only vs SE only (own national medians)")
    print("=" * 78)
    print(f"baseline (composite): INVEST {len(inv_ref):,} | DEPLOY {len(dep_ref):,}")

    for name, (col, anchor_key) in SUBS.items():
        cut = anchors[anchor_key]
        inv_s, dep_s = matrix_boxes(P, col, cut)
        cmp_ = compare_runs(P.dropna(subset=["ddi", col]),
                            inv_ref, dep_ref, inv_s, dep_s)
        corr = P[["ddi", col]].dropna()
        r = corr["ddi"].corr(corr[col])
        rows.append({"axis": name, "ready_cut": round(cut, 2),
                     "pearson_r_vs_ddi": round(r, 3), **cmp_})
        print(f"\n[{name}] cut={cut:.2f} r(DDI)={r:.3f} | "
              f"INVEST {len(inv_s):,} DEPLOY {len(dep_s):,} | "
              f"agree={cmp_['box_agree_pct']}% "
              f"(INVEST {cmp_['invest_retained_pct']}%, DEPLOY {cmp_['deploy_retained_pct']}%) | "
              f"top10 overlap INV {cmp_['inv_top10_overlap']}/10 DEP {cmp_['dep_top10_overlap']}/10")
        tidy(inv_s).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"readiness_subscores_{name}_INVEST_top.csv"), index=False)
        tidy(dep_s).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"readiness_subscores_{name}_DEPLOY_top.csv"), index=False)
        for lab, box in [(f"{name}_INVEST", inv_s), (f"{name}_DEPLOY", dep_s)]:
            m = state_mix(box).head(8)
            mixes.append(m.rename_axis("state").reset_index().assign(run=lab))

    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "readiness_subscores_comparison.csv"), index=False)
    pd.concat(mixes, ignore_index=True).to_csv(
        os.path.join(OUT_DIR, "readiness_subscores_state_shift.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/readiness_subscores_*")


if __name__ == "__main__":
    main()
