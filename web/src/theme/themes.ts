/**
 * The site's colours, in one place (docs/react-site-plan.md §5, P7-01 mockups).
 *
 *   SITE         neutrals, the floodlight-yellow site accent, outcome
 *                (home/draw/away) and profit/loss colours - the same on
 *                every page, separate from league colours
 *   LEAGUES      one theme per competition in the registry, plus FALLBACK
 *                for any code it doesn't know and for non-league pages
 *   themeCss()   generates the CSS custom properties from both
 *   plotColors() the same values as hex, for Observable Plot
 *
 * Light and dark follow the OS (decision R8); data-mode="light" | "dark" on
 * <html> overrides it (for a toggle later). League colours apply under
 * <html data-league="e0">, set at build time, so the first paint is right.
 *
 * Values are the P7-01 sign-off, with the adjustments the P7-04 checks
 * required (theme.contrast.test.ts) - see the notes on each.
 */

import { mix } from "./color";

export type Mode = "light" | "dark";
export const MODES: readonly Mode[] = ["light", "dark"];

// ============================================================
// SITE-WIDE
// ============================================================

export interface SitePalette {
  bg: string;
  surface: string;
  text: string;
  muted: string;
  line: string;
  /** Hover / selected row background. */
  tint: string;
  home: string;
  draw: string;
  away: string;
  /** Label text on a solid outcome segment. */
  onHome: string;
  onDraw: string;
  onAway: string;
  /** Background for a probability segment that isn't the pick; label text is `text`. */
  homeTint: string;
  drawTint: string;
  awayTint: string;
  /** Profit and loss. */
  pos: string;
  neg: string;
  /** Floodlight yellow: focus rings, non-league pages. */
  site: string;
  /** The site accent as text on the surface. */
  siteText: string;
  /** Inner ring inside the yellow focus outline, so focus shows on light surfaces too. */
  focusInner: string;
}

/**
 * Outcome colours: a diverging scheme, home (blue) and away (orange) poles
 * with a neutral grey draw between them, as they sit in the probability
 * strip. Checked with the dataviz validator (P7-04): CVD separation of
 * adjacent pairs >= 15 ΔE in both modes; every mark >= 3:1 on the surface.
 * P7-04 nudged lightness only (hue and chroma kept): light draw #A7ADB7 ->
 * #8F959F and away #E27A1F -> #E1791E (both were under 3:1 on white); dark
 * away #F08F3A -> #D8791C (above the dark-mode lightness band) and draw
 * #5E6470 -> #626874 (under 3:1).
 */
const LIGHT_OUTCOME = { home: "#2C66D2", draw: "#8F959F", away: "#E1791E" };
const DARK_OUTCOME = { home: "#5A8EEA", draw: "#626874", away: "#D8791C" };

// Off-pick segments: the outcome colour mixed into a base. Dark mode mixes
// into #3A3F49 (P7-01 used #4A505C, which left text under 4.5:1 on the
// home and away tints).
const LIGHT_TINT = { base: "#FFFFFF", share: 0.28 };
const DARK_TINT = { base: "#3A3F49", share: 0.45 };

function sitePalette(
  neutrals: Pick<SitePalette, "bg" | "surface" | "text" | "muted" | "line" | "tint">,
  outcome: typeof LIGHT_OUTCOME,
  tint: typeof LIGHT_TINT,
  rest: Pick<SitePalette, "onHome" | "onDraw" | "onAway" | "pos" | "neg" | "site" | "siteText" | "focusInner">,
): SitePalette {
  return {
    ...neutrals,
    ...outcome,
    homeTint: mix(outcome.home, tint.base, tint.share),
    drawTint: mix(outcome.draw, tint.base, tint.share),
    awayTint: mix(outcome.away, tint.base, tint.share),
    ...rest,
  };
}

export const SITE: Record<Mode, SitePalette> = {
  light: sitePalette(
    { bg: "#F4F5F7", surface: "#FFFFFF", text: "#1A1D23", muted: "#5A606B", line: "#DADDE3", tint: "#EEF0F3" },
    LIGHT_OUTCOME,
    LIGHT_TINT,
    {
      onHome: "#FFFFFF",
      onDraw: "#1A1D23",
      onAway: "#1A1D23",
      pos: "#1A7F4E",
      neg: "#C23B2E",
      site: "#FFD23F",
      siteText: "#7A5C00",
      focusInner: "#1A1D23",
    },
  ),
  dark: sitePalette(
    { bg: "#121419", surface: "#1A1D24", text: "#E8EAEE", muted: "#9AA0AC", line: "#2C3039", tint: "#22262E" },
    DARK_OUTCOME,
    DARK_TINT,
    {
      onHome: "#0E1626",
      onDraw: "#E8EAEE",
      // #1A1D23 in P7-01; the darker away needs the deeper ink for 4.5:1
      onAway: "#0E1626",
      pos: "#3CC07E",
      neg: "#F06A5C",
      site: "#FFD23F",
      siteText: "#FFD23F",
      focusInner: "#1A1D24",
    },
  ),
};

// ============================================================
// LEAGUES
// ============================================================

