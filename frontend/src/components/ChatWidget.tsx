import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { SavedChat, UiMode } from '../api'
import { api } from '../api'
import { Thread, type Message } from '../pages/Chat'
import { newId } from '../id'
import { useAsync } from '../useAsync'
import { Segmented } from './Card'

const STORAGE_KEY = 'mas.widgetChat'

type View =
  | { kind: 'draft'; id: string; started: boolean }
  | { kind: 'loading'; id: string }
  | { kind: 'saved'; id: string; messages: Message[]; loadedAt: number }

const toMessages = (chat: SavedChat): Message[] => chat.messages.map((m) => ({ ...m, pending: [] }))

const draft = (): View => ({ kind: 'draft', id: newId(), started: false })

function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" title={title} aria-label={title} onClick={onClick} className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800">
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
    </button>
  )
}

/** Floating "Ask the data" assistant, available on every page except the full chat page. */
export function ChatWidget({ disabled }: { disabled: boolean }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [mode, setMode] = useState<UiMode>('mas')
  const [busy, setBusy] = useState(false)
  const [view, setView] = useState<View>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? { kind: 'loading', id: stored } : draft()
  })
  const [listVersion, setListVersion] = useState(0)
  const list = useAsync(() => (open ? api.chats() : Promise.resolve(null)), [open, listVersion])
  const title = list.data?.find((c) => c.id === view.id)?.title

  const newChat = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setShowHistory(false)
    setView(draft())
  }, [])

  const load = useCallback(
    (id: string) =>
      api
        .chat(id)
        .then((chat) => setView((v) => (v.id === id ? { kind: 'saved', id, messages: toMessages(chat), loadedAt: Date.now() } : v)))
        .catch(() => newChat()),
    [newChat],
  )

  useEffect(() => {
    if (view.kind === 'loading') void load(view.id)
  }, [view, load])

  const openChat = (id: string) => {
    localStorage.setItem(STORAGE_KEY, id)
    setShowHistory(false)
    setView({ kind: 'loading', id })
  }

  const toggle = () => {
    if (!open && !busy && (view.kind === 'saved' || (view.kind === 'draft' && view.started))) {
      // The chat may have continued on the full chat page meanwhile.
      void load(view.id)
    }
    setOpen(!open)
  }

  const expand = () => {
    setOpen(false)
    const persisted = view.kind !== 'draft' || view.started
    navigate(persisted ? `/chat/${view.id}` : '/chat')
  }

  const onStarted = useCallback(() => {
    setView((v) => {
      if (v.kind !== 'draft') return v
      localStorage.setItem(STORAGE_KEY, v.id)
      return { ...v, started: true }
    })
  }, [])
  const onSaved = useCallback(() => setListVersion((n) => n + 1), [])

  const hidden = disabled || location.pathname.startsWith('/chat')

  let body
  if (showHistory) {
    body = (
      <div className="flex-1 overflow-y-auto p-2">
        {list.data?.length === 0 && <p className="p-4 text-center text-sm text-slate-500">No saved chats yet.</p>}
        {list.data?.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => openChat(c.id)}
            className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100 ${c.id === view.id ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700'}`}
          >
            {c.title}
          </button>
        ))}
      </div>
    )
  } else if (view.kind === 'loading') {
    body = <div className="flex-1 pt-16 text-center text-sm text-slate-400">Loading conversation…</div>
  } else {
    body = (
      <Thread
        key={view.kind === 'saved' ? `${view.id}-${view.loadedAt}` : view.id}
        chatId={view.id}
        initial={view.kind === 'saved' ? view.messages : []}
        mode={mode}
        profile=""
        onStarted={onStarted}
        onSaved={onSaved}
        onBusyChange={setBusy}
        compact
      />
    )
  }

  return (
    <div className={hidden ? 'hidden' : ''}>
      <div
        role="dialog"
        aria-label="Ask the data"
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        className={`fixed bottom-24 right-6 z-40 flex h-[min(680px,calc(100vh-8rem))] w-[440px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl ${open ? '' : 'hidden'}`}
      >
        <div className="space-y-2 border-b border-slate-200 bg-slate-50/60 px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-900">{showHistory ? 'Recent chats' : (title ?? 'Ask the data')}</div>
              {!showHistory && <div className="text-[11px] text-slate-500">Questions over the traces, answered by local models</div>}
            </div>
            <div className="flex shrink-0 items-center">
              <IconButton title={showHistory ? 'Back to chat' : 'Recent chats'} onClick={() => setShowHistory(!showHistory)}>
                {showHistory ? <path d="M15 18l-6-6 6-6" /> : <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2" />}
              </IconButton>
              <IconButton title="New chat" onClick={newChat}>
                <path d="M12 5v14M5 12h14" />
              </IconButton>
              <IconButton title="Open full chat page" onClick={expand}>
                <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
              </IconButton>
              <IconButton title="Close" onClick={() => setOpen(false)}>
                <path d="M18 6L6 18M6 6l12 12" />
              </IconButton>
            </div>
          </div>
          {!showHistory && (
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: 'mas', label: 'Multi-agent' },
                { value: 'baseline', label: 'Single model' },
                { value: 'compare', label: 'Compare' },
              ]}
            />
          )}
        </div>
        {body}
      </div>

      <button
        type="button"
        onClick={toggle}
        title={open ? 'Close chat' : 'Ask the data'}
        aria-label={open ? 'Close chat' : 'Ask the data'}
        aria-expanded={open}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg transition hover:scale-105 hover:bg-indigo-700"
      >
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          {open ? <path d="M6 9l6 6 6-6" /> : <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />}
        </svg>
        {busy && !open && <span className="absolute right-1 top-1 h-3 w-3 animate-pulse rounded-full border-2 border-white bg-amber-400" />}
      </button>
    </div>
  )
}
