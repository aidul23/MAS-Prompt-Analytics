import { type FormEvent, useEffect, useState } from 'react'
import { api, type InstalledModel, type ModelProfile, type ModelPull, type ModelRole, type ModelsOverview } from '../api'
import { useAsync } from '../useAsync'

const ROLE_LABELS: Record<ModelRole, string> = {
  query_understanding: 'Query Understanding Agent',
  visualization_planning: 'Visualization Planning Agent',
  answer_generation: 'Answer Generation Agent',
  baseline: 'Single model (baseline)',
}
const MAS_ROLES: ModelRole[] = ['query_understanding', 'visualization_planning', 'answer_generation']

const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm'
const button = 'rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50'

function gb(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

function modelLabel(m: InstalledModel): string {
  return [m.name, m.parameter_size].filter(Boolean).join(' · ')
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function RoleRows({
  profile,
  draft,
  chatModels,
  onChange,
}: {
  profile: ModelProfile
  draft?: Record<ModelRole, string>
  chatModels: InstalledModel[]
  onChange?: (role: ModelRole, model: string) => void
}) {
  const row = (role: ModelRole) => {
    const value = draft ? draft[role] : profile.models[role]
    const missing = value && chatModels.length > 0 && !chatModels.some((m) => m.name === value)
    return (
      <div key={role} className="flex items-center justify-between gap-3 py-1.5">
        <span className="text-sm text-slate-600">{ROLE_LABELS[role]}</span>
        {onChange && draft ? (
          <select
            className="w-64 rounded-md border border-slate-200 bg-white px-2 py-1 text-sm"
            value={value ?? ''}
            onChange={(e) => onChange(role, e.target.value)}
          >
            {!value && <option value="">Choose a model…</option>}
            {missing && <option value={value}>{value} (not installed)</option>}
            {chatModels.map((m) => (
              <option key={m.name} value={m.name}>
                {modelLabel(m)}
              </option>
            ))}
          </select>
        ) : (
          <code className={`text-sm ${missing ? 'text-red-600' : 'text-slate-900'}`}>
            {value ?? '—'}
            {missing && ' (not installed)'}
          </code>
        )}
      </div>
    )
  }
  return (
    <div className="mt-3 grid gap-4 md:grid-cols-2">
      <div>
        <p className="text-xs font-semibold tracking-wide text-slate-400 uppercase">Multi-agent system</p>
        <div className="divide-y divide-slate-100">{MAS_ROLES.map(row)}</div>
        <p className="mt-1 text-xs text-slate-400">The Metrics Agent runs SQL without a model.</p>
      </div>
      <div>
        <p className="text-xs font-semibold tracking-wide text-slate-400 uppercase">Single model</p>
        <div className="divide-y divide-slate-100">{row('baseline')}</div>
      </div>
    </div>
  )
}

function ProfileCard({
  profile,
  isDefault,
  chatModels,
  taken,
  onSaved,
}: {
  profile: ModelProfile
  isDefault: boolean
  chatModels: InstalledModel[]
  taken: string[]
  onSaved: (o: ModelsOverview, select?: string) => void
}) {
  const [draft, setDraft] = useState<Record<ModelRole, string> | null>(null)
  const [name, setName] = useState(profile.name)
  const [error, setError] = useState<string | null>(null)
  const editing = draft !== null

  const startEditing = () => {
    let copyName = profile.name
    if (profile.builtin) {
      copyName = `${profile.name}-custom`
      for (let i = 2; taken.includes(copyName); i++) copyName = `${profile.name}-custom-${i}`
    }
    setName(copyName)
    setDraft({ ...(profile.models as Record<ModelRole, string>) })
    setError(null)
  }

  const save = async () => {
    if (!draft) return
    try {
      const overview = await api.saveProfile(name.trim(), draft, profile.builtin ? `Based on ${profile.name}` : profile.description)
      setDraft(null)
      onSaved(overview, name.trim())
    } catch (e) {
      setError(errorText(e))
    }
  }

  const act = (fn: () => Promise<ModelsOverview>) => () => {
    setError(null)
    fn()
      .then((o) => onSaved(o))
      .catch((e: unknown) => setError(errorText(e)))
  }

  return (
    <div className={`rounded-lg border p-4 ${isDefault ? 'border-indigo-300 ring-1 ring-indigo-100' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          {editing ? (
            <input
              className="rounded-md border border-slate-200 px-2 py-1 text-sm font-medium"
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase())}
              disabled={!profile.builtin}
              title={profile.builtin ? 'Name of the new profile' : 'Custom profiles keep their name'}
            />
          ) : (
            <span className="text-sm font-semibold text-slate-900">{profile.name}</span>
          )}
          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{profile.builtin ? 'built-in' : 'custom'}</span>
          {isDefault && <span className="ml-1 rounded bg-indigo-50 px-1.5 py-0.5 text-xs font-medium text-indigo-700">default</span>}
          {profile.description && !editing && <p className="mt-0.5 text-xs text-slate-500">{profile.description}</p>}
          {editing && profile.builtin && (
            <p className="mt-1 text-xs text-slate-500">Built-in profiles stay unchanged for the evaluation; this saves a new custom profile.</p>
          )}
        </div>
        <div className="flex gap-2">
          {editing ? (
            <>
              <button className={`${button} text-slate-600 hover:bg-slate-100`} onClick={() => setDraft(null)}>
                Cancel
              </button>
              <button className={`${button} bg-indigo-600 text-white hover:bg-indigo-700`} onClick={() => void save()}>
                Save
              </button>
            </>
          ) : (
            <>
              {!isDefault && (
                <button className={`${button} text-indigo-700 hover:bg-indigo-50`} onClick={act(() => api.setDefaultProfile(profile.name))}>
                  Use as default
                </button>
              )}
              <button className={`${button} border border-slate-200 text-slate-700 hover:bg-slate-50`} onClick={startEditing}>
                {profile.builtin ? 'Customize' : 'Edit'}
              </button>
              {!profile.builtin && (
                <button
                  className={`${button} text-red-600 hover:bg-red-50`}
                  onClick={() => {
                    if (confirm(`Delete the profile "${profile.name}"?`)) act(() => api.deleteProfile(profile.name))()
                  }}
                >
                  Delete
                </button>
              )}
            </>
          )}
        </div>
      </div>
      <RoleRows
        profile={profile}
        draft={draft ?? undefined}
        chatModels={chatModels}
        onChange={editing ? (role, model) => setDraft((d) => (d ? { ...d, [role]: model } : d)) : undefined}
      />
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  )
}

function PullRow({ pull, onCancel }: { pull: ModelPull; onCancel: () => void }) {
  const pct = pull.total ? Math.round((pull.completed / pull.total) * 100) : null
  const tone = { running: 'bg-indigo-500', done: 'bg-emerald-500', error: 'bg-red-500', cancelled: 'bg-slate-300' }[pull.state]
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between gap-3 text-sm">
        <code className="text-slate-900">{pull.name}</code>
        <span className="text-xs text-slate-500">
          {pull.state === 'running' && (pct !== null ? `${pct}% · ${gb(pull.completed)} of ${gb(pull.total)}` : pull.status)}
          {pull.state === 'done' && 'Installed. It is now available in the profile editors.'}
          {pull.state === 'cancelled' && 'Cancelled'}
          {pull.state === 'error' && <span className="text-red-600">{pull.error}</span>}
          {pull.state === 'running' && (
            <button className="ml-3 text-slate-400 hover:text-red-600" onClick={onCancel}>
              Cancel
            </button>
          )}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-100">
        <div className={`h-full ${tone} transition-all`} style={{ width: `${pull.state === 'done' ? 100 : (pct ?? 3)}%` }} />
      </div>
    </div>
  )
}

function DownloadModels({ overview, onChange }: { overview: ModelsOverview; onChange: (o: ModelsOverview) => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { ollama } = overview
  const installed = new Set(overview.installed.map((m) => m.name))
  const busy = new Set(overview.pulls.filter((p) => p.state === 'running').map((p) => p.name))

  const pull = async (model: string) => {
    setError(null)
    try {
      await api.pullModel(model)
      onChange(await api.models())
      setName('')
    } catch (e) {
      setError(errorText(e))
    }
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) void pull(name.trim())
  }

  return (
    <section className={card}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Download models</h2>
        <span className="flex items-center gap-1.5 text-xs text-slate-500">
          <span className={`h-2 w-2 rounded-full ${ollama.running ? 'bg-emerald-500' : 'bg-red-500'}`} />
          {ollama.running
            ? `Ollama ${ollama.version} running`
            : ollama.installed
              ? 'Ollama is installed but not running'
              : 'Ollama not found'}
        </span>
      </div>
      {!ollama.running ? (
        <p className="mt-2 text-sm text-slate-600">
          {ollama.installed ? (
            <>Start the Ollama app (or run <code>ollama serve</code>), then reload this page.</>
          ) : (
            <>
              Install Ollama from{' '}
              <a className="text-indigo-600 hover:underline" href="https://ollama.com/download" target="_blank" rel="noreferrer">
                ollama.com/download
              </a>
              , start it, then reload this page.
            </>
          )}
        </p>
      ) : (
        <>
          <p className="mt-1 text-xs text-slate-500">
            Downloads a model into the local Ollama. Any name from the{' '}
            <a className="text-indigo-600 hover:underline" href="https://ollama.com/library" target="_blank" rel="noreferrer">
              Ollama library
            </a>{' '}
            works, e.g. <code>qwen2.5:3b</code>. Downloads continue in the background if you leave this page.
          </p>
          <form onSubmit={submit} className="mt-3 flex gap-2">
            <input
              className="flex-1 rounded-md border border-slate-200 px-2 py-1.5 text-sm"
              placeholder="Model name, e.g. qwen2.5:3b"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className={`${button} bg-indigo-600 text-white hover:bg-indigo-700`} type="submit" disabled={!name.trim()}>
              Download
            </button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {overview.suggested
              .filter((s) => !installed.has(s.name))
              .map((s) => (
                <button
                  key={s.name}
                  className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50"
                  title={s.note}
                  disabled={busy.has(s.name)}
                  onClick={() => void pull(s.name)}
                >
                  {s.name} · {s.size_gb} GB
                </button>
              ))}
          </div>
        </>
      )}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {overview.pulls.length > 0 && (
        <div className="mt-4 space-y-2">
          {overview.pulls.map((p) => (
            <PullRow
              key={p.name}
              pull={p}
              onCancel={() =>
                void api
                  .cancelPull(p.name)
                  .then(() => api.models())
                  .then(onChange)
              }
            />
          ))}
        </div>
      )}
    </section>
  )
}

export function Models() {
  const loaded = useAsync(() => api.models(), [])
  const [overview, setOverview] = useState<ModelsOverview | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const data = overview ?? loaded.data
  const pulling = data?.pulls.some((p) => p.state === 'running') ?? false
  useEffect(() => {
    if (!pulling) return
    const timer = window.setInterval(() => {
      api
        .models()
        .then(setOverview)
        .catch(() => {})
    }, 1500)
    return () => window.clearInterval(timer)
  }, [pulling])

  if (loaded.error && !data) return <p className="p-6 text-sm text-red-600">{loaded.error}</p>
  if (!data) return <p className="p-6 text-sm text-slate-400">Loading models…</p>

  const chatModels = data.installed.filter((m) => !m.embedding)
  const loadedNames = new Set(data.loaded.map((m) => m.name))
  const usedBy = (model: string) =>
    data.profiles.filter((p) => Object.values(p.models).includes(model)).map((p) => p.name)
  const saved = (o: ModelsOverview, select?: string) => {
    setOverview(o)
    setNotice(select ? `Saved profile "${select}". Choose it in the chat or make it the default.` : null)
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Models</h1>
        <p className="text-sm text-slate-500">
          Choose which local Ollama model powers each agent and the single-model baseline. A profile is one such assignment; the chat
          uses the default profile unless you pick another one there. Changes apply from the next question.
        </p>
      </div>
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}

      <section className={`${card} space-y-3`}>
        <h2 className="text-sm font-semibold text-slate-900">Profiles</h2>
        {data.profiles.map((p) => (
          <ProfileCard
            key={p.name}
            profile={p}
            isDefault={p.name === data.default_profile}
            chatModels={chatModels}
            taken={data.profiles.map((x) => x.name)}
            onSaved={saved}
          />
        ))}
      </section>

      <section className={card}>
        <h2 className="text-sm font-semibold text-slate-900">Installed models</h2>
        {data.installed.length === 0 ? (
          <p className="mt-2 text-sm text-red-600">No models found. Is Ollama running?</p>
        ) : (
          <table className="mt-3 w-full text-left text-sm [&_td]:pr-4 [&_td]:whitespace-nowrap [&_th]:pr-4">
            <thead className="text-xs text-slate-400">
              <tr>
                <th className="py-1 font-medium">Model</th>
                <th className="py-1 font-medium">Parameters</th>
                <th className="py-1 font-medium">Quantization</th>
                <th className="py-1 font-medium">Size</th>
                <th className="py-1 font-medium">Used by</th>
                <th />
              </tr>
            </thead>
            <tbody className="text-slate-700">
              {data.installed.map((m) => {
                const users = usedBy(m.name)
                if (m.name === data.data_processing_model) users.push('data processing')
                if (m.name === data.embedding_model || m.name === `${data.embedding_model}:latest`) users.push('embeddings')
                return (
                  <tr key={m.name} className="border-t border-slate-100">
                    <td className="py-1.5">
                      <code>{m.name}</code>
                      {loadedNames.has(m.name) && <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">in memory</span>}
                      {m.embedding && <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">embedding</span>}
                    </td>
                    <td>{m.parameter_size ?? '—'}</td>
                    <td>{m.quantization ?? '—'}</td>
                    <td>{gb(m.size)}</td>
                    <td className="text-xs text-slate-500">{users.join(', ') || '—'}</td>
                    <td className="text-right">
                      {users.length === 0 && (
                        <button
                          className="text-xs text-slate-400 hover:text-red-600"
                          title="Remove this model from Ollama to free disk space"
                          onClick={() => {
                            if (confirm(`Delete ${m.name} from Ollama (${gb(m.size)})? You can download it again later.`))
                              api
                                .deleteModel(m.name)
                                .then((o) => saved(o))
                                .catch((e: unknown) => setNotice(errorText(e)))
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <DownloadModels overview={data} onChange={setOverview} />

      <section className={card}>
        <h2 className="text-sm font-semibold text-slate-900">Data processing</h2>
        <p className="mt-1 text-sm text-slate-600">
          When data is synced, <code>{data.data_processing_model}</code> translates prompts, classifies intents and labels topics, and{' '}
          <code>{data.embedding_model}</code> computes embeddings for topic clustering. Their outputs are cached and shared by all
          profiles, so they are set in <code>backend/app/mas/config.yaml</code>; changing them re-analyses the whole dataset.
        </p>
      </section>
    </div>
  )
}
