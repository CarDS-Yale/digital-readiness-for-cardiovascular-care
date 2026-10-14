"""
analyze_urban_rural.py
======================
Does the priority classification reduce to an urban-rural divide?

Everything here runs on the 26,517 tracts that carry a priority label under
the primary classification (investment priority = high burden, lower
readiness; deployment priority = high burden, higher readiness). Four
questions, each answered by one output table:

  composition    where the tracts and residents of each group sit across the
                 six 2023 NCHS county classes, the metro/nonmetro split and
                 2020 Census tract urban/rural status
  cooccurrence   how often one county holds both groups, overall and by
                 county class
  variance       the share of readiness variance (DDI and its two subscores)
                 that county class, the metro split, tract urban status and
                 county identity explain, as one-way ANOVA R-squared
  barriers       what "lower readiness" means in urban versus rural
                 investment tracts: DDI subscores and their national
                 percentiles, FCC broadband availability and ACS household
                 adoption and socioeconomic shares, with deployment tracts as
                 the reference column

A tract is called infrastructure-dominant when its infrastructure/adoption
subscore sits at a higher national percentile than its socioeconomic
subscore. Percentiles are taken across all analyzed tracts.

Inputs: the master cache, the NCHS and tract urban-rural files from
fetch_urban_rural.py, the ACS component file and the FCC availability file.

Outputs (outputs/urban_rural/)
  composition.csv            tracts and residents by stratum and group
  composition_within_class.csv
                             share of labelled tracts that are investment
                             priority within each county class
  cooccurrence.csv           county counts holding either or both groups
  cooccurrence_by_class.csv  the same by NCHS class
  variance_explained.csv     R-squared by readiness measure and classification
  barrier_profile.csv        medians (IQR) and shares by stratum
  metro_counties_most_investment_tracts.csv
  urban_rural_summary.md     all of the above in one readable log
"""
import os

import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, box_label, acs_population,
                          acs_components, fcc_availability, nchs_classes,
                          tract_urban_rural, markdown_table as md, NCHS_ORDER,
                          PROJECT_DIR)

OUT = os.path.join(PROJECT_DIR, "outputs", "urban_rural")
os.makedirs(OUT, exist_ok=True)
METRO = NCHS_ORDER[:4]
LOG = []


def log(s=""):
    print(s)
    LOG.append(s)


def iqr(s, nd=1):
    return f"{s.median():.{nd}f} ({s.quantile(.25):.{nd}f} to {s.quantile(.75):.{nd}f})"


def r2_groups(y, g):
    """One-way ANOVA R-squared: between-group sum of squares over total."""
    d = pd.DataFrame({"y": y, "g": g}).dropna()
    gm = d.groupby("g")["y"].transform("mean")
    ss_tot = ((d["y"] - d["y"].mean()) ** 2).sum()
    ss_within = ((d["y"] - gm) ** 2).sum()
    return 1 - ss_within / ss_tot, d["g"].nunique(), len(d)


def r2_linear(y, x):
    d = pd.DataFrame({"y": y, "x": x}).dropna()
    return np.corrcoef(d["x"], d["y"])[0, 1] ** 2, len(d)


