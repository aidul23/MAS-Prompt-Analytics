import { useState } from 'react'
import type { ChatResponse } from '../api'
import { label, number } from '../format'

const AGENT_COLORS: Record<string, string> = {
  data_processing: 'bg-slate-400',
  query_understanding: 'bg-indigo-500',
  metrics: 'bg-emerald-500',
  visualization_planning: 'bg-amber-500',
  answer_generation: 'bg-sky-500',
  'single_model:sql': 'bg-indigo-500',
  'single_model:answer': 'bg-sky-500',
}

export function AgentTrace({ resp }: { resp: ChatResponse }) {
  const [open, setOpen] = useState<number | null>(null)
  const total = Math.max(resp.total_latency_s, 0.001)
  return (
    <div className="space-y-3 text-xs">
      <div className="flex h-2 overflow-hidden rounded-full bg-slate-100">
        {resp.steps.map((s, i) => (
          <div key={i} className={AGENT_COLORS[s.agent] ?? 'bg-slate-400'} style={{ width: `${(100 * s.latency_s) / total}%` }} title={`${s.agent}: ${s.latency_s}s`} />
        ))}
      </div>
      <ol className="space-y-1">
        {resp.steps.map((s, i) => (
          <li key={i} className="rounded-md border border-slate-200 bg-white">
            <button type="button" onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50">
              <span className={`h-2 w-2 shrink-0 rounded-full ${AGENT_COLORS[s.agent] ?? 'bg-slate-400'}`} />
              <span className="font-medium text-slate-800">{label(s.agent.replace('single_model:', 'single model: '))}</span>
              {s.llm_calls > 0 ? (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">{s.model}</span>
              ) : (
                <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">deterministic</span>
              )}
              {s.error && <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-700">error</span>}
              <span className="ml-auto tabular-nums text-slate-500">
                {s.llm_calls > 0 && `${s.llm_calls} call${s.llm_calls > 1 ? 's' : ''} · ${number(s.prompt_tokens + s.completion_tokens)} tok · `}
                {s.latency_s.toFixed(2)} s
              </span>
            </button>
            {open === i && (
              <div className="border-t border-slate-100 px-3 py-2">
                {s.error && <p className="mb-2 text-red-700">{s.error}</p>}
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
                  {JSON.stringify(s.output, null, 2)}
                </pre>
              </div>
            )}
          </li>
        ))}
      </ol>
      {resp.sql && (
        <div>
          <div className="mb-1 font-medium text-slate-600">SQL {resp.mode === 'mas' ? '(compiled from query spec)' : '(written by the model)'}</div>
          <pre className="overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-100">{resp.sql}</pre>
        </div>
      )}
    </div>
  )
}