export interface LeagueTheme {
  /** Registry code ("E0") and URL slug ("e0"); "fallback" for the fallback. */
  div: string;
  slug: string;
  /** Short text mark (R2: no logos). */
  mark: string;
  /** League band (scoreboard) background and its text. Same in both modes. */
  band: string;
  onBand: string;
  /** Fills: gameweek tab, active chip, swatch. */
  accent: string;
  onAccent: string;
  /** League colour as text / thin graphics (tab underline) on the surface. */
  accentText: Record<Mode, string>;
  /** League colour as a chart series on the surface. */
  chart: Record<Mode, string>;
}

const league = (t: LeagueTheme): LeagueTheme => t;

/**
 * Evocative approximations, hues shifted off official values (R2). P7-01
 * signed these off; EL and ECL are P7-04 additions (no pages yet - they
 * appear only as clubs' European competitions).
 */
export const LEAGUES: Record<string, LeagueTheme> = {
  E0: league({
    div: "E0", slug: "e0", mark: "PL", band: "#37003C", onBand: "#FFFFFF", accent: "#00FF85", onAccent: "#1A0020",
    accentText: { light: "#C4004A", dark: "#00FF85" }, chart: { light: "#7A1C8C", dark: "#04F5FF" },
  }),
  SP1: league({
    div: "SP1", slug: "sp1", mark: "LL", band: "#1B1F3B", onBand: "#FFFFFF", accent: "#FF4B44", onAccent: "#1B1F3B",
    accentText: { light: "#C0241C", dark: "#FF6B64" }, chart: { light: "#C0241C", dark: "#FFB400" },
  }),
  D1: league({
    // Band red, not ink: black ink is too close to the dark background.
    // Accent #1A1A1A -> #0A0A0A in P7-04 (the tab needs 3:1 on the red band).
    div: "D1", slug: "d1", mark: "BL", band: "#C8061A", onBand: "#FFFFFF", accent: "#0A0A0A", onAccent: "#FFFFFF",
    accentText: { light: "#B00012", dark: "#FF5A66" }, chart: { light: "#1A1A1A", dark: "#C9CCD1" },
  }),
  I1: league({
    div: "I1", slug: "i1", mark: "SA", band: "#0B1E4A", onBand: "#FFFFFF", accent: "#2FD4A3", onAccent: "#0B1E4A",
    accentText: { light: "#0A58CA", dark: "#5B9BFF" }, chart: { light: "#0A58CA", dark: "#2FD4A3" },
  }),
  F1: league({
    div: "F1", slug: "f1", mark: "L1", band: "#0B1F3A", onBand: "#FFFFFF", accent: "#D4F01E", onAccent: "#0B1F3A",
    accentText: { light: "#00706F", dark: "#D4F01E" }, chart: { light: "#00706F", dark: "#00B3B3" },
  }),
  P1: league({
    div: "P1", slug: "p1", mark: "LP", band: "#0A2A5E", onBand: "#FFFFFF", accent: "#00B2A9", onAccent: "#0A2A5E",
    accentText: { light: "#006E69", dark: "#2FD1C7" }, chart: { light: "#006E69", dark: "#F2C200" },
  }),
  N1: league({
    div: "N1", slug: "n1", mark: "ERE", band: "#0E2240", onBand: "#FFFFFF", accent: "#FF6A13", onAccent: "#0E2240",
    accentText: { light: "#B83A0B", dark: "#FF8A45" }, chart: { light: "#B83A0B", dark: "#3B82F6" },
  }),
  CL: league({
    // Cyan accent: violet on navy was too low-contrast (P7-01); violet kept for light-mode text
    div: "CL", slug: "cl", mark: "UCL", band: "#0A0F3D", onBand: "#FFFFFF", accent: "#00D2FF", onAccent: "#0A0F3D",
    accentText: { light: "#3A1FB8", dark: "#00D2FF" }, chart: { light: "#4C2BD9", dark: "#00D2FF" },
  }),
  EL: league({
    div: "EL", slug: "el", mark: "UEL", band: "#1F1A14", onBand: "#FFFFFF", accent: "#FF8A1F", onAccent: "#1F1A14",
    accentText: { light: "#A14A00", dark: "#FF9E45" }, chart: { light: "#A14A00", dark: "#FF9E45" },
  }),
  ECL: league({
    div: "ECL", slug: "ecl", mark: "UECL", band: "#0F2A1F", onBand: "#FFFFFF", accent: "#3BE07A", onAccent: "#0F2A1F",
    accentText: { light: "#137A3E", dark: "#5BE892" }, chart: { light: "#137A3E", dark: "#5BE892" },
  }),
};

/** For a code the registry doesn't know, and for pages without a league (/, /about, /ratings). */
export const FALLBACK: LeagueTheme = league({
  div: "fallback", slug: "fallback", mark: "FP", band: "#16181D", onBand: "#FFFFFF", accent: "#FFD23F", onAccent: "#1A1D23",
  accentText: { light: "#7A5C00", dark: "#FFD23F" }, chart: { light: "#5A606B", dark: "#FFD23F" },
});

