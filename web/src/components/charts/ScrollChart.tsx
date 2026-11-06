/**
 * A chart with one column per gameweek that scrolls sideways on a phone
 * (plan §3 V4/V5): below 480 px, when the gameweeks don't fit at `minItem`
 * px each, the chart is drawn at `perItem` px per gameweek inside a horizontal scroller
 * that starts at `focus` (the latest or selected gameweek) rather than
 * squeezing a whole season into 330 px. Wider, it is just the chart.
 *
 *   <ScrollChart count={gameweeks.length} focus={index}>
 *     {(compact) => <PlotFigure compact={compact} scrub={false} ... />}
 *   </ScrollChart>
 *
 * The child gets `compact` to pass on to PlotFigure, which would otherwise
 * see the scroller's wide content and choose the desktop layout. Turn off
 * PlotFigure's `scrub` inside: horizontal drags belong to the scroller.
 */

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { COMPACT_WIDTH } from "./PlotFigure";
import styles from "./ScrollChart.module.css";

// useLayoutEffect warns during server rendering
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

interface Props {
  /** Columns in the chart (gameweeks). */
  count: number;
  /** Index of the column to bring into view (default: the last). */
  focus?: number;
  /** Width per column when scrolling. */
  perItem?: number;
  /** Narrowest column before it scrolls instead of squeezing. */
  minItem?: number;
  /** Accessible name of the scroll area. */
  label: string;
  children: (compact: boolean) => ReactNode;
}

export default function ScrollChart({ count, focus = count - 1, perItem = 40, minItem = 32, label, children }: Props) {
  const outer = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = outer.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => entry && setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const compact = width > 0 && width < COMPACT_WIDTH;
  // Fits at minItem a column: no scrolling; otherwise perItem a column
  const scrolls = compact && count * minItem > width;
  const inner = scrolls ? count * perItem : undefined;

  // Bring the focused column into the middle of the view
  useIsoLayoutEffect(() => {
    const el = outer.current;
    if (!el || !scrolls || inner == null) return;
    const centre = ((focus + 0.5) / count) * inner;
    el.scrollLeft = Math.max(0, Math.min(inner - width, centre - width / 2));
  }, [scrolls, inner, width, focus, count]);

  return (
    <div
      ref={outer}
      className={styles.outer}
      data-scrolls={scrolls || undefined}
      tabIndex={scrolls ? 0 : undefined}
      role={scrolls ? "region" : undefined}
      aria-label={scrolls ? `${label} (scrolls sideways)` : undefined}
    >
      <div style={inner ? { width: inner } : undefined}>{children(compact)}</div>
    </div>
  );
}
