"""
fetch_workforce.py
============================
Extracts adult cardiology (Cardiovascular Disease, AMA specialty) workforce
data from the Area Health Resources File (AHRF) across seven calendar years
and produces a county × year analytic panel for the publication.

Years and sources
-----------------
  2010, 2015, 2019  →  ASCII fixed-width file from the 2020-2021 release
                       (AHRF/AHRF_2020-2021/DATA/ahrf2021.asc)
                       Field positions parsed from AHRF2020-2021.sas.
  2020, 2021        →  CSV from the 2022-2023 release
                       (AHRF/AHRF_CSV_2022-2023.zip → ahrf2023HP.csv)
  2022              →  CSV from the 2023-2024 release
                       (AHRF/AHRF 2023-2024 CSV/CSV Files by Categories/ahrf2024hp.csv)
  2023              →  CSV from the 2024-2025 release
                       (AHRF/NCHWA-2024-2025+AHRF+COUNTY+CSV/AHRF2025hp.csv)

When years overlap across releases, the MOST RECENT release is preferred for
that year (it includes late-reported corrections).

Cardiology proxy
----------------
We use AHRF "Cardiovascular Disease" (AMA specialty) non-federal MDs:
    ASCII:  F04631-{yy}        (Cardiovas Dis, Total)
    CSV  :  md_nf_card_dis_{yy} (same specialty)

This is the standard county-level proxy for adult cardiologists. We do NOT
use the smaller "Vascular Medicine" subspecialty (md_nf_vasc_med, ~40 MDs
nationally), nor "Pediatric Cardiology" (md_nf_ped_card).

Outputs
-------
outputs/ahrf_card_dis_panel_2010_2023.csv
    Long-format table with one row per county × year. Columns:
      fips_st_cnty, year,
      md_nf_card_dis                      total cardiology MDs (non-federal)
      card_lt35, card_35_44, card_45_54,  age-band counts
        card_55_64, card_65_74, card_ge75
      workforce_aging_share_ge55          share of age-known workforce aged >=55
      county_pop_year                     year-matched county population
      county_pop_cens2020                 Census 2020 population (anchor)
      card_per_100k_year                  per-100k using year-matched pop
      card_per_100k_cens2020              per-100k using Census 2020 anchor

outputs/ahrf_workforce_trend_summary.csv
    Wide-format table with one row per county. Columns:
      fips_st_cnty, n_years_available, mean_card_dis, mean_aging_share,
      first_year, last_year, card_first, card_last,
      workforce_slope, workforce_pct_chg, workforce_trend

Trend classification
--------------------
A county is classified only if mean_card_dis >= MIN_COUNT_FOR_TREND (default 3)
across observed panel years. Otherwise: workforce_trend = "insufficient_data".

For qualifying counties (using OLS slope of count vs year):
  slope >  0  →  "growing"
  slope <  0  →  "declining"
  slope == 0  →  "stagnant"

Dependencies: pandas, numpy
Install:  pip install pandas numpy openpyxl
"""

from __future__ import annotations
import os
import re
import zipfile
from io import StringIO

import numpy as np
import pandas as pd


# =============================================================================
# CONFIGURATION
# =============================================================================

