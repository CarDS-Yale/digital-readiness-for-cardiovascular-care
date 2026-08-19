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
median. The composite standardizes the age-adjusted prevalence of ten conditions across tracts
and averages the resulting z scores, using the 2025 CDC PLACES census tract release. The
workforce screen uses the most recent year of county cardiologist counts in a 2010 to
2023 panel.

Sensitivity analyses ask whether the two groups survive reasonable changes to those
choices. Four of them vary how readiness is measured: rebuilding the index from raw ACS
and FCC inputs, splitting it into its infrastructure and socioeconomic halves, and
swapping the 2022 vintage for 2024. Three vary the workforce definition: primary care
supply instead of cardiology, a 25-mile cross-county access rule, and a pool that counts
cardiology NPs and PAs as coverage. The rest relax the sample and the cutoffs, including
a run with no workforce screen at all and a 3 x 3 grid of alternative burden and
readiness thresholds. Two more check the burden composite in Kentucky and Pennsylvania,
where CDC suppressed 9 of the 10 measures in the release used here. Each run reports box
agreement, group retention, and top-N overlap against the primary result.

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

The following scripts are network-bound and may take considerable time to complete. They
need to be run only once, as their outputs are written to disk and read by the analysis
scripts that follow.

| Script | Output |
|---|---|
| `fetch_workforce.py` | County cardiologist counts, 2010 to 2023 panel (AHRF) |
| `fetch_burden.py` | Tract-level prevalence for 10 conditions (CDC PLACES) |
| `fetch_acs_components.py` | ACS indicators behind the Divide Index |
| `fetch_broadband.py`, then `aggregate_broadband.py` | Tract broadband availability (FCC BDC) |
| `fetch_clinicians.py`, then `process_clinicians.py` | Cardiology NP/PA affiliations (CMS) |
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
suppression reason described above. `compare_runs()` computes the agreement and overlap
statistics reported for each sensitivity analysis.

### Sensitivity Analyses

Each module is self-contained and reports its results relative to the primary run. They
may be executed in any order.

```bash
python sens_readiness_components.py          # readiness rebuilt from raw ACS + FCC inputs
python sens_readiness_subscores.py           # infrastructure and socioeconomic halves
python sens_readiness_vintage.py             # 2024 Divide Index instead of 2022
python sens_all_tracts.py                    # no workforce screen
python sens_thresholds.py                    # 3 x 3 grid of burden and readiness cutoffs
python sens_workforce_primary_care.py        # pool rebuilt on primary care supply
python sens_workforce_distance.py            # 25-mile cross-county access
python sens_workforce_advanced_practice.py   # cardiology NPs and PAs added
python sens_burden_kypa.py                   # KY/PA burden check
python sens_burden_kypa_crosswalk.py         # KY/PA full-measure burden on 2020 tracts
```

### Tables and Figures

```bash
python make_table1.py     # Table 1, group characteristics
python make_tables.py     # ranked tract lists, main and supplementary
python make_figure1.py    # county-level landscape, five panels
python make_figure2.py    # burden-readiness decision space
python make_figure3.py    # national maps of all priority tracts + population bar
python make_figure4.py    # five metropolitan areas
```

`geo.py` provides the Albers projection parameters, the county and tract geometry
loaders, and the color palette imported by the figure scripts. Execution order is
otherwise unconstrained, apart from the requirement that `build_master.py` be run first.

### Outputs

All outputs are written to `outputs/`, with one subdirectory per product. `master/`
contains the cached master table and the sensitivity logs, `burden_workforce/` contains
the burden composite and the county workforce summary, `tables/` contains the ranked
lists, `table1/` contains the group characteristics table, and `figure1/` through
`figure4/` contain the manuscript figures. The data acquisition scripts write their
intermediate files to `outputs/` itself.

## Dashboards

`dashboard/` contains the source for two browser-based tools that accompany the
manuscript. Both are deployed at the URLs below and may also be run locally. Neither
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
