"""
fetch_burden.py
========================
Processes CDC PLACES health data into a tidy CV burden panel and computes
per-geography burden trend summaries. Geography is **census tract** by
preference; falls back to county if no tract file is found.

Auto-detection
--------------
For each .csv in `CDC Places/`, the script inspects LocationID width:
   5  → county-level file
   11 → tract-level file

If at least one tract file is present, the script ignores county files for the
primary outputs (and writes a county rollup derived from the tract data, so
downstream scripts can still operate on counties when needed).

Inputs (any in CDC Places/)
---------------------------
PLACES__Local_Data_for_Better_Health,_County_Data_*.csv         (legacy)
PLACES__Local_Data_for_Better_Health,_Census_Tract_Data_*.csv   (preferred)

Outputs (when tract data is available)
--------------------------------------
outputs/cdc_places_cv_tract_long.csv
    Long-format: one row per (fips_tract, year, measure_id).
outputs/cdc_places_cv_tract_wide.csv
    Wide-format: one row per tract; columns = {measure_label}_{year}
    plus year-over-year deltas.
outputs/cdc_places_burden_trend_tract_summary.csv
    Tract-level burden trend summary using composite z-score.
outputs/cdc_places_cv_county_long.csv
    County rollup of tract data (mean prevalence within each county).
outputs/cdc_places_burden_trend_county_summary.csv
    County rollup of tract burden trend (mean of tract z-scores).

Outputs (county-only fallback)
------------------------------
Same as before with county-level files.

Cardiovascular Measures Extracted
----------------------------------
Clinical: HIGHCHOL, BPHIGH, CHD, DIABETES, OBESITY, STROKE
Behavioural: CSMOKING, LPA, SLEEP, BINGE
"""

import os
import glob
import pandas as pd
import numpy as np

# pyarrow is used for fast streaming of very large CSVs (the tract-level
# PLACES file is ~14M rows / 868 MB). Fallback to pandas if unavailable.
try:
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.compute as pc
    _HAS_PYARROW = True
except ImportError:
    _HAS_PYARROW = False


# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_DIR  = os.path.join(PROJECT_DIR, "CDC Places")
OUTPUT_DIR  = os.path.join(PROJECT_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Geographic-level constants
COUNTY_FIPS_LEN = 5
TRACT_FIPS_LEN  = 11

# =============================================================================
# CV MEASURES OF INTEREST
# =============================================================================

CV_MEASURES = {
    # ── Primary cardiovascular outcomes ──────────────────────────────────────
    "HIGHCHOL": "high_cholesterol",
    "BPHIGH":   "hypertension",
    "CHD":      "coronary_heart_disease",
    "DIABETES": "diabetes",
    "OBESITY":  "obesity",
    "STROKE":   "stroke",
    # ── Behavioural risk factors ─────────────────────────────────────────────
    "CSMOKING": "smoking",
    "LPA":      "physical_inactivity",
    "SLEEP":    "short_sleep",
    "BINGE":    "binge_drinking",
}

# Value-type filter. PLACES has a short-code column and a full-text column.
# We filter on the short-code column (more stable across releases).
PREFERRED_VALUE_TYPE = "AgeAdjPrv"   # age-adjusted prevalence
FALLBACK_VALUE_TYPE  = "CrdPrv"      # crude prevalence


# =============================================================================
# FILE DISCOVERY + LEVEL DETECTION
# =============================================================================

def detect_level(file_path: str) -> str | None:
    """
    Peek at the first data row of a PLACES CSV to determine geographic level.

    LocationID is the FIPS code:
      county-level files: 4-5 digit integer (5-digit FIPS, often loaded as int
                          which strips leading zeros)
      tract-level files : 10-11 digit integer (11-digit tract FIPS)
    Returns 'tract', 'county', or None if undetermined.
    """
    try:
        peek = pd.read_csv(file_path, nrows=20, low_memory=False)
    except Exception as e:
        print(f"  [warn] Could not peek into {os.path.basename(file_path)}: {e}")
        return None
    peek.columns = [c.strip('"').strip().lower() for c in peek.columns]
    if "locationid" not in peek.columns:
        return None
    # Coerce to numeric and check magnitude.
    # County FIPS max is 56045 (Wyoming) → at most 5 digits, < 100_000.
    # Tract FIPS has 11 digits (zero-padded), but parsed as int can be as
    # low as ~1.0e9 (Alabama tract 01001020100 → 1,001,020,100) and as high
    # as ~78e9 (Puerto Rico). Anything > 1e6 is unambiguously a tract.
    nums = pd.to_numeric(peek["locationid"], errors="coerce").dropna()
    if nums.empty:
        return None
    max_val = int(nums.max())
    if max_val > 1_000_000:
        return "tract"
    if max_val < 100_000:
        return "county"
    return None


def discover_places_files(places_dir: str) -> dict[str, list[str]]:
    """Find all PLACES CSVs and bucket by geographic level."""
    pattern = os.path.join(places_dir, "*.csv")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No CSV files in {places_dir}. Download from data.cdc.gov and "
            "place the file(s) there."
        )

    buckets: dict[str, list[str]] = {"tract": [], "county": [], "unknown": []}
    print(f"  Found {len(files)} PLACES file(s):")
    for f in files:
        lvl = detect_level(f)
        bucket = lvl if lvl in ("tract", "county") else "unknown"
        buckets[bucket].append(f)
        print(f"    [{bucket:>7}] {os.path.basename(f)}")
    return buckets


