"""
make_table_decile.py
====================
Table 1 again, for stricter priority groups.

The primary groups use the national mean burden and median readiness as
anchors, which is a broad net. This table repeats the Table 1 rows for
smaller, more extreme groups so the two can be read side by side:

  Primary          burden above the national mean; readiness split at the
                   national median DDI
  Burden decile    burden in the national top decile; readiness split at the
                   national median DDI
  Both deciles     burden in the national top decile; readiness in the lowest
                   DDI decile (deployment) or the highest (investment)

All cuts are national, taken across the analyzed tracts, and groups are drawn
from the workforce-constrained pool, as in the primary analysis.

Outputs (outputs/table1/)
  table1_decile_groups.csv, table1_decile_groups.md
"""
import os

import pandas as pd

from build_master import (load_master, acs_population, nchs_classes,
                          tract_urban_rural, NCHS_ORDER)
from make_table1 import fmt_iqr, fmt_wiqr, df_to_markdown, OUT


def main():
    tracts, anchors = load_master()
    nat_med = float(anchors["nat_med_ddi"])
    allt = tracts.dropna(subset=["burden_z", "ddi"]).drop_duplicates("fips_tract")
    b90 = float(allt["burden_z"].quantile(0.90))
    d10 = float(allt["ddi"].quantile(0.10))
    d90 = float(allt["ddi"].quantile(0.90))
    print(f"national cuts: burden mean 0 / p90 {b90:.3f}; "
          f"DDI median {nat_med:.1f}, p10 {d10:.1f}, p90 {d90:.1f}")

    pop = acs_population()
    P = (tracts[tracts["in_pool"]].dropna(subset=["burden_z", "ddi"])
         .drop_duplicates("fips_tract").copy())
    P["pop"] = P["fips_tract"].map(pop)
    P = (P.merge(nchs_classes(), left_on="fips_county", right_on="fips_st_cnty", how="left")
          .drop(columns="fips_st_cnty")
          .merge(tract_urban_rural()[["GEOID", "pct_urban", "urban_flag"]],
                 left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID"))

    hb_mean, hb_p90 = P["burden_z"] > 0, P["burden_z"] >= b90
    ready_med, ready_p10, low_p90 = P["ddi"] <= nat_med, P["ddi"] <= d10, P["ddi"] >= d90
    groups = [
        ("Primary: deployment priority", hb_mean & ready_med),
        ("Primary: investment priority", hb_mean & ~ready_med),
        ("Burden top decile: deployment priority", hb_p90 & ready_med),
        ("Burden top decile: investment priority", hb_p90 & ~ready_med),
        ("Both deciles: deployment priority", hb_p90 & ready_p10),
        ("Both deciles: investment priority", hb_p90 & low_p90),
    ]

    table = {}
    for name, m in groups:
        d = P[m]
        w = d["pop"]
        col = {
            "Tracts, n": f"{len(d):,}",
            "Residents, n": f"{w.sum():,.0f}",
            "Share of US population, %": f"{w.sum() / pop.sum() * 100:.1f}",
            "Counties, n": f"{d['fips_county'].nunique():,}",
            "States, n": f"{d['state_abbr'].nunique()}",
            "Median tract population": f"{w.median():,.0f}",
            "Burden z score, median (IQR)": fmt_iqr(d["burden_z"], 2),
            "DDI, median (IQR)": fmt_iqr(d["ddi"]),
            "DDI infrastructure/adoption subscore, median (IQR)": fmt_iqr(d["infa"]),
            "DDI socioeconomic subscore, median (IQR)": fmt_iqr(d["se"]),
            "Cardiologists per 100,000, median (IQR)": fmt_iqr(d["card_per_100k_last"], 2),
            "Tracts in counties with no cardiologist, %": f"{d['pool_nocard'].mean() * 100:.1f}",
            "Burden z score, population-weighted median (IQR)": fmt_wiqr(d["burden_z"], w, 2),
            "DDI, population-weighted median (IQR)": fmt_wiqr(d["ddi"], w),
            "Residents in urban tracts, %":
                f"{w[d['urban_flag'].eq('Urban')].sum() / w.sum() * 100:.1f}",
            "Tract population urban, median % (IQR)": fmt_iqr(d["pct_urban"]),
        }
        for lvl in NCHS_ORDER:
            mm = d["nchs_label"].eq(lvl)
            col[f"  {lvl}, % of residents"] = f"{w[mm].sum() / w.sum() * 100:.1f}"
        table[name] = col

    out = pd.DataFrame(table)
    out.index.name = "Characteristic"
    out.to_csv(os.path.join(OUT, "table1_decile_groups.csv"))
    md = df_to_markdown(out)
    with open(os.path.join(OUT, "table1_decile_groups.md"), "w") as fh:
        fh.write("# Priority groups under stricter national cuts\n\n"
                 f"Cuts: burden p90 = {b90:.3f}; DDI median {nat_med:.1f}, "
                 f"p10 {d10:.1f}, p90 {d90:.1f}\n\n" + md + "\n")
    print(md)
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
