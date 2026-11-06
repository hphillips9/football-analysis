/**
 * Every bet (plan §3 "Tables": "every-bet grouped by GW, collapsed"): one
 * disclosure per gameweek, latest first, with a one-line summary; inside, a
 * DataTable of its bets. The filter shows a single gameweek, opened.
 *
 * Parity: the Observable Track Record's "Every bet" table (GW, date, match,
 * pick, H/D/A %, FT, P/L, live/backfilled) with its gameweek select.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { useId, useMemo, useState } from "react";

import { formatKickoff, resultName, signed } from "../../lib/format";
import { roundLabel, roundName, type CompetitionKind } from "../../lib/routes";
import type { GameweekSummary } from "../../lib/schema";
import { toneOf } from "../kpi/ScoreStrip";
import DataTable from "../table/DataTable";
import styles from "./EveryBet.module.css";
import type { ResultBet } from "./GameweekResults";

const pct = (v: number) => `${Number(v.toFixed(1))}`;

const columns: ColumnDef<ResultBet, any>[] = [
  { id: "match", header: "Match", accessorFn: (b) => `${b.home} v ${b.away}`, enableSorting: false },
  {
    accessorKey: "kickoff",
    header: "Date",
    meta: { priority: "extra" },
    cell: (c) => formatKickoff(c.getValue<string>(), "day"),
  },
  { id: "pick", header: "Pick", accessorFn: (b) => resultName[b.prediction] },
  { accessorKey: "homeProb", header: "H %", meta: { label: "Home %", align: "end", priority: "extra" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "drawProb", header: "D %", meta: { label: "Draw %", align: "end", priority: "extra" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "awayProb", header: "A %", meta: { label: "Away %", align: "end", priority: "extra" }, cell: (c) => pct(c.getValue<number>()) },
  {
    id: "result",
    header: "FT",
    meta: { label: "Result" },
    accessorFn: (b) => (b.settled && b.result ? resultName[b.result] : undefined),
    cell: (c) => c.getValue<string | undefined>() ?? "—",
  },
  {
    // undefined (not null) so unsettled bets sort last both ways
    id: "profit",
    header: "P/L",
    meta: { label: "Simulated profit", align: "end" },
    accessorFn: (b) => (b.settled ? (b.profit ?? undefined) : undefined),
    cell: (c) => {
      const v = c.getValue<number | undefined>();
      return v == null ? "" : (
        <span className={styles.money} data-tone={toneOf(v)}>
          {signed(v)}
        </span>
      );
    },
  },
  {
    id: "made",
    header: "Made",
    meta: { label: "Prediction made", priority: "extra" },
    accessorFn: (b) => (b.backfilled ? "backfilled" : "live"),
  },
];

interface Props {
  leagueName: string;
  /** "Gameweek 9" in a league, "Matchday 4" / "Round of 16, first leg" in a cup. */
  roundKind?: CompetitionKind;
  /** False when no bet has odds (an unpriced cup): no P/L column or profit in the summaries. */
  priced?: boolean;
  bets: ResultBet[];
  gameweeks: GameweekSummary[];
}

export default function EveryBet({ leagueName, roundKind = "league", priced = true, bets, gameweeks }: Props) {
  const label = (n: number) => roundLabel(roundKind, n);
  const shown = useMemo(() => (priced ? columns : columns.filter((c) => c.id !== "profit")), [priced]);
  const all = useMemo(() => [...new Set(bets.map((b) => b.gameweek))].sort((a, b) => b - a), [bets]);
  const [filter, setFilter] = useState<number | "all">("all");
  const id = useId();

  const groups = (filter === "all" ? all : [filter]).map((gw) => ({
    gw,
    bets: bets.filter((b) => b.gameweek === gw).sort((a, b) => a.kickoff.localeCompare(b.kickoff)),
    summary: gameweeks.find((g) => g.gameweek === gw),
  }));

  return (
    <div className={styles.every}>
      <label className={styles.filter}>
        <span>Show</span>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value === "all" ? "all" : Number(e.target.value))}
          aria-controls={id}
        >
          <option value="all">Every {roundName(roundKind).toLowerCase()}</option>
          {all.map((n) => (
            <option key={n} value={n}>
              {label(n)}
            </option>
          ))}
        </select>
      </label>
      <div id={id} className={styles.groups}>
        {groups.map(({ gw, bets: rows, summary }) => {
          const backfilled = rows.some((b) => b.backfilled);
          return (
            <details key={`${filter}-${gw}`} className={styles.group} open={filter !== "all" || undefined}>
              <summary>
                <span className={styles.gw}>{label(gw)}</span>
                <span className={styles.sum}>
                  {summary && summary.settled
                    ? `${summary.hits}/${summary.settled} right`
                    : `${rows.length} ${rows.length === 1 ? "pick" : "picks"}, not settled`}
                  {priced && summary?.profit != null && (
                    <>
                      {" · "}
                      <b className={styles.money} data-tone={toneOf(summary.profit)}>
                        {signed(summary.profit)}u
                      </b>
                    </>
                  )}
                </span>
                {backfilled && <span className={styles.chip}>Backfilled</span>}
                <svg className={styles.chev} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              </summary>
              <div className={styles.body}>
                <DataTable
                  data={rows}
                  columns={shown}
                  caption={`${leagueName}, ${label(gw).toLowerCase()}: every bet`}
                  getRowId={(b) => `${b.kickoff}-${b.home}`}
                />
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
