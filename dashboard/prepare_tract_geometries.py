"""
prepare_tract_geometries.py
===========================
Splits a nationwide US census tract shapefile into per-county GeoJSON files
that the dashboard loads on demand when a user zooms into a county.

This is OPTIONAL – the dashboard works without it (it falls back to the
side-panel tract table). Run this once if you want tract POLYGONS visible
on the map when a user zooms in.

Input
-----
A single US census-tract shapefile (or GeoJSON) covering all states.
Recommended: the US Census Bureau's cartographic boundary file
(generalised, ~150 MB zipped):

  https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_tract_500k.zip

Unzip it, then point INPUT_PATH below at cb_2023_us_tract_500k.shp.

Output
------
dashboard/data/tracts/{fips_county}.geojson
  3,143 small GeoJSON files (~5-300 KB each), one per US county. The
  dashboard fetches the matching file when a user zooms into that county.

Usage
-----
  python prepare_tract_geometries.py path/to/cb_2023_us_tract_500k.shp
  python prepare_tract_geometries.py path/to/some_tract.geojson

  # Restrict output to the high-need county pool – far fewer/smaller files,
  # and still covers every deploy / invest / mixed county:
  python prepare_tract_geometries.py path/to/cb_2023_us_tract_500k.shp pool

  # Explicit full run (all US counties):
  python prepare_tract_geometries.py path/to/cb_2023_us_tract_500k.shp all
"""

import os
import sys
import json
import time
import geopandas as gpd


def pool_county_set():
    """FIPS of counties flagged v5_in_pool in county_data.json (if present)."""
    cd_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "county_data.json")
    if not os.path.exists(cd_path):
        return None
    with open(cd_path) as f:
        cd = json.load(f)
    pool = {fips for fips, rec in cd.items() if rec.get("v5_in_pool")}
    return pool or None

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH_DIR    = os.path.dirname(os.path.abspath(__file__))
OUT_DIR     = os.path.join(DASH_DIR, "data", "tracts")
os.makedirs(OUT_DIR, exist_ok=True)


def find_id_columns(gdf: gpd.GeoDataFrame) -> tuple[str, str]:
    """Identify the tract FIPS column and the county FIPS column."""
    cols_upper = {c.upper(): c for c in gdf.columns}
    tract_col = (cols_upper.get("GEOID") or cols_upper.get("GEOID20")
                 or cols_upper.get("GEOID10") or cols_upper.get("GEOIDFQ"))
    if not tract_col:
        raise ValueError(f"Could not find GEOID column. Saw: {list(gdf.columns)}")

    cty_col = (cols_upper.get("COUNTYFP") or cols_upper.get("COUNTYFP20")
               or cols_upper.get("COUNTY"))
    st_col  = (cols_upper.get("STATEFP")  or cols_upper.get("STATEFP20")
               or cols_upper.get("STATE"))
    return tract_col, st_col, cty_col


def main(in_path: str, scope: str = "pool"):
    print(f"[1/4] Loading {in_path}...")
    t0 = time.time()
    gdf = gpd.read_file(in_path)
    print(f"  rows: {len(gdf):,}   crs: {gdf.crs}")
    print(f"  load time: {time.time()-t0:.1f}s")

    tract_col, st_col, cty_col = find_id_columns(gdf)
    print(f"  GEOID column: {tract_col!r}   state: {st_col!r}   county: {cty_col!r}")

    # Reproject to WGS84 (the dashboard expects lon/lat)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        print("[2/4] Reprojecting to EPSG:4326 (WGS84)...")
        gdf = gdf.to_crs("EPSG:4326")

    # Standardise tract FIPS to 11-char string, derive 5-char county FIPS
    print("[3/4] Normalising FIPS and grouping by county...")
    gdf["fips_tract"] = gdf[tract_col].astype(str).str.zfill(11)
    if st_col and cty_col:
        gdf["fips_st_cnty"] = (gdf[st_col].astype(str).str.zfill(2)
                               + gdf[cty_col].astype(str).str.zfill(3))
    else:
        gdf["fips_st_cnty"] = gdf["fips_tract"].str[:5]

    # Filter to CONUS + AK + HI + DC; drop territories if not desired
    drop_states = set()   # e.g., {"60", "66", "69", "72", "78"} to drop territories
    if drop_states:
        before = len(gdf)
        gdf = gdf[~gdf["fips_st_cnty"].str[:2].isin(drop_states)]
        print(f"  dropped {before - len(gdf):,} rows in territories")

    # Optionally restrict to the high-need county pool to keep output lean.
    if scope == "pool":
        pool = pool_county_set()
        if pool:
            before = len(gdf)
            gdf = gdf[gdf["fips_st_cnty"].isin(pool)]
            print(f"  scope=pool: kept {len(gdf):,}/{before:,} tracts "
                  f"across {gdf['fips_st_cnty'].nunique():,} high-need counties")
        else:
            print("  scope=pool requested but county_data.json/pool not found; "
                  "writing ALL counties instead")
    else:
        print(f"  scope=all: writing every county ({gdf['fips_st_cnty'].nunique():,})")

    # Simplify the geometry slightly to reduce file size while preserving shape.
    # Tolerance is in degrees (~ 0.0005 ≈ 50 m). Tune as needed.
    print("[4/4] Simplifying geometries and writing per-county files...")
    gdf["geometry"] = gdf["geometry"].simplify(0.0005, preserve_topology=True)

    # Group and write
    n_written, n_features = 0, 0
    by_county = gdf.groupby("fips_st_cnty", sort=False)
    total_groups = len(by_county)
    for i, (fips, sub) in enumerate(by_county, start=1):
        # Build feature collection
        features = []
        for _, row in sub.iterrows():
            features.append({
                "type": "Feature",
                "id":   row["fips_tract"],
                "properties": {
                    "fips_tract":   row["fips_tract"],
                    "fips_st_cnty": row["fips_st_cnty"],
                },
                "geometry": row["geometry"].__geo_interface__,
            })
        fc = {"type": "FeatureCollection", "features": features}
        out_path = os.path.join(OUT_DIR, f"{fips}.geojson")
        with open(out_path, "w") as f:
            json.dump(fc, f, separators=(",", ":"))
        n_written += 1
        n_features += len(features)
        if i % 250 == 0 or i == total_groups:
            print(f"  ...{i:,}/{total_groups:,} counties  "
                  f"({n_features:,} tracts written so far)")

    total_mb = sum(os.path.getsize(os.path.join(OUT_DIR, f))
                   for f in os.listdir(OUT_DIR)) / 1024 / 1024
    print(f"\n✓ Wrote {n_written:,} county tract files to {OUT_DIR}")
    print(f"  Total: {n_features:,} tract features, {total_mb:.1f} MB on disk")
    print(f"  (Files are loaded on demand by the dashboard, so disk size "
          f"only matters for hosting.)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prepare_tract_geometries.py <path/to/tract_shapefile_or_geojson> [pool|all]")
        print("\nDownload the US tract cartographic boundary file from:")
        print("  https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_tract_500k.zip")
        print("Unzip and point at cb_2023_us_tract_500k.shp")
        print("\nSecond arg (optional): 'pool' (default, high-need counties only) or 'all'.")
        sys.exit(1)
    scope = sys.argv[2].lower() if len(sys.argv) > 2 else "pool"
    if scope not in ("pool", "all"):
        print(f"Unknown scope {scope!r}; use 'pool' or 'all'."); sys.exit(1)
    main(sys.argv[1], scope)
