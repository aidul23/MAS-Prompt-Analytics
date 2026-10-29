import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ChartSpec, DataTable } from '../api'
import { cell, label, PALETTE } from '../format'

const AXIS = { fontSize: 11, fill: '#64748b' }

export function ResultChart({ chart, table }: { chart: ChartSpec; table: DataTable }) {
  if (chart.type === 'table' || !table.rows.length) return null
  const records = table.rows.map((r) => Object.fromEntries(table.columns.map((c, i) => [c, r[i]])))
  const y = chart.y.filter((c) => table.columns.includes(c))
  if (!y.length) return null

  if (chart.type === 'kpi') {
    const dims = table.columns.filter((c) => !y.includes(c))
    return (
      <div className="flex flex-wrap gap-3">
        {records.slice(0, 3).map((rec, i) => (
          <div key={i} className="flex flex-wrap gap-3">
            {y.map((m) => (
              <div key={m} className="rounded-lg border border-indigo-100 bg-indigo-50/60 px-4 py-3">
                <div className="text-xs text-indigo-700">
                  {label(m)}
                  {dims.length > 0 && ` · ${dims.map((d) => cell(d, rec[d])).join(', ')}`}
                </div>
                <div className="text-2xl font-semibold tabular-nums text-slate-900">{cell(m, rec[m])}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    )
  }

  const x = chart.x ?? table.columns[0]
  const tickFormatter = (v: unknown) => cell(x, v)
  const valueFormatter = (v: unknown, name: unknown) => cell(String(name), v)

  if (chart.type === 'pie') {
    return (
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie isAnimationActive={false} data={records} dataKey={y[0]} nameKey={x} innerRadius={50} outerRadius={90} paddingAngle={2}>
            {records.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip formatter={valueFormatter} />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    )
  }

  const rates = y.filter((c) => /(_rate|share_of_prompts)$/.test(c))
  const others = y.filter((c) => !rates.includes(c))
  const dual = rates.length > 0 && others.length > 0
  const axisFor = (c: string) => (dual && rates.includes(c) ? 'r' : 'l')
  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
      <XAxis dataKey={x} tick={AXIS} tickFormatter={tickFormatter} minTickGap={8} interval="preserveStartEnd" />
      <YAxis yAxisId="l" tick={AXIS} width={48} tickFormatter={(v) => cell(dual ? others[0] : y[0], v)} />
      {dual && <YAxis yAxisId="r" orientation="right" tick={AXIS} width={44} tickFormatter={(v) => cell(rates[0], v)} />}
      <Tooltip labelFormatter={tickFormatter} formatter={valueFormatter} />
      {y.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => label(String(v))} />}
    </>
  )

  if (chart.type === 'line') {
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={records}>
          {common}
          {y.map((c, i) => (
            <Line isAnimationActive={false} key={c} yAxisId={axisFor(c)} type="monotone" dataKey={c} stroke={PALETTE[i]} strokeWidth={2} dot={records.length < 40} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={Math.min(320, 160 + records.length * 8)}>
      <BarChart data={records}>
        {common}
        {y.map((c, i) => (
          <Bar isAnimationActive={false} key={c} yAxisId={axisFor(c)} dataKey={c} fill={PALETTE[i]} radius={[4, 4, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
