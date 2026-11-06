/**
 * A cup's league-phase tables (/{c}/league-phase/), on DataTable:
 *
 *   current     # Team P W D L GF GA GD Pts
 *   projected   # Team P Pts, Δ vs now
 *
 * The Team cell carries the position, a zone marker (solid: straight to
 * the round of 16; outline: knockout play-off; none: out) and the club's
 * country, since a cup mixes leagues. The projected table drops W/D/L/GD:
 * they're expected values, and there's no goal model for a cup.
 */

import type { ColumnDef } from "@tanstack/react-table";

import { signed } from "../../lib/format";
import type { CupProjectedStanding, CupStanding } from "../../lib/schema";
import DataTable from "../table/DataTable";
import styles from "./CupStandings.module.css";
import standings from "./Standings.module.css";

export interface Zones {
  direct: number;
  playoff: number;
}

export type Zone = "direct" | "playoff" | "out";

export function zoneOf(position: number, zones: Zones): Zone {
  return position <= zones.direct ? "direct" : position <= zones.playoff ? "playoff" : "out";
}

const ZONE_LABEL: Record<Zone, string> = {
  direct: "round of 16",
  playoff: "play-off",
  out: "out",
};

type Row = (CupStanding | CupProjectedStanding) & { country: string };

function teamColumn<T extends Row>(zones: Zones): ColumnDef<T, any> {
  return {
    id: "team",
    header: "Team",
    accessorFn: (r) => r.position,
    meta: { label: "Position and team" },
    cell: (c) => {
      const r = c.row.original;
      const zone = zoneOf(r.position, zones);
      return (
        <span className={standings.team}>
          <span className={styles.zone} data-zone={zone} title={ZONE_LABEL[zone]} />
          <span className={standings.pos}>{r.position}</span>
          <span>
            {r.team}
            {r.country && <span className={styles.country}> {r.country}</span>}
            <span className={styles.srOnly}>, {ZONE_LABEL[zone]}</span>
          </span>
        </span>
      );
    },
  };
}

const num = <T,>(key: keyof T & string, header: string, label: string, extra = true): ColumnDef<T, any> => ({
  accessorKey: key,
  header,
  meta: { label, align: "end", priority: extra ? "extra" : "key" },
});

function Move({ value }: { value: number }) {
  return (
    <span className={styles.move} data-dir={value > 0 ? "up" : value < 0 ? "down" : undefined}>
      {value === 0 ? "–" : `${value > 0 ? "▲" : "▼"} ${Math.abs(value)}`}
      <span className={styles.srOnly}>
        {value === 0 ? " no change" : value > 0 ? ` up ${value}` : ` down ${-value}`}
      </span>
    </span>
  );
}

type Props =
  | { kind: "current"; rows: (CupStanding & { country: string })[]; zones: Zones; caption: string }
  | { kind: "projected"; rows: (CupProjectedStanding & { country: string })[]; zones: Zones; caption: string };

export default function CupStandings(props: Props) {
  const sort = [{ id: "team", desc: false }];

  if (props.kind === "current") {
    type R = (typeof props.rows)[number];
    const columns: ColumnDef<R, any>[] = [
      teamColumn<R>(props.zones),
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

  type R = (typeof props.rows)[number];
  const columns: ColumnDef<R, any>[] = [
    teamColumn<R>(props.zones),
    num("played", "P", "Played"),
    num("points", "Pts", "Expected points", false),
    {
      accessorKey: "movement",
      header: "vs now",
      meta: { label: "Places gained or lost on today's table", align: "end" },
      cell: (c) => <Move value={c.getValue<number>()} />,
    },
  ];
  return <DataTable data={props.rows} columns={columns} caption={props.caption} initialSort={sort} getRowId={(r) => r.team} />;
}
