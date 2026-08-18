"""
Full ranked priority lists, written for the dashboards.

The manuscript tables report only the highest-ranked tracts. The dashboards need
the complete ranked frames plus the two national cutoffs, so this writes them
once from the cached master table.

Outputs (outputs/master/)
  priority_INVEST_ranked.csv   every investment-priority tract, ranked
  priority_DEPLOY_ranked.csv   every deployment-priority tract, ranked
  priority_thresholds.csv      the burden and readiness cutoffs, single row

Ranks here cover all tracts, including Kentucky and Pennsylvania. Consumers that
need the publication ranking apply rank_eligible() themselves.
"""
import os

import pandas as pd

from build_master import load_master, matrix_boxes, tidy, OUT_DIR

INVEST_FILE = os.path.join(OUT_DIR, "priority_INVEST_ranked.csv")
DEPLOY_FILE = os.path.join(OUT_DIR, "priority_DEPLOY_ranked.csv")
THRESH_FILE = os.path.join(OUT_DIR, "priority_thresholds.csv")

EXTRA = ["card_per_100k_last", "in_pool"]


def main():
    tracts, anchors = load_master()
    nat = float(anchors["nat_med_ddi"])
    pool = (tracts[tracts["in_pool"]]
            .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract"))
    inv, dep = matrix_boxes(pool, "ddi", nat)

    tidy(inv, EXTRA).to_csv(INVEST_FILE, index=False)
    tidy(dep, EXTRA).to_csv(DEPLOY_FILE, index=False)
    pd.DataFrame([{
        "high_burden_cut": 0.0,
        "ready_cut_national_median": nat,
        "n_invest": len(inv),
        "n_deploy": len(dep),
    }]).to_csv(THRESH_FILE, index=False)

    print(f"investment {len(inv):,} | deployment {len(dep):,} -> {OUT_DIR}")


if __name__ == "__main__":
    main()
