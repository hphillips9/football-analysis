/**
 * /about/: the backtest summary, one row per competition plus every league
 * together (the pooled row last). On a phone the table keeps competition,
 * accuracy, edge and ROI; the rest fold into each row.
 */

import type { ColumnDef } from "@tanstack/react-table";

import { signed } from "../../lib/format";
import DataTable from "../table/DataTable";
import type { Numbers } from "./BacktestExplorer";
import Money from "./Money";

export interface SummaryRow extends Numbers {
  key: string;
  competition: string;
}

const pct = (n: number) => `${n}%`;

const columns: ColumnDef<SummaryRow, any>[] = [
  { accessorKey: "competition", header: "Competition", enableSorting: false },
  { accessorKey: "matches", header: "Matches", meta: { align: "end", priority: "extra" }, cell: (c) => c.getValue<number>().toLocaleString("en-GB") },
  { accessorKey: "accuracy", header: "Acc", meta: { label: "Accuracy", align: "end" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "baselineAccuracy", header: "Base", meta: { label: "Always home", align: "end", priority: "extra" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "edge", header: "Edge", meta: { label: "Edge (points)", align: "end" }, cell: (c) => signed(c.getValue<number>(), 1) },
  { accessorKey: "logLoss", header: "Log loss", meta: { align: "end", priority: "extra" } },
  { accessorKey: "profit", header: "Profit", meta: { label: "Profit (units)", align: "end", priority: "extra" }, cell: (c) => <Money value={c.getValue<number>()} unit="u" /> },
  { accessorKey: "roi", header: "ROI", meta: { align: "end" }, cell: (c) => <Money value={c.getValue<number>()} digits={1} unit="%" /> },
];

export default function BacktestSummary({ rows, caption }: { rows: SummaryRow[]; caption: string }) {
  return <DataTable data={rows} columns={columns} caption={caption} getRowId={(r) => r.key} />;
}
