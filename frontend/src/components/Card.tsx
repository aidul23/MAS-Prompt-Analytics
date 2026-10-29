import type { ReactNode } from 'react'
import type { AsyncState } from '../useAsync'

type Props = {
  title: string
  subtitle?: string
  id?: string
  actions?: ReactNode
  className?: string
  children: ReactNode
}

export function Card({ title, subtitle, id, actions, className = '', children }: Props) {
  return (
    <section id={id} className={`scroll-mt-24 rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  )
}

export function Loadable<T>({ state, height = 260, children }: { state: AsyncState<T>; height?: number; children: (data: T) => ReactNode }) {
  if (state.error) return <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">Failed to load: {state.error}</div>
  if (!state.data) return <div className="animate-pulse rounded-md bg-slate-100" style={{ height }} />
  return <div className={state.loading ? 'opacity-60 transition-opacity' : ''}>{children(state.data)}</div>
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 font-medium transition ${value === o.value ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
