/**
 * Colour arithmetic for the theme: WCAG 2 contrast and sRGB mixing.
 * Used to precompute tints (so the CSS ships the exact colours the
 * contrast test checked) and by the test itself.
 */

type Rgb = [number, number, number];

function parse(hex: string): Rgb {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);

  if (!match) throw new Error(`Not a #rrggbb colour: "${hex}"`);

  const n = parseInt(match[1]!, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

/** WCAG 2 relative luminance. */
export function luminance(hex: string): number {
  const [r, g, b] = parse(hex).map((c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as Rgb;

  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio, 1-21. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** ``share`` of ``colour`` over ``base`` (like color-mix(in srgb, colour share%, base)). */
export function mix(colour: string, base: string, share: number): string {
  const a = parse(colour);
  const b = parse(base);

  return toHex(a.map((c, i) => c * share + b[i]! * (1 - share)) as Rgb);
}
