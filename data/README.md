# Data sources

Nothing in this folder is tracked. Every input is public and must be downloaded
separately; the scripts in `src/` expect the layout below, resolved relative to the
repository root.

```
digital-readiness/
├── AHRF/                  # Area Health Resources Files, one folder per release
├── CDC Places/            # PLACES tract-level CSV exports
├── DDI/                   # Digital Divide Index workbook
├── ACS/                   # written by fetch_acs_components.py
├── FCC/                   # written by fetch_broadband.py
├── DAC_CMS/               # written by fetch_clinicians.py
├── GEO/                   # written by fetch_urban_rural.py
├── tract_geo/             # tract boundaries, cached on first figure run
└── outputs/               # everything the analysis writes
```

## Sources

**Cardiology workforce** — HRSA Area Health Resources Files.
https://data.hrsa.gov/data/download

Each AHRF release carries only two years of the non-federal cardiovascular disease
physician count, so the 2010–2023 panel is assembled from four releases: the
2020–2021 ASCII file (2010, 2015, 2019), then the 2022–2023, 2023–2024 and 2024–2025
CSV releases. `fetch_workforce.py` documents the field names and expected filenames.

**Cardiometabolic burden** — CDC PLACES, census tract releases.
2024 release: https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-Census-Tract-D/ai6z-tcin
2025 release: https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-Census-Tract-D/cwsq-ngmh

Ten measures are used: hypertension, high cholesterol, coronary heart disease, stroke,
diabetes, obesity, current smoking, physical inactivity, short sleep duration and binge
drinking. Age-adjusted prevalence, averaged across the two releases.

**Digital readiness** — Purdue Center for Regional Development Digital Divide Index.
https://pcrd.purdue.edu/digital-divide-index/

The workbook holds several vintages as separate sheets. The primary analysis reads the
2022 tract sheet; `sens_readiness_vintage.py` re-runs the classification on 2024.

**ACS indicators** — Census Bureau API, 5-year estimates.
https://api.census.gov/data

Used for the raw-component sensitivity analysis and for tract population weights. A free
API key raises the rate limit: https://api.census.gov/data/key_signup.html

**Broadband availability** — FCC Broadband Data Collection, served and unserved location
files. https://broadbandmap.fcc.gov/data-download

The analysis uses terrestrial service at 100/20 Mbps. Satellite is excluded because it
covers nearly everywhere and would erase the signal.

**Cardiology NPs and PAs** — CMS Doctors and Clinicians National Downloadable File.
https://data.cms.gov/provider-data

The download URL changes each release, so `fetch_clinicians.py` queries the CMS
metastore for the current one. The file is large (~800 MB).

**Urban–rural classification** — NCHS scheme for counties, plus 2020 Census table P2 for
tract-level urban population.
https://www.cdc.gov/nchs/data-analysis-tools/urban-rural.html
https://api.census.gov/data/2020/dec/dhc

CDC blocks automated download of the NCHS file; `fetch_urban_rural.py` prints
instructions and reads a manually saved copy if the request fails.

**Tract and county boundaries** — Census Bureau cartographic boundary files. The figure
scripts pull the 2020 500k tract layer from a GitHub mirror of these files and cache it
under `tract_geo/`; county geometry ships as `geojson-counties-fips.json`.
https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html
