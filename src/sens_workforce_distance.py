"""
sens_workforce_distance.py
==========================
Additional analysis E: cross-county workforce access within 25 miles.

The main analysis treats county lines as hard walls. Here we assume a patient
can reach any cardiologist in a county whose population-free geographic
centroid lies within 25 miles of their own county's centroid (great-circle
distance between county centroids, computed from the repo's county GeoJSON).

Both pool arms are redefined on the 25-mile aggregate (per user decision
2026-07-19):
  no access  : zero cardiologists across the 25-mile neighborhood in 2023
  declining  : falling per-capita rate of the aggregated workforce
               (aggregate counts / aggregate population, 2010-2023; same
               OLS + mean-count>=3 gate as the county rule, small-neighborhood
               fallback = last rate < first rate)

Outputs (outputs/master/)
  workforce_distance_county_access.csv    per-county neighbor count + aggregate access stats
  workforce_distance_pools.csv            pool stats vs the county-line pool
  workforce_distance_comparison.csv       matrix comparison vs baseline
  workforce_distance_INVEST_top.csv / workforce_distance_DEPLOY_top.csv, workforce_distance_state_shift.csv
"""
import os
import json
import numpy as np
import pandas as pd

from build_master import (load_master, matrix_boxes, compare_runs,
                              state_mix, tidy, OUT_DIR, PROJECT_DIR)

GEOJSON = os.path.join(PROJECT_DIR, "geojson-counties-fips.json")
PANEL   = os.path.join(PROJECT_DIR, "outputs", "ahrf_card_dis_panel_2010_2023.csv")
RADIUS_MILES = 25.0
MIN_COUNT, MIN_YEARS = 3, 3
TOP_N = 10
ACCESS_FILE = os.path.join(OUT_DIR, "workforce_distance_county_access.csv")


def ring_centroid(ring):
    """Shoelace centroid of one polygon ring [[lon, lat], ...]."""
    a = np.asarray(ring, dtype=float)
    x, y = a[:, 0], a[:, 1]
    cross = x[:-1] * y[1:] - x[1:] * y[:-1]
    area = cross.sum() / 2.0
    if abs(area) < 1e-12:
        return float(x.mean()), float(y.mean())
    cx = ((x[:-1] + x[1:]) * cross).sum() / (6 * area)
    cy = ((y[:-1] + y[1:]) * cross).sum() / (6 * area)
    return float(cx), float(cy)


def county_centroids():
    with open(GEOJSON) as f:
        gj = json.load(f)
    recs = []
    for feat in gj["features"]:
        fips = str(feat["id"]).zfill(5)
        geom = feat["geometry"]
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        # use the largest ring (mainland part) of the largest polygon
        best, best_n = None, -1
        for poly in polys:
            ring = poly[0]
            if len(ring) > best_n:
                best, best_n = ring, len(ring)
        lon, lat = ring_centroid(best)
        recs.append({"fips_st_cnty": fips, "lon": lon, "lat": lat})
    return pd.DataFrame(recs)


