"""
sens_readiness_vintage.py
===========================
Readiness-vintage sensitivity: does the classification hold if digital
readiness is measured with the 2024 Digital Divide Index instead of 2022?

The primary analysis reads the "Tracts 22" sheet of the DDI workbook. That
workbook also carries "Tracts 23" and "Tracts 24". This script re-runs the
canonical matrix on the 2024 vintage and reports the standard comparison
metrics (box agreement, retention, top-N overlap) against the primary run.

Two anchorings are tested, because the national DDI distribution shifted
downward between vintages:
  (a) own-year anchor  - national median of the 2024 tract distribution
  (b) fixed anchor     - the primary 2022 median, held constant

Outputs (outputs/master/)
  readiness_vintage.md          narrative log
  readiness_vintage_top25.csv   top 25 per group under the 2024 vintage

Run after build_master.py.
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              rank_eligible, top_overlap, PROJECT_DIR, OUT_DIR)

DDI_FILE = os.path.join(PROJECT_DIR, "DDI", "2022-2024 US DDI.xlsx")
LOG = os.path.join(OUT_DIR, "readiness_vintage.md")
TOP_CSV = os.path.join(OUT_DIR, "readiness_vintage_top25.csv")
N = 25

lines = []


def say(s=""):
    print(s)
    lines.append(s)


def load_vintage(sheet, fips_col):
    d = pd.read_excel(DDI_FILE, sheet_name=sheet, dtype={fips_col: str})
    d.columns = [c.strip() for c in d.columns]
    d = d.rename(columns={fips_col: "fips_tract"})
    d["fips_tract"] = d["fips_tract"].astype(str).str.zfill(11)
    return d[["fips_tract", "DDI", "SE", "INFA"]].drop_duplicates("fips_tract")


def main():
    tracts, anchors = load_master()
    nat22 = float(anchors["nat_med_ddi"])

    d24 = load_vintage("Tracts 24", "FIPS_Tract")
    nat24 = float(d24["DDI"].median())

    say("## readiness-vintage sensitivity (2024 DDI vs primary 2022 DDI)\n")
    say(f"- National median tract DDI: 2022 = {nat22:.2f}; 2024 = {nat24:.2f}")

    # agreement between vintages, all tracts
    both = (tracts[["fips_tract", "ddi"]]
            .merge(d24[["fips_tract", "DDI"]], on="fips_tract", how="inner")
            .dropna())
    say(f"- Tracts with both vintages: {len(both):,}")
    say(f"- Correlation between vintages: Pearson r = "
        f"{both['ddi'].corr(both['DDI']):.3f}, Spearman rho = "
        f"{both['ddi'].corr(both['DDI'], method='spearman'):.3f}")
    say(f"- Mean absolute change: {(both['DDI'] - both['ddi']).abs().mean():.2f} "
        "index points")

    # primary run
    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract").copy())
    inv0, dep0 = matrix_boxes(P, "ddi", nat22)

    # attach 2024 vintage to the same pool
    P = P.merge(d24.rename(columns={"DDI": "ddi24", "SE": "se24",
                                    "INFA": "infa24"}),
                on="fips_tract", how="left")
    cov = P["ddi24"].notna().mean() * 100
    say(f"- Pool tracts with a 2024 DDI value: {P['ddi24'].notna().sum():,} "
        f"({cov:.1f}%)\n")

    for label, cut in [("own-year anchor (2024 median)", nat24),
                       ("fixed anchor (primary 2022 median)", nat22)]:
        inv, dep = matrix_boxes(P.dropna(subset=["ddi24"]), "ddi24", cut)
        cmp_ = compare_runs(P, inv0, dep0, inv, dep)
        say(f"### {label}, cut = {cut:.2f}")
        say(f"- Boxes: investment {len(inv0):,} -> {len(inv):,}; "
            f"deployment {len(dep0):,} -> {len(dep):,}")
        say(f"- Box agreement: {cmp_['box_agree_pct']}%")
        say(f"- Retention: investment {cmp_['invest_retained_pct']}%, "
            f"deployment {cmp_['deploy_retained_pct']}%")
        inv0e, depe0 = rank_eligible(inv0), rank_eligible(dep0)
        inve, depe = rank_eligible(inv), rank_eligible(dep)
        for n in (10, 25):
            say(f"- Top-{n} overlap (rank-eligible): investment "
                f"{top_overlap(inv0e, inve, n)}/{n}; deployment "
                f"{top_overlap(depe0, depe, n)}/{n}")
        say("")

        if cut == nat24:      # keep the own-year run for the supplement table
            keep = ["rank", "fips_tract", "county_state", "state_abbr",
                    "burden_z", "ddi24", "se24", "infa24"]
            rows = []
            for grp, df in [("Investment", inve), ("Deployment", depe)]:
                d = df.head(N)[[c for c in keep if c in df.columns]].copy()
                d.insert(0, "Group", grp)
                prim = set(rank_eligible(inv0 if grp == "Investment" else dep0)
                           ["fips_tract"].head(N))
                d["In primary top 25"] = np.where(
                    d["fips_tract"].isin(prim), "Yes", "No")
                rows.append(d)
            pd.concat(rows, ignore_index=True).round(3).to_csv(TOP_CSV, index=False)

    with open(LOG, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nlog -> {LOG}\ntop25 -> {TOP_CSV}")


if __name__ == "__main__":
    main()
