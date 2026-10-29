import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { api, type DataSource, type DataStatus, type SyncRun } from '../api'

const ACCEPT = '.csv,.json,.jsonl,.ndjson,.xlsx'
const INTERVALS: { label: string; value: number | null }[] = [
  { label: 'Manual only', value: null },
  { label: 'Every 5 min', value: 5 },
  { label: 'Every 15 min', value: 15 },
  { label: 'Hourly', value: 60 },
  { label: 'Daily', value: 1440 },
]

const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm'
const button =
  'rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50'

function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function SyncBadge({ status }: { status: SyncRun['status'] }) {
  const style = {
    running: 'bg-amber-50 text-amber-700',
    ok: 'bg-emerald-50 text-emerald-700',
    error: 'bg-red-50 text-red-700',
  }[status]
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style}`}>{status === 'ok' ? 'up to date' : status}</span>
}

function StatusCard({ status, onSync, busy }: { status: DataStatus | null; onSync: () => void; busy: boolean }) {
  const last = status?.last_sync
  return (
    <section className={card}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Current dataset</h2>
          {status?.data ? (
            <p className="mt-1 text-2xl font-semibold text-slate-900">
              {status.data.rows.toLocaleString()} <span className="text-sm font-normal text-slate-500">traces</span>
            </p>
          ) : (
            <p className="mt-1 text-sm text-slate-500">No data loaded yet. Upload a trace export below.</p>
          )}
          {status?.data && (
            <p className="text-xs text-slate-500">
              {status.data.start.slice(0, 16)} → {status.data.end.slice(0, 16)} UTC
            </p>
          )}
        </div>
        <button
          className={`${button} bg-indigo-600 text-white hover:bg-indigo-700`}
          onClick={onSync}
          disabled={busy || status?.running}
        >
          {status?.running ? 'Syncing…' : 'Sync now'}
        </button>
      </div>
      {last && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
          <SyncBadge status={status?.running ? 'running' : last.status} />
          <span>
            Last sync {when(last.finished_at ?? last.started_at)} ({last.trigger})
          </span>
          {last.status === 'ok' && last.new_traces !== null && <span>· {last.new_traces} new traces</span>}
          {last.status === 'error' && <span className="text-red-600">· {last.message}</span>}
        </div>
      )}
    </section>
  )
}

function UploadZone({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<{ ok: boolean; text: string }[]>([])

  async function upload(files: FileList | File[]) {
    setBusy(true)
    const out: { ok: boolean; text: string }[] = []
    for (const file of Array.from(files)) {
      try {
        const r = await api.upload(file)
        out.push({
          ok: true,
          text: `${r.file.name}: ${r.file.rows} traces, ${r.file.new_traces} new. ${r.sync_id ? 'Syncing…' : 'Queued for the next sync.'}`,
        })
      } catch (e) {
        out.push({ ok: false, text: `${file.name}: ${e instanceof Error ? e.message : String(e)}` })
      }
    }
    setMessages(out)
    setBusy(false)
    onUploaded()
  }

  return (
    <section className={card}>
      <h2 className="text-sm font-semibold text-slate-900">Upload trace exports</h2>
      <p className="mt-1 text-xs text-slate-500">
        Langfuse-style exports as CSV, JSON, JSONL or Excel. Each trace needs an <code>id</code>, a <code>timestamp</code> and the
        user <code>input</code>. Traces already in the dataset are updated, new ones are added.
      </p>
      <div
        className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-8 text-sm transition ${
          dragging ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200 hover:border-slate-300'
        }`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (e.dataTransfer.files.length) void upload(e.dataTransfer.files)
        }}
      >
        <span className="font-medium text-slate-700">{busy ? 'Uploading and validating…' : 'Drop files here or click to choose'}</span>
        <span className="mt-1 text-xs text-slate-400">{ACCEPT.replaceAll(',', ' ')}</span>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) void upload(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
      {messages.map((m, i) => (
        <p key={i} className={`mt-2 text-xs ${m.ok ? 'text-emerald-700' : 'text-red-600'}`}>
          {m.text}
        </p>
      ))}
    </section>
  )
}

