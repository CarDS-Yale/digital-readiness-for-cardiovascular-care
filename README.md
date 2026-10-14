# Digital Readiness for Cardiovascular Care

## Overview

The pipeline links three national datasets at the census-tract level: cardiometabolic
disease burden from CDC PLACES, cardiology workforce supply from the HRSA Area Health
Resources Files, and digital readiness from the Purdue Digital Divide Index.

- **Deployment priority.** Higher burden, higher readiness. Digital tools can plausibly
  reach patients now.
- **Investment priority.** Higher burden, lower readiness. Infrastructure and adoption
  support are likely needed first.

A tract counts as higher burden if its composite burden z score is above the national
mean, and as higher readiness if its Digital Divide Index falls at or below the national
median. The composite standardizes the prevalence of ten conditions across tracts and
averages the resulting z scores, using the 2025 CDC PLACES census tract release. The
workforce screen admits counties with no cardiologist in 2023 or a declining number of
cardiologists per 100,000 residents over a 2010 to 2023 panel.

Beyond the classification itself, the repository covers four further sets of analyses.
Urban-rural analyses ask whether the two groups reduce to an urban-rural divide. Access
analyses measure county-based proxies for cross-county cardiology access and primary care
supply. Cross-source validation rebuilds each input from an independent source or vintage
and checks whether the labels hold. Nine sensitivity analyses vary the readiness measure,
the workforce definition, the geographic access assumption and the thresholds. Each
comparison reports box agreement, group retention and top-10 overlap against the primary
result.

## Data Requirements

No data files are distributed with this repository. All inputs are publicly available,
and `data/README.md` documents each source, its download URL, and its expected location
on disk. Scripts resolve paths relative to the repository root, so reproducing the
directory layout described in that file is the only configuration step required.

## Running the Analysis

Install the dependencies and change to the source directory:

```bash
pip install -r requirements.txt
cd src
```

### Data Acquisition

The following scripts are network-bound and may take some time to complete. They need
to be run only once; their outputs are written to disk and read by the analysis scripts
that follow.

| Script | Output |
|---|---|
| `fetch_workforce.py` | County cardiologist counts, 2010 to 2023 panel (AHRF) |
| `fetch_burden.py` | Tract-level prevalence for 10 conditions (CDC PLACES) |
| `fetch_acs_components.py` | ACS indicators behind the Divide Index, and tract population |
| `fetch_broadband.py`, then `aggregate_broadband.py` | Tract broadband availability (FCC BDC) |
| `fetch_clinicians.py`, then `process_clinicians.py` | CMS Doctors and Clinicians file; cardiology NP/PA affiliations |
| `fetch_urban_rural.py` | NCHS county classification, 2020 Census tract urban/rural |

### Primary Analysis

Execute in the order shown:

```bash
python build_burden_and_workforce.py   # burden composite + county workforce summary
python build_master.py                 # one tract-level table, read by all later scripts
python export_priority_lists.py        # full ranked lists + cutoffs, used by the dashboards
```

`build_master.py` is the central module of the repository. It constructs the master
tract-level table and defines the shared functions used throughout the analysis.
`matrix_boxes()` applies the 2x2 classification to an arbitrary readiness measure.
`rank_eligible()` excludes Kentucky and Pennsylvania from ranked lists, for the
suppression reason described below. `compare_runs()` computes the agreement and overlap
statistics reported for each comparison, and `fisher_ci()` the confidence interval
attached to each correlation.

### Sensitivity Analyses

Each module reports its results relative to the primary run. Three of them cache county
tables that later scripts read, so run the block in the order shown the first time.

```bash
python sens_readiness_components.py          # readiness rebuilt from raw ACS + FCC inputs
python sens_readiness_subscores.py           # infrastructure and socioeconomic halves
python sens_all_tracts.py                    # no workforce screen
python sens_thresholds.py                    # 3 x 3 grid of burden and readiness cutoffs
python sens_workforce_distance.py            # 25-mile cross-county access
python sens_workforce_advanced_practice.py   # cardiology NPs and PAs added
python sens_workforce_primary_care.py        # pool rebuilt on primary care supply
python sens_burden_kypa.py                   # KY/PA burden rebuilt from the 2023 PLACES release
python sens_burden_kypa_crosswalk.py         # the same, carried onto 2020 tracts
python sens_workforce_endocrinology.py       # endocrinologists counted with cardiologists
```

### Descriptive and Validation Analyses

These read the caches written above.

```bash
python analyze_urban_rural.py        # composition, co-occurrence, variance explained, barriers
python analyze_care_access.py        # cross-county cardiology access and primary care supply
python validate_workforce_source.py  # AHRF versus CMS cardiologist counts, pool swap
python validate_cross_source.py      # all three inputs against an alternative source
python check_workforce_stability.py  # year-to-year movement in county cardiologist counts
```

