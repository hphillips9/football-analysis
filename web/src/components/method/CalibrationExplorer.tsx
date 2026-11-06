/**
 * /about/: this season's calibration (V7) and the record by pick, for all
 * competitions together or one of them (the Observable page's second
 * select drove both). Bets as stats.json has them: live plus backfilled.
 */

import { useId, useMemo, useState } from "react";

import type { CalibrationBin, PickSummary } from "../../lib/schema";
import { leagueAttr } from "../../theme/themes";
import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import { calibration } from "../charts/specs";
import Money from "./Money";
import styles from "./Method.module.css";

export interface CalibrationChoice {
  /** "all", or a Div. */
  key: string;
  name: string;
  settledBets: number;
  calibration: CalibrationBin[];
  byPick: PickSummary[];
}

interface Props {
  choices: CalibrationChoice[];
}

export default function CalibrationExplorer({ choices }: Props) {
  const [key, setKey] = useState(choices[0]!.key);
  const pickHeading = useId();
  const chosen = choices.find((c) => c.key === key) ?? choices[0]!;
  const spec = useMemo(() => calibration(chosen.calibration), [chosen]);
  const league = chosen.key === "all" ? undefined : chosen.key;

  return (
    <div className={styles.explorer} data-league={leagueAttr(league)}>
      <div className={styles.block}>
        <div className={styles.filters}>
          <label>
            <span>Competition</span>
            <select value={chosen.key} onChange={(e) => setKey(e.target.value)}>
              {choices.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <span className={styles.count} aria-live="polite">
            {chosen.settledBets} settled bets
          </span>
        </div>
        {chosen.calibration.length ? (
          <PlotFigure
            spec={spec}
            label={`${chosen.name}: calibration of the model's picks across ${chosen.calibration.length} probability bands`}
            height={340}
            compactHeight={320}
            league={league ?? "fallback"}
            caption={
              <Legend
                items={[
                  { label: "A probability band (size = bets in it)", color: "var(--lg-chart)", shape: "dot" },
                  { label: "Perfect calibration", color: "var(--muted)", shape: "line" },
                ]}
              />
            }
          />
        ) : (
          <p className={styles.note}>No bet settled yet.</p>
        )}
      </div>

      <section className={styles.block} aria-labelledby={pickHeading}>
        <h2 id={pickHeading} className={styles.h2}>
          Which outcomes it backs
        </h2>
        <p className={styles.note}>For the same competition as above: {chosen.name}.</p>
        <table className={styles.plain}>
          <caption className={styles.srOnly}>{chosen.name}: record by pick</caption>
          <thead>
            <tr>
              <th scope="col">Pick</th>
              <th scope="col" className={styles.num}>
                Picks
              </th>
              <th scope="col" className={styles.num}>
                Right
              </th>
              <th scope="col" className={styles.num}>
                Hit rate
              </th>
              <th scope="col" className={styles.num}>
                Profit
              </th>
            </tr>
          </thead>
          <tbody>
            {chosen.byPick.map((p) => (
              <tr key={p.pick}>
                <th scope="row">{p.label}</th>
                <td className={styles.num}>{p.bets}</td>
                <td className={styles.num}>{p.bets ? p.hits : "—"}</td>
                <td className={styles.num}>{p.hitRate == null ? "—" : `${p.hitRate}%`}</td>
                <td className={styles.num}>{p.bets ? <Money value={p.profit} unit="u" /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
