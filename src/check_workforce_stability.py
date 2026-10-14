"""
check_workforce_stability.py
============================
How much does the county cardiology workforce move from one year to the next?

The workforce measure ends in 2023, so this script asks whether a one-year
lag would matter: it compares county cardiologist counts in 2022 and 2023
(the two most recent years in the AHRF panel) and reports the correlation,
the share of counties whose count did not change, and the share that kept
the same no-cardiologist status. The same pair of numbers is reported for
every consecutive pair of years in the panel for context.

Reads outputs/ahrf_card_dis_panel_2010_2023.csv (from fetch_workforce.py) and
restricts it to the counties that appear in the master tract table, so the
territories and counties without analyzed tracts drop out.

Outputs (outputs/master/)
  workforce_stability.csv   one row per consecutive year pair
"""
import os

import pandas as pd

from build_master import load_master, corr_with_ci, OUT_DIR, PROJECT_DIR

PANEL = os.path.join(PROJECT_DIR, "outputs", "ahrf_card_dis_panel_2010_2023.csv")


def main():
    if not os.path.exists(PANEL):
        raise SystemExit("workforce panel missing. Run fetch_workforce.py first.")
    panel = pd.read_csv(PANEL, dtype={"fips_st_cnty": str})
    panel["fips_st_cnty"] = panel["fips_st_cnty"].str.zfill(5)
    tracts, _ = load_master()
    analyzed = set(tracts["fips_county"].dropna())
    panel = panel[panel["fips_st_cnty"].isin(analyzed)]
    wide = (panel.pivot_table(index="fips_st_cnty", columns="year",
                              values="md_nf_card_dis", aggfunc="first"))
    years = sorted(int(y) for y in wide.columns)

    rows = []
    for y0, y1 in zip(years[:-1], years[1:]):
        d = wide[[y0, y1]].dropna()
        cc = corr_with_ci(d[y0], d[y1])
        rows.append({"year_from": y0, "year_to": y1, "counties": cc["n"],
                     "pearson_r": cc["r"], "ci_low": cc["ci_low"], "ci_high": cc["ci_high"],
                     "pct_count_unchanged": round((d[y0] == d[y1]).mean() * 100, 1),
                     "pct_same_no_cardiologist_status":
                         round(((d[y0] == 0) == (d[y1] == 0)).mean() * 100, 1),
                     "n_gained_first_cardiologist": int(((d[y0] == 0) & (d[y1] > 0)).sum()),
                     "n_lost_last_cardiologist": int(((d[y0] > 0) & (d[y1] == 0)).sum())})
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT_DIR, "workforce_stability.csv"), index=False)
    print(out.to_string(index=False))
    last = out.iloc[-1]
    print(f"\n{int(last['year_from'])} to {int(last['year_to'])}: r = {last['pearson_r']:.3f} "
          f"(95% CI {last['ci_low']:.3f} to {last['ci_high']:.3f}, n = {int(last['counties']):,}); "
          f"{last['pct_same_no_cardiologist_status']:.1f}% of counties kept the same "
          "no-cardiologist status")


if __name__ == "__main__":
    main()