# =============================================================================
# LOAD + FILTER
# =============================================================================

def _find_actual_cols(file_path: str) -> dict[str, str]:
    """Inspect the CSV header to map our canonical names to actual column names."""
    header = pd.read_csv(file_path, nrows=0, low_memory=False).columns
    norm = [c.strip('"').strip().lower() for c in header]
    aliases = {
        "year":       ["year", "releaseyear"],
        "fips":       ["locationid", "tractfips", "countyfips", "fips"],
        "locality":   ["locationname", "tractname", "countyname"],
        "state":      ["stateabbr", "state"],
        "measure_id": ["measureid"],
        "value_type": ["datavaluetypeid"],
        "value":      ["data_value", "datavalue"],
        "low_ci":     ["low_confidence_limit", "lowconfidencelimit"],
        "high_ci":    ["high_confidence_limit", "highconfidencelimit"],
        "pop":        ["totalpopulation", "population"],
    }
    out = {}
    lookup = dict(zip(norm, header))  # normalised → original
    for k, opts in aliases.items():
        for o in opts:
            if o in lookup:
                out[k] = lookup[o]
                break
    return out


def _decide_value_type(file_path: str, vt_col: str) -> str | None:
    """Probe the file to decide which value type to filter on."""
    probe = pd.read_csv(file_path, usecols=[vt_col], nrows=200_000)
    available = set(probe[vt_col].dropna().astype(str).str.strip().unique())
    if PREFERRED_VALUE_TYPE in available:
        return PREFERRED_VALUE_TYPE
    if FALLBACK_VALUE_TYPE in available:
        print(f"    [info] {PREFERRED_VALUE_TYPE} not present; using {FALLBACK_VALUE_TYPE} "
              f"(typical for tract-level data — only crude prevalence is published "
              f"at tract level)")
        return FALLBACK_VALUE_TYPE
    return None


def _read_filtered_pyarrow(file_path: str, col_map: dict,
                            keep_vt: str | None) -> pd.DataFrame:
    """Fast path: read with pyarrow, filter, return pandas DataFrame."""
    usecols = [v for v in col_map.values() if v is not None]
    # Read with all columns as strings to avoid type-inference cost; we cast
    # downstream where needed.
    convert_opts = pacsv.ConvertOptions(
        include_columns=usecols,
        column_types={c: pa.string() for c in usecols},
    )
    # Bigger blocksize → fewer chunks, faster but more memory. 64 MB is fine.
    read_opts = pacsv.ReadOptions(block_size=64 * 1024 * 1024)
    table = pacsv.read_csv(file_path,
                            read_options=read_opts,
                            convert_options=convert_opts)
    print(f"    pyarrow read: {table.num_rows:,} rows")
    # Filter to CV measures
    mid_col = col_map["measure_id"]
    mid_array = pc.is_in(table.column(mid_col),
                          value_set=pa.array(list(CV_MEASURES.keys())))
    mask = mid_array
    if keep_vt is not None:
        vt_col = col_map["value_type"]
        vt_match = pc.equal(pc.utf8_trim_whitespace(table.column(vt_col)), keep_vt)
        mask = pc.and_(mask, vt_match)
    table = table.filter(mask)
    print(f"    after filters: {table.num_rows:,} rows")
    return table.to_pandas()


