/**
 * Checks a NanoPlot report as ARVA serves it, in headless Chromium: with the sandboxed report CSP the
 * embedded plotly.js draws every plot without script errors; the page runs in an opaque origin, cannot
 * script a same-origin window, and requests nothing from any other host, not even when page scripts try
 * (a probe fetch and image must be blocked by the CSP).
 *
 *   node scripts/check_nanoplot_report.cjs <URL of /jobs/{id}/outputs/<prefix>NanoPlot-report.html>
 *   node scripts/check_nanoplot_report.cjs <report.html> <headers.json>
 *
 * The second form serves the saved report with the saved response headers (see the API test
 * test_nanoplot_report_in_chromium). Prints a JSON summary; exits 1 if a check fails.
 */
const { main } = require("./report_browser_check.cjs");

main(
  "check_nanoplot_report.cjs",
  {
    renderSelector: ".js-plotly-plot .main-svg",
    measure: () => ({
      graphDivs: document.querySelectorAll(".plotly-graph-div").length,
      plots: document.querySelectorAll(".js-plotly-plot").length,
      plotsWithSvg: [...document.querySelectorAll(".js-plotly-plot")].filter((p) => p.querySelector(".main-svg")).length,
      summaryRows: document.querySelectorAll("table tr").length,
    }),
    probeFetch: "https://cdn.plot.ly/plotly-3.7.0.min.js",
    probeImage: "https://tile.openstreetmap.org/0/0/0.png",
  },
  (r) => {
    const failures = [];
    if (r.rendered.graphDivs === 0 || r.rendered.plotsWithSvg !== r.rendered.graphDivs) failures.push(`plots not rendered: ${JSON.stringify(r.rendered)}`);
    if (r.rendered.summaryRows === 0) failures.push("summary table is empty");
    return failures;
  },
);
