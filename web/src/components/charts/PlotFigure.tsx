/**
 * An Observable Plot chart as a React component (plan §3, decision R5).
 *
 *   <PlotFigure
 *     label="Running profit, Premier League"
 *     height={220} compactHeight={80}
 *     spec={({ Plot, width, height, compact, colors }) => Plot.plot({ width, height, ... })}
 *   />
 *
 * - Width comes from a ResizeObserver on the frame; the chart is redrawn
 *   when it changes. `compact` is true below 480 px *of chart width* (not
 *   viewport), which is what the phone layouts in plan §3 key off.
 * - Colours: `colors` are hex values from themes.ts for the current mode
 *   and league (SVG attributes don't reliably take var()). The chart is
 *   redrawn when the OS / data-mode switches. Axes and text use
 *   currentColor, so they follow the page's text colour by themselves.
 * - The frame has a fixed height from the start (compactHeight inside a
 *   narrow container, via a container query), with a skeleton until Plot
 *   arrives, so nothing shifts when the chart appears.
 * - Plot + d3 load lazily (plot.ts): the server-rendered HTML is just the
 *   skeleton, and pages without charts never download Plot.
 * - Touch: a tap shows Plot's tip for the nearest point; a tap anywhere
 *   else dismisses it. With `scrub` (the default) a horizontal drag moves
 *   the tip and a vertical one still scrolls the page; turn it off for a
 *   chart inside a horizontal scroller.
 *
 * Specs must keep the whole chart, legends included, inside `height`:
 * put legends in HTML next to the figure, not Plot's `legend: true`.
 * A spec is plain code, not data, so a PlotFigure lives inside an island
 * (a .tsx with client:visible) that passes the page's data to it.
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { plotColors, type Mode, type PlotColors } from "../../theme/themes";
import { loadPlot, type PlotModule } from "./plot";
import styles from "./PlotFigure.module.css";
import { useMode } from "./useMode";

/** Chart width below which a figure is compact (plan §3: "< 480 px"). */
export const COMPACT_WIDTH = 480;

export interface ChartContext {
  Plot: PlotModule;
  /** Frame width in px. */
  width: number;
  /** The frame's height in px: `compactHeight` when compact, else `height`. */
  height: number;
  /** Width below COMPACT_WIDTH. */
  compact: boolean;
  mode: Mode;
  /** Outcome, profit/loss, league and neutral colours as hex. */
  colors: PlotColors;
  /** Base style for Plot.plot({ style }): the site's font and sizes. */
  style: Record<string, string>;
}

export type ChartSpec = (ctx: ChartContext) => SVGSVGElement | HTMLElement;

export interface PlotFigureProps {
  spec: ChartSpec;
  /** Accessible name for the chart (it is exposed as one image). */
  label: string;
  height: number;
  compactHeight?: number;
  /** Div or slug for the league colour; defaults to the nearest data-league. */
  league?: string;
  /** Drag horizontally to move the tip on touch screens. */
  scrub?: boolean;
  /** Shown under the chart (a legend, a note). */
  caption?: ReactNode;
  /**
   * Force the compact layout (a chart inside a horizontal scroller is wide
   * but sits on a phone); by default, width < COMPACT_WIDTH.
   */
  compact?: boolean;
  /**
   * Called with the datum under the pointer when the chart is clicked or
   * tapped (Plot's `value` for a pointer mark, e.g. a tip). Needs a
   * pointer-based mark in the spec.
   */
  onPick?: (datum: unknown) => void;
  /** False keeps the skeleton (e.g. while the island reads its data). */
  ready?: boolean;
  className?: string;
}

type Status = "loading" | "ready" | "error";

export default function PlotFigure({
  spec,
  label,
  height,
  compactHeight = height,
  league,
  scrub = true,
  caption,
  className,
  compact: forceCompact,
  onPick,
  ready = true,
}: PlotFigureProps) {
  const frame = useRef<HTMLDivElement>(null);
  const mode = useMode();
  const [width, setWidth] = useState(0);
  const [plot, setPlot] = useState<PlotModule>();
  const [status, setStatus] = useState<Status>("loading");

  // Measure the frame; only whole-pixel changes trigger a redraw
  useEffect(() => {
    const el = frame.current;
    if (!el) return;

    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(el);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let live = true;
    loadPlot().then(
      (module) => live && setPlot(() => module),
      () => live && setStatus("error"),
    );
    return () => {
      live = false;
    };
  }, []);

  // Draw (and redraw on width / mode / spec changes)
  useEffect(() => {
    const el = frame.current;
    if (!el || !plot || width <= 0 || !ready) return;

    const compact = forceCompact ?? width < COMPACT_WIDTH;
    const div = league ?? el.closest<HTMLElement>("[data-league]")?.dataset.league;

    try {
      const node = spec({
        Plot: plot,
        width,
        height: compact ? compactHeight : height,
        compact,
        mode,
        colors: plotColors(div, mode),
        style: {
          fontFamily: "inherit",
          fontSize: compact ? "12px" : "13px",
          fontVariantNumeric: "tabular-nums",
          overflow: "visible",
        },
      });
      // The frame is one image with its own label (role="img"); Plot's
      // per-mark aria-labels on <g> are invalid ARIA there (P7-11, axe)
      node.querySelectorAll("[aria-label], [aria-description]").forEach((n) => {
        n.removeAttribute("aria-label");
        n.removeAttribute("aria-description");
      });
      el.replaceChildren(node);
      setStatus("ready");
    } catch (error) {
      console.error(`Chart "${label}" failed to draw`, error);
      el.replaceChildren();
      setStatus("error");
    }
  }, [plot, width, mode, league, spec, height, compactHeight, label, forceCompact, ready]);

  // Click / tap → the datum Plot's pointer marks are showing
  const pick = useRef(onPick);
  pick.current = onPick;
  useEffect(() => {
    const el = frame.current;
    if (!el || status !== "ready" || !onPick) return;

    const onClick = () => {
      const value = (el.firstElementChild as (Element & { value?: unknown }) | null)?.value;
      if (value != null) pick.current?.(value);
    };
    el.addEventListener("click", onClick);
    el.style.cursor = "pointer";

    return () => {
      el.removeEventListener("click", onClick);
      el.style.cursor = "";
    };
  }, [status, onPick != null]);

  // Touch: a tap outside the chart clears a tip left showing (Plot only
  // clears it on mouse leave)
  useEffect(() => {
    const el = frame.current;
    if (!el || status !== "ready") return;

    const onDown = (event: PointerEvent) => {
      if (event.pointerType === "mouse" || el.contains(event.target as Node)) return;
      el.querySelectorAll("svg").forEach((svg) =>
        svg.dispatchEvent(new PointerEvent("pointerleave", { pointerType: "mouse" })),
      );
    };
    document.addEventListener("pointerdown", onDown);

    return () => document.removeEventListener("pointerdown", onDown);
  }, [status]);

  const sizes = { "--h": `${height}px`, "--h-compact": `${compactHeight}px` } as CSSProperties;

  return (
    <figure className={[styles.figure, className].filter(Boolean).join(" ")} style={sizes}>
      <div className={styles.box}>
        <div
          ref={frame}
          className={styles.frame}
          data-scrub={scrub || undefined}
          role="img"
          aria-label={label}
          aria-busy={status === "loading" || undefined}
        />
        {status !== "ready" && (
          <div className={styles.skeleton} data-status={status} aria-hidden={status === "loading"}>
            {status === "error" && <span>Chart unavailable</span>}
          </div>
        )}
      </div>
      {caption && <figcaption className={styles.caption}>{caption}</figcaption>}
    </figure>
  );
}