### Tables and Figures

```bash
python make_table1.py        # Table 1, group characteristics
python make_table_decile.py  # Table 1 again under top-decile cutoffs
python make_tables.py        # ranked tract lists and the threshold grid, numbered as in the supplement
python make_figure1.py       # county-level landscape, five panels
python make_figure2.py       # burden-readiness decision space
python make_figure3.py       # national maps of all priority tracts + population bar
python make_figure4.py       # metropolitan areas (Figure 4 and Figure S1)
```

`geo.py` provides the Albers projection parameters, the county and tract geometry
loaders, and the color palette imported by the figure scripts.

### Where Each Table and Figure Comes From

| Item | Script | File under `outputs/` |
|---|---|---|
| Table 1 | `make_table1.py` | `table1/table1_group_summary.csv` |
| Table 2 | `analyze_urban_rural.py` | `urban_rural/composition.csv` |
| Table 3 | `analyze_urban_rural.py` | `urban_rural/variance_explained.csv` |
| Table 4 | `analyze_urban_rural.py` | `urban_rural/cooccurrence_by_class.csv` |
| Table 5 | `analyze_urban_rural.py` | `urban_rural/barrier_profile.csv` |
| Figure 1 | `make_figure1.py` | `figure1/` |
| Figure 2 | `make_figure2.py` | `figure2/figure2_decision_space.png` |
| Figure 3 | `make_figure3.py` | `figure3/figure3_priority_tracts_panels.png`; legend figures in `figure3_land_area.csv` |
| Figure 4 | `make_figure4.py` | `figure4/figure4a_chicago.png`, `figure4b_philadelphia.png` |
| Figure S1 | `make_figure4.py` | `figure4/figureS1a_dallas.png`, `figureS1b_washington_dc.png`, `figureS1c_boston.png` |
| Tables S1, S2 | `make_tables.py` | `tables/table_S1_investment_primary.csv`, `table_S2_deployment_primary.csv` |
| Table S3 | `make_table_decile.py` | `table1/table1_decile_groups.csv` |
| Table S4 | `sens_burden_kypa_crosswalk.py` | `master/burden_kypa_crosswalk.md`, `burden_kypa_crosswalk_delaware.csv` |
| Table S5 | `analyze_care_access.py` | `care_access/access_constraints.csv` |
| Table S6 | `validate_workforce_source.py` | `master/workforce_source_*.csv` |
| Table S7 | `validate_cross_source.py` | `master/cross_source_readiness_gradient.csv` |
| Table S8 | `validate_cross_source.py` | `master/cross_source_summary.csv` (burden row) |
| Tables S9 to S24 | `make_tables.py` | `tables/table_S<n>_*.csv`, odd = investment, even = deployment |
| Table S25 | `make_tables.py` | `tables/table_S25_threshold_grid.csv` |
| Agreement statistics quoted in the text | each `sens_*.py` | `master/<analysis>_comparison.csv` |
| Workforce stability (2022 versus 2023) | `check_workforce_stability.py` | `master/workforce_stability.csv` |

Table S26 lists the PLACES measure definitions and is transcribed from CDC documentation
rather than computed.

### Outputs

All outputs are written to `outputs/`, with one subdirectory per product. `master/`
contains the cached master table, the sensitivity and validation results,
`burden_workforce/` the burden composite and county workforce summary, `tables/` the
ranked lists, `table1/` the group characteristics tables, `urban_rural/` and
`care_access/` the descriptive analyses, and `figure1/` through `figure4/` the figures.
The data acquisition scripts write their intermediate files to `outputs/` itself.

## Dashboards

`dashboard/` contains the source for two browser-based tools that accompany the
analysis. Both are deployed at the URLs below and may also be run locally. Neither
requires server-side infrastructure beyond static file hosting, and both vendor their
JavaScript libraries locally rather than loading them from a CDN.

- **US Census Tract Atlas** (`dashboard/map/`). A MapLibre GL atlas of all counties and
  tracts, displaying workforce supply, burden, readiness, and priority classification.
  https://digital-readiness.cards-lab.org/map
- **Implementation Decision Space** (`dashboard/decision-space/`). A D3 scatterplot of
  workforce-constrained tracts by burden and readiness, with adjustable thresholds that
  allow users to examine how priority assignments respond to alternative cutoffs.
  https://digital-readiness.cards-lab.org/decision-space

Both applications are accessible from the landing page at
https://digital-readiness.cards-lab.org/.

The `prepare_*.py` scripts generate the JSON and GeoJSON layers consumed by the two
applications. They depend on the analysis outputs, so the pipeline must be run through
`export_priority_lists.py` before they are executed. The generated layers are not
distributed with this repository. `dashboard/README.md` documents each layer and its
approximate size.

## License

Released under the MIT License. See `LICENSE`.
