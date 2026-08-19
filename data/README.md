# Data sources

Nothing in this folder is tracked. Every input is public and must be downloaded
separately. The scripts in `src/` expect the layout below, resolved relative to the
repository root.

```
digital-readiness/
├── AHRF/                          # Area Health Resources Files, one folder per release
├── CDC Places/                    # PLACES tract-level CSV export
├── DDI/                           # Digital Divide Index workbook
├── ACS/                           # written by fetch_acs_components.py
├── FCC/                           # written by fetch_broadband.py
├── DAC_CMS/                       # written by fetch_clinicians.py
├── GEO/                           # written by fetch_urban_rural.py
├── tract_geo/                     # tract boundaries, cached on first figure run
├── geojson-counties-fips.json     # county boundaries, downloaded once (see below)
└── outputs/                       # everything the analysis writes
```

## Sources

**Cardiology workforce** — HRSA Area Health Resources Files.
https://data.hrsa.gov/data/download

Each AHRF release carries only two years of the non-federal cardiovascular disease
physician count, so the 2010–2023 panel is assembled from four releases: the
2020–2021 ASCII file (2010, 2015, 2019), then the 2022–2023, 2023–2024 and 2024–2025
CSV releases. `fetch_workforce.py` documents the field names and expected filenames.

**Cardiometabolic burden** — CDC PLACES, census tract release, 2025.
https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-Census-Tract-D/cwsq-ngmh

Ten measures are used: hypertension, high cholesterol, coronary heart disease, stroke,
diabetes, obesity, current smoking, physical inactivity, short sleep duration and binge
drinking. The composite standardizes the age-adjusted prevalence of each measure across
tracts and averages the resulting z scores.

The 2025 release reports 2023 Behavioral Risk Factor Surveillance System data for nine
of these measures. Short sleep duration is asked only in even survey years, so CDC
carries it forward from 2022. Drop the tract-level CSV into `CDC Places/`; the script
detects tract files by the width of the LocationID column, and ignores county files
whenever a tract file is present.

**Cardiometabolic burden, Kentucky and Pennsylvania** — CDC PLACES, census tract
release, 2023. https://data.cdc.gov/resource/hky2-3tpn.csv

CDC suppressed 9 of the 10 measures for these two states in the 2025 release. The 2023
release is the most recent one in which both states reported all ten, so
`sens_burden_kypa.py` and `sens_burden_kypa_crosswalk.py` rebuild their burden from it.
Both scripts pull the file over the Socrata API and cache it under `outputs/master/`; no
manual download is needed.

**Census tract relationship file, 2010 to 2020** — US Census Bureau.
https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt

The 2023 PLACES release is published on 2010 tract boundaries, so
`sens_burden_kypa_crosswalk.py` uses this file to carry those estimates onto 2020
tracts. It downloads and caches the file automatically (~50 MB).

**Digital readiness** — Purdue Center for Regional Development Digital Divide Index.
https://pcrd.purdue.edu/ddi

Available at no cost on request. The workbook holds several vintages as separate sheets.
The primary analysis reads the 2022 tract sheet; `sens_readiness_vintage.py` re-runs the
classification on 2024.

**ACS indicators** — Census Bureau API, 5-year estimates.
https://api.census.gov/data

Used for the raw-component sensitivity analysis and for tract population weights. A free
API key raises the rate limit: https://api.census.gov/data/key_signup.html

**Broadband availability** — FCC Broadband Data Collection, served and unserved location
files. https://broadbandmap.fcc.gov/data-download

The analysis uses terrestrial service at 100/20 Mbps, vintage 31 December 2024. Satellite
is excluded because it covers nearly everywhere and would erase the signal. Set
`FCC_VINTAGE` to use a different as-of date.

**Cardiology NPs and PAs** — CMS Doctors and Clinicians National Downloadable File.
https://data.cms.gov/provider-data

The download URL changes each release, so `fetch_clinicians.py` queries the CMS
metastore for the current one. The file is large (~800 MB).

**Urban–rural classification** — NCHS scheme for counties, plus 2020 Census table P2 for
tract-level urban population.
https://www.cdc.gov/nchs/data-analysis-tools/urban-rural.html
https://api.census.gov/data/2020/dec/dhc

CDC blocks automated download of the NCHS file, so `fetch_urban_rural.py` prints
instructions and reads a manually saved copy if the request fails. The 2020 Census
endpoint requires a Census API key.

**County boundaries** — a GeoJSON of US counties keyed by 5-digit FIPS, saved to the
repository root as `geojson-counties-fips.json`. It is not distributed here. The widely
mirrored copy works:
https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json

`geo.py`, `sens_workforce_distance.py` and the dashboard preparation scripts all read it.
The file carries three pre-2015 county codes whose analytic data lives under a successor
code, so `geo.py` re-keys 46113 to 46102 (Oglala Lakota), 02270 to 02158 (Kusilvak) and
51515 to 51019 (Bedford). The dashboards apply the same aliases in
`prepare_fips_patches.py`.

**Tract boundaries** — Census Bureau cartographic boundary files, 2020, 500k scale. The
figure scripts pull each state layer from a GitHub mirror on first use and cache it under
`tract_geo/`.
https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html
