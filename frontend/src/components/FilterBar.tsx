import { useEffect, useRef, useState } from 'react'
import type { FilterOptions, Filters } from '../api'
import { emptyFilters } from '../api'
import { language } from '../format'

type MultiProps = { label: string; options: string[]; value: string[]; onChange: (v: string[]) => void; render?: (v: string) => string }

function MultiSelect({ label, options, value, onChange, render = (v) => v }: MultiProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter((v) => v !== o) : [...value, o])
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition ${value.length ? 'border-indigo-300 bg-indigo-50 text-indigo-800' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'}`}
      >
        {label}
        {value.length > 0 && <span className="rounded bg-indigo-600 px-1.5 text-xs text-white">{value.length}</span>}
        <span className="text-slate-400">▾</span>
      </button>
      {open && (
        <div className="absolute z-20 mt-1 max-h-72 min-w-56 overflow-auto rounded-lg border border-slate-200 bg-white p-1 shadow-lg">
          {options.map((o) => (
            <label key={o} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50">
              <input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} className="accent-indigo-600" />
              {render(o)}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function FilterBar({ options, value, onChange }: { options: FilterOptions | null; value: Filters; onChange: (f: Filters) => void }) {
  if (!options) return <div className="h-9" />
  const minDate = options.range.start.slice(0, 10)
  const maxDate = options.range.end.slice(0, 10)
  const active = value.app.length + value.user_role.length + value.prompt_language.length + value.topic.length + (value.start ? 1 : 0) + (value.end ? 1 : 0)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm">
        <input
          type="date"
          min={minDate}
          max={maxDate}
          value={value.start?.slice(0, 10) ?? ''}
          onChange={(e) => onChange({ ...value, start: e.target.value || undefined })}
          className="bg-transparent outline-none"
        />
        <span className="text-slate-400">–</span>
        <input
          type="date"
          min={minDate}
          max={maxDate}
          value={value.end?.slice(0, 10) ?? ''}
          onChange={(e) => onChange({ ...value, end: e.target.value ? `${e.target.value}T23:59:59` : undefined })}
          className="bg-transparent outline-none"
        />
      </div>
      <MultiSelect label="App" options={options.app} value={value.app} onChange={(app) => onChange({ ...value, app })} />
      <MultiSelect label="Role" options={options.user_role} value={value.user_role} onChange={(user_role) => onChange({ ...value, user_role })} />
      <MultiSelect
        label="Language"
        options={options.prompt_language}
        value={value.prompt_language}
        render={language}
        onChange={(prompt_language) => onChange({ ...value, prompt_language })}
      />
      {/* Topic filter, hidden for now:
      <MultiSelect label="Topic" options={options.topic} value={value.topic} onChange={(topic) => onChange({ ...value, topic })} />
      */}
      {active > 0 && (
        <button type="button" onClick={() => onChange(emptyFilters)} className="px-2 text-sm text-slate-500 hover:text-slate-900">
          Clear ({active})
        </button>
      )}
    </div>
  )
}