def labelled_tracts():
    """Priority tracts with population, county class, urban share, ACS and FCC."""
    tracts, anchors = load_master()
    nat = float(anchors["nat_med_ddi"])
    pool = (tracts[tracts["in_pool"]].dropna(subset=["burden_z", "ddi"])
            .drop_duplicates("fips_tract").copy())
    inv, dep = matrix_boxes(pool, "ddi", nat)
    pool["group"] = box_label(pool, inv, dep)
    L = pool[pool["group"].isin(["INVEST", "DEPLOY"])].copy()
    log(f"Pool tracts with burden and DDI: {len(pool):,}; "
        f"investment {len(inv):,}; deployment {len(dep):,}")

    acs = acs_components()
    L = (L.merge(nchs_classes()[["fips_st_cnty", "nchs_label"]],
                 left_on="fips_county", right_on="fips_st_cnty", how="left")
           .drop(columns="fips_st_cnty")
           .merge(tract_urban_rural()[["GEOID", "pct_urban", "urban_flag"]],
                  left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID")
           .merge(acs[["GEOID", "no_internet_pct", "no_computer_pct", "poverty_pct",
                       "disability_pct", "age_65plus_pct", "lt_highschool_pct"]],
                  left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID")
           .merge(fcc_availability()[["GEOID", "n_locations", "terr_unserved_pct"]],
                  left_on="fips_tract", right_on="GEOID", how="left").drop(columns="GEOID"))
    L["pop"] = L["fips_tract"].map(acs_population())
    L["nchs_label"] = pd.Categorical(L["nchs_label"], NCHS_ORDER)
    L["metro"] = L["nchs_label"].isin(METRO)
    L["rural_tract"] = L["urban_flag"].eq("Rural")
    L["is_invest"] = L["group"].eq("INVEST")

    # national percentiles of the subscores, across every analyzed tract
    allddi = tracts.dropna(subset=["ddi"]).drop_duplicates("fips_tract")
    for c in ("infa", "se"):
        pct = (allddi[c].rank(pct=True) * 100)
        L[f"{c}_pct_nat"] = L["fips_tract"].map(dict(zip(allddi["fips_tract"], pct)))
    L["infra_dominant"] = L["infa_pct_nat"] > L["se_pct_nat"]
    L["infa_above_med"] = L["infa"] > float(anchors["nat_med_infa"])
    L["se_above_med"] = L["se"] > float(anchors["nat_med_se"])

    for col, name in (("nchs_label", "NCHS class"), ("urban_flag", "tract urban status"),
                      ("pop", "ACS population"), ("terr_unserved_pct", "FCC availability")):
        log(f"  {name} matched for {L[col].notna().mean() * 100:.1f}% of labelled tracts")
    return L


def composition(L):
    log("\n## Composition by urban-rural status")
    rows = []
    for grp in ("INVEST", "DEPLOY"):
        d = L[L["group"] == grp]
        tot_t, tot_p = len(d), d["pop"].sum()
        strata = [(f"NCHS: {lab}", d["nchs_label"] == lab) for lab in NCHS_ORDER]
        strata += [("County: metro (NCHS 1-4)", d["metro"]),
                   ("County: nonmetro (NCHS 5-6)", ~d["metro"]),
                   ("Tract: urban (>=50% urban population)", ~d["rural_tract"]),
                   ("Tract: rural (<50% urban population)", d["rural_tract"])]
        for name, m in strata:
            s = d[m]
            rows.append({"group": grp, "stratum": name, "tracts": len(s),
                         "pct_tracts": round(100 * len(s) / tot_t, 1),
                         "residents": int(s["pop"].sum()),
                         "pct_residents": round(100 * s["pop"].sum() / tot_p, 1)})
    A = pd.DataFrame(rows)
    A.to_csv(os.path.join(OUT, "composition.csv"), index=False)
    log(md(A.set_index(["group", "stratum"])))

    split = (L.groupby("nchs_label", observed=True)["is_invest"]
              .agg(tracts="size", pct_invest=lambda s: 100 * s.mean()))
    split["pct_deploy"] = 100 - split["pct_invest"]
    split = split.round(1)
    split.to_csv(os.path.join(OUT, "composition_within_class.csv"))
    log("\nWithin each county class, share of labelled tracts in each group:")
    log(md(split))
    return A


def cooccurrence(L):
    log("\n## Counties holding both groups")
    cty = (L.groupby("fips_county")
             .agg(n_invest=("is_invest", "sum"),
                  n_deploy=("is_invest", lambda s: (~s).sum()),
                  pop_invest=("pop", lambda s: s[L.loc[s.index, "is_invest"]].sum()),
                  pop_deploy=("pop", lambda s: s[~L.loc[s.index, "is_invest"]].sum()),
                  nchs=("nchs_label", "first"), county=("county_state", "first")))
    cty["both"] = (cty["n_invest"] > 0) & (cty["n_deploy"] > 0)
    n_dep = int((cty["n_deploy"] > 0).sum())
    n_inv = int((cty["n_invest"] > 0).sum())
    summary = {
        "counties_with_any_priority_tract": len(cty),
        "counties_with_investment": n_inv,
        "counties_with_deployment": n_dep,
        "counties_with_both": int(cty["both"].sum()),
        "pct_deployment_counties_also_investment": round(100 * cty["both"].sum() / n_dep, 1),
        "pct_investment_counties_also_deployment": round(100 * cty["both"].sum() / n_inv, 1),
        "pct_investment_residents_in_both_counties": round(
            100 * cty.loc[cty["both"], "pop_invest"].sum() / cty["pop_invest"].sum(), 1),
        "pct_deployment_residents_in_both_counties": round(
            100 * cty.loc[cty["both"], "pop_deploy"].sum() / cty["pop_deploy"].sum(), 1),
    }
    pd.Series(summary).to_csv(os.path.join(OUT, "cooccurrence.csv"), header=["value"])
    for k, v in summary.items():
        log(f"- {k}: {v:,.1f}" if isinstance(v, float) else f"- {k}: {v:,}")

    by_class = (cty.groupby("nchs", observed=True)
                  .agg(counties=("both", "size"),
                       with_investment=("n_invest", lambda s: (s > 0).sum()),
                       with_deployment=("n_deploy", lambda s: (s > 0).sum()),
                       with_both=("both", "sum")))
    by_class.index = by_class.index.astype(str)
    by_class.loc["All"] = [len(cty), n_inv, n_dep, int(cty["both"].sum())]
    by_class["pct_with_both"] = (100 * by_class["with_both"] / by_class["counties"]).round(1)
    by_class.to_csv(os.path.join(OUT, "cooccurrence_by_class.csv"))
    log("\nBy county class (counties holding at least one priority tract):")
    log(md(by_class))
    return cty


def variance_explained(L):
    log("\n## Share of readiness variance explained by rurality")
    rows = []
    for y, name_y in (("ddi", "DDI composite"), ("infa", "INFA subscore"),
                      ("se", "SE subscore")):
        for name, g in (("Tract urban vs rural (2020 Census)", L["rural_tract"]),
                        ("County metro vs nonmetro", L["metro"]),
                        ("County NCHS six-class", L["nchs_label"].astype(str)),
                        ("County identity", L["fips_county"])):
            r2, k, n = r2_groups(L[y], g)
            rows.append({"readiness_measure": name_y, "classification": name,
                         "r2_pct": round(100 * r2, 1), "levels": k, "n": n})
        r2, n = r2_linear(L[y], L["pct_urban"])
        rows.append({"readiness_measure": name_y,
                     "classification": "Tract percent urban (linear)",
                     "r2_pct": round(100 * r2, 1), "levels": np.nan, "n": n})
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(OUT, "variance_explained.csv"), index=False)
    log(md(D.set_index(["readiness_measure", "classification"])))
    return D


def barrier_profile(L):
    log("\n## Barrier profile: urban versus rural investment tracts")
    I = L[L["is_invest"]]
    strata = [("Investment, urban tracts", I[~I["rural_tract"]]),
              ("Investment, rural tracts", I[I["rural_tract"]]),
              ("Investment, metro counties", I[I["metro"]]),
              ("Investment, nonmetro counties", I[~I["metro"]]),
              ("All investment priority", I),
              ("Deployment priority", L[~L["is_invest"]])]
    rows = []
    for name, d in strata:
        rows.append({
            "stratum": name, "tracts": len(d),
            "residents_millions": round(d["pop"].sum() / 1e6, 1),
            "DDI composite": iqr(d["ddi"]),
            "INFA subscore": iqr(d["infa"]), "SE subscore": iqr(d["se"]),
            "INFA subscore, national percentile": iqr(d["infa_pct_nat"], 0),
            "SE subscore, national percentile": iqr(d["se_pct_nat"], 0),
            "Infrastructure-dominant barrier, % of tracts": round(100 * d["infra_dominant"].mean(), 1),
            "INFA above national median, % of tracts": round(100 * d["infa_above_med"].mean(), 1),
            "SE above national median, % of tracts": round(100 * d["se_above_med"].mean(), 1),
            "FCC locations unserved, %": iqr(100 * d["terr_unserved_pct"]),
            "Tracts with >10% of locations unserved, %":
                round(100 * (d["terr_unserved_pct"] > 0.10).mean(), 1),
            "Households without internet subscription, %": iqr(100 * d["no_internet_pct"]),
            "Households without a computer, %": iqr(100 * d["no_computer_pct"]),
            "Residents in poverty, %": iqr(100 * d["poverty_pct"]),
            "Adults without high school diploma, %": iqr(100 * d["lt_highschool_pct"]),
            "Residents aged 65 or older, %": iqr(100 * d["age_65plus_pct"]),
            "Residents with a disability, %": iqr(100 * d["disability_pct"]),
        })
    E = pd.DataFrame(rows).set_index("stratum").T
    E.index.name = "Characteristic"
    E.to_csv(os.path.join(OUT, "barrier_profile.csv"))
    log(md(E, ".1f"))
    return E


def metro_investment_counties(cty):
    log("\n## Metro counties with the most investment tracts")
    F = (cty[cty["nchs"].isin(METRO)].sort_values("n_invest", ascending=False)
           .head(25)[["county", "nchs", "n_invest", "pop_invest", "n_deploy", "pop_deploy"]])
    F.to_csv(os.path.join(OUT, "metro_counties_most_investment_tracts.csv"))
    log(md(F.set_index("county"), ".0f"))


def main():
    L = labelled_tracts()
    composition(L)
    cty = cooccurrence(L)
    variance_explained(L)
    barrier_profile(L)
    metro_investment_counties(cty)
    lcm = L[L["is_invest"] & L["nchs_label"].eq("Large central metro")]
    log(f"\nInvestment tracts in large central metro counties: {len(lcm):,} tracts, "
        f"{lcm['pop'].sum() / 1e6:.1f} million residents, "
        f"{lcm['fips_county'].nunique()} counties")
    with open(os.path.join(OUT, "urban_rural_summary.md"), "w") as fh:
        fh.write("# Priority classification and the urban-rural divide\n\n"
                 "Labelled tracts = investment + deployment priority under the primary "
                 "classification. Residents = ACS 5-year total population.\n\n")
        fh.write("\n".join(LOG) + "\n")
    print(f"\nwritten -> {OUT}")


if __name__ == "__main__":
    main()
