import { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { api, type Health } from './api'
import { ChatWidget } from './components/ChatWidget'
import { Chat } from './pages/Chat'
import { Dashboard } from './pages/Dashboard'
import { DataSources } from './pages/DataSources'
import { Models } from './pages/Models'

const HEALTH_POLL_MS = 15000

/** Polls health; `dataEpoch` increments whenever a sync swaps in new data, so data views can remount. */
function useHealth(): { health: Health | null; dataEpoch: number } {
  const [health, setHealth] = useState<Health | null>(null)
  const [dataEpoch, setDataEpoch] = useState(0)
  const seenVersion = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    let cancelled = false
    const load = () =>
      api
        .health()
        .then((h) => {
          if (cancelled) return
          if (seenVersion.current !== undefined && seenVersion.current !== h.data_version) setDataEpoch((n) => n + 1)
          seenVersion.current = h.data_version
          setHealth(h)
        })
        .catch(() => !cancelled && setHealth(null))
    void load()
    const timer = window.setInterval(() => void load(), HEALTH_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])
  return { health, dataEpoch }
}

function StatusDot({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500">
      <span className={`h-2 w-2 rounded-full ${ok === undefined ? 'bg-slate-300' : ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
      {label}
    </span>
  )
}

function Nav({ health }: { health: Health | null }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:text-slate-900'}`
  return (
    <header className="sticky top-0 z-30 h-14 border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-6">
        <div className="flex items-center gap-6">
          <span className="font-semibold tracking-tight text-slate-900">
            Prompt<span className="text-indigo-600">Analytics</span>
          </span>
          <nav className="flex gap-1">
            <NavLink to="/" end className={link}>
              Dashboard
            </NavLink>
            <NavLink to="/data" className={link}>
              Data sources
            </NavLink>
            <NavLink to="/models" className={link}>
              Models
            </NavLink>
          </nav>
        </div>
        <div className="flex gap-4">
          <StatusDot ok={health?.database} label="Data" />
          <StatusDot ok={health?.ollama} label="Ollama" />
        </div>
      </div>
    </header>
  )
}

function NoData({ what }: { what: string }) {
  return (
    <div className="mx-auto max-w-xl px-6 pt-24 text-center">
      <h1 className="text-lg font-semibold text-slate-900">No data loaded</h1>
      <p className="mt-2 text-sm text-slate-500">
        All data sources were removed, so there is nothing to {what}. Upload a trace export or add a watched folder to get started.
      </p>
      <Link to="/data" className="mt-4 inline-block rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
        Go to Data sources
      </Link>
    </div>
  )
}

export default function App() {
  const { health, dataEpoch } = useHealth()
  const noData = health?.database === false
  return (
    <BrowserRouter>
      <Nav health={health} />
      <Routes>
        <Route path="/" element={noData ? <NoData what="show on the dashboard" /> : <Dashboard key={dataEpoch} />} />
        <Route path="/chat" element={noData ? <NoData what="ask about" /> : <Chat />} />
        <Route path="/chat/:chatId" element={noData ? <NoData what="ask about" /> : <Chat />} />
        <Route path="/data" element={<DataSources />} />
        <Route path="/models" element={<Models />} />
      </Routes>
      <ChatWidget disabled={noData} />
    </BrowserRouter>
  )
}