def _read_filtered_pandas(file_path: str, col_map: dict,
                           keep_vt: str | None) -> pd.DataFrame:
    """Slow fallback path: pandas streaming with chunks."""
    usecols = [v for v in col_map.values() if v is not None]
    vt_col  = col_map["value_type"]
    mid_col = col_map["measure_id"]
    chunks, n_read, n_kept = [], 0, 0
    for chunk in pd.read_csv(file_path, usecols=usecols, chunksize=500_000,
                              low_memory=False):
        n_read += len(chunk)
        mask = chunk[mid_col].isin(CV_MEASURES.keys())
        if keep_vt is not None:
            mask &= chunk[vt_col].astype(str).str.strip() == keep_vt
        sub = chunk.loc[mask]
        if not sub.empty:
            chunks.append(sub)
            n_kept += len(sub)
    print(f"    pandas stream: {n_read:,} rows; kept {n_kept:,}")
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def load_and_filter_places(file_path: str, level: str) -> pd.DataFrame:
    """
    Read a PLACES CSV (uses pyarrow when available for large files), filter to
    CV measures + preferred value-type, and return a tidy long-format DataFrame.
    """
    print(f"\n  Loading [{level}]: {os.path.basename(file_path)}")
    col_map = _find_actual_cols(file_path)
    missing = [k for k in ("year", "fips", "measure_id", "value_type", "value")
               if k not in col_map]
    if missing:
        raise ValueError(f"Missing essential columns in {file_path}: {missing}")
    expected_fips_len = TRACT_FIPS_LEN if level == "tract" else COUNTY_FIPS_LEN

    print("    Probing value-type availability...")
    vt_col  = col_map["value_type"]
    mid_col = col_map["measure_id"]
    keep_vt = _decide_value_type(file_path, vt_col)
    if keep_vt:
        print(f"    Filtering to value_type = {keep_vt}")

    if _HAS_PYARROW:
        df_cv = _read_filtered_pyarrow(file_path, col_map, keep_vt)
    else:
        print("    pyarrow not installed; using slower pandas stream")
        df_cv = _read_filtered_pandas(file_path, col_map, keep_vt)
    if df_cv.empty:
        return pd.DataFrame()

    # Drop rows missing the value
    val = col_map["value"]
    before = len(df_cv)
    df_cv = df_cv.dropna(subset=[val])
    if before - len(df_cv) > 0:
        print(f"    Dropped {before - len(df_cv):,} rows with missing values")

    # Clean FIPS to canonical zero-padded form
    fips_clean = (df_cv[col_map["fips"]].astype(str)
                  .str.replace(r"\D", "", regex=True)
                  .str.zfill(expected_fips_len))

    tidy = pd.DataFrame({
        "year":          df_cv[col_map["year"]],
        "fips":          fips_clean,
        "fips_county":   fips_clean.str[:COUNTY_FIPS_LEN],
        "locality_name": df_cv[col_map["locality"]] if "locality" in col_map else np.nan,
        "state_abbr":    df_cv[col_map["state"]]    if "state"    in col_map else np.nan,
        "measure_id":    df_cv[mid_col],
        "measure_label": df_cv[mid_col].map(CV_MEASURES),
        "prevalence":    pd.to_numeric(df_cv[val], errors="coerce"),
        "value_type":    df_cv[vt_col],
        "low_ci":        pd.to_numeric(df_cv[col_map["low_ci"]],  errors="coerce") if "low_ci" in col_map else np.nan,
        "high_ci":       pd.to_numeric(df_cv[col_map["high_ci"]], errors="coerce") if "high_ci" in col_map else np.nan,
        "population":    pd.to_numeric(df_cv[col_map["pop"]],     errors="coerce") if "pop" in col_map else np.nan,
    })
    tidy["geo_level"] = level
    return tidy.reset_index(drop=True)


def build_long_format(files: list[str], level: str) -> pd.DataFrame:
    """Stack all files of a given level and de-dup (fips, year, measure)."""
    frames = []
    for f in files:
        try:
            frames.append(load_and_filter_places(f, level))
        except Exception as e:
            print(f"  [ERROR] Skipping {os.path.basename(f)}: {e}")

    long_df = pd.concat(frames, ignore_index=True)
    long_df = long_df.drop_duplicates(
        subset=["fips", "year", "measure_id"], keep="last"
    )
    print(f"\n  Combined long table [{level}]: {len(long_df):,} rows | "
          f"{long_df['fips'].nunique():,} {level}s | "
          f"years: {sorted(long_df['year'].unique())}")
    return long_df


# =============================================================================
# WIDE FORMAT + TRENDS
# =============================================================================

