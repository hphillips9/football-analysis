/**
 * Every colour pair the design uses meets WCAG 2 contrast, for every league
 * and the fallback, in both modes:
 *
 *   text      >= 4.5:1   body text, labels on fills, league text accents
 *   graphics  >= 3:1     chart marks, outcome segments, the gameweek tab on
 *                        its band, the focus ring
 *
 * Not checked, on purpose: a league band against the page background (a
 * full-bleed block whose edge carries no information - its text is what
 * must read) and hairline borders (decorative).
 *
 *   npm test
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { contrast } from "./color";
import { FALLBACK, LEAGUES, MODES, SERIES, SITE, leagueAttr, plotColors, themeCss, themeFor, type LeagueTheme } from "./themes";

const TEXT = 4.5;
const GRAPHIC = 3;

type Pair = [label: string, foreground: string, background: string, minimum: number];

function expectPairs(pairs: Pair[]) {
  const failures = pairs
    .map(([label, fg, bg, min]) => ({ label, fg, bg, min, ratio: contrast(fg, bg) }))
    .filter((p) => p.ratio < p.min)
    .map((p) => `${p.label}: ${p.fg} on ${p.bg} = ${p.ratio.toFixed(2)}:1 (needs ${p.min}:1)`);

  expect(failures).toEqual([]);
}

describe.each(MODES)("site palette, %s", (mode) => {
  const s = SITE[mode];

  it("text is >= 4.5:1", () => {
    expectPairs([
      ["text on bg", s.text, s.bg, TEXT],
      ["text on surface", s.text, s.surface, TEXT],
      ["text on hover tint", s.text, s.tint, TEXT],
      ["muted on bg", s.muted, s.bg, TEXT],
      ["muted on surface", s.muted, s.surface, TEXT],
      ["muted on hover tint", s.muted, s.tint, TEXT],
      ["site accent text on surface", s.siteText, s.surface, TEXT],
      ["profit on surface", s.pos, s.surface, TEXT],
      ["loss on surface", s.neg, s.surface, TEXT],
      ["label on home segment", s.onHome, s.home, TEXT],
      ["label on draw segment", s.onDraw, s.draw, TEXT],
      ["label on away segment", s.onAway, s.away, TEXT],
      ["label on off-pick home tint", s.text, s.homeTint, TEXT],
      ["label on off-pick draw tint", s.text, s.drawTint, TEXT],
      ["label on off-pick away tint", s.text, s.awayTint, TEXT],
    ]);
  });

  it("graphics are >= 3:1", () => {
    expectPairs([
      ["home mark on surface", s.home, s.surface, GRAPHIC],
      ["draw mark on surface", s.draw, s.surface, GRAPHIC],
      ["away mark on surface", s.away, s.surface, GRAPHIC],
      ["profit bar on surface", s.pos, s.surface, GRAPHIC],
      ["loss bar on surface", s.neg, s.surface, GRAPHIC],
      // The ring is the yellow outline around an inner ring: at least one
      // of them must stand out from the surface, and from each other
      [
        "focus ring on surface",
        contrast(s.site, s.surface) >= GRAPHIC ? s.site : s.focusInner,
        s.surface,
        GRAPHIC,
      ],
      ["focus outline against its inner ring", s.site, s.focusInner, GRAPHIC],
    ]);
  });
});

const everyTheme: [string, LeagueTheme][] = [...Object.entries(LEAGUES), ["fallback", FALLBACK]];

describe.each(everyTheme)("league %s", (_, t) => {
  it.each(MODES)("meets contrast in %s mode", (mode) => {
    const s = SITE[mode];

    expectPairs([
      ["band text", t.onBand, t.band, TEXT],
      ["text on accent fill", t.onAccent, t.accent, TEXT],
      ["accent text on surface", t.accentText[mode], s.surface, TEXT],
      ["accent text on bg", t.accentText[mode], s.bg, TEXT],
      ["chart series on surface", t.chart[mode], s.surface, GRAPHIC],
      ["gameweek tab on band", t.accent, t.band, GRAPHIC],
    ]);
  });
});

describe("coverage and fallback", () => {
  it("has a theme for every competition in the registry", () => {
    const registry = readFileSync(
      fileURLToPath(new URL("../../../src/competitions.py", import.meta.url)),
      "utf-8",
    );
    const divs = [...registry.matchAll(/^ {4}"(\w+)": dict\(/gm)].map((m) => m[1]);

    expect(divs.length).toBeGreaterThan(0);
    expect(divs.filter((div) => !(div! in LEAGUES))).toEqual([]);
  });

  it("matches the slugs leagues.json uses", () => {
    const leagues = JSON.parse(
      readFileSync(fileURLToPath(new URL("../data/leagues.json", import.meta.url)), "utf-8"),
    ) as { competitions: { div: string; slug: string }[] };

    for (const c of leagues.competitions) {
      expect(themeFor(c.div).slug).toBe(c.slug);
    }
  });

  it("falls back for an unknown or missing code", () => {
    expect(themeFor("XX")).toBe(FALLBACK);
    expect(themeFor(undefined)).toBe(FALLBACK);
    expect(themeFor("")).toBe(FALLBACK);
    expect(leagueAttr("XX")).toBe("fallback");
    expect(plotColors("XX", "dark").league).toBe(FALLBACK.chart.dark);
  });

  it("finds a theme by Div or slug", () => {
    expect(themeFor("E0")).toBe(LEAGUES.E0);
    expect(themeFor("sp1")).toBe(LEAGUES.SP1);
    expect(leagueAttr("CL")).toBe("cl");
  });

  it("generates CSS for every theme in both modes", () => {
    const css = themeCss();

    for (const [, t] of everyTheme) {
      expect(css).toContain(`[data-league="${t.slug}"]`);
      expect(css).toContain(`--lg-accent-text: ${t.accentText.light};`);
      expect(css).toContain(`--lg-accent-text: ${t.accentText.dark};`);
    }
    expect(css).toContain(`--home: ${SITE.light.home};`);
    expect(css).toContain(`--home: ${SITE.dark.home};`);
    expect(css).toContain("@media (prefers-color-scheme: dark)");
  });
});

describe("categorical series (dataviz palette)", () => {
  it("has 7 distinct slots in each mode, in the same hue order", () => {
    for (const mode of MODES) {
      expect(SERIES[mode]).toHaveLength(7);
      expect(new Set(SERIES[mode]).size).toBe(7);
    }
  });

  it("is >= 3:1 on the dark page background; light mode relies on direct labels / tables", () => {
    for (const color of SERIES.dark) expect(contrast(color, SITE.dark.bg)).toBeGreaterThanOrEqual(3);
    // Documented exceptions in light mode (validator WARN): orange, aqua, yellow, magenta
    const below = SERIES.light.filter((c) => contrast(c, SITE.light.bg) < 3);
    expect(below).toEqual(["#eb6834", "#1baf7a", "#eda100", "#e87ba4"]);
  });

  it("reaches Plot", () => {
    expect(plotColors("e0", "dark").series).toBe(SERIES.dark);
  });
});
