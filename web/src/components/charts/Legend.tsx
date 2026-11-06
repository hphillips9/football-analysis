/**
 * A chart legend in HTML, next to a PlotFigure (charts keep legends out of
 * the SVG so the frame height stays fixed). Swatches take a CSS colour, so
 * they can use the theme's variables: var(--home), var(--pos)...
 */

import styles from "./Legend.module.css";

export interface LegendItem {
  label: string;
  color: string;
  /** "box" for fills (default), "line" for a series line, "dot" for points. */
  shape?: "box" | "line" | "dot";
}

export default function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul className={styles.legend}>
      {items.map((item) => (
        <li key={item.label}>
          <i data-shape={item.shape ?? "box"} style={{ background: item.color }} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
