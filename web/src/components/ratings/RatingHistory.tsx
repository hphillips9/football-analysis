/**
 * /ratings/: up to four clubs' shared-scale ratings over the last year.
 * Each chosen club keeps its colour slot while others come and go (colour
 * follows the entity, not the order); a removed club frees its slot.
 * Chips double as the legend; the chart labels each line's end on wide
 * screens.
 */

import { useMemo, useState } from "react";

import { addDays, usePageData } from "../../lib/pageData";
import PlotFigure from "../charts/PlotFigure";
import { ratingHistory, type HistoryLine } from "../charts/specs";
import styles from "./Ratings.module.css";

const MAX = 4;

/**
 * Every club's history, compact (the page's JSON block): for each club a
 * flat [day, rating, day, rating, ...] array, days counted from `from`.
 */
export interface HistoryData {
  from: string;
  series: Record<string, number[]>;
}

interface Props {
  /** Id of the page's JSON block with the HistoryData. */
  dataId: string;
  /** Clubs for the picker, grouped by league, strongest first. */
  groups: { name: string; clubs: string[] }[];
  /** Chosen at first: the top three on the shared scale. */
  initial: string[];
  from: string;
}

interface Chosen {
  team: string;
  slot: number;
}

export default function RatingHistory({ dataId, groups, initial, from }: Props) {
  const data = usePageData<HistoryData>(dataId);
  const [chosen, setChosen] = useState<Chosen[]>(initial.slice(0, MAX).map((team, slot) => ({ team, slot })));

  const add = (team: string) => {
    if (!team || chosen.length >= MAX || chosen.some((c) => c.team === team)) return;
    const used = new Set(chosen.map((c) => c.slot));
    const slot = [0, 1, 2, 3].find((s) => !used.has(s))!;
    setChosen([...chosen, { team, slot }]);
  };
  const remove = (team: string) => setChosen(chosen.filter((c) => c.team !== team));

  const lines: HistoryLine[] = useMemo(
    () =>
      chosen
        .map((c) => {
          const flat = data?.series[c.team] ?? [];
          const points: [string, number][] = [];
          for (let i = 0; i < flat.length; i += 2) points.push([addDays(data!.from, flat[i]!), flat[i + 1]!]);
          return { ...c, points };
        })
        .filter((l) => l.points.length > 0),
    [chosen, data],
  );
  const spec = useMemo(() => ratingHistory(lines), [lines]);

  return (
    <div className={styles.block}>
      <div className={styles.filters}>
        <ul className={styles.chips} aria-label="Clubs on the chart">
          {chosen.map((c) => (
            <li key={c.team}>
              <i style={{ background: `var(--series-${c.slot + 1})` }} aria-hidden="true" />
              {c.team}
              <button type="button" onClick={() => remove(c.team)} aria-label={`Remove ${c.team}`}>
                ×
              </button>
            </li>
          ))}
        </ul>
        <label>
          <span className={styles.srOnly}>Add a club</span>
          <select value="" onChange={(e) => add(e.target.value)} disabled={chosen.length >= MAX}>
            <option value="">{chosen.length >= MAX ? `Up to ${MAX} clubs` : "Add a club…"}</option>
            {groups.map((g) => (
              <optgroup key={g.name} label={g.name}>
                {g.clubs.map((team) => (
                  <option key={team} value={team} disabled={chosen.some((c) => c.team === team)}>
                    {team}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </div>

      {!data || lines.length ? (
        <PlotFigure
          spec={spec}
          ready={data != null}
          label={`Shared-scale rating over the last year: ${lines.map((l) => `${l.team} now ${l.points.at(-1)?.[1]}`).join(", ")}`}
          height={320}
          compactHeight={260}
          caption={`A point after each match the club played, league or European, since ${from}.`}
        />
      ) : (
        <p className={styles.empty}>Add a club to see its rating over the last year.</p>
      )}
    </div>
  );
}
