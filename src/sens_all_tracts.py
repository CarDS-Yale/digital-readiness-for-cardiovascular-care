"""
sens_all_tracts.py
==========================
Additional analysis C1: drop the workforce filter. Apply the same 2x2 matrix
(burden_z > 0; DDI <= national median) to ALL US tracts, not just tracts in
counties with no or declining per-capita cardiology workforce.

Questions answered
  - How much does the workforce screen shape the target lists?
  - Do the same places surface when every county is eligible?
  - How many of the all-tract targets sit in counties the screen excludes?

Outputs (outputs/master/)
  all_tracts_comparison.csv        box sizes, agreement on the shared pool, overlap
  all_tracts_INVEST_top.csv / all_tracts_DEPLOY_top.csv   top tracts, flagged in_pool or not
  all_tracts_state_shift.csv       state mix of the all-tract boxes vs baseline
"""
import os
import pandas as pd

from build_master import (load_master, matrix_boxes, top_overlap,
                              state_mix, tidy, OUT_DIR)

TOP_N = 25


def main():
    tracts, anchors = load_master()
    P_pool = tracts[tracts["in_pool"]].copy()
    inv_ref, dep_ref = matrix_boxes(P_pool, "ddi", anchors["nat_med_ddi"])

    # all tracts, same anchored cutoffs
    inv_all, dep_all = matrix_boxes(tracts, "ddi", anchors["nat_med_ddi"])
    for df in (inv_all, dep_all):
        df["in_pool"] = df["in_pool"].astype(bool)

    print("=" * 78)
    print("matrix on ALL tracts (no workforce filter)")
    print("=" * 78)
    print(f"pool baseline : INVEST {len(inv_ref):,} | DEPLOY {len(dep_ref):,}")
    print(f"all tracts    : INVEST {len(inv_all):,} | DEPLOY {len(dep_all):,}")

    # where do the all-tract targets sit relative to the workforce screen
    stats = {}
    for lab, ref, allb in [("INVEST", inv_ref, inv_all), ("DEPLOY", dep_ref, dep_all)]:
        in_pool_share = allb["in_pool"].mean() * 100
        top_in_pool = {n: int(allb.head(n)["in_pool"].sum()) for n in (10, 50, 100)}
        ov = {n: top_overlap(ref, allb, n) for n in (10, 50, 100)}
        stats[lab] = (in_pool_share, top_in_pool, ov)
        print(f"\n[{lab}] all-tract box: {len(allb):,} tracts; "
              f"{in_pool_share:.1f}% lie in the high-need pool")
        print(f"  top10/50/100 in pool: {top_in_pool[10]}/10, {top_in_pool[50]}/50, {top_in_pool[100]}/100")
        print(f"  top10/50/100 overlap with pool baseline: "
              f"{ov[10]}/10, {ov[50]}/50, {ov[100]}/100")

    rows = [{
        "n_invest_pool": len(inv_ref), "n_deploy_pool": len(dep_ref),
        "n_invest_all": len(inv_all), "n_deploy_all": len(dep_all),
        "invest_all_in_pool_pct": round(stats["INVEST"][0], 1),
        "deploy_all_in_pool_pct": round(stats["DEPLOY"][0], 1),
        "inv_top10_in_pool": stats["INVEST"][1][10],
        "dep_top10_in_pool": stats["DEPLOY"][1][10],
        "inv_top100_in_pool": stats["INVEST"][1][100],
        "dep_top100_in_pool": stats["DEPLOY"][1][100],
        "inv_top10_overlap": stats["INVEST"][2][10],
        "dep_top10_overlap": stats["DEPLOY"][2][10],
        "inv_top100_overlap": stats["INVEST"][2][100],
        "dep_top100_overlap": stats["DEPLOY"][2][100],
    }]
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "all_tracts_comparison.csv"), index=False)

    tidy(inv_all, extra=["in_pool"]).head(TOP_N).to_csv(
        os.path.join(OUT_DIR, "all_tracts_INVEST_top.csv"), index=False)
    tidy(dep_all, extra=["in_pool"]).head(TOP_N).to_csv(
        os.path.join(OUT_DIR, "all_tracts_DEPLOY_top.csv"), index=False)

    mixes = []
    for lab, box in [("pool_INVEST", inv_ref), ("pool_DEPLOY", dep_ref),
                     ("all_INVEST", inv_all), ("all_DEPLOY", dep_all)]:
        mixes.append(state_mix(box).head(8).rename_axis("state")
                     .reset_index().assign(run=lab))
    pd.concat(mixes, ignore_index=True).to_csv(
        os.path.join(OUT_DIR, "all_tracts_state_shift.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/all_tracts_*")


if __name__ == "__main__":
    main()
