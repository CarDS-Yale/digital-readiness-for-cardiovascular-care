/* tour-steps.js — the guided walkthrough for the county atlas.
   Uses ../tour.js (MiniTour) and the window.__dash hooks in app.js. */
(function () {
  "use strict";
  const { Tour, offer, sleep } = window.MiniTour;
  const D = () => window.__dash;
  const sw = c => `<span class="mt-sw" style="background:${c}"></span>`;

  const COOK = "17031";

  async function waitFor(fn, ms = 8000, step = 200) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try { if (fn()) return true; } catch (e) {}
      await sleep(step);
    }
    return false;
  }

  const steps = [
    {
      place: "center",
      title: "Welcome to the atlas",
      html: `This map shows cardiology workforce, cardiovascular disease burden,
        and digital readiness for every US county, with census-tract detail
        underneath. The tour takes about two minutes. The map drives itself;
        you just click <b>Next</b>. Press <b>Esc</b> anytime to exit.`,
    },
    {
      target: "#views-bar .vgroup:nth-child(1)",
      title: "Digital divide views",
      html: `The map opens on the <b>Composite DDI</b>, the Digital Divide Index.
        ${sw("#1f5fa6")}Blue counties carry higher digital readiness and ${sw("#c1272d")}red
        counties face a wide divide. The other two buttons show its parts:
        the infrastructure sub-score and the socioeconomic sub-score.`,
    },
    {
      target: "#views-bar .vgroup:nth-child(2)",
      title: "Workforce views",
      before: async () => D().clickMetric("cards_per_100k_latest"),
      html: `The map now shows <b>cardiologists per 100,000 residents</b>.
        ${sw("#8f1e24")}Red counties have few or none and ${sw("#1f5fa6")}blue
        counties have the most. The other buttons add cardiology NPs and PAs,
        show primary care physicians, or show the per-capita workforce trend
        over time.`,
    },
    {
      target: "#views-bar .vgroup:nth-child(3)",
      title: "Disease burden views",
      before: async () => D().clickMetric("burden_z_last"),
      html: `This is the <b>composite cardiometabolic burden</b> from the main
        analysis: ten conditions and risk factors folded into one z-score.
        ${sw("#8f1e24")}Red = above-average burden. Kentucky and Pennsylvania
        show as grey; their tract burden rests on short sleep alone. The
        dropdown maps any single disease instead.`,
    },
    {
      target: "#kpi-bar",
      title: "The national headline numbers",
      html: `These cards summarize the prioritization analysis: <b>2,582</b> workforce-constrained
        counties, holding ${sw("#1f5fa6")}<b>4,765</b> deployment-priority tracts
        (high burden, higher readiness) and ${sw("#c1272d")}<b>21,752</b>
        investment-priority tracts (high burden, lower readiness).`,
    },
    {
      target: "#legend",
      title: "The legend follows the view",
      before: async () => D().clickMetric("mean_ddi_composite"),
      html: `Whatever view you pick, this corner explains the colors and the
        value range. Grey always means no data.`,
    },
    {
      target: ".search-wrap",
      title: "Find any county",
      html: `Type a county name or 5-digit FIPS code here to jump straight to
        it. An empty search lists <b>mixed</b> counties, the interesting ones
        that hold both deployment-priority and investment-priority tracts.`,
    },
    {
      target: "#map",
      title: "Inside a county: census tracts",
      before: async () => {
        D().selectCounty(COOK, { zoom: true });
        await waitFor(() => { try { return !!D().map().getLayer("tracts-fill"); } catch (e) { return false; } }, 7000);
        await sleep(900);
      },
      html: `We zoomed into <b>Cook County, IL</b> (Chicago). Each shape is one
        census tract. ${sw("#1f5fa6")}Solid blue tracts are <b>deployment
        priority</b> and ${sw("#c1272d")}solid red tracts are <b>investment
        priority</b>. Every other tract shades by its lean: blue toward higher
        readiness, ${sw("#6f4d8f")}purple near the national median, red toward
        lower readiness.
        Deeper color = higher burden.`,
    },
    {
      target: "#side-panel",
      title: "The tract profile",
      before: async () => {
        await waitFor(() => D().tractData() && D().tractData()[COOK], 10000);
        const td = D().tractData()[COOK] || {};
        const pick = Object.keys(td).find(k => td[k].priority_bucket === "invest")
                  || Object.keys(td).find(k => td[k].priority_bucket === "deploy")
                  || Object.keys(td)[0];
        if (pick) D().showTract(COOK, pick);
        await sleep(350);
      },
      html: `Clicking any tract fills this panel: a plain-language read at the
        top, then its priority group and national rank, disease burden,
        Digital Divide scores, and the county workforce behind it. The tract
        table at the bottom of the county view lists every tract; click any
        row to jump to it.`,
    },
    {
      target: "#map",
      title: "Back to the whole country",
      before: async () => { D().resetView(); await sleep(1300); },
      html: `Click any empty map area, press <b>Esc</b>, or close the panel to
        return to the national view. Zoom and pan work like any web map.`,
    },
    {
      target: "#tour-btn",
      title: "That is the tour",
      html: `Restart it anytime from this <b>Tour</b> button. The <b>About</b>
        button next to it holds the full methods, data sources, and
        limitations. Happy exploring.`,
    },
  ];

  const tour = new Tour({
    key: "map",
    steps,
    onEnd: () => {
      try {
        D().deselectCounty();
        D().clickMetric("mean_ddi_composite");
        D().resetView();
      } catch (e) {}
    },
  });

  document.getElementById("tour-btn").addEventListener("click", () => tour.start());

  offer({
    key: "map",
    title: "Take a quick tour?",
    body: `New here? A two-minute walkthrough shows the map views, zooms into a
      county, and explains what the colors and panels mean. The map drives
      itself; you just click Next.`,
    onStart: () => tour.start(),
  });
})();
