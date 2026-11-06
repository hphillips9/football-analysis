/**
 * The site's data table (plan §3 "Tables", R6), on TanStack Table:
 *
 * - Sortable headers (buttons, with aria-sort on the <th>). Number columns
 *   sort high-to-low first. Return `undefined` from an accessor for a
 *   missing value: it sorts last in both directions.
 * - The first column is the row header and sticks on horizontal scroll.
 * - Columns with `meta: { priority: "extra" }` drop out on a narrow table
 *   (< 480 px of its container, like the charts' `compact`); each row then
 *   gets a toggle that shows them underneath as label: value pairs.
 *   Done with container queries, so the server HTML is already right on a
 *   phone and nothing shifts when the island hydrates.
 *
 *   const columns: ColumnDef<Standing, any>[] = [
 *     { accessorKey: "team", header: "Team" },
 *     { accessorKey: "played", header: "P", meta: { label: "Played", align: "end", priority: "extra" } },
 *     { accessorKey: "points", header: "Pts", meta: { label: "Points", align: "end" } },
 *   ];
 *   <DataTable data={rows} columns={columns} caption="Premier League table" />
 *
 * Columns are code (cell renderers), so a DataTable lives inside an island
 * that gets the rows as props.
 */

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type Column,
  type ColumnDef,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { Fragment, useId, useState } from "react";

import styles from "./DataTable.module.css";

declare module "@tanstack/react-table" {
  // Declaration merging needs TanStack's exact type parameters, used or not
  // (astro check lists this as a hint)
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Full name, when the header is an abbreviation ("P" → "Played"). */
    label?: string;
    /** "end" for numbers. */
    align?: "start" | "end";
    /** "extra": hidden on a narrow table, shown in the row's expanded part. */
    priority?: "key" | "extra";
  }
}

export interface DataTableProps<T> {
  data: T[];
  // Columns of different value types in one array: TanStack's own docs use any here
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  /** What the table is; read out by screen readers, shown when `showCaption`. */
  caption: string;
  showCaption?: boolean;
  initialSort?: SortingState;
  /** Stable row ids (e.g. team name); defaults to the index. */
  getRowId?: (row: T, index: number) => string;
  /** Shown instead of an empty table. */
  empty?: string;
}

// The generic is on the column's own value type, which DataTable doesn't use
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function labelOf<T>(column: Column<T, any>): string {
  const header = column.columnDef.header;
  return column.columnDef.meta?.label ?? (typeof header === "string" ? header : column.id);
}

/**
 * A sort button's accessible name. It starts with the header's visible text
 * (WCAG 2.5.3 label in name: speech users say what they see), then the full
 * label when the header is an abbreviation: "GA (Goals against), sort".
 */
function sortName(header: unknown, label: string): string {
  const visible = typeof header === "string" ? header : label;
  return visible === label ? `${label}, sort` : `${visible} (${label}), sort`;
}

export default function DataTable<T>({
  data,
  columns,
  caption,
  showCaption = false,
  initialSort = [],
  getRowId,
  empty = "Nothing to show yet.",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const id = useId();

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
    defaultColumn: { sortUndefined: "last" },
  });

  if (data.length === 0) {
    return <p className={styles.empty}>{empty}</p>;
  }

  const leaves = table.getVisibleLeafColumns();
  const hasExtras = leaves.some((c) => c.columnDef.meta?.priority === "extra");
  const cellClass = (column: Column<T, unknown>, index: number) =>
    [
      index === 0 && styles.sticky,
      column.columnDef.meta?.align === "end" && styles.num,
      column.columnDef.meta?.priority === "extra" && styles.extra,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className={styles.root}>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption className={showCaption ? styles.caption : styles.srOnly}>{caption}</caption>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header, i) => {
                  const column = header.column;
                  const sorted = column.getIsSorted();
                  const label = labelOf(column);
                  const content = flexRender(column.columnDef.header, header.getContext());
                  const shown =
                    typeof column.columnDef.header === "string" && label !== column.columnDef.header ? (
                      <abbr title={label}>{content}</abbr>
                    ) : (
                      content
                    );

                  return (
                    <th
                      key={header.id}
                      scope="col"
                      className={cellClass(column, i)}
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                    >
                      {column.getCanSort() ? (
                        <button
                          type="button"
                          className={styles.sort}
                          onClick={column.getToggleSortingHandler()}
                          aria-label={sortName(column.columnDef.header, label)}
                        >
                          {shown}
                          <span className={styles.arrow} data-dir={sorted || undefined} aria-hidden="true" />
                        </button>
                      ) : (
                        shown
                      )}
                    </th>
                  );
                })}
                {hasExtras && (
                  <th scope="col" className={styles.toggleCell}>
                    <span className={styles.srOnly}>More</span>
                  </th>
                )}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isOpen = open[row.id] ?? false;
              const detailId = `${id}-${row.id}`;
              const extras = row.getVisibleCells().filter((c) => c.column.columnDef.meta?.priority === "extra");

              return (
                <Fragment key={row.id}>
                  <tr data-open={isOpen || undefined}>
                    {row.getVisibleCells().map((cell, i) => {
                      const Cell = i === 0 ? "th" : "td";
                      return (
                        <Cell key={cell.id} scope={i === 0 ? "row" : undefined} className={cellClass(cell.column, i)}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </Cell>
                      );
                    })}
                    {hasExtras && (
                      <td className={styles.toggleCell}>
                        <button
                          type="button"
                          className={styles.toggle}
                          aria-expanded={isOpen}
                          aria-controls={detailId}
                          aria-label={`More about ${String(row.getVisibleCells()[0]?.getValue() ?? "this row")}`}
                          onClick={() => setOpen((o) => ({ ...o, [row.id]: !isOpen }))}
                        >
                          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                            <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
                          </svg>
                        </button>
                      </td>
                    )}
                  </tr>
                  {hasExtras && (
                    <tr id={detailId} className={styles.detail} data-open={isOpen || undefined}>
                      <td colSpan={leaves.length + 1}>
                        <dl>
                          {extras.map((cell) => (
                            <div key={cell.id}>
                              <dt>{labelOf(cell.column)}</dt>
                              <dd>{flexRender(cell.column.columnDef.cell, cell.getContext())}</dd>
                            </div>
                          ))}
                        </dl>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
