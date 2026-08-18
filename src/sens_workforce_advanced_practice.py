"""
sens_workforce_advanced_practice.py
==============================
Additional analysis G: fold CARDIOLOGY-SPECIFIC NPs and PAs into the
workforce picture, using the county counts built by process_clinicians.py
(DAC group-affiliation method; site_strict = cardiology-majority
practice site, primary; site_any / site_wtd as sensitivity).

Runs (per user decisions 2026-07-19: strict primary, broad sensitivity,
composite counts APP heads 1:1, point-in-time)

  1. GAP-FILL CHECK   How many no-cardiologist counties have a cardiology
                      APP? Sanity: DAC vs AHRF cardiologist counts.
  2. APP-ONLY POOL    High-need = zero strict cardiology APPs in the county
                      (point-in-time; no decline arm). Rerun the matrix.
  3. COMPOSITE POOL   Composite supply = AHRF cardiologists (2023) +
                      strict cardiology APPs, one head each. High-need =
                      zero composite clinicians OR declining per-capita
                      cardiology (the existing trend arm; APP counts have
                      no history in this build). Rerun the matrix.

Outputs (outputs/master/)
  workforce_advanced_practice_summary.csv, workforce_advanced_practice_comparison.csv
  workforce_advanced_practice_APPonly_INVEST_top.csv / _DEPLOY_top.csv
  workforce_advanced_practice_composite_INVEST_top.csv / _DEPLOY_top.csv, workforce_advanced_practice_state_shift.csv
"""
import os
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              state_mix, tidy, OUT_DIR)

APP_FILE = os.path.join(OUT_DIR, "dac_cardiology_app_county.csv")
TOP_N = 10


def main():
    if not os.path.exists(APP_FILE):
        raise SystemExit("Missing dac_cardiology_app_county.csv. "
                         "Run fetch_clinicians.py --all then process_clinicians.py "
                         "on the Mac first.")
    tracts, anchors = load_master()
    base = tracts.dropna(subset=["burden_z", "ddi"]).copy()
    P_ref = tracts[tracts["in_pool"]]
    inv_ref, dep_ref = matrix_boxes(P_ref, "ddi", anchors["nat_med_ddi"])

    app = pd.read_csv(APP_FILE, dtype={"fips_st_cnty": str})
    app["fips_st_cnty"] = app["fips_st_cnty"].str.zfill(5)

    cnty = (tracts.drop_duplicates("fips_county")
            [["fips_county", "card_last", "pool_nocard", "pool_declining", "in_pool"]]
            .merge(app, left_on="fips_county", right_on="fips_st_cnty", how="left"))
    for c in ["n_app_grp_strict", "n_app_site_strict", "n_app_site_any",
              "n_app_site_wtd", "n_cardiologists_dac"]:
        cnty[c] = cnty[c].fillna(0)

    print("=" * 78)
    print("cardiology NP/PA workforce (DAC group-affiliation counts)")
    print("=" * 78)

    # 1. gap-fill + sanity
    nocard = cnty[cnty["pool_nocard"]]
    gap_strict = (nocard["n_app_site_strict"] > 0).sum()
    gap_broad = (nocard["n_app_site_any"] > 0).sum()
    r_sanity = cnty["card_last"].corr(cnty["n_cardiologists_dac"])
    print(f"no-cardiologist counties (AHRF): {len(nocard):,}")
    print(f"  with >=1 site-strict cardiology APP: {gap_strict:,} "
          f"({gap_strict/len(nocard)*100:.1f}%)")
    print(f"  with >=1 co-located cardiology APP: {gap_broad:,} "
          f"({gap_broad/len(nocard)*100:.1f}%)")
    print(f"sanity: county corr(AHRF cardiologists, DAC cardiologists) "
          f"r={r_sanity:.3f}")

    rows, mixes = [], []
    runs = {
        "APPonly": set(cnty.loc[cnty["n_app_site_strict"] == 0, "fips_county"]),
        "composite": set(cnty.loc[
            ((cnty["card_last"].fillna(0) + cnty["n_app_site_strict"]) == 0)
            | cnty["pool_declining"].fillna(False), "fips_county"]),
    }
    card_pool = set(tracts.loc[tracts["in_pool"], "fips_county"])
    for name, pool_set in runs.items():
        jac = len(pool_set & card_pool) / len(pool_set | card_pool)
        Pw = tracts[tracts["fips_county"].isin(pool_set)]
        inv_w, dep_w = matrix_boxes(Pw, "ddi", anchors["nat_med_ddi"])
        cmp_ = compare_runs(base, inv_ref, dep_ref, inv_w, dep_w)
        rows.append({"run": name, "n_counties_pool": len(pool_set),
                     "jaccard_vs_card_pool": round(jac, 3), **cmp_})
        print(f"\n[{name}] pool {len(pool_set):,} counties (jaccard {jac:.2f}) | "
              f"INVEST {len(inv_w):,} DEPLOY {len(dep_w):,} | "
              f"agree {cmp_['box_agree_pct']}% "
              f"(INVEST kept {cmp_['invest_retained_pct']}%, "
              f"DEPLOY kept {cmp_['deploy_retained_pct']}%) | "
              f"top10 INV {cmp_['inv_top10_overlap']}/10 "
              f"DEP {cmp_['dep_top10_overlap']}/10")
        tidy(inv_w).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_advanced_practice_{name}_INVEST_top.csv"), index=False)
        tidy(dep_w).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"workforce_advanced_practice_{name}_DEPLOY_top.csv"), index=False)
        for lab, box in [(f"{name}_INVEST", inv_w), (f"{name}_DEPLOY", dep_w)]:
            mixes.append(state_mix(box).head(8).rename_axis("state")
                         .reset_index().assign(run=lab))

    pd.DataFrame([{
        "n_nocard_counties": len(nocard),
        "gap_filled_strict": int(gap_strict),
        "gap_filled_broad": int(gap_broad),
        "corr_ahrf_dac_cardiologists": round(r_sanity, 3),
        "national_app_site_strict": int(cnty["n_app_site_strict"].sum()),
        "national_app_grp_strict": int(cnty["n_app_grp_strict"].sum()),
        "national_app_site_wtd": round(float(cnty["n_app_site_wtd"].sum())),
    }]).to_csv(os.path.join(OUT_DIR, "workforce_advanced_practice_summary.csv"), index=False)
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "workforce_advanced_practice_comparison.csv"), index=False)
    pd.concat(mixes, ignore_index=True).to_csv(
        os.path.join(OUT_DIR, "workforce_advanced_practice_state_shift.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/workforce_advanced_practice_*")


if __name__ == "__main__":
    main()
