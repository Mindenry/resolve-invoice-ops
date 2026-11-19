import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/ui";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  className?: string;
  width?: string;
  align?: "left" | "right" | "center";
}

export function DataTable<T>({
  columns,
  rows,
  loading,
  empty,
  rowKey,
  onRowClick,
  skeletonRows = 7,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  loading?: boolean;
  empty?: ReactNode;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  skeletonRows?: number;
}) {
  if (loading) return <TableSkeleton rows={skeletonRows} />;
  if (!rows || rows.length === 0) return <>{empty}</>;
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  column.align === "right" && "text-right",
                  column.align === "center" && "text-center",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              data-clickable={Boolean(onRowClick)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    column.className,
                    column.align === "right" && "text-right",
                    column.align === "center" && "text-center",
                  )}
                >
                  {column.render ? column.render(row) : ((row as Record<string, unknown>)[column.key] as ReactNode)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