# Project root (folder containing this script and the AHRF/ subdirectory)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AHRF_DIR    = os.path.join(PROJECT_DIR, "AHRF")
OUTPUT_DIR  = os.path.join(PROJECT_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Historical ASCII source (one file covers years 2010, 2015, 2019) ─────────
ASCII_PATH = os.path.join(AHRF_DIR, "AHRF_2020-2021", "DATA", "ahrf2021.asc")
SAS_PATH   = os.path.join(AHRF_DIR, "AHRF_2020-2021", "DOC", "AHRF2020-2021.sas")

# ── Recent CSV sources (2020-2023) ───────────────────────────────────────────
CSV_2022_2023_ZIP = os.path.join(AHRF_DIR, "AHRF_CSV_2022-2023.zip")
CSV_2023_2024     = os.path.join(AHRF_DIR, "AHRF 2023-2024 CSV",
                                 "CSV Files by Categories", "ahrf2024hp.csv")
CSV_2024_2025     = os.path.join(AHRF_DIR, "NCHWA-2024-2025+AHRF+COUNTY+CSV",
                                 "AHRF2025hp.csv")

# POP CSVs (population fields live in separate POP files, not HP files)
POP_2023_2024     = os.path.join(AHRF_DIR, "AHRF 2023-2024 CSV",
                                 "CSV Files by Categories", "ahrf2024pop.csv")
POP_2024_2025     = os.path.join(AHRF_DIR, "NCHWA-2024-2025+AHRF+COUNTY+CSV",
                                 "AHRF2025pop.csv")

# ── Trend-classification rules ───────────────────────────────────────────────
MIN_COUNT_FOR_TREND = 3   # mean cardiologists/year required to assign a label
MIN_YEARS_FOR_TREND = 3   # need at least this many panel years for a slope

# ── ASCII field codes we want (canonical → AMA specialty / position label) ──
# ASCII field naming: f<6-digit-id><2-digit-year>
# Year suffixes 10, 15, 19 correspond to calendar years 2010, 2015, 2019.
ASCII_BASE_CODES = {
    # canonical name           ASCII base id   description (from SAS dictionary)
    "md_nf_card_dis":          "f04631",   # Cardiovas Dis, Total
    "card_admin":              "f09977",   # Cardiovas Dis, Administration
    "card_teach":              "f09978",   # Cardiovas Dis, Teaching
    "card_resrch":             "f11086",   # Cardiovas Dis, Research
    "card_oth":                "f09980",   # Cardiovas Dis, Other
    "card_all_pc":             "f11084",   # Cardiovas Dis, Total Patient Care
    "card_pc_ofc":             "f04633",   # Cardiovas Dis, PC, Office Based
    "card_pc_rsdnt":           "f12505",   # Cardiovas Dis, PC, Hospital Resident
    "card_pc_hosp_ft":         "f04635",   # Cardiovas Dis, PC, Hospital FT Staff
    "card_lt35":               "f04928",   # Cardiovascular Diseases, < 35
    "card_35_44":              "f04929",   # Cardiovascular Diseases, 35-44
    "card_45_54":              "f04930",   # Cardiovascular Diseases, 45-54
    "card_55_64":              "f04931",   # Cardiovascular Diseases, 55-64
    "card_65_74":              "f12038",   # Cardiovascular Diseases, 65-74
    "card_ge75":               "f12039",   # Cardiovascular Diseases, 75+
}
# Year-matched population from ASCII:
#   2010 → Census 2010 (f0453010, no estimate exists for 2010)
#   2015 → Population Estimate 2015 (f1198415)
#   2019 → Population Estimate 2019 (f1198419)
ASCII_POP_BY_YEAR = {
    "10": "f0453010",   # Census 2010 (also our 2010-anchor for ASCII years)
    "15": "f1198415",
    "19": "f1198419",
}

# FIPS layout in the ASCII file: position 2-6 (1-indexed), 5 chars.
# (The file has one leading whitespace byte before each record.)
ASCII_FIPS_COLSPEC = (1, 6)

# Age columns used for the aging-share denominator
AGE_COLS = ["card_lt35", "card_35_44", "card_45_54",
            "card_55_64", "card_65_74", "card_ge75"]
OLDER_COLS = ["card_55_64", "card_65_74", "card_ge75"]


# =============================================================================
# SAS DICTIONARY PARSER (for historical ASCII file)
# =============================================================================

# Matches lines like:   @01930    f0463119    03.  /* description */
_SAS_PAT = re.compile(
    r"@\s*(\d+)\s+(\w+)\s+\$?(\d+)\.?\s*(?:/\*(.*?)\*/)?"
)

def parse_sas_dictionary(sas_path: str) -> pd.DataFrame:
    """Parse an AHRF SAS dictionary into a DataFrame of (pos, name, width, desc)."""
    rows = []
    with open(sas_path, "r", encoding="latin-1") as f:
        for line in f:
            m = _SAS_PAT.search(line)
            if m:
                pos, name, width, desc = m.groups()
                rows.append({
                    "pos":   int(pos),          # 1-indexed start position (SAS)
                    "name":  name.lower(),
                    "width": int(width),
                    "desc":  (desc or "").strip(),
                })
    return pd.DataFrame(rows)


def build_ascii_spec(sas_df: pd.DataFrame,
                     wanted_fields: dict[str, str]) -> tuple[list, list]:
    """
    Build a (colspecs, names) spec for pd.read_fwf to pull cardiology +
    year-matched population fields from the AHRF ASCII file.

    Output names follow the convention "<canonical>__<yy>" so the
    long-form reshape downstream is mechanical.
    """
    name_to_row = {r["name"]: r for _, r in sas_df.iterrows()}

    colspecs  = [ASCII_FIPS_COLSPEC]
    out_names = ["fips_st_cnty"]

    def add_field(field_id: str, out_name: str):
        if field_id not in name_to_row:
            print(f"  [warn] ASCII field {field_id} not in SAS dictionary")
            return
        r = name_to_row[field_id]
        start = r["pos"] - 1                # SAS 1-indexed → Python 0-indexed
        end   = start + r["width"]
        colspecs.append((start, end))
        out_names.append(out_name)

    # Cardiology workforce fields × 3 historical years
    for canonical, base in wanted_fields.items():
        for yy in ("10", "15", "19"):
            add_field(f"{base}{yy}", f"{canonical}__{yy}")

    # Year-matched population (Census 2010 for 2010, estimates for 2015/2019)
    for yy, field_id in ASCII_POP_BY_YEAR.items():
        add_field(field_id, f"county_pop_year__{yy}")

    return colspecs, out_names


def load_ascii_panel(asc_path: str, sas_path: str) -> pd.DataFrame:
    """Read selected fields from the AHRF ASCII file and reshape to long format."""
    print(f"  Parsing SAS dictionary: {os.path.basename(sas_path)}")
    sas_df = parse_sas_dictionary(sas_path)
    print(f"    {len(sas_df)} fields catalogued")

    colspecs, out_names = build_ascii_spec(sas_df, ASCII_BASE_CODES)
    print(f"  Reading ASCII file:    {os.path.basename(asc_path)}")
    print(f"    Columns to extract: {len(colspecs)}")

    df = pd.read_fwf(
        asc_path,
        colspecs=colspecs,
        names=out_names,
        dtype=str,
        encoding="latin-1",
        header=None,
    )
    print(f"    Rows read: {len(df):,}")

    # Normalise FIPS to 5-char zero-padded string
    df["fips_st_cnty"] = df["fips_st_cnty"].astype(str).str.strip().str.zfill(5)

    frames = []
    for yr, yy in [(2010, "10"), (2015, "15"), (2019, "19")]:
        cols_this_year = [c for c in df.columns if c.endswith(f"__{yy}")]
        if not cols_this_year:
            continue
        sub = df[["fips_st_cnty"] + cols_this_year].copy()
        sub = sub.rename(columns={c: c.replace(f"__{yy}", "") for c in cols_this_year})
        for c in sub.columns:
            if c != "fips_st_cnty":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub["year"] = yr
        frames.append(sub)

    long_df = pd.concat(frames, ignore_index=True)
    print(f"    ASCII long-form rows: {len(long_df):,}  "
          f"({long_df['year'].nunique()} years × {long_df['fips_st_cnty'].nunique():,} counties)")
    return long_df


# =============================================================================
# CSV LOADERS (2020-2023)
# =============================================================================

def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip('"').strip() for c in df.columns]
    return df


