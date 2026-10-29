import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import type { ChatMode, ChatResponse, ModelProfile, SavedChat, UiMode } from '../api'
import { api } from '../api'
import { AgentTrace } from '../components/AgentTrace'
import { Segmented } from '../components/Card'
import { ChatSidebar } from '../components/ChatSidebar'
import { DataTableView } from '../components/DataTableView'
import { ResultChart } from '../components/ResultChart'
import { label, number } from '../format'
import { useAsync } from '../useAsync'

type Message = { id: string; question: string; mode: UiMode; responses: ChatResponse[]; pending: ChatMode[]; error?: string }

const SUGGESTIONS = [
  'How many prompts were sent in Finnish?',
  'Which app has the highest average latency?',
  'Show daily prompt volume',
  'What share of answers is off-topic for each topic?',
  'Top 3 topics among admins',
  'How many tokens were used yesterday?',
  'Show some Finnish prompts about newsletters',
]

const MODE_LABEL: Record<ChatMode, string> = { mas: 'Multi-agent', baseline: 'Single model' }
const SECTION_LABEL: Record<string, string> = {
  overview: 'Overview',
  volume: 'Prompt volume',
  topics: 'Topics',
  quality: 'Response quality',
  latency_tokens: 'Latency & tokens',
  prompts: 'Top prompts',
  sessions: 'Sessions',
}

const toMessages = (chat: SavedChat): Message[] => chat.messages.map((m) => ({ ...m, pending: [] }))

function ResponseView({ resp }: { resp: ChatResponse }) {
  const [showTrace, setShowTrace] = useState(false)
  const [showTable, setShowTable] = useState(false)
  const section = resp.chart?.dashboard_section
  return (
    <div className="space-y-3">
      <p className={`whitespace-pre-wrap text-sm leading-relaxed ${resp.status === 'error' ? 'text-red-700' : 'text-slate-800'}`}>{resp.answer}</p>
      {resp.chart && resp.data && resp.chart.type !== 'table' && (
        <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3">
          {resp.chart.title && <div className="mb-2 text-xs font-medium text-slate-600">{resp.chart.title}</div>}
          <ResultChart chart={resp.chart} table={resp.data} />
        </div>
      )}
      {resp.data && (resp.chart?.type === 'table' || showTable) && <DataTableView table={resp.data} maxRows={25} compact />}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span className="tabular-nums">
          {resp.total_latency_s.toFixed(1)} s · {resp.llm_calls} LLM call{resp.llm_calls === 1 ? '' : 's'} · {number(resp.prompt_tokens + resp.completion_tokens)} tokens
        </span>
        {resp.data && resp.chart?.type !== 'table' && (
          <button type="button" className="text-indigo-600 hover:underline" onClick={() => setShowTable(!showTable)}>
            {showTable ? 'Hide' : 'Show'} data ({resp.data.total_rows} rows)
          </button>
        )}
        <button type="button" className="text-indigo-600 hover:underline" onClick={() => setShowTrace(!showTrace)}>
          {showTrace ? 'Hide' : 'Show'} {resp.mode === 'mas' ? 'agent trace' : 'trace'}
        </button>
        {section && (
          <Link to={`/?section=${section}`} className="text-indigo-600 hover:underline">
            Dashboard: {SECTION_LABEL[section] ?? label(section)} →
          </Link>
        )}
      </div>
      {showTrace && <AgentTrace resp={resp} />}
    </div>
  )
}

