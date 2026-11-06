/**
 * The part of Observable Plot the site's charts use (P7-11 JS budget).
 *
 * plot.ts imports this module, not "@observablehq/plot" itself: a dynamic
 * import of the package keeps every mark, transform and the d3 behind them,
 * while named re-exports let the bundler drop what no chart calls. Using a
 * Plot function that isn't listed here is a type error in the spec; add it
 * below.
 */
export {
  areaY,
  barX,
  barY,
  dot,
  line,
  lineY,
  plot,
  pointer,
  pointerX,
  pointerY,
  rectY,
  ruleX,
  ruleY,
  text,
  tickY,
  tip,
} from "@observablehq/plot";
