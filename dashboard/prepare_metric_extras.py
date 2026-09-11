"""prepare_metric_extras.py — add the sectioned map-view fields.

Run from dashboard/ AFTER prepare_dashboard_data.py + prepare_v5_layers.py.

Injects into data/counties.geojson + data/county_data.json:
  card_app_per_100k   (AHRF cardiologists 2023 + DAC site-strict cardiology
                       NPs/PAs, one head each, per 100k; mirrors the advanced-practice workforce analysis)
  n_card_app_strict   DAC site-strict cardiology NP/PA count
  pcp_per_100k        MD+DO primary care, patient care excl residents,
                      2023, per 100k (primary-care panel)
  disease_<measure>   10 CDC PLACES county crude prevalences (latest year)

Writes data/extras_meta.json: per-metric quantile stops + labels for the
map's color ramps and legends (also for the pre-existing DDI INFA/SE,
cardiologists-per-100k, and burden-z fields).
"""
import json
import os

import numpy as np
import pandas as pd

DASH = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DASH)
DATA = os.path.join(DASH, "data")
MASTER = os.path.join(REPO, "outputs", "master")

PLACES = os.path.join(REPO, "outputs", "cdc_places_cv_county_wide.csv")
PANEL = os.path.join(MASTER, "workforce_primary_care_county_panels.csv")
DAC = os.path.join(MASTER, "dac_cardiology_app_county.csv")
WF_TREND = os.path.join(REPO, "outputs", "ahrf_workforce_trend_summary.csv")

DISEASES = {  # csv column prefix -> (metric key, label)
    "coronary_heart_disease": ("disease_chd", "Coronary heart disease"),
    "stroke": ("disease_stroke", "Stroke"),
    "diabetes": ("disease_diabetes", "Diabetes"),
    "hypertension": ("disease_htn", "Hypertension"),
    "high_cholesterol": ("disease_chol", "High cholesterol"),
    "obesity": ("disease_obesity", "Obesity"),
    "smoking": ("disease_smoking", "Current smoking"),
    "physical_inactivity": ("disease_inactivity", "Physical inactivity"),
    "short_sleep": ("disease_sleep", "Short sleep"),
    "binge_drinking": ("disease_binge", "Binge drinking"),
}


def quantile_stops(values, probs=(0.02, 0.25, 0.5, 0.75, 0.98)):
    v = pd.Series(values, dtype=float).dropna()
    if v.empty:
        return None
    q = [round(float(v.quantile(p)), 2) for p in probs]
    out = []          # strictly increasing (MapLibre interpolate requires it)
    for x in q:
        if not out or x > out[-1]:
            out.append(x)
    return out if len(out) >= 2 else None