function Thread({
  chatId,
  initial,
  mode,
  profile,
  onStarted,
  onSaved,
}: {
  chatId: string
  initial: Message[]
  mode: UiMode
  profile: string
  onStarted: () => void
  onSaved: () => void
}) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>(initial)
  const bottom = useRef<HTMLDivElement>(null)
  const busy = messages.some((m) => m.pending.length > 0)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q || busy) return
    setInput('')
    if (messages.length === 0) onStarted()
    const modes: ChatMode[] = mode === 'compare' ? ['mas', 'baseline'] : [mode]
    const id = crypto.randomUUID()
    setMessages((ms) => [...ms, { id, question: q, mode, responses: [], pending: modes }])
    for (const m of modes) {
      try {
        const resp = await api.ask({ question: q, mode: m, profile: profile || undefined, chat_id: chatId, message_id: id, ui_mode: mode })
        setMessages((ms) => ms.map((x) => (x.id === id ? { ...x, responses: [...x.responses, resp], pending: x.pending.filter((p) => p !== m) } : x)))
        onSaved()
      } catch (e) {
        setMessages((ms) => ms.map((x) => (x.id === id ? { ...x, error: String(e), pending: x.pending.filter((p) => p !== m) } : x)))
      }
    }
  }

  return (
    <>
      <div className="flex-1 space-y-6 overflow-y-auto py-6">
        {messages.length === 0 && (
          <div className="mx-auto max-w-xl pt-10 text-center">
            <p className="text-sm text-slate-500">Try one of these, or ask your own. Follow-up questions keep the context.</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:border-indigo-300 hover:text-indigo-700">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className="space-y-3">
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-sm text-white">{m.question}</div>
            </div>
            <div className={`grid gap-3 ${m.mode === 'compare' ? 'md:grid-cols-2' : ''}`}>
              {(m.mode === 'compare' ? (['mas', 'baseline'] as ChatMode[]) : [m.mode as ChatMode]).map((cm) => {
                const resp = m.responses.find((r) => r.mode === cm)
                return (
                  <div key={cm} className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                      {MODE_LABEL[cm]}
                      {resp && <span className="normal-case tracking-normal">· {resp.profile}</span>}
                    </div>
                    {resp ? (
                      <ResponseView resp={resp} />
                    ) : m.pending.includes(cm) ? (
                      <div className="flex items-center gap-2 text-sm text-slate-400">
                        <span className="h-2 w-2 animate-ping rounded-full bg-indigo-400" />
                        {cm === 'mas' ? 'Agents are working…' : 'Thinking…'}
                      </div>
                    ) : (
                      <p className="text-sm text-red-700">{m.error ?? 'No response'}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(input)
        }}
        className="flex gap-2 border-t border-slate-200 py-4"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Which topics get the most Finnish prompts?"
          className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
        />
        <button type="submit" disabled={busy || !input.trim()} className="rounded-xl bg-indigo-600 px-5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
          Ask
        </button>
      </form>
    </>
  )
}

function ActiveModels({ profile, mode }: { profile: ModelProfile; mode: UiMode }) {
  const m = profile.models
  const parts: [string, string | null][] = []
  if (mode !== 'baseline') parts.push(['Query', m.query_understanding], ['Chart', m.visualization_planning], ['Answer', m.answer_generation])
  if (mode !== 'mas') parts.push(['Single model', m.baseline])
  return (
    <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
      {parts.map(([role, model]) => (
        <span key={role}>
          {role}: <code className="text-slate-700">{model ?? '—'}</code>
        </span>
      ))}
      <Link to="/models" className="text-indigo-600 hover:underline">
        Change models
      </Link>
    </div>
  )
}

export function Chat() {
  const { chatId } = useParams()
  const navigate = useNavigate()
  const models = useAsync(() => api.models(), [])
  const [mode, setMode] = useState<UiMode>('mas')
  const [chosenProfile, setProfile] = useState<string>('')
  const profile = chosenProfile || models.data?.default_profile || ''
  const activeProfile = models.data?.profiles.find((p) => p.name === profile)

  // A new chat gets its id up front; the URL switches to /chat/<id> once the first question is asked,
  // without remounting the thread, and the chat is stored by the API with its first response.
  const [draftId, setDraftId] = useState(() => crypto.randomUUID())
  const isDraft = !chatId || chatId === draftId
  const threadId = chatId ?? draftId
  const [version, setVersion] = useState(0)
  const refresh = () => setVersion((v) => v + 1)
  const list = useAsync(() => api.chats(), [version])
  const saved = useAsync(() => (chatId && !isDraft ? api.chat(chatId) : Promise.resolve(null)), [isDraft ? null : chatId])
  const title = list.data?.find((c) => c.id === threadId)?.title

  const newChat = () => {
    setDraftId(crypto.randomUUID())
    navigate('/chat')
  }
  const remove = async (id: string) => {
    await api.deleteChat(id)
    refresh()
    if (id === threadId) newChat()
  }
  const rename = async (id: string, t: string) => {
    await api.renameChat(id, t)
    refresh()
  }

  let thread
  if (isDraft) {
    thread = <Thread key={threadId} chatId={threadId} initial={[]} mode={mode} profile={profile} onStarted={() => navigate(`/chat/${threadId}`)} onSaved={refresh} />
  } else if (saved.data?.id === chatId) {
    thread = <Thread key={chatId} chatId={chatId} initial={toMessages(saved.data)} mode={mode} profile={profile} onStarted={() => {}} onSaved={refresh} />
  } else if (saved.error) {
    thread = (
      <div className="pt-16 text-center text-sm text-slate-500">
        This chat no longer exists.{' '}
        <button type="button" onClick={newChat} className="text-indigo-600 hover:underline">
          Start a new chat
        </button>
      </div>
    )
  } else {
    thread = <div className="pt-16 text-center text-sm text-slate-400">Loading conversation…</div>
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <ChatSidebar chats={list.data ?? []} activeId={threadId} onNew={newChat} onOpen={(id) => navigate(`/chat/${id}`)} onRename={rename} onDelete={remove} />
      <div className="mx-auto flex min-w-0 max-w-5xl flex-1 flex-col px-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 py-3">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-slate-900">{title ?? 'Ask the data'}</h1>
            <p className="text-xs text-slate-500">Natural-language questions over the chatbot traces, answered by small local models.</p>
          </div>
          <div className="flex items-center gap-2">
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: 'mas', label: 'Multi-agent' },
                { value: 'baseline', label: 'Single model' },
                { value: 'compare', label: 'Compare' },
              ]}
            />
            <select value={profile} onChange={(e) => setProfile(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs" title="Model profile">
              {models.data?.profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  profile: {p.name}
                </option>
              ))}
            </select>
          </div>
          {activeProfile && <ActiveModels profile={activeProfile} mode={mode} />}
        </div>
        {thread}
      </div>
    </div>
  )
}
