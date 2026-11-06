/**
 * The Table page's three tables (plan §3 "Tables", V8 on a phone), on
 * DataTable:
 *
 *   current     # Team P W D L GF GA GD Pts
 *   predicted   # Team P W D L Pts, Δ vs the real table
 *   projected   # Team P W D L GD Pts, Δ vs now (the V8 numbers as a column)
 *
 * The position sits in the Team cell (the sticky column), and sorting by
 * Team sorts by position. On a phone P/W/D/L/GF/GA fold into each row; the
 * Δ column stays, with a mini bar, which is V8's phone form.
 */

import type { ColumnDef } from "@tanstack/react-table";

import { signed } from "../../lib/format";
import type { LeagueTable } from "../../lib/schema";
import DataTable from "../table/DataTable";
import styles from "./Standings.module.css";

type Current = LeagueTable["current"][number];
type Predicted = LeagueTable["predicted"][number];
type Projected = LeagueTable["projected"][number];
type Row = { team: string; position: number };

function teamColumn<T extends Row>(): ColumnDef<T, any> {
  return {
    id: "team",
    header: "Team",
    accessorFn: (r) => r.position,
    meta: { label: "Position and team" },
    cell: (c) => (
      <span className={styles.team}>
        <span className={styles.pos}>{c.row.original.position}</span>
        {c.row.original.team}
      </span>
    ),
  };
}

const num = <T,>(key: keyof T & string, header: string, label: string, extra = true): ColumnDef<T, any> => ({
  accessorKey: key,
  header,
  meta: { label, align: "end", priority: extra ? "extra" : "key" },
});

/** "▲ 3" / "▼ 2" / "–", with a mini bar scaled to the table's biggest move. */
function Move({ value, max, label }: { value: number; max: number; label: string }) {
  // Each direction has half the track
  const width = max ? `${Math.max(4, (Math.abs(value) / max) * 50)}%` : "0";
  const dir = value > 0 ? "up" : value < 0 ? "down" : undefined;
  return (
    <span className={styles.move} data-dir={dir} title={label}>
      <span className={styles.track} aria-hidden="true">
        {dir && <span className={styles.bar} style={{ width }} />}
      </span>
      <span className={styles.moveText}>
        {value === 0 ? "–" : `${value > 0 ? "▲" : "▼"} ${Math.abs(value)}`}
        <span className={styles.srOnly}>
          {value === 0 ? " no change" : value > 0 ? ` up ${value}` : ` down ${-value}`}
        </span>
      </span>
    </span>
  );
}

function moveColumn<T extends Row & { movement: number }>(header: string, label: string, max: number): ColumnDef<T, any> {
  return {
    accessorKey: "movement",
    header,
    meta: { label, align: "end" },
    cell: (c) => <Move value={c.getValue<number>()} max={max} label={label} />,
  };
}

type Props =
  | { kind: "current"; rows: Current[]; caption: string }
  | { kind: "predicted"; rows: Predicted[]; caption: string }
  | { kind: "projected"; rows: Projected[]; caption: string };

export default function Standings(props: Props) {
  const sort = [{ id: "team", desc: false }];

  if (props.kind === "current") {
    const columns: ColumnDef<Current, any>[] = [
      teamColumn<Current>(),
      num("played", "P", "Played"),
      num("won", "W", "Won"),
      num("drawn", "D", "Drawn"),
      num("lost", "L", "Lost"),
      num("gf", "GF", "Goals for"),
      num("ga", "GA", "Goals against"),
      { accessorKey: "gd", header: "GD", meta: { label: "Goal difference", align: "end" }, cell: (c) => signed(c.getValue<number>(), 0) },
      num("points", "Pts", "Points", false),
    ];
    return <DataTable data={props.rows} columns={columns} caption={props.caption} initialSort={sort} getRowId={(r) => r.team} />;
  }

  const max = Math.max(1, ...props.rows.map((r) => Math.abs(r.movement)));

  if (props.kind === "predicted") {
    const columns: ColumnDef<Predicted, any>[] = [
      teamColumn<Predicted>(),
      num("played", "P", "Played"),
      num("won", "W", "Won"),
      num("drawn", "D", "Drawn"),
      num("lost", "L", "Lost"),
      num("points", "Pts", "Points", false),
      moveColumn<Predicted>("vs real", "Places vs the real table", max),
    ];
    return <DataTable data={props.rows} columns={columns} caption={props.caption} initialSort={sort} getRowId={(r) => r.team} />;
  }

  const columns: ColumnDef<Projected, any>[] = [
    teamColumn<Projected>(),
    num("played", "P", "Played"),
    num("won", "W", "Won"),
    num("drawn", "D", "Drawn"),
    num("lost", "L", "Lost"),
    { accessorKey: "gd", header: "GD", meta: { label: "Goal difference", align: "end" }, cell: (c) => signed(c.getValue<number>(), 0) },
    num("points", "Pts", "Points", false),
    moveColumn<Projected>("vs now", "Projected places gained or lost", max),
  ];
  return <DataTable data={props.rows} columns={columns} caption={props.caption} initialSort={sort} getRowId={(r) => r.team} />;
}
