/**
 * /ratings/: every club on the shared scale (P4-04), with the Observable
 * page's two filters (league, how many), the dot chart and the "All
 * clubs" table. Rank is across every club, whatever the filter.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import { sharedHeight, sharedRatings, type SharedRow } from "../charts/specs";
import DataTable from "../table/DataTable";
import styles from "./Ratings.module.css";

export interface Club extends SharedRow {
  rank: number;
  div: string;
}

interface Props {
  clubs: Club[];
  leagues: { div: string; name: string }[];
  /** "Outside the seven": clubs from no modelled league, counted from leagues.json. */
  outsideLabel: string;
}

const OUTSIDE = "outside";
const SIZES = [25, 50, 100, 0] as const;

const columns: ColumnDef<Club, any>[] = [
  { accessorKey: "team", header: "Club", enableSorting: false },
  { accessorKey: "rank", header: "#", meta: { label: "Rank", align: "end" } },
  { accessorKey: "league", header: "League", meta: { priority: "extra" } },
  { accessorKey: "rating", header: "Rating", meta: { label: "Rating (shared scale)", align: "end" } },
  {
    id: "elo",
    header: "League Elo",
    accessorFn: (c) => c.elo ?? undefined,
    meta: { align: "end", priority: "extra" },
    cell: (c) => c.getValue<number | undefined>() ?? "–",
  },
];

export default function SharedRatings({ clubs, leagues, outsideLabel }: Props) {
  const [league, setLeague] = useState("all");
  const [size, setSize] = useState<number>(25);

  const filtered = useMemo(
    () => clubs.filter((c) => (league === "all" ? true : league === OUTSIDE ? !c.modelled : c.div === league)),
    [clubs, league],
  );
  const shown = useMemo(() => (size ? filtered.slice(0, size) : filtered), [filtered, size]);
  const spec = useMemo(() => sharedRatings(shown), [shown]);
  const leagueName = league === "all" ? "every league" : league === OUTSIDE ? `clubs ${outsideLabel.toLowerCase()}` : leagues.find((l) => l.div === league)?.name;

  return (
    <div className={styles.block}>
      <div className={styles.filters}>
        <label>
          <span>League</span>
          <select value={league} onChange={(e) => setLeague(e.target.value)}>
            <option value="all">All leagues</option>
            {leagues.map((l) => (
              <option key={l.div} value={l.div}>
                {l.name}
              </option>
            ))}
            <option value={OUTSIDE}>{outsideLabel}</option>
          </select>
        </label>
        <label>
          <span>Show</span>
          <select value={size} onChange={(e) => setSize(Number(e.target.value))}>
            {SIZES.map((n) => (
              <option key={n} value={n}>
                {n ? `Top ${n}` : "All clubs"}
              </option>
            ))}
          </select>
        </label>
        <span className={styles.count} aria-live="polite">
          {shown.length} of {filtered.length} clubs
        </span>
      </div>

      <PlotFigure
        spec={spec}
        label={`Ratings on the shared scale: top ${shown.length} clubs, ${leagueName}`}
        height={sharedHeight(shown.length)}
        compactHeight={sharedHeight(shown.length, true)}
        caption={
          <>
            <Legend
              items={[
                { label: "In a modelled league", color: "var(--series-1)", shape: "dot" },
                { label: `${outsideLabel} leagues *`, color: "var(--series-2)", shape: "dot" },
                { label: "1500, the Premier League's baseline", color: "var(--muted)", shape: "line" },
              ]}
            />
          </>
        }
      />

      <details className={styles.table}>
        <summary>All {filtered.length} clubs as a table</summary>
        <DataTable
          data={filtered}
          columns={columns}
          caption={`Ratings on the shared scale, ${leagueName}`}
          initialSort={[{ id: "rank", desc: false }]}
          getRowId={(c) => `${c.div}-${c.team}`}
        />
      </details>
    </div>
  );
}
