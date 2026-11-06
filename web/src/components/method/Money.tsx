/** A signed profit-like number, coloured by sign (the sign is always shown too). */

import { signed } from "../../lib/format";
import { toneOf } from "../kpi/ScoreStrip";
import styles from "./Method.module.css";

export default function Money({ value, digits = 2, unit = "" }: { value: number; digits?: number; unit?: string }) {
  return (
    <span className={styles.money} data-tone={toneOf(value)}>
      {signed(value, digits)}
      {unit}
    </span>
  );
}
