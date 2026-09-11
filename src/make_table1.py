#!/usr/bin/env python3
"""
make_table1.py
============================
Group-level ("Table 1") characteristics of the 2x2 priority framework, to
replace top-25 ranges as the description of the groups.

For each cell of the matrix within the workforce-constrained pool:
    tracts, residents represented, median tract population,
    median (IQR) burden z, DDI, INFA, SE,
    median (IQR) cardiologists per 100,000, % in no-cardiologist counties,
    urban/rural composition (NCHS 6-level and 2020 Census tract urban share),
    and the population-weighted median (IQR) of burden and DDI.

Weights default to ACS 5-year total tract population (the DDI's own source).
Set WEIGHT_SOURCE = "census2020" to weight by decennial population instead;
the two are reported side by side in the console for comparison.

Outputs -> outputs/table1_group_summary/
    table1_group_summary.csv     one row per characteristic, one column per group
    table1_group_summary.md      same, markdown, ready to paste
    table1_urban_rural_long.csv  full NCHS composition (tracts and residents)

Requires only pandas and numpy, both already in the project venv.

RUN
    cd path/to/digital-readiness
    .venv/bin/python fetch_urban_rural.py      # once, for urban/rural
    .venv/bin/python make_table1.py

Urban/rural rows are skipped with a warning if GEO/ files are absent, so this
runs before the fetch if you just want the population and IQR rows.
"""
import glob
import os

import numpy as np
import pandas as pd

from build_master import load_master, PROJECT_DIR

OUT = os.path.join(PROJECT_DIR, "outputs", "table1")
os.makedirs(OUT, exist_ok=True)

NCHS_CSV = os.path.join(PROJECT_DIR, "GEO", "nchs_urban_rural_county.csv")
TRACT_CSV = os.path.join(PROJECT_DIR, "GEO", "census2020_tract_urban_rural.csv")

WEIGHT_SOURCE = "acs"          # "acs" or "census2020"

GROUPS = [
    ("Deployment priority", lambda d: d["hb"] & d["ready"]),
    ("Investment priority", lambda d: d["hb"] & ~d["ready"]),
    ("Lower burden, higher readiness", lambda d: ~d["hb"] & d["ready"]),
    ("Lower burden, lower readiness", lambda d: ~d["hb"] & ~d["ready"]),
    ("All workforce-constrained", lambda d: pd.Series(True, index=d.index)),
]