def haversine_matrix(lat, lon):
    """Pairwise great-circle distance in miles (vectorized)."""
    R = 3958.7613
    la = np.radians(lat)[:, None]
    lo = np.radians(lon)[:, None]
    dla = la - la.T
    dlo = lo - lo.T
    h = np.sin(dla / 2) ** 2 + np.cos(la) * np.cos(la.T) * np.sin(dlo / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def build_access():
    cent = county_centroids()
    panel = pd.read_csv(PANEL, dtype={"fips_st_cnty": str})
    panel["fips_st_cnty"] = panel["fips_st_cnty"].str.zfill(5)
    years = sorted(panel["year"].unique())

    counts = panel.pivot_table(index="fips_st_cnty", columns="year",
                               values="md_nf_card_dis", aggfunc="first")
    pops = panel.pivot_table(index="fips_st_cnty", columns="year",
                             values="county_pop_year", aggfunc="first")
    fips = counts.index.to_numpy()
    cent = cent.set_index("fips_st_cnty").reindex(fips)
    have_xy = cent["lat"].notna().to_numpy()
    print(f"counties in panel: {len(fips):,}; with centroid: {have_xy.sum():,}")

    D = haversine_matrix(cent["lat"].fillna(9999).to_numpy(),
                         cent["lon"].fillna(9999).to_numpy())
    A = D <= RADIUS_MILES                     # adjacency incl. self
    np.fill_diagonal(A, True)                 # self always included
    A[~have_xy, :] = False                    # no centroid -> self only
    A[:, ~have_xy] = False
    A[np.arange(len(fips)), np.arange(len(fips))] = True

    C = counts.reindex(columns=years).to_numpy(dtype=float)
    Pn = pops.reindex(columns=years).to_numpy(dtype=float)
    A_f = A.astype(float)
    agg_c = A_f @ np.nan_to_num(C)
    agg_p = A_f @ np.nan_to_num(Pn)
    n_present = A_f @ (~np.isnan(C)).astype(float)
    agg_c[n_present == 0] = np.nan
    agg_p[agg_p <= 0] = np.nan
    rate = agg_c / agg_p * 1e5

    recs = []
    yr_arr = np.array(years, dtype=float)
    for i, f in enumerate(fips):
        c = agg_c[i]
        r = rate[i]
        ok = ~np.isnan(c)
        if not ok.any():
            continue
        mean_count = np.nanmean(c)
        count_last = c[ok][-1]
        okr = ~np.isnan(r)
        slope = np.nan
        if okr.sum() >= MIN_YEARS and mean_count >= MIN_COUNT:
            slope, _ = np.polyfit(yr_arr[okr], r[okr], 1)
        declining = ((not np.isnan(slope) and slope < 0) or
                     (mean_count < MIN_COUNT and okr.sum() >= 2
                      and r[okr][-1] < r[okr][0]))
        recs.append({
            "fips_st_cnty": f,
            "n_neighbors_25mi": int(A[i].sum()),
            "card_25mi_last": count_last,
            "rate_25mi_last": (round(r[okr][-1], 3) if okr.any() else np.nan),
            "slope_25mi_pc": (round(slope, 5) if not np.isnan(slope) else np.nan),
            "pool_zero_25mi": count_last == 0,
            "pool_declining_25mi": count_last > 0 and declining,
        })
    acc = pd.DataFrame(recs)
    acc["in_pool_25mi"] = acc["pool_zero_25mi"] | acc["pool_declining_25mi"]
    return acc


def main():
    tracts, anchors = load_master()
    base = tracts.dropna(subset=["burden_z", "ddi"]).copy()
    P_ref = tracts[tracts["in_pool"]]
    inv_ref, dep_ref = matrix_boxes(P_ref, "ddi", anchors["nat_med_ddi"])
    card_pool = set(tracts.loc[tracts["in_pool"], "fips_county"])

    if os.path.exists(ACCESS_FILE):
        acc = pd.read_csv(ACCESS_FILE, dtype={"fips_st_cnty": str})
        print(f"loaded cached access table: {ACCESS_FILE}")
    else:
        acc = build_access()
        acc.to_csv(ACCESS_FILE, index=False)
        print(f"built access table -> {ACCESS_FILE}")

    pool_set = set(acc.loc[acc["in_pool_25mi"], "fips_st_cnty"])
    print("=" * 78)
    print(f"25-mile cross-county access (centroid distance <= {RADIUS_MILES:.0f} mi)")
    print("=" * 78)
    print(f"median neighbors per county: {acc['n_neighbors_25mi'].median():.0f}")
    n_zero = int(acc["pool_zero_25mi"].sum())
    n_dec = int(acc["pool_declining_25mi"].sum())
    jac = len(pool_set & card_pool) / len(pool_set | card_pool)
    print(f"pool: {len(pool_set):,} counties (zero-access {n_zero:,}, "
          f"declining {n_dec:,}); county-line pool {len(card_pool):,}; jaccard {jac:.2f}")

    # who leaves the pool once neighbors count
    left = tracts[tracts["in_pool"] & ~tracts["fips_county"].isin(pool_set)]
    joined = tracts[~tracts["in_pool"] & tracts["fips_county"].isin(pool_set)]
    print(f"tracts leaving the high-need pool: {left['fips_tract'].nunique():,}; "
          f"joining: {joined['fips_tract'].nunique():,}")

    Pw = tracts[tracts["fips_county"].isin(pool_set)]
    inv_w, dep_w = matrix_boxes(Pw, "ddi", anchors["nat_med_ddi"])
    cmp_ = compare_runs(base, inv_ref, dep_ref, inv_w, dep_w)
    print(f"INVEST {len(inv_w):,} DEPLOY {len(dep_w):,} | "
          f"baseline INVEST retained {cmp_['invest_retained_pct']}% "
          f"DEPLOY retained {cmp_['deploy_retained_pct']}% | "
          f"top10 overlap INV {cmp_['inv_top10_overlap']}/10 "
          f"DEP {cmp_['dep_top10_overlap']}/10")

    pd.DataFrame([{
        "radius_miles": RADIUS_MILES, "n_counties_pool_25mi": len(pool_set),
        "n_zero_access": n_zero, "n_declining": n_dec,
        "n_counties_pool_countyline": len(card_pool),
        "jaccard": round(jac, 3),
        "n_tracts_leaving_pool": int(left["fips_tract"].nunique()),
        "n_tracts_joining_pool": int(joined["fips_tract"].nunique()),
    }]).to_csv(os.path.join(OUT_DIR, "workforce_distance_pools.csv"), index=False)
    pd.DataFrame([cmp_]).to_csv(os.path.join(OUT_DIR, "workforce_distance_comparison.csv"), index=False)
    tidy(inv_w).head(TOP_N).to_csv(os.path.join(OUT_DIR, "workforce_distance_INVEST_top.csv"), index=False)
    tidy(dep_w).head(TOP_N).to_csv(os.path.join(OUT_DIR, "workforce_distance_DEPLOY_top.csv"), index=False)
    mixes = []
    for lab, box in [("25mi_INVEST", inv_w), ("25mi_DEPLOY", dep_w)]:
        mixes.append(state_mix(box).head(8).rename_axis("state")
                     .reset_index().assign(run=lab))
    pd.concat(mixes, ignore_index=True).to_csv(
        os.path.join(OUT_DIR, "workforce_distance_state_shift.csv"), index=False)
    print(f"\nwritten -> {OUT_DIR}/workforce_distance_*")


if __name__ == "__main__":
    main()
