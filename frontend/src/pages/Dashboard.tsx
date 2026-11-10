import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
// Add AlignmentCell back to this import when the alignment matrix is re-enabled.
import type { Filters, Granularity, Summary } from '../api'
import { api, emptyFilters } from '../api'
import { Card, Loadable, Segmented } from '../components/Card'
import { DataTableView } from '../components/DataTableView'
import { FilterBar } from '../components/FilterBar'
// Add percent back to this import when the on-topic KPIs or charts are re-enabled.
import { compact, dateTime, language, number, PALETTE } from '../format'
import { useAsync } from '../useAsync'

const AXIS = { fontSize: 11, fill: '#64748b' }
const GRID = <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />

const BREAKDOWNS = [
  { value: 'app', label: 'App' },
  { value: 'intent', label: 'Intent' },
  { value: 'user_role', label: 'Role' },
  { value: 'hour', label: 'Hour' },
  { value: 'weekday', label: 'Weekday' },
] as const
type BreakdownDim = (typeof BREAKDOWNS)[number]['value']

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
    </div>
  )
}

function KpiGrid({ s }: { s: Summary }) {
  return (
    // With all eight KPIs enabled, use xl:grid-cols-8.
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Kpi label="Prompts" value={number(s.prompts)} />
      <Kpi label="Sessions" value={number(s.sessions)} hint={`${number(s.prompts_per_session, 2)} prompts / session`} />
      <Kpi label="Users" value={number(s.users)} hint={`${number(s.organizations)} organizations`} />
      <Kpi label="Avg latency" value={`${number(s.avg_latency_s, 1)} s`} hint={`p95 ${number(s.p95_latency_s, 1)} s`} />
      <Kpi label="Tokens" value={compact(s.total_tokens)} hint={`${compact(s.avg_tokens_per_prompt)} per prompt`} />
      {/* Hidden for now:
      <Kpi label="Prompt length" value={`${number(s.avg_prompt_words, 1)} words`} />
      <Kpi label="On-topic answers" value={percent(s.on_topic_rate)} hint="response matches prompt topic" />
      <Kpi label="Language match" value={percent(s.language_match_rate)} hint="reply in prompt language" />
      */}
    </div>
  )
}

/* Used by the hidden Response topic alignment chart.
function AlignmentMatrix({ cells }: { cells: AlignmentCell[] }) {
  const topics = [...new Set(cells.map((c) => c.topic))].sort()
  const responses = [...new Set(cells.map((c) => c.response_topic ?? '–'))].sort()
  const lookup = new Map(cells.map((c) => [`${c.topic}|${c.response_topic ?? '–'}`, c.count]))
  const max = Math.max(1, ...cells.map((c) => c.count))
  return (
    <div className="overflow-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="p-1 text-left font-medium text-slate-500">Prompt topic ↓ / Response topic →</th>
            {responses.map((r) => (
              <th key={r} className="h-28 w-12 p-1 align-bottom font-medium text-slate-500">
                <div className="w-6 origin-bottom-left translate-x-5 -rotate-45 whitespace-nowrap">{r}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {topics.map((t) => (
            <tr key={t}>
              <td className="whitespace-nowrap py-0.5 pr-3 text-slate-700">{t}</td>
              {responses.map((r) => {
                const n = lookup.get(`${t}|${r}`) ?? 0
                const diag = t === r
                return (
                  <td key={r} className="p-0.5">
                    <div
                      title={`${t} → ${r}: ${n}`}
                      className={`flex h-9 w-11 items-center justify-center rounded tabular-nums ${diag ? 'ring-2 ring-emerald-500' : ''}`}
                      style={{ background: n ? `rgba(79,70,229,${0.08 + (0.85 * n) / max})` : '#f8fafc', color: n / max > 0.55 ? 'white' : '#334155' }}
                    >
                      {n || ''}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">Green outline = response on the same topic as the prompt. Off-diagonal cells are off-topic answers.</p>
    </div>
  )
}
*/