def build_wide_format(long_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot long → wide; one row per locality; year-over-year deltas added."""
    wide = long_df.pivot_table(
        index   = ["fips", "fips_county", "locality_name", "state_abbr"],
        columns = ["measure_label", "year"],
        values  = "prevalence",
        aggfunc = "mean",
    )
    wide.columns = [f"{m}_{y}" for m, y in wide.columns]
    wide = wide.reset_index()

    years = sorted(long_df["year"].unique())
    for label in CV_MEASURES.values():
        year_cols = [f"{label}_{y}" for y in years if f"{label}_{y}" in wide.columns]
        for i in range(1, len(year_cols)):
            ce, cl = year_cols[i-1], year_cols[i]
            ye = int(ce.split("_")[-1]); yl = int(cl.split("_")[-1])
            wide[f"{label}_delta_{ye}_{yl}"] = wide[cl] - wide[ce]
    return wide


def add_zscored_composite(long_df: pd.DataFrame) -> pd.DataFrame:
    """Add a per-year z-score column for each measure; then mean across measures."""
    out = long_df.copy()
    grp = out.groupby(["measure_id", "year"])["prevalence"]
    mu = grp.transform("mean")
    sd = grp.transform(lambda s: s.std(ddof=0))
    out["prevalence_z"] = np.where(sd > 0, (out["prevalence"] - mu) / sd, 0.0)
    return out


def composite_burden_trends(long_df: pd.DataFrame,
                            geo_key: str = "fips",
                            min_years: int = 2) -> pd.DataFrame:
    """
    Per-geography burden trend using z-scored composite. Vectorised.

    geo_key='fips' for tract-level / county-level direct;
    geo_key='fips_county' to roll tract-level up to county.
    """
    z = add_zscored_composite(long_df)

    # Composite per (geo, year): mean of measure z-scores
    composite = (
        z.groupby([geo_key, "year"], as_index=False)["prevalence_z"]
         .mean()
         .rename(columns={"prevalence_z": "composite_burden_z"})
    )

    # Wide format: rows = geos, columns = years, values = composite z
    wide = composite.pivot(index=geo_key, columns="year",
                           values="composite_burden_z")
    years = sorted(c for c in wide.columns if pd.notna(c))
    if not years:
        return pd.DataFrame()

    # Years present per geo
    n_years = wide.notna().sum(axis=1)

    # For each geo, compute OLS slope vectorised using closed-form:
    #   slope = cov(x, y) / var(x), where x is the year, y is composite
    # Handle the "different geos have different missing years" case by using
    # broadcast and masking.
    yrs_arr = np.array(years, dtype=float)               # shape (Y,)
    vals    = wide.reindex(columns=years).to_numpy(float)  # shape (N, Y)
    mask    = ~np.isnan(vals)                            # shape (N, Y)

    # Per-row x means/vars only over the non-missing years
    x_bcast = np.broadcast_to(yrs_arr, vals.shape)        # (N, Y)
    x_masked = np.where(mask, x_bcast, np.nan)
    y_masked = np.where(mask, vals,    np.nan)

    x_mean = np.nanmean(x_masked, axis=1, keepdims=True)
    y_mean = np.nanmean(y_masked, axis=1, keepdims=True)
    dx = x_masked - x_mean
    dy = y_masked - y_mean
    num = np.nansum(dx * dy, axis=1)
    den = np.nansum(dx * dx, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(den > 0, num / den, np.nan)

    # First / last observed values across the years sorted ascending
    # Use the chronologically-ordered year columns (already ascending in years)
    def _first(row):
        valid = np.where(~np.isnan(row))[0]
        return row[valid[0]] if valid.size else np.nan

    def _last(row):
        valid = np.where(~np.isnan(row))[0]
        return row[valid[-1]] if valid.size else np.nan

    y_first = np.apply_along_axis(_first, 1, vals)
    y_last  = np.apply_along_axis(_last,  1, vals)
    delta   = y_last - y_first

    trend = np.where(
        slope > 0, "increasing",
        np.where(slope < 0, "decreasing", "stable"))

    out = pd.DataFrame({
        geo_key:           wide.index.values,
        "burden_slope":    np.round(slope.astype(float),   4),
        "burden_z_first":  np.round(y_first.astype(float), 4),
        "burden_z_last":   np.round(y_last.astype(float),  4),
        "burden_z_delta":  np.round(delta.astype(float),   4),
        "burden_trend":    trend,
        "n_years_burden":  n_years.values.astype(int),
    })
    # Drop geos that didn't meet the minimum year threshold
    out = out[out["n_years_burden"] >= min_years].reset_index(drop=True)
    # Drop any rows where slope is NaN (e.g., a geo with all-equal years)
    out = out.dropna(subset=["burden_slope"]).reset_index(drop=True)
    return out


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 66)
    print("CDC PLACES Disease Burden Processing Pipeline (tract-preferred)")
    print("=" * 66)

    # ── 1. Discover and bucket files ─────────────────────────────────────────
    print("\n[1/4] Discovering PLACES files...")
    buckets = discover_places_files(PLACES_DIR)

    use_tract = len(buckets["tract"]) > 0
    if use_tract:
        print(f"\n  → Tract-level file present; using TRACT as primary.")
        primary_files, primary_level = buckets["tract"], "tract"
    elif buckets["county"]:
        print(f"\n  → No tract file found; using COUNTY level. "
              "(Drop a tract-level PLACES CSV in CDC Places/ to upgrade.)")
        primary_files, primary_level = buckets["county"], "county"
    else:
        raise RuntimeError("No usable PLACES files (need tract or county).")

    # ── 2. Build the long table ──────────────────────────────────────────────
    print(f"\n[2/4] Loading {primary_level}-level data...")
    long_df = build_long_format(primary_files, level=primary_level)

    # ── 3. Save long + wide outputs ──────────────────────────────────────────
    print(f"\n[3/4] Saving {primary_level}-level long/wide tables + trends...")
    suffix = primary_level

    long_path = os.path.join(OUTPUT_DIR, f"cdc_places_cv_{suffix}_long.csv")
    long_df.to_csv(long_path, index=False)
    print(f"  ✓ {long_path}  ({len(long_df):,} rows)")

    wide_df = build_wide_format(long_df)
    wide_path = os.path.join(OUTPUT_DIR, f"cdc_places_cv_{suffix}_wide.csv")
    wide_df.to_csv(wide_path, index=False)
    print(f"  ✓ {wide_path}  shape={wide_df.shape}")

    trends_df = composite_burden_trends(long_df, geo_key="fips")
    trends_path = os.path.join(
        OUTPUT_DIR, f"cdc_places_burden_trend_{suffix}_summary.csv")
    trends_df.to_csv(trends_path, index=False)
    print(f"  ✓ {trends_path}  ({len(trends_df):,} {suffix}s with trend)")
    print(f"    Burden trend distribution:")
    print(trends_df["burden_trend"].value_counts().to_string().replace("\n", "\n      "))

    # ── 4. If tract-level, also produce a county rollup for downstream use ───
    if use_tract:
        print("\n[4/4] Computing county rollup (mean of tract z-scores)...")
        # County-level long table: mean prevalence across tracts in each county
        county_long = (long_df
            .groupby(["fips_county", "state_abbr", "year",
                      "measure_id", "measure_label"], as_index=False)
            .agg(prevalence=("prevalence", "mean"),
                 n_tracts  =("fips",       "nunique"))
        )
        county_long = county_long.rename(columns={"fips_county": "fips"})
        county_long["fips_county"] = county_long["fips"]
        county_long["geo_level"]   = "county_from_tract"
        county_long_path = os.path.join(OUTPUT_DIR, "cdc_places_cv_county_long.csv")
        county_long.to_csv(county_long_path, index=False)
        print(f"  ✓ {county_long_path}  ({len(county_long):,} rows)")

        # County burden trend: roll tract z-scores up to county
        county_trends = composite_burden_trends(long_df, geo_key="fips_county")
        county_trends = county_trends.rename(columns={"fips_county": "fips"})
        county_trends_path = os.path.join(
            OUTPUT_DIR, "cdc_places_burden_trend_county_summary.csv")
        county_trends.to_csv(county_trends_path, index=False)
        print(f"  ✓ {county_trends_path}  ({len(county_trends):,} counties)")
    else:
        print("\n[4/4] No tract data — skipping county rollup.")

    # ── Quality summary ──────────────────────────────────────────────────────
    print("\n── Data Quality Summary ─────────────────────────────────────────")
    print(f"  Geographic level (primary):  {primary_level}")
    print(f"  Measures available:          {sorted(long_df['measure_id'].unique())}")
    print(f"  Years available:             {sorted(long_df['year'].unique())}")
    print(f"  Localities × measures × yrs: {len(long_df):,}")
    print(f"  Unique localities:           {long_df['fips'].nunique():,}")
    if use_tract:
        n_counties = long_df["fips_county"].nunique()
        avg_tracts = long_df["fips"].nunique() / n_counties
        print(f"  Counties represented:        {n_counties:,}  "
              f"(avg {avg_tracts:.1f} tracts/county)")
    print("─" * 66)


if __name__ == "__main__":
    main()