/** The theme for a Div ("E0") or slug ("e0"); FALLBACK for anything else. */
export function themeFor(divOrSlug: string | null | undefined): LeagueTheme {
  if (!divOrSlug) return FALLBACK;

  const key = divOrSlug.toUpperCase();
  return LEAGUES[key] ?? Object.values(LEAGUES).find((t) => t.slug === divOrSlug.toLowerCase()) ?? FALLBACK;
}

/** The value for <html data-league>: the league's slug, or "fallback". */
export function leagueAttr(divOrSlug: string | null | undefined): string {
  return themeFor(divOrSlug).slug;
}

// ============================================================
// CSS
// ============================================================

const kebab = (name: string) => name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

function declarations(values: Record<string, string>, prefix = ""): string {
  return Object.entries(values)
    .map(([name, value]) => `  --${prefix}${kebab(name)}: ${value};`)
    .join("\n");
}

function leagueDeclarations(t: LeagueTheme, mode: Mode): string {
  return declarations(
    {
      band: t.band,
      onBand: t.onBand,
      accent: t.accent,
      onAccent: t.onAccent,
      accentText: t.accentText[mode],
      chart: t.chart[mode],
    },
    "lg-",
  );
}

function selectors(theme: LeagueTheme): string {
  const attr = `[data-league="${theme.slug}"]`;
  // The fallback also covers a page that sets no data-league at all
  return theme === FALLBACK ? `:root, ${attr}` : attr;
}

/** --series-1 ... --series-7, for HTML legends next to charts. */
const seriesVars = (mode: Mode) => Object.fromEntries(SERIES[mode].map((c, i) => [`series-${i + 1}`, c]));

/**
 * Every custom property, light then dark:
 *
 *   :root                    --bg, --surface, --text, --home, --pos, --site...
 *   [data-league="e0"]       --lg-band, --lg-accent, --lg-accent-text, --lg-chart...
 *
 * Dark applies under prefers-color-scheme: dark unless data-mode="light",
 * and always under data-mode="dark".
 */
export function themeCss(): string {
  const themes = [FALLBACK, ...Object.values(LEAGUES)];

  const block = (mode: Mode, scope: (selector: string) => string) =>
    [
      `${scope(":root")} {\n${declarations({ ...SITE[mode], ...seriesVars(mode) })}\n}`,
      ...themes.map((t) => `${selectors(t).split(", ").map(scope).join(", ")} {\n${leagueDeclarations(t, mode)}\n}`),
    ].join("\n");

  const darkBySystem = (selector: string) =>
    selector === ":root" ? ":root:not([data-mode=\"light\"])" : `:root:not([data-mode="light"]) ${selector}, :root:not([data-mode="light"])${selector}`;
  const darkByChoice = (selector: string) =>
    selector === ":root" ? ":root[data-mode=\"dark\"]" : `:root[data-mode="dark"] ${selector}, :root[data-mode="dark"]${selector}`;

  return [
    "/* Generated by src/theme/themes.ts - edit the values there */",
    ":root { color-scheme: light dark; }",
    ':root[data-mode="light"] { color-scheme: light; }',
    ':root[data-mode="dark"] { color-scheme: dark; }',
    block("light", (s) => s),
    `@media (prefers-color-scheme: dark) {\n${block("dark", darkBySystem)}\n}`,
    block("dark", darkByChoice),
  ].join("\n\n");
}

// ============================================================
// CATEGORICAL SERIES
// ============================================================

/**
 * For charts whose series are entities rather than outcomes or leagues:
 * clubs on the rating-history chart, league lines on the offsets chart.
 * The dataviz skill's reference palette, slots 1-7 in fixed order (never
 * cycled; colour follows the entity, not its rank). Validated with its
 * validate_palette.js on this site's page backgrounds (P7-09):
 *   light on #F4F5F7  CVD worst adjacent ΔE 9.1, normal 19.6; slots 2-5
 *                     are under 3:1, so every use carries direct labels
 *                     or a table (the validator's required relief)
 *   dark on #121419   CVD 8.4, normal 19.3, all >= 3:1
 */
export const SERIES: Record<Mode, readonly string[]> = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
};

// ============================================================
// PLOT
// ============================================================

export interface PlotColors {
  /** Outcome colours by result code. */
  outcome: { H: string; D: string; A: string };
  pos: string;
  neg: string;
  /** The league's own series colour; FALLBACK's when there's no league. */
  league: string;
  text: string;
  muted: string;
  line: string;
  surface: string;
  /** Categorical slots (SERIES), in order. */
  series: readonly string[];
}

/**
 * Hex values for Observable Plot, which takes colours as values rather
 * than CSS variables. A chart island renders once per mode it may be seen
 * in, or re-renders when the mode changes, with these.
 */
export function plotColors(divOrSlug: string | null | undefined, mode: Mode): PlotColors {
  const site = SITE[mode];

  return {
    outcome: { H: site.home, D: site.draw, A: site.away },
    pos: site.pos,
    neg: site.neg,
    league: themeFor(divOrSlug).chart[mode],
    text: site.text,
    muted: site.muted,
    line: site.line,
    surface: site.surface,
    series: SERIES[mode],
  };
}
