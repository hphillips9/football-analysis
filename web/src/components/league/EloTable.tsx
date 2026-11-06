/**
 * The league Ratings page's table: #, team, Elo, vs 1500 (sortable).
 */

import type { ColumnDef } from "@tanstack/react-table";

import { signed } from "../../lib/format";
import DataTable from "../table/DataTable";

export interface EloRow {
  rank: number;
  team: string;
  elo: number;
}

const columns: ColumnDef<EloRow, any>[] = [
  { accessorKey: "team", header: "Team", enableSorting: false },
  { accessorKey: "rank", header: "#", meta: { label: "Rank", align: "end" } },
  { accessorKey: "elo", header: "Elo", meta: { align: "end" } },
  {
    id: "vs",
    header: "vs 1500",
    accessorFn: (r) => r.elo - 1500,
    meta: { label: "Elo vs the 1500 average", align: "end" },
    cell: (c) => signed(c.getValue<number>(), 0),
  },
];

export default function EloTable({ rows, caption }: { rows: EloRow[]; caption: string }) {
  return <DataTable data={rows} columns={columns} caption={caption} initialSort={[{ id: "rank", desc: false }]} getRowId={(r) => r.team} />;
}
