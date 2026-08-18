"""
Sensitivity: composite Divide Index versus its raw components.

Swaps the readiness axis for
  (1) ACS_6           six ACS component shares (equal-weight national z-mean)
  (2) ACS_6_plus_FCC  adds the FCC terrestrial 100/20 unserved share
and reruns the classification against the primary run.

Outputs (outputs/master/)
  readiness_components_comparison.csv
  readiness_components_<variant>_INVEST_top.csv / _DEPLOY_top.csv
"""
import os, glob
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              tidy, OUT_DIR, PROJECT_DIR)

ACS_COMPS = ["no_internet_pct", "no_computer_pct", "poverty_pct",
             "disability_pct", "age_65plus_pct", "lt_highschool_pct"]
FCC_COMP = "terr_unserved_pct"
TOP_N = 10


def national_index(df, cols):
    a = df.dropna(subset=cols).copy()
    z = (a[cols] - a[cols].mean()) / a[cols].std()
    a["cidx"] = z.mean(axis=1)                      # higher = worse readiness
    return a[["GEOID", "cidx"]], float(a["cidx"].median())


def main():
    tracts, anchors = load_master()
    P = tracts[tracts["in_pool"]].copy()
    inv_ref, dep_ref = matrix_boxes(P, "ddi", anchors["nat_med_ddi"])

    acs_files = sorted(glob.glob(os.path.join(PROJECT_DIR, "ACS",
                                              "acs5_*_tract_ddi_components.csv")))
    acs = pd.read_csv(acs_files[-1], dtype={"GEOID": str})
    variants = {"ACS_6": national_index(acs, ACS_COMPS)}

    fcc_files = sorted(glob.glob(os.path.join(PROJECT_DIR, "FCC",
                                              "fcc_*_tract_availability.csv")))
    if fcc_files:
        fcc = pd.read_csv(fcc_files[-1], dtype={"GEOID": str})[["GEOID", FCC_COMP]]
        variants["ACS_6_plus_FCC_7"] = national_index(
            acs.merge(fcc, on="GEOID", how="inner"), ACS_COMPS + [FCC_COMP])

    rows = []
    print("=" * 78)
    print("composite DDI vs raw components (ACS +/- FCC)")
    print("=" * 78)
    for name, (idx, med) in variants.items():
        Pv = P.merge(idx, left_on="fips_tract", right_on="GEOID", how="left")
        mm = Pv.dropna(subset=["ddi", "cidx"])
        r = mm["ddi"].corr(mm["cidx"])
        rho = mm["ddi"].rank().corr(mm["cidx"].rank())
        inv_c, dep_c = matrix_boxes(Pv, "cidx", med)
        cmp_ = compare_runs(Pv.dropna(subset=["ddi", "cidx"]),
                            inv_ref, dep_ref, inv_c, dep_c)
        row = {"variant": name, "pearson_r": round(r, 3),
               "spearman_rho": round(rho, 3),
               "coverage_pct": round(Pv["cidx"].notna().mean() * 100, 1), **cmp_}
        rows.append(row)
        print(f"\n[{name}] r={r:.3f} rho={rho:.3f} "
              f"agree={cmp_['box_agree_pct']}% "
              f"(INVEST {cmp_['invest_retained_pct']}%, DEPLOY {cmp_['deploy_retained_pct']}%)")
        tidy(inv_c).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"readiness_components_{name}_INVEST_top.csv"), index=False)
        tidy(dep_c).head(TOP_N).to_csv(
            os.path.join(OUT_DIR, f"readiness_components_{name}_DEPLOY_top.csv"), index=False)

    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "readiness_components_comparison.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/readiness_components_*")


if __name__ == "__main__":
    main()
