import type { DataTable } from '../api'
import { cell, label } from '../format'

export function DataTableView({ table, maxRows = 50, compact = false }: { table: DataTable; maxRows?: number; compact?: boolean }) {
  if (!table.columns.length) return null
  const rows = table.rows.slice(0, maxRows)
  return (
    <div className="overflow-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-50 text-slate-500">
          <tr>
            {table.columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                {label(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {r.map((v, j) => (
                <td key={j} className={`px-3 ${compact ? 'py-1' : 'py-1.5'} ${typeof v === 'number' ? 'text-right tabular-nums' : ''} max-w-md truncate`} title={String(v ?? '')}>
                  {cell(table.columns[j], v)}
                </td>
              ))}
            </tr>
          ))}
          {table.total_rows === 0 && (
            <tr>
              <td className="px-3 py-3 text-slate-400" colSpan={table.columns.length}>
                No rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {table.total_rows > rows.length && <div className="border-t border-slate-100 px-3 py-1.5 text-xs text-slate-400">Showing {rows.length} of {table.total_rows} rows</div>}
    </div>
  )
}
