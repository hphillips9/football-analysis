/**
 * /_lab: DataTable with real data - a league table and the latest bets.
 */

import type { ColumnDef } from "@tanstack/react-table";

import { formatKickoff, resultName, signed } from "../../lib/format";
import type { Bet, LeagueTable } from "../../lib/schema";
import DataTable from "../table/DataTable";
import styles from "./Lab.module.css";

type Standing = LeagueTable["current"][number];

const standingColumns: ColumnDef<Standing, any>[] = [
  { accessorKey: "team", header: "Team", enableSorting: false, cell: (c) => c.getValue<string>() },
  { accessorKey: "position", header: "#", meta: { label: "Position", align: "end" } },
  { accessorKey: "played", header: "P", meta: { label: "Played", align: "end", priority: "extra" } },
  { accessorKey: "won", header: "W", meta: { label: "Won", align: "end", priority: "extra" } },
  { accessorKey: "drawn", header: "D", meta: { label: "Drawn", align: "end", priority: "extra" } },
  { accessorKey: "lost", header: "L", meta: { label: "Lost", align: "end", priority: "extra" } },
  { accessorKey: "gf", header: "GF", meta: { label: "Goals for", align: "end", priority: "extra" } },
  { accessorKey: "ga", header: "GA", meta: { label: "Goals against", align: "end", priority: "extra" } },
  {
    accessorKey: "gd",
    header: "GD",
    meta: { label: "Goal difference", align: "end" },
    cell: (c) => signed(c.getValue<number>(), 0),
  },
  { accessorKey: "points", header: "Pts", meta: { label: "Points", align: "end" } },
];

const pickName = (b: Bet) => (b.prediction === "H" ? b.home : b.prediction === "A" ? b.away : "Draw");

const betColumns: ColumnDef<Bet, any>[] = [
  { id: "match", header: "Match", accessorFn: (b) => `${b.home} v ${b.away}`, enableSorting: false },
  { accessorKey: "gameweek", header: "GW", meta: { label: "Gameweek", align: "end" } },
  {
    accessorKey: "kickoff",
    header: "Kick-off",
    meta: { priority: "extra" },
    cell: (c) => formatKickoff(c.getValue<string>(), "long"),
  },
  { id: "pick", header: "Pick", accessorFn: pickName, meta: { priority: "extra" } },
  {
    id: "pickProb",
    header: "Prob",
    meta: { label: "Pick probability", align: "end", priority: "extra" },
    accessorFn: (b) => (b.prediction === "H" ? b.homeProb : b.prediction === "D" ? b.drawProb : b.awayProb),
    cell: (c) => `${Math.round(c.getValue<number>())}%`,
  },
  {
    id: "result",
    header: "Result",
    accessorFn: (b) => (b.result ? resultName[b.result] : undefined),
    meta: { priority: "extra" },
    cell: (c) => c.getValue<string | undefined>() ?? "—",
  },
  {
    // undefined (not null) so unsettled bets sort last both ways
    id: "profit",
    header: "Profit",
    meta: { label: "Simulated profit", align: "end" },
    accessorFn: (b) => b.profit ?? undefined,
    cell: (c) => {
      const v = c.getValue<number | undefined>();
      return (
        <span className={styles.money} data-tone={v == null ? undefined : v > 0 ? "pos" : v < 0 ? "neg" : undefined}>
          {signed(v)}
        </span>
      );
    },
  },
];

interface Props {
  leagueName: string;
  standings: Standing[];
  bets: Bet[];
}

export default function LabTables({ leagueName, standings, bets }: Props) {
  return (
    <div className={styles.tables}>
      <DataTable
        data={standings}
        columns={standingColumns}
        caption={`${leagueName} table`}
        showCaption
        initialSort={[{ id: "position", desc: false }]}
        getRowId={(r) => r.team}
      />
      <DataTable
        data={bets}
        columns={betColumns}
        caption={`${leagueName}: last ${bets.length} simulated stakes`}
        showCaption
        initialSort={[{ id: "gameweek", desc: true }]}
        getRowId={(b) => `${b.kickoff}-${b.home}`}
      />
    </div>
  );
}