def main():
    geo = json.load(open(os.path.join(DATA, "counties.geojson")))
    cdata = json.load(open(os.path.join(DATA, "county_data.json")))

    # ── PCP per 100k (primary-care panel, latest year 2023) ─────
    panel = pd.read_csv(PANEL, dtype={"fips_st_cnty": str})
    pcp = (panel[(panel["workforce"] == "PCP") & (panel["year"] == 2023)]
           .set_index("fips_st_cnty")["rate_100k"])

    # ── DAC cardiology APPs (site-strict = primary definition) ────────
    dac = pd.read_csv(DAC, dtype={"fips_st_cnty": str})
    dac["fips_st_cnty"] = dac["fips_st_cnty"].str.zfill(5)
    app = dac.set_index("fips_st_cnty")["n_app_site_strict"]

    # ── per-capita workforce trend (matches the manuscript's decline rule) ──
    wt = pd.read_csv(WF_TREND, dtype={"fips_st_cnty": str})
    wt["fips_st_cnty"] = wt["fips_st_cnty"].str.zfill(5)
    wt = wt.set_index("fips_st_cnty")
    trend_pc = wt["workforce_trend_pc"].to_dict()
    slope_pc = wt["workforce_slope_pc"].to_dict()
    rate_first = wt["rate_first"].to_dict()
    rate_last = wt["rate_last"].to_dict()

    # ── PLACES county prevalences (columns carry the vintage year) ────
    places = pd.read_csv(PLACES, dtype={"fips_county": str})
    places["fips_county"] = places["fips_county"].str.zfill(5)
    places = places.set_index("fips_county")
    dcolmap, dyears = {}, {}
    for col in places.columns:
        for prefix, (key, _) in DISEASES.items():
            if col.startswith(prefix + "_2"):
                dcolmap[key] = col
                dyears[key] = col.rsplit("_", 1)[1]

    def num(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 2)

    n_app_tot = n_pcp = 0
    for ft in geo["features"]:
        p = ft["properties"]
        f = p.get("fips_st_cnty")
        c = cdata.get(f, {})
        pop = p.get("county_pop_latest") or c.get("county_pop_latest")
        card = p.get("card_last") if p.get("card_last") is not None else c.get("card_last")

        a = num(app.get(f))
        if a is None:
            a = 0.0          # absent from DAC = no cardiology APPs (mirrors the advanced-practice analysis)
        extras = {"n_card_app_strict": a}
        if a is not None and card is not None and pop:
            extras["card_app_per_100k"] = round((card + a) / pop * 1e5, 2)
            n_app_tot += 1
        else:
            extras["card_app_per_100k"] = None

        r = num(pcp.get(f))
        extras["pcp_per_100k"] = r
        if r is not None:
            n_pcp += 1

        for key, col in dcolmap.items():
            extras[key] = num(places[col].get(f))

        tpc = trend_pc.get(f)
        extras["workforce_trend_pc"] = tpc if isinstance(tpc, str) else None
        extras["workforce_slope_pc"] = num(slope_pc.get(f))
        extras["rate_first"] = num(rate_first.get(f))
        extras["rate_last"] = num(rate_last.get(f))

        p.update(extras)
        if f in cdata:
            cdata[f].update(extras)

    # ── color-ramp metadata ───────────────────────────────────────────
    def col_vals(prop):
        return [ft["properties"].get(prop) for ft in geo["features"]]

    meta = {}
    meta["mean_ddi_infa"] = {"stops": quantile_stops(col_vals("mean_ddi_infa")),
                             "dir": "worse_high", "label": "DDI infrastructure sub-score",
                             "fmt": "num", "lo": "Better infrastructure", "hi": "Worse infrastructure"}
    meta["mean_ddi_se"] = {"stops": quantile_stops(col_vals("mean_ddi_se")),
                           "dir": "worse_high", "label": "DDI socioeconomic sub-score",
                           "fmt": "num", "lo": "Better socioeconomic", "hi": "Worse socioeconomic"}
    meta["cards_per_100k_latest"] = {"stops": quantile_stops(col_vals("cards_per_100k_latest")),
                                     "dir": "better_high", "label": "Cardiologists per 100,000 (2023)",
                                     "fmt": "num", "lo": "No cardiologists", "hi": "Most per capita"}
    meta["card_app_per_100k"] = {"stops": quantile_stops(col_vals("card_app_per_100k")),
                                 "dir": "better_high",
                                 "label": "Cardiologists + cardiology NPs/PAs per 100,000",
                                 "fmt": "num", "lo": "None", "hi": "Most per capita"}
    meta["pcp_per_100k"] = {"stops": quantile_stops(col_vals("pcp_per_100k")),
                            "dir": "better_high", "label": "Primary care physicians per 100,000 (2023)",
                            "fmt": "num", "lo": "Fewest", "hi": "Most per capita"}
    meta["burden_z_last"] = {"stops": quantile_stops(col_vals("burden_z_last")),
                             "dir": "worse_high", "label": "Cardiometabolic burden (composite z, 2023)",
                             "fmt": "num", "lo": "Below-average burden", "hi": "Above-average burden"}
    for prefix, (key, label) in DISEASES.items():
        meta[key] = {"stops": quantile_stops(col_vals(key), (0.02, 0.5, 0.98)),
                     "dir": "prevalence",
                     "label": f"{label}, crude prevalence ({dyears.get(key, '')})",
                     "fmt": "pct", "lo": "Lowest", "hi": "Highest"}

    json.dump(geo, open(os.path.join(DATA, "counties.geojson"), "w"),
              separators=(",", ":"))
    json.dump(cdata, open(os.path.join(DATA, "county_data.json"), "w"),
              separators=(",", ":"))
    json.dump(meta, open(os.path.join(DATA, "extras_meta.json"), "w"), indent=1)
    print(f"counties with card+APP rate: {n_app_tot:,}; with PCP rate: {n_pcp:,}")
    print(f"disease columns mapped: {len(dcolmap)}/10 -> {sorted(dyears.values())}")
    print("wrote counties.geojson, county_data.json, extras_meta.json")


if __name__ == "__main__":
    main()