def _load_csv_hp(path_or_zip: str,
                 inner_csv: str | None = None) -> pd.DataFrame:
    """Load an HP CSV (optionally from inside a zip)."""
    if path_or_zip.lower().endswith(".zip"):
        with zipfile.ZipFile(path_or_zip) as z:
            name = inner_csv or next(
                n for n in z.namelist()
                if "HP" in n.upper() and n.endswith(".csv")
            )
            with z.open(name) as f:
                df = pd.read_csv(f, low_memory=False)
    else:
        df = pd.read_csv(path_or_zip, low_memory=False)
    return _clean_cols(df)


def _csv_col_map(year_2digit: str) -> dict[str, str]:
    """
    Map canonical names → AHRF HP-CSV column names for one year.
    (Population columns live in the POP CSV, loaded separately.)
    """
    y = year_2digit
    return {
        "md_nf_card_dis":  f"md_nf_card_dis_{y}",
        "card_admin":      f"md_nf_card_dis_admin_{y}",
        "card_teach":      f"md_nf_card_dis_teach_{y}",
        "card_resrch":     f"md_nf_card_dis_resrch_{y}",
        "card_oth":        f"md_nf_card_dis_oth_{y}",
        "card_all_pc":     f"md_nf_card_dis_all_pc_{y}",
        "card_pc_ofc":     f"md_nf_card_dis_pc_ofc_{y}",
        "card_pc_rsdnt":   f"md_nf_card_dis_pc_rsdnt_{y}",
        "card_pc_hosp_ft": f"md_nf_card_dis_pc_hosp_ft_{y}",
        "card_lt35":       f"md_nf_card_dis_lt35_{y}",
        "card_35_44":      f"md_nf_card_dis_35_44_{y}",
        "card_45_54":      f"md_nf_card_dis_45_54_{y}",
        "card_55_64":      f"md_nf_card_dis_55_64_{y}",
        "card_65_74":      f"md_nf_card_dis_65_74_{y}",
        "card_ge75":       f"md_nf_card_dis_ge75_{y}",
    }


