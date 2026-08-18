/* ============================================================
   CarDS Lab dashboard — app.js
   Map: MapLibre GL JS (no basemap; pure GeoJSON layers)
   Data: counties.geojson, county_data.json, tract_data.json
   ============================================================ */

(() => {
  "use strict";

  // ── Constants ─────────────────────────────────────────────────────────
  const COLORS = {
    yale:         "#00356B",
    yale_soft:    "#DCE5EF",
    Q1_high_risk: "#c1272d",
    Q2_recovering:"#DD7E3A",
    Q3_low_risk:  "#1f5fa6",
    Q4_watch:     "#C9A227",
    unclassified: "#D7DADD",
    border:       "#FFFFFF",
    hoverBorder:  "#00356B",
    selectBorder: "#00224A",
    tract_fill:   "rgba(0,53,107,0.05)",
    tract_line:   "rgba(0,53,107,0.4)",
  };

  const QUADRANT_ORDER = [
    "Q1_high_risk", "Q2_recovering", "Q3_low_risk",
    "Q4_watch",     "unclassified",
  ];
  const QUADRANT_LABEL = {
    Q1_high_risk:  "Q1 High risk",
    Q2_recovering: "Q2 Recovering",
    Q3_low_risk:   "Q3 Low risk",
    Q4_watch:      "Q4 Watch",
    unclassified:  "Unclassified",
  };

  // priority digital-health prioritization palette (county classes + tract buckets)
  const PRIORITY = {
    deploy:           "#1f5fa6",  // higher readiness
    invest:           "#c1272d",  // lower readiness, investment priority
    mixed:            "#6f4d8f",  // both strategies within one county
    high_need_other:  "#8FA0AE",  // in workforce-constrained pool, no target-box tracts
    pool_other:       "#C6D0DA",  // tract in pool but neither bucket
    not_pool:         "#E7EBEF",  // not workforce-constrained
    tract_other:      "#b7bcc3",  // any non-deploy/invest tract (drill-in view)
    county_dim:       "#D7DADD",  // other counties, greyed while zoomed in
  };
  const PRIORITY_CLASS_LABEL = {
    mixed:           "Mixed (both priorities)",
    deploy_lean:     "Deployment-lean",
    invest_lean:     "Investment-lean",
    high_need_other: "Workforce-constrained (other)",
    // tract-level bucket labels
    deploy:          "Deployment priority",
    invest:          "Investment priority",
    both:            "Deployment priority (also high-burden)",
    pool_other:      "Workforce-constrained (outside priority groups)",
  };

  // ── State ─────────────────────────────────────────────────────────────
  let MAP             = null;
  let COUNTY_DATA     = {};
  let EXTRAS_META     = {};     // quantile stops + labels for the new views
  let TRACT_DATA      = null;   // null until lazy-loaded
  let TRACT_LOADING   = false;
  let PRIORITY_SUMMARY      = null;   // national KPI figures
  let CURRENT_METRIC  = "mean_ddi_composite";
  let HOVERED_FIPS    = null;
  let SELECTED_FIPS   = null;
  let TRACT_GEO_CACHE = {};     // {countyFips: GeoJSON | "missing"}
  let CURRENT_TRACT_COUNTY = null;
  let HOVERED_TRACT  = null;
  let SELECTED_TRACT = null;
  const TRACT_OVERLAY_MIN_ZOOM = 7.5;

  // ── DOM refs ──────────────────────────────────────────────────────────
  const $loading = document.getElementById("loading-overlay");
  const $panel   = document.getElementById("side-panel");
  const $panelBody = document.getElementById("panel-content");
  const $panelClose = document.getElementById("panel-close");
  const $about   = document.getElementById("about-panel");
  const $aboutBtn= document.getElementById("about-btn");
  const $aboutClose = document.getElementById("about-close");
  const $searchIn  = document.getElementById("search-input");
  const $searchOut = document.getElementById("search-results");
  const $searchWrap= document.querySelector(".search-wrap");
  const $viewsBar = document.getElementById("views-bar");
  const $disease  = document.getElementById("disease-select");
  const $legend  = document.getElementById("legend");
  const $tractStatus = document.getElementById("tract-status");
  const $kpiCards = document.getElementById("kpi-cards");

  // ── Helpers ───────────────────────────────────────────────────────────
  const fmt = {
    int:   v => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString()),
    pct:   v => (v == null || isNaN(v) ? "—" : (Number(v) * 100).toFixed(1) + "%"),
    num1:  v => (v == null || isNaN(v) ? "—" : Number(v).toFixed(1)),
    num2:  v => (v == null || isNaN(v) ? "—" : Number(v).toFixed(2)),
    num3:  v => (v == null || isNaN(v) ? "—" : Number(v).toFixed(3)),
    pct1:  v => (v == null || isNaN(v) ? "—" : Number(v).toFixed(1) + "%"),
    str:   v => (v == null || v === "" ? "—" : String(v)),
    fips:  s => String(s ?? "").padStart(5, "0"),
    tfips: s => String(s ?? "").padStart(11, "0"),
  };

  const escape = s => String(s ?? "").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);

  // ── Bootstrapping ─────────────────────────────────────────────────────
  async function main() {
    initMap();
    try {
      await loadCountyData();
      loadPrioritySummary();          // KPI strip (non-blocking)
      addCountyLayers();
      attachInteractions();
      buildLegend();
      hideLoading();
      // Start lazy load of tract data in the background
      loadTractData();
    } catch (err) {
      console.error(err);
      showError("Failed to load data. Check the data/ folder and refresh.");
    }
  }

  const REDUCED_MOTION = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ── Map initialisation (no basemap; pure GeoJSON) ────────────────────
  function initMap() {
    MAP = new maplibregl.Map({
      container: "map",
      style: {
        version: 8,
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {},
        layers: [{
          id: "background",
          type: "background",
          paint: { "background-color": "#F7F8FA" }
        }],
      },
      center: [-96.5, 38.8],
      zoom: 3.6,
      minZoom: 2.8,
      maxZoom: 12,
      attributionControl: false,
      hash: false,
    });
    MAP.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    MAP.addControl(new maplibregl.AttributionControl({
      compact: true,
      customAttribution: "Boundaries: US Census Bureau",
    }), "bottom-right");
    MAP.scrollZoom.setWheelZoomRate(1/200);  // gentler wheel zoom
  }

  // ── Data loading ─────────────────────────────────────────────────────
  async function loadCountyData() {
    const [geo, lookup, extras] = await Promise.all([
      fetch("../data/counties.geojson").then(r => r.json()),
      fetch("../data/county_data.json").then(r => r.json()),
      fetch("../data/extras_meta.json").then(r => r.json()).catch(() => ({})),
    ]);
    window.__GEO = geo;
    COUNTY_DATA = lookup;
    EXTRAS_META = extras || {};
    return [geo, lookup];
  }

  async function loadTractData() {
    if (TRACT_LOADING || TRACT_DATA) return;
    TRACT_LOADING = true;
    showTractStatus("Loading census-tract data…");
    try {
      const data = await fetch("../data/tract_data.json").then(r => r.json());
      TRACT_DATA = data;
      hideTractStatus();
    } catch (e) {
      console.warn("tract data not available:", e);
      showTractStatus("Tract data unavailable");
      setTimeout(hideTractStatus, 4000);
    } finally {
      TRACT_LOADING = false;
    }
  }

  async function loadPrioritySummary() {
    try {
      PRIORITY_SUMMARY = await fetch("../data/priority_summary.json").then(r => r.json());
      renderKpis();
    } catch (e) {
      console.warn("priority summary unavailable:", e);
      if ($kpiCards) $kpiCards.parentElement.style.display = "none";
    }
  }

  function renderKpis() {
    if (!PRIORITY_SUMMARY || !$kpiCards) return;
    const s = PRIORITY_SUMMARY;
    const cards = [
      { cls: "k-pool",   value: s.pool?.n_counties,    label: "Workforce-constrained counties" },
      { cls: "k-deploy", value: s.tracts?.n_deploy,    label: "Deployment-priority tracts" },
      { cls: "k-invest", value: s.tracts?.n_invest,    label: "Investment-priority tracts" },
      { cls: "k-mixed",  value: s.counties?.n_mixed,   label: "Mixed counties" },
    ];
    $kpiCards.innerHTML = cards.map(c => `
      <div class="kpi-card ${c.cls}" title="${escape(c.label)}">
        <div class="kpi-value">${fmt.int(c.value)}</div>
        <div class="kpi-label">${escape(c.label)}</div>
      </div>`).join("");
  }

  // ── County layers ────────────────────────────────────────────────────
  function addCountyLayers() {
    MAP.addSource("counties", {
      type: "geojson",
      data: window.__GEO,
      promoteId: "fips_st_cnty",   // features carry FIPS in properties.fips_st_cnty
      generateId: false,
    });

    MAP.addLayer({
      id: "counties-fill",
      type: "fill",
      source: "counties",
      paint: {
        "fill-color": colorExpression(CURRENT_METRIC),
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false], 0.95,
          ["boolean", ["feature-state", "hover"], false],    0.92,
          0.85,
        ],
      },
    });

    MAP.addLayer({
      id: "counties-line",
      type: "line",
      source: "counties",
      paint: {
        "line-color": [
          "case",
          ["boolean", ["feature-state", "selected"], false], COLORS.selectBorder,
          ["boolean", ["feature-state", "hover"], false],    COLORS.hoverBorder,
          "#FFFFFF",
        ],
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false], 1.6,
          ["boolean", ["feature-state", "hover"], false],    1.2,
          0.3,
        ],
      },
    });

    // State outlines: a subtly darker line layer above the county borders,
    // so users can orient themselves by state shapes. Dissolved from the
    // same county file by prepare_state_lines.py; quiet fallback if absent.
    fetch("../data/states.geojson")
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(gj => {
        if (MAP.getSource("states")) return;
        MAP.addSource("states", { type: "geojson", data: gj });
        MAP.addLayer({
          id: "states-line",
          type: "line",
          source: "states",
          paint: {
            "line-color": "#4b5563",
            "line-opacity": 0.55,
            "line-width": [
              "interpolate", ["linear"], ["zoom"],
              3, 0.8,
              6, 1.5,
              9, 2.2,
            ],
          },
        });
      })
      .catch(e => console.warn("state outlines unavailable:", e));
  }

  // ── Color expressions per metric ─────────────────────────────────────
  // Tracts in the drilled-in county are ALWAYS colored by their targeting
  // bucket, independent of the county-level metric dropdown:
  //   deploy/both → green, invest → red, everything else → yellow.
  const NAT_MED_DDI = 18.77;   // priority national-median DDI anchor (manuscript)
  function tractColorExpression() {
    // Target tracts keep solid colors. Every other tract shades by its
    // lean: hue runs blue (higher readiness) through purple (near the
    // national median DDI) to red (lower readiness), as in Figure 4.
    const lean = [
      "case",
      ["==", ["get", "ddi_composite"], null], "#c9ced6",
      ["interpolate", ["linear"], ["get", "ddi_composite"],
        0,           "#15498c",
        NAT_MED_DDI, "#6f4d8f",
        45,          "#c1272d",
      ],
    ];
    return [
      "match", ["coalesce", ["get", "priority_bucket"], "other"],
      "deploy", PRIORITY.deploy,
      "both",   PRIORITY.deploy,
      "invest", PRIORITY.invest,
      lean,
    ];
  }

  // Color depth carries the burden: pale = low burden, deep = high.
  function tractOpacityExpression() {
    const burden = ["coalesce", ["get", "priority_burden_z"], ["get", "burden_z_last"], 0];
    return [
      "case",
      ["boolean", ["feature-state", "selected"], false], 0.97,
      ["boolean", ["feature-state", "hover"], false],    0.92,
      ["match", ["coalesce", ["get", "priority_bucket"], "other"],
        ["deploy", "both", "invest"], 0.88,
        ["interpolate", ["linear"], burden,
          -1.0, 0.25,
           0.0, 0.48,
           1.0, 0.75,
           2.0, 0.93],
      ],
    ];
  }

  function colorExpression(metric) {
    if (metric === "priority_targeting") {
      // One expression serves both county polygons (priority_county_class) and
      // tract polygons (priority_bucket); their value sets are disjoint.
      return [
        "match",
        ["coalesce", ["get", "priority_county_class"], ["get", "priority_bucket"], "none"],
        "mixed",           PRIORITY.mixed,
        "deploy_lean",     PRIORITY.deploy,
        "deploy",          PRIORITY.deploy,
        "both",            PRIORITY.deploy,
        "invest_lean",     PRIORITY.invest,
        "invest",          PRIORITY.invest,
        "high_need_other", PRIORITY.high_need_other,
        "pool_other",      PRIORITY.pool_other,
        PRIORITY.not_pool,   // not in the workforce-constrained pool (or no data)
      ];
    }
    if (metric === "quadrant") {
      return [
        "match", ["coalesce", ["get", "quadrant"], "unclassified"],
        "Q1_high_risk",  COLORS.Q1_high_risk,
        "Q2_recovering", COLORS.Q2_recovering,
        "Q3_low_risk",   COLORS.Q3_low_risk,
        "Q4_watch",      COLORS.Q4_watch,
        COLORS.unclassified,
      ];
    }
    if (metric === "composite_risk_score") {
      // Sequential white → yale-blue → red
      return [
        "case",
        ["==", ["get", "composite_risk_score"], null], COLORS.unclassified,
        ["interpolate", ["linear"], ["get", "composite_risk_score"],
          0,    "#f2f3f0",
          0.25, "#aebfd8",
          0.5,  "#607ea8",
          0.75, "#d3777b",
          1.0,  "#8f1e24",
        ],
      ];
    }
    if (metric === "mean_ddi_composite") {
      // Lower DDI = better readiness → green. Higher = worse → red.
      return [
        "case",
        ["==", ["get", "mean_ddi_composite"], null], COLORS.unclassified,
        ["interpolate", ["linear"], ["get", "mean_ddi_composite"],
          0,    "#1f5fa6",
          15,   "#7fa3cf",
          25,   "#efeeea",
          35,   "#d3777b",
          50,   "#8f1e24",
        ],
      ];
    }
    if (metric === "workforce_trend") {
      return [
        "match", ["coalesce", ["get", "workforce_trend_pc"], ["get", "workforce_trend"], "insufficient_data"],
        "growing",   COLORS.Q3_low_risk,
        "stagnant",  "#C9A227",
        "declining", COLORS.Q1_high_risk,
        COLORS.unclassified,
      ];
    }
    if (metric === "burden_trend") {
      return singleMeasureGuard([
        "match", ["coalesce", ["get", "burden_trend"], "stable"],
        "increasing", COLORS.Q1_high_risk,
        "stable",     "#CFD3D9",
        "decreasing", COLORS.Q3_low_risk,
        COLORS.unclassified,
      ]);
    }
    if (EXTRAS_META[metric] && EXTRAS_META[metric].stops) {
      const expr = ["interpolate", ["linear"], ["get", metric]];
      const cols = rampFor(metric);
      EXTRAS_META[metric].stops.forEach((s, i) => expr.push(s, cols[i]));
      const full = ["case", ["==", ["get", metric], null], COLORS.unclassified, expr];
      // The county burden composite builds from tract composites, so KY/PA
      // (single-measure burden) render as no-data there.
      return metric === "burden_z_last" ? singleMeasureGuard(full) : full;
    }
    return COLORS.unclassified;
  }

  // KY and PA: PLACES tract burden rests on short sleep alone, so burden-
  // derived county views treat them as no data.
  const SINGLE_MEASURE_STATES = ["21", "42"];
  function singleMeasureGuard(expr) {
    return ["match", ["slice", ["get", "fips_st_cnty"], 0, 2],
            SINGLE_MEASURE_STATES, COLORS.unclassified,
            expr];
  }
  function isSingleMeasureFips(fips) {
    return SINGLE_MEASURE_STATES.includes(String(fips || "").slice(0, 2));
  }
  const SINGLE_MEASURE_NOTE =
    "Kentucky and Pennsylvania show as no data here. Their tract burden " +
    "score rests on short sleep alone, so it does not compare on the " +
    "10-measure burden scale.";

  // Data-driven ramps for the sectioned views. Blue = favorable, red =
  // unfavorable throughout; single-disease prevalence uses light → red.
  const RAMP5 = {
    worse_high:  ["#1f5fa6", "#7fa3cf", "#efeeea", "#d3777b", "#8f1e24"],
    better_high: ["#8f1e24", "#d3777b", "#efeeea", "#7fa3cf", "#1f5fa6"],
    prevalence:  ["#f7ece9", "#e0b1a9", "#d3777b", "#b2444a", "#8f1e24"],
  };
  function rampFor(metric) {
    const m = EXTRAS_META[metric];
    const full = RAMP5[m.dir] || RAMP5.worse_high;
    const n = m.stops.length;
    if (n >= 5) return full;
    return m.stops.map((_, i) =>
      full[Math.round(i * (full.length - 1) / Math.max(1, n - 1))]);
  }

  // ── Legend ───────────────────────────────────────────────────────────
  function buildLegend() {
    const m = CURRENT_METRIC;
    let html = `<div class="legend-title">${legendTitle(m)}</div>`;
    if (m === "priority_targeting") {
      [[PRIORITY.deploy, "Deployment-lean county"],
       [PRIORITY.invest, "Investment-lean county"],
       [PRIORITY.mixed,  "Mixed (both priorities)"],
       [PRIORITY.high_need_other, "Workforce-constrained, other"],
       [PRIORITY.not_pool, "Not workforce-constrained"]].forEach(([c, l]) => {
        html += `<div class="legend-row"><div class="legend-swatch" style="background:${c}"></div><div>${l}</div></div>`;
      });
      html += `<div class="legend-note">Zoom into a county to see its individual
        <span style="color:${PRIORITY.deploy};font-weight:600">deploy</span> /
        <span style="color:${PRIORITY.invest};font-weight:600">invest</span> tracts.</div>`;
      $legend.innerHTML = html;
      return;
    }
    if (m === "quadrant") {
      QUADRANT_ORDER.forEach(q => {
        html += `<div class="legend-row">
          <div class="legend-swatch" style="background:${COLORS[q]}"></div>
          <div>${QUADRANT_LABEL[q]}</div>
        </div>`;
      });
    } else if (m === "composite_risk_score") {
      html += `<div class="legend-gradient" style="background: linear-gradient(to right, #f2f3f0, #aebfd8, #607ea8, #d3777b, #8f1e24)"></div>
        <div class="legend-axis"><span>Low risk</span><span>High risk</span></div>`;
    } else if (m === "mean_ddi_composite") {
      html += `<div class="legend-gradient" style="background: linear-gradient(to right, #1f5fa6, #7fa3cf, #efeeea, #d3777b, #8f1e24)"></div>
        <div class="legend-axis"><span>Better readiness</span><span>Greater divide</span></div>`;
    } else if (m === "workforce_trend") {
      [["growing", COLORS.Q3_low_risk, "Growing"],
       ["declining", COLORS.Q1_high_risk, "Declining"],
       ["unclassified", COLORS.unclassified, "No cardiologists or too few to assess"]].forEach(([_, c, l]) => {
         html += `<div class="legend-row"><div class="legend-swatch" style="background:${c}"></div><div>${l}</div></div>`;
       });
      html += `<div class="legend-note">Trend in cardiologists per 100,000 residents, 2010 to 2023, as in the manuscript's decline rule.</div>`;
    } else if (m === "burden_trend") {
      [["increasing", COLORS.Q1_high_risk, "Burden increasing"],
       ["stable", "#CFD3D9", "Stable"],
       ["decreasing", COLORS.Q3_low_risk, "Burden decreasing"]].forEach(([_, c, l]) => {
         html += `<div class="legend-row"><div class="legend-swatch" style="background:${c}"></div><div>${l}</div></div>`;
       });
      html += `<div class="legend-note">${SINGLE_MEASURE_NOTE}</div>`;
    } else if (EXTRAS_META[m] && EXTRAS_META[m].stops) {
      const meta = EXTRAS_META[m];
      const cols = rampFor(m);
      const lo = meta.stops[0], hi = meta.stops[meta.stops.length - 1];
      const unit = meta.fmt === "pct" ? "%" : "";
      html += `<div class="legend-gradient" style="background: linear-gradient(to right, ${cols.join(", ")})"></div>
        <div class="legend-axis"><span>${fmt.num1(lo)}${unit}</span><span>${fmt.num1(hi)}${unit}</span></div>
        <div class="legend-axis"><span>${escape(meta.lo)}</span><span>${escape(meta.hi)}</span></div>
        <div class="legend-note">Color range spans the 2nd–98th county percentiles. Grey = no data.</div>`;
      if (m === "burden_z_last") {
        html += `<div class="legend-note">${SINGLE_MEASURE_NOTE}</div>`;
      }
    }
    $legend.innerHTML = html;
  }

  function buildTractLegend() {
    let html = `<div class="legend-title">Tracts: digital-health priority</div>`;
    [[PRIORITY.deploy, "Deployment priority"],
     [PRIORITY.invest, "Investment priority"]].forEach(([c, l]) => {
      html += `<div class="legend-row"><div class="legend-swatch" style="background:${c}"></div><div>${l}</div></div>`;
    });
    html += `<div class="legend-note" style="margin-top:6px">Other tracts shade by lean:</div>
      <div class="legend-gradient" style="background: linear-gradient(to right, #15498c, #6f4d8f, #c1272d)"></div>
      <div class="legend-axis"><span>Higher readiness (low DDI)</span><span>Lower readiness</span></div>
      <div class="legend-note">Purple sits near the national median DDI (${NAT_MED_DDI.toFixed(1)}).
      Deeper color = higher burden; pale = low burden. Click a tract for detail.</div>`;
    $legend.innerHTML = html;
  }

  function legendTitle(m) {
    if (EXTRAS_META[m] && EXTRAS_META[m].label) return EXTRAS_META[m].label;
    return ({
      priority_targeting: "Digital Health Prioritization",
      quadrant: "Workforce × burden quadrant",
      composite_risk_score: "Composite risk score",
      mean_ddi_composite: "Mean Digital Divide Index",
      workforce_trend: "Cardiology workforce trend",
      burden_trend: "CVD burden trend (county)",
    })[m] || "";
  }

  // ── Interactions ─────────────────────────────────────────────────────
  function attachInteractions() {
    MAP.on("mousemove", "counties-fill", evt => {
      if (!evt.features.length) return;
      MAP.getCanvas().style.cursor = "pointer";
      const f = evt.features[0];
      const fips = f.id;
      if (HOVERED_FIPS && HOVERED_FIPS !== fips) {
        MAP.setFeatureState({ source: "counties", id: HOVERED_FIPS }, { hover: false });
      }
      HOVERED_FIPS = fips;
      MAP.setFeatureState({ source: "counties", id: fips }, { hover: true });
    });
    MAP.on("mouseleave", "counties-fill", () => {
      MAP.getCanvas().style.cursor = "";
      if (HOVERED_FIPS) {
        MAP.setFeatureState({ source: "counties", id: HOVERED_FIPS }, { hover: false });
      }
      HOVERED_FIPS = null;
    });

    MAP.on("click", "counties-fill", evt => {
      if (!evt.features.length) return;
      // If a tract overlay covers this point, let the tract handler take it —
      // clicking a tract should show its detail without re-zooming the county.
      if (MAP.getLayer("tracts-fill")) {
        const t = MAP.queryRenderedFeatures(evt.point, { layers: ["tracts-fill"] });
        if (t.length) return;
      }
      const fips = evt.features[0].id;
      selectCounty(fips, { zoom: true });
    });

    // Click on empty map area (outside any county/tract) → back to default view
    MAP.on("click", evt => {
      const layers = ["counties-fill", "tracts-fill"].filter(l => MAP.getLayer(l));
      const hits = MAP.queryRenderedFeatures(evt.point, { layers });
      if (!hits.length) resetView();
    });

    // Metric selector: sectioned button groups + the single-disease dropdown.
    // All buttons across the bar act as one radio set.
    function setMetric(mkey) {
      CURRENT_METRIC = mkey;
      // While drilled into a county, counties stay grey and the tract
      // targeting colors persist; the new metric applies when you zoom back out.
      if (!CURRENT_TRACT_COUNTY) {
        MAP.setPaintProperty("counties-fill", "fill-color", colorExpression(CURRENT_METRIC));
        buildLegend();
      }
    }
    const $viewBtns = $viewsBar.querySelectorAll(".seg button");
    $viewBtns.forEach(b => b.addEventListener("click", () => {
      $viewBtns.forEach(x => x.classList.toggle("on", x === b));
      if ($disease) $disease.value = "";
      setMetric(b.dataset.m);
    }));
    if ($disease) $disease.addEventListener("change", () => {
      if (!$disease.value) return;
      $viewBtns.forEach(x => x.classList.remove("on"));
      setMetric($disease.value);
    });

    // Panel close
    $panelClose.addEventListener("click", deselectCounty);
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") {
        if (!$searchOut.hidden) hideSearchResults();
        else if ($about.classList.contains("open")) closeAbout();
        else if ($panel.classList.contains("open")) deselectCounty();
      }
    });

    // About panel
    $aboutBtn.addEventListener("click", openAbout);
    $aboutClose.addEventListener("click", closeAbout);

    // Inline search
    $searchIn.addEventListener("focus", () => runSearch($searchIn.value));
    $searchIn.addEventListener("input", debounce(() => runSearch($searchIn.value), 120));
    $searchIn.addEventListener("keydown", handleSearchKeys);
    document.addEventListener("click", e => {
      if (!$searchWrap.contains(e.target)) hideSearchResults();
    });
  }

  function selectCounty(fips, { zoom = false } = {}) {
    if (SELECTED_FIPS) {
      MAP.setFeatureState({ source: "counties", id: SELECTED_FIPS }, { selected: false });
    }
    SELECTED_FIPS = fips;
    MAP.setFeatureState({ source: "counties", id: fips }, { selected: true });
    renderCountyPanel(fips);
    openPanel();
    if (zoom) zoomToCounty(fips);
  }

  function deselectCounty() {
    if (SELECTED_FIPS) {
      MAP.setFeatureState({ source: "counties", id: SELECTED_FIPS }, { selected: false });
      SELECTED_FIPS = null;
    }
    clearTractOverlay();
    closePanel();
  }

  // Return to the opening view: whole continental US, county-level shading,
  // no tract overlay, nothing selected.
  function resetView() {
    deselectCounty();
    if (!$searchOut.hidden) hideSearchResults();
    MAP.easeTo({ center: [-96.5, 38.8], zoom: 3.6, duration: REDUCED_MOTION ? 0 : 800 });
  }

  function zoomToCounty(fips) {
    const feat = window.__GEO.features.find(f => f.id === fips);
    if (!feat) return;
    const bbox = computeBbox(feat.geometry);
    if (!bbox) return;
    MAP.fitBounds(bbox, {
      padding: { top: 80, bottom: 80, left: 80, right: 460 },
      duration: REDUCED_MOTION ? 0 : 900,
      maxZoom: 9,
    });
    // Once we've zoomed in, try to load tract polygons for this county.
    // Quiet failure if the tract geometry file isn't present.
    loadTractOverlay(fips);
  }

  // ── Tract polygon overlay (hybrid mode) ──────────────────────────────
  // When a county is zoomed in, we try to fetch its per-county tract
  // GeoJSON from `../data/tracts/{fips_county}.geojson`. If present, we render
  // the tracts as a clickable overlay; if not, we silently fall back to
  // the side-panel table view (already implemented).
  async function loadTractOverlay(countyFips) {
    if (CURRENT_TRACT_COUNTY === countyFips) return; // already showing
    clearTractOverlay();

    // Try cache first
    let geo = TRACT_GEO_CACHE[countyFips];
    if (geo === "missing") return;
    if (!geo) {
      try {
        const url = `../data/tracts/${countyFips}.geojson`;
        const r = await fetch(url, { cache: "force-cache" });
        if (!r.ok) {
          TRACT_GEO_CACHE[countyFips] = "missing";
          return;
        }
        geo = await r.json();
        TRACT_GEO_CACHE[countyFips] = geo;
      } catch (e) {
        TRACT_GEO_CACHE[countyFips] = "missing";
        return;
      }
    }
    if (SELECTED_FIPS !== countyFips) return;   // user moved on
    showTractOverlay(countyFips, geo);
  }

  function showTractOverlay(countyFips, geo) {
    // Attach analytic properties to each tract feature
    const tdata = (TRACT_DATA && TRACT_DATA[countyFips]) || {};
    geo.features.forEach(f => {
      const tfips = String(f.id || f.properties?.GEOID || f.properties?.geoid || "")
                      .padStart(11, "0");
      f.id = tfips;
      const rec = tdata[tfips] || {};
      f.properties = Object.assign({}, f.properties || {}, rec, {
        fips_tract:   tfips,
        fips_st_cnty: countyFips,
      });
    });

    if (!MAP.getSource("tracts")) {
      MAP.addSource("tracts", { type: "geojson", data: geo, promoteId: "fips_tract" });
      MAP.addLayer({
        id: "tracts-fill",
        type: "fill",
        source: "tracts",
        paint: {
          "fill-color": tractColorExpression(),
          "fill-opacity": tractOpacityExpression(),
        },
      }, "counties-line"); // beneath the county outlines
      MAP.addLayer({
        id: "tracts-line",
        type: "line",
        source: "tracts",
        paint: {
          "line-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false], COLORS.selectBorder,
            ["boolean", ["feature-state", "hover"], false],    COLORS.hoverBorder,
            "rgba(255,255,255,0.6)",
          ],
          "line-width": [
            "case",
            ["boolean", ["feature-state", "selected"], false], 1.4,
            ["boolean", ["feature-state", "hover"], false],    1.0,
            0.4,
          ],
        },
      }, "counties-line");
      attachTractInteractions();
    } else {
      MAP.getSource("tracts").setData(geo);
      MAP.setPaintProperty("tracts-fill", "fill-color", tractColorExpression());
      MAP.setPaintProperty("tracts-fill", "fill-opacity", tractOpacityExpression());
    }
    CURRENT_TRACT_COUNTY = countyFips;
    dimCounties(true);            // grey out all other counties
    buildTractLegend();          // switch legend to the tract targeting key
  }

  // Grey every county while a tract overlay is active; restore on exit.
  function dimCounties(on) {
    if (!MAP.getLayer("counties-fill")) return;
    MAP.setPaintProperty("counties-fill", "fill-color",
      on ? PRIORITY.county_dim : colorExpression(CURRENT_METRIC));
  }

  function clearTractOverlay() {
    if (MAP.getLayer("tracts-fill")) MAP.removeLayer("tracts-fill");
    if (MAP.getLayer("tracts-line")) MAP.removeLayer("tracts-line");
    if (MAP.getSource("tracts"))     MAP.removeSource("tracts");
    CURRENT_TRACT_COUNTY = null;
    HOVERED_TRACT = null;
    SELECTED_TRACT = null;
    dimCounties(false);   // restore county choropleth
    buildLegend();        // restore the metric legend
  }

  function attachTractInteractions() {
    MAP.on("mousemove", "tracts-fill", evt => {
      if (!evt.features.length) return;
      MAP.getCanvas().style.cursor = "pointer";
      const tfips = evt.features[0].id;
      if (HOVERED_TRACT && HOVERED_TRACT !== tfips) {
        MAP.setFeatureState({ source: "tracts", id: HOVERED_TRACT }, { hover: false });
      }
      HOVERED_TRACT = tfips;
      MAP.setFeatureState({ source: "tracts", id: tfips }, { hover: true });
    });
    MAP.on("mouseleave", "tracts-fill", () => {
      if (HOVERED_TRACT) {
        MAP.setFeatureState({ source: "tracts", id: HOVERED_TRACT }, { hover: false });
      }
      HOVERED_TRACT = null;
      MAP.getCanvas().style.cursor = "";
    });
    MAP.on("click", "tracts-fill", evt => {
      if (!evt.features.length) return;
      const f = evt.features[0];
      const parentFips = String(f.properties?.fips_st_cnty || CURRENT_TRACT_COUNTY);
      const tfips = f.id;
      if (SELECTED_TRACT) {
        MAP.setFeatureState({ source: "tracts", id: SELECTED_TRACT }, { selected: false });
      }
      SELECTED_TRACT = tfips;
      MAP.setFeatureState({ source: "tracts", id: tfips }, { selected: true });
      renderTractPanel(tfips, parentFips);
      openPanel();
    });
  }

  function computeBbox(geom) {
    let minX =  Infinity, minY =  Infinity, maxX = -Infinity, maxY = -Infinity;
    const walk = c => {
      if (typeof c[0] === "number") {
        const [x, y] = c;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      } else c.forEach(walk);
    };
    walk(geom.coordinates);
    return isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null;
  }

  // ── Side panel rendering ─────────────────────────────────────────────
  function openPanel()  { $panel.classList.add("open");  $panel.setAttribute("aria-hidden", "false"); }
  function closePanel() { $panel.classList.remove("open"); $panel.setAttribute("aria-hidden", "true"); }
  function openAbout()  { $about.classList.add("open"); $about.setAttribute("aria-hidden", "false"); }
  function closeAbout() { $about.classList.remove("open"); $about.setAttribute("aria-hidden", "true"); }
  function hideSearchResults() { $searchOut.hidden = true; }
  function showSearchResults() { $searchOut.hidden = false; }

  function renderCountyPanel(fips) {
    const d = COUNTY_DATA[fips];
    if (!d) {
      $panelBody.innerHTML = `<div class="panel-eyebrow">County FIPS ${fips}</div>
        <div class="panel-title">Data unavailable</div>
        <p>No analytic record found for this county.</p>`;
      return;
    }

    const tracts = (TRACT_DATA && TRACT_DATA[fips]) ? TRACT_DATA[fips] : {};
    const nTracts = Object.keys(tracts).length;
    const ruralLabel = ruralUrbanLabel(d.rural_urban_code);
    const interp = interpretCounty(d, tracts);

    const html = `
      <div class="panel-eyebrow">County FIPS ${fips}</div>
      <div class="panel-title">${escape(d.county_name || "—")}, ${escape(d.state_abbr || "")}</div>
      <div class="panel-meta">${escape(d.state_name || "")}${d.cbsa_name ? " &middot; " + escape(d.cbsa_name) : ""}</div>
      ${priorityBadge(priorityCountyClass(d))}

      <div class="summary-block">
        <div class="summary-eyebrow">What we think about this county</div>
        ${interp.html}
      </div>

      ${priorityCountySection(d)}

      <div class="section-title">Demographics</div>
      <div class="kv-grid">
        <div class="k">County population (2023)</div>             <div class="v">${valOrNull(d.county_pop_latest, fmt.int)}</div>
        <div class="k">Rural-urban code</div>                     <div class="v">${escape(ruralLabel)}</div>
        <div class="k">Census tracts in county</div>              <div class="v">${fmt.int(nTracts || d.n_tracts || 0)}</div>
      </div>

      <div class="section-title">Cardiology workforce (county)</div>
      <div class="kv-grid">
        <div class="k">Cardiologists (latest year)</div>          <div class="v">${valOrNull(d.cards_latest, fmt.int)}</div>
        <div class="k">Per 100,000 residents</div>                <div class="v">${valOrNull(d.cards_per_100k_latest, fmt.num2)}</div>
        <div class="k">Cardiology NPs/PAs (DAC, strict)</div>     <div class="v">${valOrNull(d.n_card_app_strict, fmt.int)}</div>
        <div class="k">Cards + NPs/PAs per 100,000</div>          <div class="v">${valOrNull(d.card_app_per_100k, fmt.num2)}</div>
        <div class="k">Primary care MD/DO per 100,000</div>       <div class="v">${valOrNull(d.pcp_per_100k, fmt.num1)}</div>
        <div class="k">Share of workforce ≥55 yrs</div>           <div class="v">${valOrNull(d.aging_share_latest, fmt.pct)}</div>
        <div class="k">Trend per 100,000 (${d.first_year ?? "—"}→${d.last_year ?? "—"})</div>
                                                                 <div class="v">${trendPill(d.workforce_trend_pc || d.workforce_trend)}</div>
        <div class="k">Per 100,000, first → last</div>            <div class="v">${d.rate_first != null && d.rate_last != null ? fmt.num1(d.rate_first) + " → " + fmt.num1(d.rate_last) : valOrNull(null)}</div>
        <div class="k">% change in counts</div>                   <div class="v">${valOrNull(d.workforce_pct_chg, v => fmt.num1(v) + "%")}</div>
        <div class="k">Slope (cardiologists / year)</div>         <div class="v">${valOrNull(d.workforce_slope, fmt.num3)}</div>
      </div>

      <div class="section-title">Disease burden (county aggregate)</div>
      <div class="kv-grid">
        <div class="k">Burden trend (2022→2023)</div>             <div class="v">${trendPill(d.burden_trend)}</div>
        <div class="k">Composite z, latest</div>                  <div class="v">${valOrNull(d.burden_z_last, fmt.num3)}</div>
        <div class="k">Δ composite z</div>                        <div class="v">${valOrNull(d.burden_z_delta, fmt.num3)}</div>
        <div class="k">Tracts contributing</div>                  <div class="v">${valOrNull(d.n_tracts_burden, fmt.int)}</div>
      </div>
      ${isSingleMeasureFips(d.fips_st_cnty || fips) ? `<p class="priority-hint">Caution:
        the tract burden composite in this state rests on short sleep alone
        (CDC suppressed the other nine PLACES measures), so these values do not
        compare against the 10-measure national scale.</p>` : ""}

      <div class="section-title">Digital readiness (DDI, county mean over tracts)</div>
      <div class="kv-grid">
        <div class="k">Mean DDI (composite)</div>                 <div class="v">${valOrNull(d.mean_ddi_composite, fmt.num2)}</div>
        <div class="k">Mean infrastructure (INFA)</div>           <div class="v">${valOrNull(d.mean_ddi_infa, fmt.num2)}</div>
        <div class="k">Mean socioeconomic (SE)</div>              <div class="v">${valOrNull(d.mean_ddi_se,   fmt.num2)}</div>
        <div class="k">Readiness tier (county)</div>              <div class="v">${tierPill(d.digital_readiness_tier)}</div>
      </div>


      <div class="section-title">Census tracts in this county (${nTracts || 0})</div>
      ${nTracts > 0 ? tractsTable(fips, tracts)
                    : (TRACT_DATA ? `<p style="color:var(--text-mute);font-size:12.5px">No tracts indexed for this county.</p>`
                                  : `<p style="color:var(--text-mute);font-size:12.5px">Loading tract data…</p>`)}
    `;
    $panelBody.innerHTML = html;
    $panelBody.scrollTop = 0;
    attachTractTableHandlers(fips);
  }

  function attachTractTableHandlers(fips) {
    const t = $panelBody.querySelector("#tract-table");
    if (!t) return;
    t.addEventListener("click", e => {
      const row = e.target.closest("tr[data-tract]");
      if (!row) return;
      const tfips = row.dataset.tract;
      renderTractPanel(tfips, fips);
    });
    // keyboard: Enter or Space opens the focused tract row
    t.addEventListener("keydown", e => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest("tr[data-tract]");
      if (!row) return;
      e.preventDefault();
      renderTractPanel(row.dataset.tract, fips);
    });
    // Column sort
    t.querySelectorAll("th[data-sort]").forEach(th => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        const ascending = th.dataset.dir !== "asc";
        const tbody = t.querySelector("tbody");
        const rows  = Array.from(tbody.querySelectorAll("tr"));
        const get   = r => {
          const v = r.dataset[key];
          if (v === "" || v === undefined || v === "null") return null;
          const n = parseFloat(v);
          return isNaN(n) ? v : n;
        };
        rows.sort((a, b) => {
          const va = get(a), vb = get(b);
          if (va == null && vb == null) return 0;
          if (va == null) return 1;
          if (vb == null) return -1;
          return ascending ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
        });
        rows.forEach(r => tbody.appendChild(r));
        t.querySelectorAll("th").forEach(other => other.dataset.dir = "");
        th.dataset.dir = ascending ? "asc" : "desc";
      });
    });
  }

  function tractsTable(fips, tracts) {
    const rows = Object.values(tracts);
    // Surface deploy/invest tracts first by default.
    const order = { deploy: 0, both: 0, invest: 1, pool_other: 2 };
    rows.sort((a, b) => {
      const oa = order[a.priority_bucket] ?? 3, ob = order[b.priority_bucket] ?? 3;
      if (oa !== ob) return oa - ob;
      return (b.burden_z_last ?? -99) - (a.burden_z_last ?? -99);
    });
    const head = `<thead><tr>
      <th data-sort="tract">Tract</th>
      <th data-sort="bucket">Priority</th>
      <th data-sort="ddi" class="num">DDI</th>
      <th data-sort="burden_z_last" class="num">Burden z</th>
      <th data-sort="tier">Tier</th>
    </tr></thead>`;
    const body = rows.map(r => `<tr class="row-clickable" tabindex="0" role="button"
        aria-label="Open tract ${escape(r.fips_tract)}"
        data-tract="${escape(r.fips_tract)}"
        data-bucket="${r.priority_bucket ?? ""}"
        data-ddi="${r.ddi_composite ?? ""}"
        data-burden_z_last="${r.burden_z_last ?? ""}"
        data-tier="${r.digital_readiness_tier ?? ""}">
      <td>${escape(r.fips_tract.slice(5))}</td>
      <td>${shortBucket(r.priority_bucket)}</td>
      <td class="num">${valOrNull(r.ddi_composite, fmt.num2)}</td>
      <td class="num">${valOrNull(r.burden_z_last, fmt.num2)}</td>
      <td>${shortTier(r.digital_readiness_tier)}</td>
    </tr>`).join("");
    return `<table class="tract-table" id="tract-table">${head}<tbody>${body}</tbody></table>`;
  }

  function renderTractPanel(tfips, parentFips) {
    const t = TRACT_DATA && TRACT_DATA[parentFips] && TRACT_DATA[parentFips][tfips];
    const parent = COUNTY_DATA[parentFips];
    if (!t) return;

    const interp = interpretTract(t, parent);

    const html = `
      <button class="back-btn" id="tract-back">&larr; Back to ${escape(parent.county_name || "county")}, ${escape(parent.state_abbr || "")}</button>
      <div class="panel-eyebrow">Census tract ${tfips}</div>
      <div class="panel-title">Tract ${tfips.slice(5)}</div>
      <div class="panel-meta">${escape(parent.county_name || "")}, ${escape(parent.state_abbr || "")}</div>
      ${priorityBadge(priorityTractClass(t))}

      <div class="summary-block">
        <div class="summary-eyebrow">What we think about this tract</div>
        ${interp.html}
      </div>

      ${priorityTractSection(t)}

      <div class="section-title">Disease burden (tract)</div>
      <div class="kv-grid">
        <div class="k">Burden trend (2022→2023)</div>      <div class="v">${trendPill(t.burden_trend)}</div>
        <div class="k">Composite z, 2022</div>             <div class="v">${valOrNull(t.burden_z_first, fmt.num3)}</div>
        <div class="k">Composite z, 2023</div>             <div class="v">${valOrNull(t.burden_z_last,  fmt.num3)}</div>
        <div class="k">Δ composite z</div>                 <div class="v">${valOrNull(t.burden_z_delta, fmt.num3)}</div>
        <div class="k">Slope (z per year)</div>            <div class="v">${valOrNull(t.burden_slope, fmt.num3)}</div>
      </div>
      ${t.priority_single_measure ? `<p class="priority-hint">Caution: this burden composite
        rests on short sleep alone (CDC suppressed the other nine PLACES
        measures in this state), so it does not compare against the 10-measure
        national scale.</p>` : ""}

      <div class="section-title">Digital readiness (tract DDI)</div>
      <div class="kv-grid">
        <div class="k">DDI composite</div>                 <div class="v">${valOrNull(t.ddi_composite, fmt.num2)}</div>
        <div class="k">Infrastructure (INFA)</div>         <div class="v">${valOrNull(t.ddi_infa, fmt.num2)}</div>
        <div class="k">Socioeconomic (SE)</div>            <div class="v">${valOrNull(t.ddi_se, fmt.num2)}</div>
        <div class="k">Readiness tier</div>                <div class="v">${tierPill(t.digital_readiness_tier)}</div>
      </div>

      <div class="section-title">Parent-county workforce</div>
      <div class="kv-grid">
        <div class="k">Workforce trend, per 100,000</div>  <div class="v">${trendPill(parent?.workforce_trend_pc || t.workforce_trend)}</div>
        <div class="k">County workforce slope</div>        <div class="v">${valOrNull(t.workforce_slope, fmt.num3)}</div>
        <div class="k">Mean cardiologists (county)</div>   <div class="v">${valOrNull(t.mean_card_dis, fmt.num1)}</div>
      </div>

    `;
    $panelBody.innerHTML = html;
    document.getElementById("tract-back").addEventListener("click",
      () => renderCountyPanel(parentFips));
    $panelBody.scrollTop = 0;
  }

  // ── Inline search (top-bar dropdown) ─────────────────────────────────
  let SEARCH_ACTIVE_IDX = -1;

  function runSearch(q) {
    q = (q || "").trim().toLowerCase();
    SEARCH_ACTIVE_IDX = -1;
    let out = [];
    if (q.length === 0) {
      // Surface bimodal ("mixed") workforce-constrained counties as starter results —
      // the within-county heterogeneity is the most interesting entry point.
      const arr = [];
      for (const fips in COUNTY_DATA) {
        const d = COUNTY_DATA[fips];
        if (d.priority_county_class === "mixed") arr.push(d);
      }
      arr.sort((a, b) => ((b.priority_n_deploy || 0) + (b.priority_n_invest || 0))
                        - ((a.priority_n_deploy || 0) + (a.priority_n_invest || 0)));
      out = arr.slice(0, 8);
    } else {
      for (const fips in COUNTY_DATA) {
        const d = COUNTY_DATA[fips];
        const hay = `${d.county_name || ""}, ${d.state_abbr || ""} ${d.state_name || ""} ${fips}`.toLowerCase();
        if (hay.includes(q)) out.push(d);
        if (out.length > 60) break;
      }
      out.sort((a, b) => {
        const ai = `${a.county_name}, ${a.state_abbr}`.toLowerCase().indexOf(q);
        const bi = `${b.county_name}, ${b.state_abbr}`.toLowerCase().indexOf(q);
        return ai - bi;
      });
      out = out.slice(0, 10);
    }

    if (out.length === 0) {
      $searchOut.innerHTML = `<div class="search-empty">No matching counties</div>`;
    } else {
      const heading = q.length === 0
        ? `<div class="search-empty" style="text-align:left;padding:6px 14px;color:var(--text-mute);font-size:11px;text-transform:uppercase;letter-spacing:.05em">Mixed workforce-constrained counties (both strategies)</div>`
        : "";
      $searchOut.innerHTML = heading + out.map(d => `
        <div class="search-row" data-fips="${d.fips_st_cnty}">
          <span class="place">${escape(d.county_name || "—")}, ${escape(d.state_abbr || "")}</span>
          <span class="meta">${d.fips_st_cnty} &middot; ${priorityCountyClass(d).label}</span>
        </div>`).join("");
      $searchOut.querySelectorAll(".search-row").forEach(r => {
        r.addEventListener("mousedown", e => e.preventDefault());  // keep input focused
        r.addEventListener("click", () => {
          const f = r.dataset.fips;
          $searchIn.value = "";
          hideSearchResults();
          $searchIn.blur();
          selectCounty(f, { zoom: true });
        });
      });
    }
    showSearchResults();
  }

  function handleSearchKeys(e) {
    const rows = $searchOut.querySelectorAll(".search-row");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      SEARCH_ACTIVE_IDX = Math.min(SEARCH_ACTIVE_IDX + 1, rows.length - 1);
      updateActiveRow(rows);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      SEARCH_ACTIVE_IDX = Math.max(SEARCH_ACTIVE_IDX - 1, 0);
      updateActiveRow(rows);
    } else if (e.key === "Enter") {
      if (SEARCH_ACTIVE_IDX >= 0 && rows[SEARCH_ACTIVE_IDX]) {
        rows[SEARCH_ACTIVE_IDX].click();
      } else if (rows[0]) {
        rows[0].click();
      }
    }
  }
  function updateActiveRow(rows) {
    rows.forEach((r, i) => r.classList.toggle("active", i === SEARCH_ACTIVE_IDX));
    if (SEARCH_ACTIVE_IDX >= 0 && rows[SEARCH_ACTIVE_IDX]) {
      rows[SEARCH_ACTIVE_IDX].scrollIntoView({ block: "nearest" });
    }
  }

  // ── Plain-text interpretation ("What we think") ──────────────────────
  // Produces { html, flag, label } for a tract or county record.
  function interpretTract(t, parent) {
    const place = `${parent?.county_name || "this county"}, ${parent?.state_abbr || ""}`.trim();
    const wfTrend  = parent?.workforce_trend_pc || t.workforce_trend;
    const bxTrend  = t.burden_trend;
    const tier     = t.digital_readiness_tier;
    const ddi      = t.ddi_composite;
    const bz_first = t.burden_z_first;
    const bz_last  = t.burden_z_last;
    const bz_delta = t.burden_z_delta;

    const wfPhrase  = wfTrendPhrase(wfTrend, "the parent county's cardiology workforce");
    const bxPhrase  = burdenPhrase(bxTrend, bz_first, bz_last, bz_delta);
    const ddiPhrase = ddiPhraseFor(tier, ddi);
    const ddiBlurb  = ddiContext(tier);

    // Decide the "flag" + recommendation
    let flag = "neutral", label = "Mixed signal", action = "";

    if (wfTrend === "insufficient_data" || !wfTrend) {
      flag  = "neutral";
      label = "Insufficient workforce signal";
      action = `Without a defensible county-level cardiology workforce signal, this tract sits outside the deployment / investment classification.`;
    } else if (bxTrend === "increasing" && (wfTrend === "declining" || wfTrend === "stagnant")) {
      // Q1 high risk — sub-classify by tier
      if (tier === "Tier1_high_readiness") {
        flag = "deploy"; label = "Deployment-priority candidate";
        action = `Digital readiness here is high, so this tract may be positioned for <strong>digital health deployment</strong>: telecardiology, remote monitoring, or digital therapeutics may reach patients without new infrastructure investment.`;
      } else if (tier === "Tier3_low_readiness") {
        flag = "invest"; label = "Investment-priority candidate";
        action = `Digital infrastructure is a limiting factor here. This tract is a strong candidate for <strong>investment in digital determinants of health</strong>: broadband expansion, device access, and digital-literacy programs would need to precede or accompany any remote-care rollout.`;
      } else {
        flag = "watch"; label = "Mixed-readiness high risk";
        action = `Digital readiness is in the <strong>middle</strong> tier. A combined approach (infrastructure investment alongside digital health tools) may fit best.`;
      }
    } else if (bxTrend === "increasing" && wfTrend === "growing") {
      flag = "steady"; label = "Recovering";
      action = `Burden is rising but the local cardiology workforce is growing to meet it. Digital tools could augment in-person care.`;
    } else if (bxTrend !== "increasing" && wfTrend === "growing") {
      flag = "steady"; label = "Low risk";
      action = `Both signals are favorable here.`;
    } else if (bxTrend !== "increasing" && (wfTrend === "declining" || wfTrend === "stagnant")) {
      flag = "watch"; label = "Watch";
      action = `Burden is stable, but workforce headwinds warrant monitoring. ${tier === "Tier1_high_readiness" ? "Telecardiology could maintain access as in-person availability declines." : ""}`;
    }

    const sentences = [
      `${capFirst(bxPhrase)} ${wfPhrase}`,
      ddiPhrase,
      action,
    ].filter(Boolean).map(s => s.trim().replace(/\.+$/, "") + ".");

    return {
      flag, label,
      html: `<ul class="summary-list">${sentences.map(s => `<li>${s}</li>`).join("")}</ul>`,
    };
  }

  function interpretCounty(d, tractsInCounty) {
    const wfTrend = d.workforce_trend_pc || d.workforce_trend;
    const bxTrend = d.burden_trend;
    const ddi     = d.mean_ddi_composite;
    const tier    = d.digital_readiness_tier;
    const wfPctChg = (d.workforce_trend_pc && d.rate_first > 0 && d.rate_last != null)
      ? (d.rate_last - d.rate_first) / d.rate_first * 100
      : d.workforce_pct_chg;
    const cards   = d.cards_latest;
    const per100k = d.cards_per_100k_latest;
    const tracts  = Object.values(tractsInCounty || {});

    // Count high-risk tracts split by readiness tier
    let q1 = 0, hi = 0, lo = 0;
    tracts.forEach(r => {
      if (r.quadrant === "Q1_high_risk") {
        q1++;
        if (r.digital_readiness_tier === "Tier1_high_readiness") hi++;
        else if (r.digital_readiness_tier === "Tier3_low_readiness") lo++;
      }
    });

    const wfPhrase  = wfTrendPhrase(wfTrend, "the cardiology workforce", wfPctChg);
    const bxPhrase  = burdenPhrase(bxTrend, d.burden_z_first, d.burden_z_last, d.burden_z_delta);
    const ddiPhrase = ddiPhraseFor(tier, ddi);

    // Build a workforce capacity sentence if available
    const capacity = (cards != null && per100k != null)
      ? `The county had ${fmt.int(cards)} non-federal cardiologists in 2023 (${fmt.num1(per100k)} per 100,000 residents).`
      : "";

    // Determine flag + recommendation
    let flag = "neutral", label = "Mixed signal", action = "";
    if (wfTrend === "insufficient_data") {
      flag = "neutral"; label = "Insufficient workforce signal";
      action = `The county carries too few cardiologists for a defensible workforce trend (mean < 3 across panel years), so it is excluded from the deployment / investment classification at the county level. Burden and readiness signals still apply to individual tracts.`;
    } else if (q1 > 0 && hi > 0 && lo > 0 && Math.min(hi, lo) >= 3) {
      flag = "both"; label = "Bimodal, both buckets";
      action = `Within this county, ${fmt.int(hi)} high-risk tracts sit in the <strong>highest</strong> digital-readiness tier (deployment-priority candidates) while ${fmt.int(lo)} sit in the <strong>lowest</strong> (investment-priority candidates). The two approaches may need to run in parallel, aimed at the specific tracts.`;
    } else if (q1 > 0 && hi >= lo && tier === "Tier1_high_readiness") {
      flag = "deploy"; label = "Deployment-priority candidate";
      action = `Of ${fmt.int(q1)} high-risk tract${q1 === 1 ? "" : "s"} in the county, the majority (${fmt.int(hi)}) sit in the <strong>highest</strong> digital-readiness tier, strong candidates for telecardiology and remote-monitoring deployment.`;
    } else if (q1 > 0 && lo > hi && tier !== "Tier1_high_readiness") {
      flag = "invest"; label = "Investment candidate";
      action = `Of ${fmt.int(q1)} high-risk tract${q1 === 1 ? "" : "s"} in the county, ${fmt.int(lo)} sit in the <strong>lowest</strong> digital-readiness tier. Broadband and digital-literacy investment is the priority before remote-care rollout.`;
    } else if (bxTrend === "increasing" && (wfTrend === "declining" || wfTrend === "stagnant")) {
      flag = "watch"; label = "High risk";
      action = `Burden is <strong>rising</strong> while the workforce is not keeping pace. Tract-level review below distinguishes higher-readiness from lower-readiness pockets within the county.`;
    } else if (wfTrend === "growing" && bxTrend === "increasing") {
      flag = "steady"; label = "Recovering";
      action = `Workforce growth is responding to rising burden.`;
    } else if (wfTrend === "growing") {
      flag = "steady"; label = "Low risk";
      action = `Both signals are favorable.`;
    } else {
      flag = "watch"; label = "Watch";
      action = `Burden is stable but workforce dynamics warrant monitoring.`;
    }

    const sentences = [
      `${capFirst(bxPhrase)} ${wfPhrase}`,
      capacity,
      ddiPhrase,
      action,
    ].filter(Boolean).map(s => s.trim().replace(/\.+$/, "") + ".");

    return {
      flag, label,
      html: `<ul class="summary-list">${sentences.map(s => `<li>${s}</li>`).join("")}</ul>`,
    };
  }

  function wfTrendPhrase(trend, subject, pctChg) {
    if (!trend) return "";
    const t = trend;
    const pct = pctChg != null ? ` (${pctChg > 0 ? "+" : ""}${fmt.num1(pctChg)}% across the panel)` : "";
    if (t === "growing")    return `and ${subject} is <strong>growing</strong>${pct}.`;
    if (t === "declining")  return `and ${subject} is <strong>declining</strong>${pct}.`;
    if (t === "stagnant")   return `and ${subject} is <strong>stagnant</strong>.`;
    if (t === "insufficient_data") return `; workforce trend is not classifiable (too few cardiologists).`;
    return "";
  }

  function burdenPhrase(trend, zFirst, zLast, zDelta) {
    if (!trend || trend === "stable") {
      return zLast != null
        ? `Cardiovascular disease burden is broadly <strong>stable</strong> (composite z = ${fmt.num2(zLast)})`
        : `Cardiovascular disease burden is broadly <strong>stable</strong>`;
    }
    const dir = trend === "increasing" ? "<strong>rising</strong>" : "<strong>improving</strong>";
    if (zFirst != null && zLast != null) {
      return `Cardiovascular disease burden is ${dir} (composite z moved from ${fmt.num2(zFirst)} to ${fmt.num2(zLast)}${zDelta != null ? `, a change of ${zDelta > 0 ? "+" : ""}${fmt.num2(zDelta)}` : ""})`;
    }
    return `Cardiovascular disease burden is ${dir}`;
  }

  function ddiPhraseFor(tier, ddi) {
    if (!tier && ddi == null) return "";
    const score = ddi != null ? ` (DDI = ${fmt.num1(ddi)})` : "";
    if (tier === "Tier1_high_readiness")
      return `Digital readiness is in the <strong>top</strong> national tier${score}, among the best-served tracts in the country.`;
    if (tier === "Tier3_low_readiness")
      return `Digital readiness is in the <strong>bottom</strong> national tier${score}, among the most digitally underserved tracts in the country.`;
    if (tier === "Tier2_moderate_readiness")
      return `Digital readiness is in the <strong>middle</strong> national tier${score}.`;
    return ddi != null ? `Mean Digital Divide Index is ${fmt.num1(ddi)}.` : "";
  }

  function ddiContext(tier) {
    return ({
      "Tier1_high_readiness": "Broadband adoption, device access, and socioeconomic supports for digital use are strong.",
      "Tier2_moderate_readiness": "",
      "Tier3_low_readiness": "Broadband, devices, and digital literacy are the limiting factors.",
    })[tier] || "";
  }

  function capFirst(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  // ── priority targeting UI ──────────────────────────────────────────────────
  function priorityCountyClass(d) {
    if (!d || !d.priority_in_pool) return { cls: "not_pool", label: "Not workforce-constrained" };
    const cls = d.priority_county_class || "high_need_other";
    return { cls, label: PRIORITY_CLASS_LABEL[cls] || "Workforce-constrained" };
  }
  function priorityBadge({ cls, label }) {
    return `<span class="quadrant-badge ${cls}">${escape(label)}</span>`;
  }
  function poolReasonLabel(r) {
    return ({ no_cardiologist: "No cardiologists (latest year)",
              declining_workforce: "Declining cardiology workforce" })[r] || "—";
  }
  function priorityCountySection(d) {
    if (!d || !d.priority_in_pool) {
      return `<div class="section-title">Digital Health Prioritization</div>
        <p style="color:var(--text-mute);font-size:12.5px;margin:2px 0 4px">
          This county is not in the workforce-constrained pool (it has an adequate, non-declining
          cardiology workforce), so it is not classified into the priority groups.</p>`;
    }
    const nd = d.priority_n_deploy || 0, ni = d.priority_n_invest || 0;
    return `
      <div class="section-title">Digital Health Prioritization</div>
      <div class="kv-grid">
        <div class="k">Workforce-constrained reason</div>          <div class="v">${poolReasonLabel(d.priority_pool_reason)}</div>
        <div class="k"><span class="dot" style="background:${PRIORITY.deploy}"></span>Deployment-priority tracts</div>
                                                        <div class="v">${fmt.int(nd)}</div>
        <div class="k"><span class="dot" style="background:${PRIORITY.invest}"></span>Investment-priority tracts</div>
                                                        <div class="v">${fmt.int(ni)}</div>
      </div>
      <p class="priority-hint">${priorityCountyHint(d.priority_county_class, nd, ni)}</p>`;
  }
  function priorityCountyHint(cls, nd, ni) {
    if (cls === "mixed")
      return `Bimodal: this county holds <strong>both</strong> deployment-priority and
        investment-priority tracts. Aim each approach at the specific tracts below.`;
    if (cls === "deploy_lean")
      return `Deployment-lean: its highest-need tracts carry higher readiness, so
        digital health tools may be positioned to reach patients now.`;
    if (cls === "invest_lean")
      return `Investment-lean: its highest-need tracts carry lower readiness, so
        broadband, device, and digital-literacy investment may need to come first.`;
    return `Workforce-constrained, but none of its tracts sits above the national-average burden cut.`;
  }
  function priorityTractClass(t) {
    const b = t && t.priority_bucket;
    if (!b) return { cls: "not_pool", label: "Not a priority tract" };
    return { cls: b, label: PRIORITY_CLASS_LABEL[b] || b };
  }
  function priorityTractSection(t) {
    const b = t && t.priority_bucket;
    if (!b || b === "pool_other") {
      const inPoolNote = b === "pool_other"
        ? "This tract's parent county is workforce-constrained, but its burden sits at or below the national average, so it falls outside both priority groups."
        : "This tract is not in the workforce-constrained pool.";
      return `<div class="section-title">Digital Health Prioritization</div>
        <p style="color:var(--text-mute);font-size:12.5px;margin:2px 0 4px">${inPoolNote}</p>`;
    }
    const isDeploy = (b === "deploy" || b === "both");
    const rank  = isDeploy ? t.priority_deploy_rank : t.priority_invest_rank;
    const total = isDeploy
      ? (PRIORITY_SUMMARY?.tracts?.n_deploy_ranked ?? PRIORITY_SUMMARY?.tracts?.n_deploy)
      : (PRIORITY_SUMMARY?.tracts?.n_invest_ranked ?? PRIORITY_SUMMARY?.tracts?.n_invest);
    const color = isDeploy ? PRIORITY.deploy : PRIORITY.invest;
    const head  = isDeploy ? "Deployment priority" : "Investment priority";
    const blurb = isDeploy
      ? "<strong>High</strong> cardiovascular burden with higher digital readiness: this tract may be positioned for telecardiology and remote-monitoring deployment."
      : "<strong>High</strong> cardiovascular burden with lower digital readiness: this tract may require broadband, device-access, and digital-literacy investment alongside any remote-care effort.";
    const rankCell = t.priority_single_measure
      ? `<span title="Kentucky and Pennsylvania tracts hold box membership but are not ranked">Not ranked</span>`
      : (rank != null ? "#" + fmt.int(rank) + (total ? " of " + fmt.int(total) : "") : "—");
    const smNote = t.priority_single_measure
      ? `<p class="priority-hint">This tract keeps its priority classification, but its burden score
         rests on <strong>short sleep alone</strong> (CDC suppressed the other nine
         PLACES measures in this state). It is not ranked against the
         10-measure national lists.</p>`
      : "";
    return `
      <div class="section-title" style="color:${color};border-bottom-color:${color}44">Digital Health Prioritization</div>
      <div class="kv-grid">
        <div class="k">Bucket</div>       <div class="v" style="color:${color};font-weight:600">${head}</div>
        <div class="k">National rank</div> <div class="v">${rankCell}</div>
        <div class="k">DDI</div>          <div class="v">${valOrNull(t.priority_ddi, fmt.num1)}</div>
        <div class="k">Burden z</div>     <div class="v">${valOrNull(t.priority_burden_z, fmt.num2)}</div>
      </div>
      <p class="priority-hint">${blurb}</p>${smNote}`;
  }
  function shortBucket(b) {
    if (!b) return "—";
    const map = {
      deploy: `<span class="trend-pill" style="background:rgba(31,95,166,.13);color:${PRIORITY.deploy}">Deployment</span>`,
      both:   `<span class="trend-pill" style="background:rgba(31,95,166,.13);color:${PRIORITY.deploy}">Deployment*</span>`,
      invest: `<span class="trend-pill" style="background:rgba(193,39,45,.12);color:${PRIORITY.invest}">Investment</span>`,
      pool_other: `<span class="trend-pill unclassified">—</span>`,
    };
    return map[b] || "—";
  }

  // ── UI helpers ───────────────────────────────────────────────────────
  function trendPill(t) {
    if (!t) return `<span class="kv-null">—</span>`;
    return `<span class="trend-pill ${t}">${t.replace(/_/g, " ")}</span>`;
  }
  function tierPill(t) {
    if (!t) return `<span class="kv-null">—</span>`;
    const label = ({ "Tier1_high_readiness": "High readiness",
                     "Tier2_moderate_readiness": "Moderate",
                     "Tier3_low_readiness": "Low readiness" })[t] || t;
    return `<span class="tier-pill ${t}">${label}</span>`;
  }
  function shortQuad(q) {
    if (!q || q === "unclassified") return '<span class="trend-pill unclassified">—</span>';
    return `<span class="trend-pill" style="background:${COLORS[q]}1A;color:${COLORS[q]}">${q.split("_")[0]}</span>`;
  }
  function shortTier(t) {
    if (!t) return "—";
    return ({ "Tier1_high_readiness": "T1", "Tier2_moderate_readiness": "T2",
              "Tier3_low_readiness": "T3" })[t] || t;
  }
  function valOrNull(v, fn) {
    if (v == null || v === "" || (typeof v === "number" && isNaN(v)))
      return '<span class="v null">—</span>';
    return fn ? fn(v) : escape(v);
  }
  function ruralUrbanLabel(c) {
    if (c == null) return "—";
    const n = Number(c);
    if (n >= 1 && n <= 3) return `${c} (Metro)`;
    if (n >= 4 && n <= 9) return `${c} (Non-metro)`;
    return String(c);
  }
  function showTractStatus(t) { $tractStatus.textContent = t; $tractStatus.hidden = false; }
  function hideTractStatus()  { $tractStatus.hidden = true; }
  function hideLoading()      { $loading.classList.add("hidden"); }
  function showError(msg) {
    $loading.innerHTML = `<div style="text-align:center;color:#c1272d;max-width:280px">
        <div style="font-size:18px;font-weight:600">${escape(msg)}</div></div>`;
  }
  function debounce(fn, ms) {
    let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
  }

  // ── Walkthrough hooks (used by tour-steps.js) ───────────────────────
  window.__dash = {
    selectCounty, deselectCounty, resetView,
    showTract: (parentFips, tfips) => renderTractPanel(tfips, parentFips),
    tractData: () => TRACT_DATA,
    map: () => MAP,
    clickMetric: m => {
      const b = document.querySelector(`#views-bar button[data-m="${m}"]`);
      if (b) b.click();
    },
  };

  // ── Go ───────────────────────────────────────────────────────────────
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", main);
  else
    main();
})();
