import { useState } from 'react'
import type { ChatSummary } from '../api'

const GROUPS = ['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older'] as const

function groupOf(iso: string, now: Date): (typeof GROUPS)[number] {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((day(now) - day(new Date(iso))) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days <= 7) return 'Previous 7 days'
  if (days <= 30) return 'Previous 30 days'
  return 'Older'
}

function ChatItem({
  chat,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  chat: ChatSummary
  active: boolean
  onOpen: () => void
  onRename: (title: string) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(chat.title)

  if (editing) {
    const commit = () => {
      setEditing(false)
      if (title.trim() && title.trim() !== chat.title) onRename(title.trim())
      else setTitle(chat.title)
    }
    return (
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setTitle(chat.title)
            setEditing(false)
          }
        }}
        className="w-full rounded-md border border-indigo-300 bg-white px-2 py-1.5 text-sm outline-none ring-2 ring-indigo-100"
      />
    )
  }

  return (
    <div
      className={`group flex items-center rounded-md text-sm ${active ? 'bg-indigo-50 text-indigo-800' : 'text-slate-700 hover:bg-slate-100'}`}
    >
      <button type="button" onClick={onOpen} title={chat.title} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left">
        {chat.title}
      </button>
      <div className={`flex shrink-0 gap-0.5 pr-1 ${active ? '' : 'invisible group-hover:visible'}`}>
        <button
          type="button"
          title="Rename"
          onClick={() => {
            setTitle(chat.title)
            setEditing(true)
          }}
          className="rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
            <path d="M13.6 3.4a2 2 0 0 1 2.8 2.8l-8.5 8.5-3.6.8.8-3.6 8.5-8.5Z" />
          </svg>
        </button>
        <button
          type="button"
          title="Delete"
          onClick={() => window.confirm(`Delete "${chat.title}"?`) && onDelete()}
          className="rounded p-1 text-slate-400 hover:bg-white hover:text-red-600"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
            <path d="M8 2h4a1 1 0 0 1 1 1v1h4v2H3V4h4V3a1 1 0 0 1 1-1Zm-3 6h10l-.8 9a1 1 0 0 1-1 1H6.8a1 1 0 0 1-1-1L5 8Z" />
          </svg>
        </button>
      </div>
    </div>
  )
}

export function ChatSidebar({
  chats,
  activeId,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: {
  chats: ChatSummary[]
  activeId: string | undefined
  onNew: () => void
  onOpen: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const [search, setSearch] = useState('')
  const [now] = useState(() => new Date())
  const visible = chats.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50/60">
      <div className="space-y-2 p-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <span className="text-base leading-none">+</span> New chat
        </button>
        {chats.length > 5 && (
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats"
            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-indigo-300"
          />
        )}
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 pb-4">
        {chats.length === 0 && <p className="px-2 text-xs text-slate-400">Your conversations will be saved here.</p>}
        {GROUPS.map((g) => {
          const items = visible.filter((c) => groupOf(c.updated_at, now) === g)
          if (!items.length) return null
          return (
            <div key={g}>
              <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">{g}</div>
              <div className="space-y-0.5">
                {items.map((c) => (
                  <ChatItem
                    key={c.id}
                    chat={c}
                    active={c.id === activeId}
                    onOpen={() => onOpen(c.id)}
                    onRename={(t) => onRename(c.id, t)}
                    onDelete={() => onDelete(c.id)}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