def extract_csv_years(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Extract the requested calendar years from a single HP CSV (long format)."""
    df = _clean_cols(df)
    if "fips_st_cnty" not in df.columns:
        raise KeyError("CSV missing 'fips_st_cnty' column")

    frames = []
    for yr in years:
        y2 = str(yr)[-2:]
        mp = _csv_col_map(y2)
        available = {k: v for k, v in mp.items() if v in df.columns}
        missing   = {k: v for k, v in mp.items() if v not in df.columns}
        if missing:
            print(f"    [warn] year {yr}: missing CSV columns "
                  f"({len(missing)}): {list(missing.values())[:3]}{'…' if len(missing)>3 else ''}")
        keep = ["fips_st_cnty"] + list(available.values())
        sub = df[keep].copy()
        sub = sub.rename(columns={v: k for k, v in available.items()})
        for c in sub.columns:
            if c != "fips_st_cnty":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub["year"] = yr
        frames.append(sub)

    out = pd.concat(frames, ignore_index=True)
    out["fips_st_cnty"] = out["fips_st_cnty"].astype(str).str.strip('"').str.zfill(5)
    return out


def load_pop_csv(pop_path: str) -> pd.DataFrame:
    """Load an AHRF POP CSV and return it with cleaned columns + 5-char FIPS."""
    df = _clean_cols(pd.read_csv(pop_path, low_memory=False))
    if "fips_st_cnty" not in df.columns:
        raise KeyError(f"POP CSV missing 'fips_st_cnty': {pop_path}")
    df["fips_st_cnty"] = df["fips_st_cnty"].astype(str).str.strip('"').str.zfill(5)
    return df


def load_year_matched_pop_csv(year_pop_pairs: list[tuple[int, str]]) -> pd.DataFrame:
    """
    Build a (fips_st_cnty, year, county_pop_year) long-format lookup from POP
    CSVs. `year_pop_pairs` is a list like [(2023, pop_csv_path), (2022, ...)]
    where for each year we know which POP file holds the matching popn_YY column.
    """
    frames = []
    for yr, path in year_pop_pairs:
        y2 = str(yr)[-2:]
        df = load_pop_csv(path)
        col = f"popn_{y2}"
        if col not in df.columns:
            print(f"    [warn] year {yr}: column {col} not in {os.path.basename(path)}")
            continue
        sub = df[["fips_st_cnty", col]].copy()
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
        sub = sub.rename(columns={col: "county_pop_year"})
        sub["year"] = yr
        frames.append(sub[["fips_st_cnty", "year", "county_pop_year"]])
    if not frames:
        return pd.DataFrame(columns=["fips_st_cnty", "year", "county_pop_year"])
    return pd.concat(frames, ignore_index=True)


def load_census_2020_anchor(pop_path: str) -> pd.DataFrame:
    """Return DataFrame: fips_st_cnty, county_pop_cens2020 (single column)."""
    df = load_pop_csv(pop_path)
    if "cens_popn_20" not in df.columns:
        print("  [warn] cens_popn_20 not in pop file — Census 2020 anchor unavailable")
        return df[["fips_st_cnty"]].assign(county_pop_cens2020=np.nan)
    out = df[["fips_st_cnty", "cens_popn_20"]].copy()
    out["cens_popn_20"] = pd.to_numeric(out["cens_popn_20"], errors="coerce")
    return out.rename(columns={"cens_popn_20": "county_pop_cens2020"})


# =============================================================================
# DERIVED METRICS + TRENDS
# =============================================================================

def add_derived_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute aging share and per-capita rates (two denominators)."""
    # Workforce aging share — share of age-classified workforce aged >= 55.
    have_all_age = all(c in panel.columns for c in AGE_COLS)
    if have_all_age:
        panel["card_total_from_age"] = panel[AGE_COLS].sum(axis=1, min_count=1)
        panel["card_aged_ge55"]      = panel[OLDER_COLS].sum(axis=1, min_count=1)
        panel["workforce_aging_share_ge55"] = np.where(
            panel["card_total_from_age"] > 0,
            panel["card_aged_ge55"] / panel["card_total_from_age"],
            np.nan,
        )

    # Per-100k rates, two denominators
    if "county_pop_year" in panel.columns:
        panel["card_per_100k_year"] = np.where(
            panel["county_pop_year"] > 0,
            panel["md_nf_card_dis"] / panel["county_pop_year"] * 100_000,
            np.nan,
        )
    if "county_pop_cens2020" in panel.columns:
        panel["card_per_100k_cens2020"] = np.where(
            panel["county_pop_cens2020"] > 0,
            panel["md_nf_card_dis"] / panel["county_pop_cens2020"] * 100_000,
            np.nan,
        )
    return panel


def compute_trend_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Per-county OLS slope of cardiologist count over time, with a minimum-count
    threshold. Counties with mean cardiologists < MIN_COUNT_FOR_TREND or fewer
    than MIN_YEARS_FOR_TREND observations are labeled 'insufficient_data'.
    """
    records = []
    for fips, grp in panel.groupby("fips_st_cnty"):
        grp = grp.sort_values("year").dropna(subset=["md_nf_card_dis"])
        n_yrs = len(grp)
        if n_yrs == 0:
            continue

        mean_count = grp["md_nf_card_dis"].mean()
        mean_aging = (grp.get("workforce_aging_share_ge55", pd.Series([np.nan]))
                       .mean())

        first_year = int(grp["year"].iloc[0])
        last_year  = int(grp["year"].iloc[-1])
        card_first = float(grp["md_nf_card_dis"].iloc[0])
        card_last  = float(grp["md_nf_card_dis"].iloc[-1])

        if n_yrs >= MIN_YEARS_FOR_TREND and mean_count >= MIN_COUNT_FOR_TREND:
            x = grp["year"].to_numpy(dtype=float)
            y = grp["md_nf_card_dis"].to_numpy(dtype=float)
            slope, _ = np.polyfit(x, y, 1)
            pct_chg = ((card_last - card_first) / card_first * 100
                       if card_first > 0 else np.nan)
            if slope > 0:
                trend = "growing"
            elif slope < 0:
                trend = "declining"
            else:
                trend = "stagnant"
        else:
            slope, pct_chg, trend = np.nan, np.nan, "insufficient_data"

        # --- per-capita (per-100k) trend, same year/count gates ---
        gr = grp.dropna(subset=["card_per_100k_year"])
        rate_first = float(gr["card_per_100k_year"].iloc[0]) if len(gr) else np.nan
        rate_last  = float(gr["card_per_100k_year"].iloc[-1]) if len(gr) else np.nan
        if len(gr) >= MIN_YEARS_FOR_TREND and mean_count >= MIN_COUNT_FOR_TREND:
            slope_pc, _ = np.polyfit(gr["year"].to_numpy(dtype=float),
                                     gr["card_per_100k_year"].to_numpy(dtype=float), 1)
            trend_pc = ("growing" if slope_pc > 0
                        else "declining" if slope_pc < 0 else "stagnant")
        else:
            slope_pc, trend_pc = np.nan, "insufficient_data"

        records.append({
            "fips_st_cnty":      fips,
            "n_years_available": n_yrs,
            "mean_card_dis":     round(mean_count, 2),
            "mean_aging_share":  (round(mean_aging, 4)
                                  if not np.isnan(mean_aging) else np.nan),
            "first_year":        first_year,
            "last_year":         last_year,
            "card_first":        card_first,
            "card_last":         card_last,
            "workforce_slope":   (round(slope, 4)
                                  if not np.isnan(slope) else np.nan),
            "workforce_pct_chg": (round(pct_chg, 2)
                                  if not np.isnan(pct_chg) else np.nan),
            "workforce_trend":   trend,
            "rate_first":        (round(rate_first, 3) if not np.isnan(rate_first) else np.nan),
            "rate_last":         (round(rate_last, 3) if not np.isnan(rate_last) else np.nan),
            "workforce_slope_pc": (round(slope_pc, 5) if not np.isnan(slope_pc) else np.nan),
            "workforce_trend_pc": trend_pc,
        })
    return pd.DataFrame(records)


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main():
    print("=" * 66)
    print("AHRF Cardiology Workforce Extraction — 2010-2023 Panel")
    print("=" * 66)

    # ── 1. Historical ASCII (2010, 2015, 2019) ───────────────────────────────
    print("\n[1/6] Loading ASCII source for 2010, 2015, 2019...")
    long_ascii = load_ascii_panel(ASCII_PATH, SAS_PATH)

    # ── 2. CSV 2022-2023 release (years 2020, 2021) ──────────────────────────
    print("\n[2/6] Loading 2022-2023 CSV release (years 2020, 2021)...")
    df_2023_rel  = _load_csv_hp(CSV_2022_2023_ZIP)
    long_2020_21 = extract_csv_years(df_2023_rel, [2020, 2021])
    print(f"    rows: {len(long_2020_21):,}  "
          f"counties: {long_2020_21['fips_st_cnty'].nunique():,}")
    del df_2023_rel

    # ── 3. CSV 2023-2024 release (year 2022, preferred over 2022-2023) ───────
    print("\n[3/6] Loading 2023-2024 CSV release (year 2022)...")
    df_2024_rel = _load_csv_hp(CSV_2023_2024)
    long_2022   = extract_csv_years(df_2024_rel, [2022])
    print(f"    rows: {len(long_2022):,}  "
          f"counties: {long_2022['fips_st_cnty'].nunique():,}")
    del df_2024_rel

    # ── 4. CSV 2024-2025 release (year 2023) ─────────────────────────────────
    print("\n[4/6] Loading 2024-2025 CSV release (year 2023)...")
    df_2025_rel = _load_csv_hp(CSV_2024_2025)
    long_2023   = extract_csv_years(df_2025_rel, [2023])
    print(f"    rows: {len(long_2023):,}  "
          f"counties: {long_2023['fips_st_cnty'].nunique():,}")
    del df_2025_rel

    # ── 5. Combine, attach year-matched + Census 2020 anchor populations ─────
    print("\n[5/6] Combining panel and computing derived metrics...")
    panel = pd.concat([long_ascii, long_2020_21, long_2022, long_2023],
                      ignore_index=True, sort=False)

    # Drop rows from non-county FIPS (state/US summary lines that may appear)
    panel = panel[panel["fips_st_cnty"].str.fullmatch(r"\d{5}")]

    # If a (county, year) pair appears in multiple sources, keep the LAST
    # occurrence — concat order is ASCII → 2022-23 → 2023-24 → 2024-25, so
    # the most recent release wins for any overlapping year.
    panel = (panel
             .sort_values(["fips_st_cnty", "year"])
             .drop_duplicates(subset=["fips_st_cnty", "year"], keep="last")
             .reset_index(drop=True))

    # Year-matched population for 2020-2023.
    #   2020, 2021 → 2022-2023 release POP (only release with popn_20/popn_21)
    #   2022, 2023 → 2024-2025 release POP (most current revisions)
    print("    Attaching year-matched population (2020-2023)...")
    with zipfile.ZipFile(CSV_2022_2023_ZIP) as z:
        pop_name = next(n for n in z.namelist()
                        if "POP" in n.upper() and n.endswith(".csv"))
        with z.open(pop_name) as f:
            pop_2022_23 = _clean_cols(pd.read_csv(f, low_memory=False))
    pop_2022_23["fips_st_cnty"] = (pop_2022_23["fips_st_cnty"]
                                   .astype(str).str.strip('"').str.zfill(5))

    early_years = pd.concat([
        pd.DataFrame({
            "fips_st_cnty":    pop_2022_23["fips_st_cnty"],
            "year":            2020,
            "county_pop_year": pd.to_numeric(pop_2022_23.get("popn_20"),
                                              errors="coerce"),
        }),
        pd.DataFrame({
            "fips_st_cnty":    pop_2022_23["fips_st_cnty"],
            "year":            2021,
            "county_pop_year": pd.to_numeric(pop_2022_23.get("popn_21"),
                                              errors="coerce"),
        }),
    ], ignore_index=True)
    later_years = load_year_matched_pop_csv([(2022, POP_2024_2025),
                                              (2023, POP_2024_2025)])
    csv_year_pop_lookup = pd.concat([early_years, later_years], ignore_index=True)

    panel = panel.merge(csv_year_pop_lookup,
                        on=["fips_st_cnty", "year"], how="left",
                        suffixes=("", "__csv"))
    # If both ASCII (years 10/15/19) and CSV (years 20-23) contributed
    # county_pop_year, coalesce.
    if "county_pop_year__csv" in panel.columns:
        panel["county_pop_year"] = panel["county_pop_year"].fillna(
            panel.pop("county_pop_year__csv"))

    # Bring in Census 2020 anchor for ALL rows
    print("    Attaching Census 2020 population anchor...")
    cens20 = load_census_2020_anchor(POP_2024_2025)
    panel = panel.merge(cens20, on="fips_st_cnty", how="left")

    panel = add_derived_metrics(panel)

    print(f"    Panel shape:     {panel.shape}")
    print(f"    Years present:   {sorted(panel['year'].unique())}")
    print(f"    Unique counties: {panel['fips_st_cnty'].nunique():,}")

    panel_path = os.path.join(OUTPUT_DIR, "ahrf_card_dis_panel_2010_2023.csv")
    panel.to_csv(panel_path, index=False)
    print(f"    ✓ Panel saved: {panel_path}")

    # ── 6. County trend summary ──────────────────────────────────────────────
    print("\n[6/6] Computing per-county workforce trends "
          f"(min mean count = {MIN_COUNT_FOR_TREND}, "
          f"min years = {MIN_YEARS_FOR_TREND})...")
    trends = compute_trend_summary(panel)
    trends_path = os.path.join(OUTPUT_DIR, "ahrf_workforce_trend_summary.csv")
    trends.to_csv(trends_path, index=False)
    print(f"    Trend summary shape: {trends.shape}")
    print(f"    Workforce trend distribution:")
    print(trends["workforce_trend"].value_counts().to_string().replace("\n", "\n        "))
    print(f"    ✓ Trend summary saved: {trends_path}")

    # ── Data quality report ──────────────────────────────────────────────────
    print("\n── Data Quality Summary ─────────────────────────────────────────")
    tot = len(panel)
    miss_card  = panel["md_nf_card_dis"].isna().sum()
    miss_year_pop = panel["county_pop_year"].isna().sum() if "county_pop_year" in panel.columns else "n/a"
    miss_cens  = panel["county_pop_cens2020"].isna().sum() if "county_pop_cens2020" in panel.columns else "n/a"
    zero_cnt   = (panel.groupby("fips_st_cnty")["md_nf_card_dis"].max() == 0).sum()
    print(f"  Total (county × year) rows:                 {tot:,}")
    print(f"  Missing md_nf_card_dis values:              {miss_card} ({miss_card/tot*100:.1f}%)")
    print(f"  Missing year-matched population:            {miss_year_pop}")
    print(f"  Missing Census 2020 anchor population:      {miss_cens}")
    print(f"  Counties with 0 cardiologists in all years: {zero_cnt:,}")
    if "card_per_100k_year" in panel.columns:
        rate = panel["card_per_100k_year"].dropna()
        print(f"  card_per_100k_year — median: {rate.median():.2f}  "
              f"p90: {rate.quantile(0.9):.2f}  max: {rate.max():.2f}")
    if "workforce_aging_share_ge55" in panel.columns:
        ag = panel["workforce_aging_share_ge55"].dropna()
        print(f"  workforce_aging_share_ge55 — mean: {ag.mean():.2%}  "
              f"median: {ag.median():.2%}")
    print("─" * 66)
    return panel, trends


if __name__ == "__main__":
    panel, trends = main()