export function Dashboard() {
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [granularity, setGranularity] = useState<Granularity>('hour')
  const [dim, setDim] = useState<BreakdownDim>('app')
  const [sessionPage, setSessionPage] = useState(0)
  const location = useLocation()
  const key = JSON.stringify(filters)
  const bucketLabel = (v: unknown) => (granularity === 'week' ? `Week of ${dateTime(v, false)}` : dateTime(v, granularity === 'hour'))

  const options = useAsync(() => api.filters(), [])
  const summary = useAsync(() => api.summary(filters), [key])
  const volume = useAsync(() => api.volume(filters, granularity), [key, granularity])
  // Data for the hidden Topics / quality charts; re-enable together with them.
  // const topics = useAsync(() => api.breakdown(filters, 'topic'), [key])
  // const alignment = useAsync(() => api.topicAlignment(filters), [key])
  const languages = useAsync(() => api.breakdown(filters, 'prompt_language'), [key])
  const breakdown = useAsync(() => api.breakdown(filters, dim), [key, dim])
  const latency = useAsync(() => api.histogram(filters, 'latency_s', 10), [key])
  const tokens = useAsync(() => api.tokens(filters, granularity), [key, granularity])
  const top = useAsync(() => api.topPrompts(filters, 20), [key])
  const sessions = useAsync(() => api.sessions(filters, 15, sessionPage * 15), [key, sessionPage])

  const changeFilters = (f: Filters) => {
    setFilters(f)
    setSessionPage(0)
  }
  useEffect(() => {
    const section = new URLSearchParams(location.search).get('section')
    if (section) setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: 'smooth' }), 300)
  }, [location.search])

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-6 py-6">
      <div className="sticky top-14 z-10 -mx-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/90 px-6 py-3 backdrop-blur">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Chatbot usage</h1>
          {options.data && (
            <p className="text-xs text-slate-500">
              {number(options.data.range.rows)} prompts · {dateTime(options.data.range.start)} – {dateTime(options.data.range.end)} UTC
            </p>
          )}
        </div>
        <FilterBar options={options.data} value={filters} onChange={changeFilters} />
      </div>

      <section id="overview" className="scroll-mt-32">
        <Loadable state={summary} height={88}>
          {(s) => <KpiGrid s={s} />}
        </Loadable>
      </section>

      <Card
        id="volume"
        title="Prompt volume"
        subtitle="Prompts and sessions over time"
        actions={<Segmented value={granularity} onChange={setGranularity} options={[{ value: 'hour', label: 'Hourly' }, { value: 'day', label: 'Daily' }, { value: 'week', label: 'Weekly' }]} />}
      >
        <Loadable state={volume}>
          {(rows) => (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={rows}>
                {GRID}
                <XAxis dataKey="bucket" tick={AXIS} tickFormatter={(v) => dateTime(v, granularity === 'hour')} minTickGap={30} />
                <YAxis tick={AXIS} allowDecimals={false} width={36} />
                <Tooltip labelFormatter={bucketLabel} />
                <Area isAnimationActive={false} type="monotone" dataKey="prompts" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2} dot={rows.length < 3} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Loadable>
      </Card>

      <div id="topics" className="grid scroll-mt-32 gap-5 lg:grid-cols-3">
        {/* Hidden for now:
        <Card title="Topics" subtitle="Clustered from prompt embeddings, labelled by an SLM" className="lg:col-span-2">
          <Loadable state={topics}>
            {(rows) => (
              <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 34)}>
                <BarChart data={rows} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" tick={AXIS} allowDecimals={false} />
                  <YAxis type="category" dataKey="key" tick={AXIS} width={190} />
                  <Tooltip />
                  <Bar isAnimationActive={false} dataKey="prompts" fill={PALETTE[0]} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
        */}
        {/* Breakdown sits here while the Topics chart is hidden. */}
        <Card
          title="Breakdown"
          subtitle="Prompt count per group"
          className="lg:col-span-2"
          actions={<Segmented value={dim} onChange={setDim} options={[...BREAKDOWNS]} />}
        >
          <Loadable state={breakdown}>
            {(rows) => (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={dim === 'hour' ? [...rows].sort((a, b) => Number(a.key) - Number(b.key)) : rows}>
                  {GRID}
                  <XAxis dataKey="key" tick={AXIS} interval={0} angle={dim === 'app' || dim === 'intent' ? -15 : 0} height={dim === 'hour' ? 24 : 44} />
                  <YAxis yAxisId="l" tick={AXIS} allowDecimals={false} width={36} />
                  {/* On-topic rate, hidden for now:
                  <YAxis yAxisId="r" orientation="right" tick={AXIS} tickFormatter={(v) => percent(v, 0)} domain={[0, 1]} width={40} />
                  <Tooltip formatter={(v, n) => (n === 'on_topic_rate' ? percent(v) : v)} />
                  */}
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar isAnimationActive={false} yAxisId="l" dataKey="prompts" fill={PALETTE[0]} radius={[4, 4, 0, 0]} />
                  {/* <Bar isAnimationActive={false} yAxisId="r" dataKey="on_topic_rate" fill={PALETTE[2]} radius={[4, 4, 0, 0]} /> */}
                </BarChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
        <Card title="Prompt languages">
          <Loadable state={languages}>
            {(rows) => (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie isAnimationActive={false} data={rows.map((r) => ({ ...r, name: language(String(r.key)) }))} dataKey="prompts" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                    {rows.map((_, i) => (
                      <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
      </div>

      {/* Hidden for now (Response topic alignment, On-topic rate by topic):
      <div id="quality" className="grid scroll-mt-32 gap-5 lg:grid-cols-5">
        <Card title="Response topic alignment" subtitle="Which topic the bot answered, per prompt topic" className="lg:col-span-3">
          <Loadable state={alignment}>{(cells) => <AlignmentMatrix cells={cells} />}</Loadable>
        </Card>
        <Card title="On-topic rate by topic" className="lg:col-span-2">
          <Loadable state={topics}>
            {(rows) => (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={[...rows].sort((a, b) => a.on_topic_rate - b.on_topic_rate)} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" domain={[0, 1]} tick={AXIS} tickFormatter={(v) => percent(v, 0)} />
                  <YAxis type="category" dataKey="key" tick={AXIS} width={170} />
                  <Tooltip formatter={(v) => percent(v)} />
                  <Bar isAnimationActive={false} dataKey="on_topic_rate" fill={PALETTE[2]} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
      </div>
      */}

      <div id="latency_tokens" className="grid scroll-mt-32 gap-5 lg:grid-cols-2">
        <Card title="Latency distribution" subtitle="Seconds per response">
          <Loadable state={latency}>
            {(bins) => (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={bins.map((b) => ({ ...b, range: `${b.from.toFixed(0)}–${b.to.toFixed(0)}` }))}>
                  {GRID}
                  <XAxis dataKey="range" tick={AXIS} />
                  <YAxis tick={AXIS} allowDecimals={false} width={36} />
                  <Tooltip />
                  <Bar isAnimationActive={false} dataKey="count" fill={PALETTE[1]} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
        <Card title="Token usage" subtitle={`Input vs output tokens per ${granularity}`}>
          <Loadable state={tokens}>
            {(rows) => (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={rows}>
                  {GRID}
                  <XAxis dataKey="bucket" tick={AXIS} tickFormatter={(v) => dateTime(v, granularity === 'hour')} minTickGap={30} />
                  <YAxis tick={AXIS} tickFormatter={compact} width={44} />
                  <Tooltip labelFormatter={bucketLabel} formatter={(v) => number(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area isAnimationActive={false} type="monotone" dataKey="input_tokens" stackId="t" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.25} dot={rows.length < 3} />
                  <Area isAnimationActive={false} type="monotone" dataKey="output_tokens" stackId="t" stroke={PALETTE[3]} fill={PALETTE[3]} fillOpacity={0.35} dot={rows.length < 3} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Loadable>
        </Card>
      </div>

      <Card id="prompts" title="Top prompts" subtitle="Most frequent prompts with their topic and how often the answer was on topic">
        <Loadable state={top}>
          {(rows) => (
            <DataTableView
              table={{
                columns: ['prompt', 'prompt_english', 'language', 'topic', 'intent', 'count', 'on_topic_rate'],
                rows: rows.map((r) => [r.prompt, r.prompt === r.prompt_english ? '' : r.prompt_english, language(r.language), r.topic, r.intent, r.count, r.on_topic_rate]),
                total_rows: rows.length,
              }}
            />
          )}
        </Loadable>
      </Card>

      <Card
        id="sessions"
        title="Sessions"
        subtitle={sessions.data ? `${number(sessions.data.total)} sessions` : undefined}
        actions={
          <div className="flex items-center gap-2 text-xs">
            <button type="button" disabled={sessionPage === 0} onClick={() => setSessionPage(sessionPage - 1)} className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40">
              Prev
            </button>
            <span className="text-slate-500">Page {sessionPage + 1}</span>
            <button
              type="button"
              disabled={!sessions.data || (sessionPage + 1) * 15 >= sessions.data.total}
              onClick={() => setSessionPage(sessionPage + 1)}
              className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        }
      >
        <Loadable state={sessions}>
          {(d) => (
            <DataTableView
              compact
              table={{
                columns: ['started_at', 'user_id', 'app', 'user_role', 'turns', 'languages', 'topics', 'total_tokens', 'avg_latency_s'],
                rows: d.rows.map((r) => [r.started_at, r.user_id, r.app, r.user_role, r.turns, r.languages, r.topics, r.total_tokens, r.avg_latency_s]),
                total_rows: d.rows.length,
              }}
            />
          )}
        </Loadable>
      </Card>
    </div>
  )
}
