/* tour-steps.js — the guided walkthrough for the decision-space scatter.
   Uses ../tour.js (MiniTour) and the window.__ds hooks in index.html. */
(function () {
  "use strict";
  const { Tour, offer, sleep } = window.MiniTour;
  const sw = c => `<span class="mt-sw" style="background:${c}"></span>`;

  async function ready(ms = 12000) {
    const t0 = Date.now();
    while (!window.__ds && Date.now() - t0 < ms) await sleep(200);
    return window.__ds;
  }

  // a mid-chart investment tract for the hover and click demos
  function demoTract() {
    return window.__ds.find(t => t.bucket === 2 && t.rank === 40)
        || window.__ds.find(t => t.bucket === 2 && t.rank != null)
        || window.__ds.find(t => t.bucket === 1);
  }

  const steps = [
    {
      place: "center",
      title: "Welcome to the decision space",
      html: `Every dot is one census tract from the workforce-constrained county pool,
        placed by digital readiness and disease burden. This tour takes about
        two minutes; the chart drives itself and you click <b>Next</b>.
        Press <b>Esc</b> anytime to exit.`,
    },
    {
      target: "#chart",
      title: "How to read the chart",
      before: async () => { await ready(); },
      html: `Left to right runs the <b>Digital Divide Index</b>: further right,
        worse readiness. Bottom to top runs <b>cardiometabolic burden</b>.
        The dashed lines mark the two national cuts. Above the burden line,
        ${sw("#1f5fa6")}blue dots left of the median are <b>deployment-priority
        tracts</b> (higher readiness) and ${sw("#c1272d")}red dots to the right
        are <b>investment-priority tracts</b> (lower readiness).
        ${sw("#b7bcc3")}Grey dots are pool tracts outside both boxes.
        Kentucky and Pennsylvania are not plotted; their burden score rests
        on short sleep alone.`,
    },
    {
      target: "#kpis",
      title: "The headline numbers",
      html: `The manuscript totals: <b>49,948</b> workforce-constrained tracts, split into
        ${sw("#1f5fa6")}<b>4,765</b> deployment-priority tracts and
        ${sw("#c1272d")}<b>21,752</b> investment-priority tracts, against a national
        median DDI of <b>18.8</b>.`,
    },
    {
      target: "#legend",
      title: "Show or hide each group",
      html: `These chips count the plotted dots. Click one to hide that group
        and declutter the view; click again to bring it back.`,
    },
    {
      target: "#chart",
      title: "Hover any dot",
      before: async () => {
        await ready();
        window.__ds.hover(demoTract());
        await sleep(400);
      },
      html: `Point at any dot and it grows, with a mini profile: the tract,
        its county, its DDI and burden values, and its national rank. We are
        hovering a high-ranked investment-priority tract right now.`,
    },
    {
      target: "#panel",
      title: "Click for the full profile",
      before: async () => {
        await ready();
        window.__ds.select(demoTract());
        await sleep(400);
      },
      html: `A click opens this panel: a plain-language read of the tract, its
        priority group and rank, disease burden detail, Digital Divide
        sub-scores, and the parent county's cardiology workforce. Close it
        with the ✕, the <b>Esc</b> key, or a click on empty space.`,
    },
    {
      target: "#hl",
      title: "Highlight the leading tracts",
      before: async () => {
        await ready();
        window.__ds.deselect();
        window.__ds.clickSeg(10);
        await sleep(450);
      },
      html: `This control spotlights the highest-ranked tracts. We turned on the
        <b>top 10</b>: the field fades and the ten leading deployment-priority
        and investment-priority tracts pop. Try 50 or 100 for a wider cut, and use the
        ${sw("#1f5fa6")}Deployment / ${sw("#c1272d")}Investment switches to show
        either group alone.`,
    },
    {
      target: "#chart",
      title: "Back to the full picture",
      before: async () => {
        window.__ds.clickSeg(0);
        await sleep(350);
      },
      html: `Highlight off, every tract back in view. Explore freely: hover,
        click, toggle. Nothing you do here changes the data.`,
    },
    {
      target: "#tour-btn",
      title: "That is the tour",
      html: `Restart it anytime from this <b>Tour</b> button. The <b>About</b>
        button next to it holds the methods, data sources, and limitations.
        Happy exploring.`,
    },
  ];

  const tour = new Tour({
    key: "decision-space",
    steps,
    onEnd: () => {
      try {
        window.__ds.deselect();
        window.__ds.clickSeg(0);
      } catch (e) {}
    },
  });

  document.getElementById("tour-btn").addEventListener("click", () => tour.start());

  offer({
    key: "decision-space",
    title: "Take a quick tour?",
    body: `New here? A two-minute walkthrough explains the axes and colors,
      demos hover and click, and shows the leading-tract highlighter. The chart
      drives itself; you just click Next.`,
    onStart: () => tour.start(),
  });
})();