def wquantile(values, weights, q):
    """Weighted quantile via the weighted empirical CDF."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[ok], w[ok]
    if not len(v):
        return np.nan
    order = np.argsort(v)
    v, w = v[order], w[order]
    cdf = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(q, cdf, v))


def df_to_markdown(df):
    """Render a DataFrame as a padded markdown table (avoids needing tabulate)."""
    head = [df.index.name or ""] + [str(c) for c in df.columns]
    body = [[str(i)] + [str(v) for v in row] for i, row in df.iterrows()]
    w = [max(len(head[k]), *(len(r[k]) for r in body)) if body else len(head[k])
         for k in range(len(head))]
    line = lambda cells: "| " + " | ".join(
        c.ljust(w[k]) for k, c in enumerate(cells)) + " |"
    rule = "|" + "|".join(
        (":" + "-" * (w[k] + 1)) if k == 0 else ("-" * (w[k] + 2))
        for k in range(len(head))) + "|"
    return "\n".join([line(head), rule] + [line(r) for r in body])


def _rng(lo, hi, nd):
    """En dash normally; ' to ' when a negative bound would make it unreadable."""
    sep = " to " if (lo < 0 or hi < 0) else "–"
    return f"({lo:.{nd}f}{sep}{hi:.{nd}f})"


def fmt_iqr(s, nd=1):
    return f"{s.median():.{nd}f} " + _rng(s.quantile(.25), s.quantile(.75), nd)


def fmt_wiqr(v, w, nd=1):
    return (f"{wquantile(v, w, .50):.{nd}f} "
            + _rng(wquantile(v, w, .25), wquantile(v, w, .75), nd))


def load_population():
    """Tract population from ACS (B01001 total) and, if present, Census 2020."""
    pops = {}

    acs_files = sorted(glob.glob(os.path.join(
        PROJECT_DIR, "ACS", "acs5_*_tract_ddi_components.csv")))
    if acs_files:
        a = pd.read_csv(acs_files[-1], dtype={"GEOID": str})
        a["GEOID"] = a["GEOID"].str.zfill(11)
        pops["acs"] = a.set_index("GEOID")["age_65plus_denom"].astype(float)
        print(f"  ACS population   {os.path.basename(acs_files[-1])}: "
              f"{pops['acs'].sum():,.0f} residents")

    if os.path.exists(TRACT_CSV):
        c = pd.read_csv(TRACT_CSV, dtype={"GEOID": str})
        c["GEOID"] = c["GEOID"].str.zfill(11)
        pops["census2020"] = c.set_index("GEOID")["pop_total_2020"].astype(float)
        print(f"  Census 2020 population: {pops['census2020'].sum():,.0f} residents")

    if not pops:
        raise SystemExit("no population source found (need ACS components file)")
    return pops


def main():
    print("=" * 72)
    print("Table 1 - group-level characteristics of the priority framework")
    print("=" * 72)

    tracts, anchors = load_master()
    nat = float(anchors["nat_med_ddi"])

    pops = load_population()
    if WEIGHT_SOURCE not in pops:
        raise SystemExit(f"WEIGHT_SOURCE={WEIGHT_SOURCE!r} unavailable; "
                         f"have {sorted(pops)}")

    P = (tracts[tracts["in_pool"]]
         .dropna(subset=["burden_z", "ddi"])
         .drop_duplicates("fips_tract").copy())
    P["pop"] = P["fips_tract"].map(pops[WEIGHT_SOURCE])
    miss = P["pop"].isna().sum()
    if miss:
        print(f"  WARNING: {miss:,} pool tracts lack population; "
              "excluded from weighted rows")
    P["hb"] = P["burden_z"] > 0
    P["ready"] = P["ddi"] <= nat

    # urban/rural joins ------------------------------------------------------
    has_nchs = os.path.exists(NCHS_CSV)
    has_tract_ur = os.path.exists(TRACT_CSV)
    if has_nchs:
        n = pd.read_csv(NCHS_CSV, dtype={"fips_st_cnty": str})
        n["fips_st_cnty"] = n["fips_st_cnty"].str.zfill(5)
        P = P.merge(n, left_on="fips_county", right_on="fips_st_cnty",
                    how="left").drop(columns=["fips_st_cnty"])
        print(f"  NCHS matched: {P['nchs_label'].notna().mean() * 100:.1f}% of tracts")
    else:
        print(f"  NOTE: {NCHS_CSV} missing - NCHS rows skipped "
              "(run fetch_urban_rural.py)")
    if has_tract_ur:
        c = pd.read_csv(TRACT_CSV, dtype={"GEOID": str})
        c["GEOID"] = c["GEOID"].str.zfill(11)
        P = P.merge(c[["GEOID", "pct_urban", "urban_flag"]],
                    left_on="fips_tract", right_on="GEOID",
                    how="left").drop(columns=["GEOID"])
        print(f"  Census urban/rural matched: "
              f"{P['urban_flag'].notna().mean() * 100:.1f}% of tracts")
    else:
        print(f"  NOTE: {TRACT_CSV} missing - tract urban rows skipped")

    # build the table -------------------------------------------------------
    table, ur_long = {}, []
    for name, mask in GROUPS:
        d = P[mask(P)]
        w = d["pop"]
        col = {
            "Tracts, n": f"{len(d):,}",
            "Residents, n": f"{w.sum():,.0f}",
            "Median tract population": f"{w.median():,.0f}",
            "Burden z score, median (IQR)": fmt_iqr(d["burden_z"], 2),
            "DDI, median (IQR)": fmt_iqr(d["ddi"]),
            "DDI infrastructure/adoption subscore, median (IQR)": fmt_iqr(d["infa"]),
            "DDI socioeconomic subscore, median (IQR)": fmt_iqr(d["se"]),
            "Cardiologists per 100,000, median (IQR)":
                fmt_iqr(d["card_per_100k_last"], 2),
            "Tracts in counties with no cardiologist, %":
                f"{d['pool_nocard'].mean() * 100:.1f}",
            "Burden z score, population-weighted median (IQR)":
                fmt_wiqr(d["burden_z"], w, 2),
            "DDI, population-weighted median (IQR)": fmt_wiqr(d["ddi"], w),
        }

        if has_tract_ur:
            urb = d["urban_flag"].eq("Urban")
            col["Residents in urban tracts, %"] = (
                f"{w[urb].sum() / w.sum() * 100:.1f}" if w.sum() else "NA")
            col["Tract population urban, median % (IQR)"] = fmt_iqr(d["pct_urban"])

        if has_nchs:
            for lvl in ["Large central metro", "Large fringe metro",
                        "Medium metro", "Small metro", "Micropolitan",
                        "Noncore (rural)"]:
                m = d["nchs_label"].eq(lvl)
                col[f"  {lvl}, % of residents"] = (
                    f"{w[m].sum() / w.sum() * 100:.1f}" if w.sum() else "NA")
                ur_long.append({"Group": name, "NCHS level": lvl,
                                "Tracts": int(m.sum()),
                                "Tracts %": round(m.mean() * 100, 1),
                                "Residents": float(w[m].sum()),
                                "Residents %": round(
                                    w[m].sum() / w.sum() * 100, 1)
                                if w.sum() else np.nan})
        table[name] = col

    out = pd.DataFrame(table)
    out.index.name = "Characteristic"

    csv_path = os.path.join(OUT, "table1_group_summary.csv")
    out.to_csv(csv_path)

    md = df_to_markdown(out)
    md_path = os.path.join(OUT, "table1_group_summary.md")
    with open(md_path, "w") as f:
        f.write("# Table 1. Characteristics of the priority groups\n\n")
        f.write(f"Weights: {WEIGHT_SOURCE} tract population. "
                f"National median DDI anchor: {nat:.1f}.\n\n")
        f.write(md + "\n")

    if ur_long:
        pd.DataFrame(ur_long).to_csv(
            os.path.join(OUT, "table1_urban_rural_long.csv"), index=False)

    print("\n" + md)
    print(f"\n-> {csv_path}")
    print(f"-> {md_path}")

    # anchor sensitivity: tract-based vs population-weighted national cuts
    allt = tracts.dropna(subset=["ddi"]).drop_duplicates("fips_tract").copy()
    allt["pop"] = allt["fips_tract"].map(pops[WEIGHT_SOURCE])
    print("\nNational anchor sensitivity (descriptive only, classification "
          "uses the tract-based cut):")
    print(f"  median DDI, tract-weighted      : {allt['ddi'].median():.1f}")
    print(f"  median DDI, population-weighted : "
          f"{wquantile(allt['ddi'], allt['pop'].fillna(0), .5):.1f}")


if __name__ == "__main__":
    main()
