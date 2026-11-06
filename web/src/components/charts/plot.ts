/**
 * Observable Plot (and the d3 it bundles), loaded on demand.
 *
 * Nothing imports Plot statically: PlotFigure calls loadPlot() once a chart
 * is on screen, so Plot + d3 end up in their own chunk that only chart pages
 * download, after the page's HTML and the island's own code. Chart specs get
 * the module through ChartContext.Plot and import Plot *types* only.
 * plotSubset.ts lists the functions they may use, so the chunk carries only
 * those (P7-11).
 */

export type PlotModule = typeof import("./plotSubset");

let pending: Promise<PlotModule> | undefined;

export function loadPlot(): Promise<PlotModule> {
  pending ??= import("./plotSubset").catch((error: unknown) => {
    // Let the next chart try again (e.g. after a flaky connection)
    pending = undefined;
    throw error;
  });
  return pending;
}