function SourceCard({ source, onChange }: { source: DataSource; onChange: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const run = (action: () => Promise<unknown>) => () => {
    setError(null)
    action()
      .then(onChange)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }
  const folder = source.kind === 'folder'
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-900">
            {source.name}{' '}
            <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-500">
              {folder ? 'watched folder' : 'uploads'}
            </span>
          </p>
          {folder && (
            <p className="mt-0.5 text-xs text-slate-500">
              {source.path} · last checked {when(source.last_checked_at)}
            </p>
          )}
        </div>
        {folder && (
          <div className="flex items-center gap-2">
            <select
              className="rounded-md border border-slate-200 px-2 py-1 text-sm"
              value={source.sync_interval_min ?? ''}
              onChange={(e) =>
                run(() => api.updateSource(source.id, { sync_interval_min: e.target.value ? Number(e.target.value) : null }))()
              }
            >
              {INTERVALS.map((i) => (
                <option key={i.label} value={i.value ?? ''}>
                  {i.label}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={source.enabled}
                onChange={(e) => run(() => api.updateSource(source.id, { enabled: e.target.checked }))()}
              />
              enabled
            </label>
            <button
              className={`${button} text-red-600 hover:bg-red-50`}
              onClick={() => {
                if (confirm(`Remove "${source.name}" and its imported files from the dataset?`)) run(() => api.deleteSource(source.id))()
              }}
            >
              Remove
            </button>
          </div>
        )}
      </div>
      {source.files.length === 0 ? (
        <p className="mt-3 text-xs text-slate-400">No files yet.</p>
      ) : (
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="py-1 font-medium">File</th>
              <th className="py-1 font-medium">Traces</th>
              <th className="py-1 font-medium">Size</th>
              <th className="py-1 font-medium">Added</th>
              <th />
            </tr>
          </thead>
          <tbody className="text-slate-700">
            {source.files.map((f) => (
              <tr key={f.id} className="border-t border-slate-100">
                <td className="py-1.5">
                  {f.name}
                  {f.missing && <span className="ml-2 text-red-600">file missing</span>}
                </td>
                <td>{f.rows.toLocaleString()}</td>
                <td>{bytes(f.size)}</td>
                <td>{when(f.added_at)}</td>
                <td className="text-right">
                  <button
                    className="text-slate-400 hover:text-red-600"
                    title="Remove this file from the dataset"
                    onClick={() => {
                      if (confirm(`Remove ${f.name}? Its traces leave the dataset unless another file contains them.`))
                        run(() => api.deleteFile(f.id))()
                    }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  )
}

function AddFolder({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [interval, setSyncInterval] = useState<number | null>(15)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      const r = await api.addFolder({ name, path, sync_interval_min: interval })
      const problems = r.problems.length ? ` Skipped: ${r.problems.join('; ')}` : ''
      setResult({ ok: true, text: `Added. Imported ${r.imported.length} file(s).${problems}` })
      setName('')
      setPath('')
      onAdded()
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) })
    }
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-dashed border-slate-200 p-4">
      <p className="text-sm font-medium text-slate-900">Watch a folder</p>
      <p className="mt-0.5 text-xs text-slate-500">
        Point to a folder where exports are dropped (e.g. a scheduled Langfuse export or a synced drive). New files are
        imported automatically on the chosen interval.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          className="w-40 rounded-md border border-slate-200 px-2 py-1 text-sm"
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="min-w-64 flex-1 rounded-md border border-slate-200 px-2 py-1 text-sm"
          placeholder="/path/to/exports"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          required
        />
        <select
          className="rounded-md border border-slate-200 px-2 py-1 text-sm"
          value={interval ?? ''}
          onChange={(e) => setSyncInterval(e.target.value ? Number(e.target.value) : null)}
        >
          {INTERVALS.map((i) => (
            <option key={i.label} value={i.value ?? ''}>
              {i.label}
            </option>
          ))}
        </select>
        <button className={`${button} bg-slate-900 text-white hover:bg-slate-700`} type="submit">
          Add folder
        </button>
      </div>
      {result && <p className={`mt-2 text-xs ${result.ok ? 'text-emerald-700' : 'text-red-600'}`}>{result.text}</p>}
    </form>
  )
}

function SyncHistory({ syncs }: { syncs: SyncRun[] }) {
  return (
    <section className={card}>
      <h2 className="text-sm font-semibold text-slate-900">Sync history</h2>
      {syncs.length === 0 ? (
        <p className="mt-2 text-xs text-slate-400">No syncs yet.</p>
      ) : (
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="py-1 font-medium">Started</th>
              <th className="py-1 font-medium">Trigger</th>
              <th className="py-1 font-medium">Status</th>
              <th className="py-1 font-medium">Traces</th>
              <th className="py-1 font-medium">New</th>
              <th className="py-1 font-medium">Details</th>
            </tr>
          </thead>
          <tbody className="text-slate-700">
            {syncs.map((s) => (
              <tr key={s.id} className="border-t border-slate-100 align-top">
                <td className="py-1.5 whitespace-nowrap">{when(s.started_at)}</td>
                <td>{s.trigger}</td>
                <td>
                  <SyncBadge status={s.status} />
                </td>
                <td>{s.rows_after ?? '—'}</td>
                <td>{s.new_traces ?? '—'}</td>
                <td className={`max-w-md ${s.status === 'error' ? 'text-red-600' : 'text-slate-500'}`}>{s.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function DataSources() {
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [syncs, setSyncs] = useState<SyncRun[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [st, src, hist] = await Promise.all([api.dataStatus(), api.sources(), api.syncs()])
      setStatus(st)
      setSources(src)
      setSyncs(hist)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const running = status?.running ?? false
  useEffect(() => {
    const first = window.setTimeout(() => void reload(), 0)
    const timer = window.setInterval(() => void reload(), running ? 2000 : 15000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
    }
  }, [reload, running])

  async function syncNow() {
    setBusy(true)
    try {
      await api.sync()
    } finally {
      setBusy(false)
      void reload()
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Data sources</h1>
        <p className="text-sm text-slate-500">
          Add chatbot trace exports. Each sync analyses only new prompts and updates the dashboard and the chat.
        </p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <StatusCard status={status} onSync={() => void syncNow()} busy={busy} />
      <UploadZone onUploaded={() => void reload()} />
      <section className={`${card} space-y-3`}>
        <h2 className="text-sm font-semibold text-slate-900">Sources</h2>
        {sources.map((s) => (
          <SourceCard key={s.id} source={s} onChange={() => void reload()} />
        ))}
        <AddFolder onAdded={() => void reload()} />
      </section>
      <SyncHistory syncs={syncs} />
    </div>
  )
}
