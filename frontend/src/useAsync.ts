import { useEffect, useState } from 'react'

export type AsyncState<T> = { data: T | null; error: string | null; loading: boolean }

/** Runs `load` whenever `deps` change; keeps the previous data visible while reloading. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true })
  const depKey = JSON.stringify(deps)
  useEffect(() => {
    let cancelled = false
    load()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((e: unknown) => !cancelled && setState({ data: null, error: String(e), loading: false }))
    return () => {
      cancelled = true
      setState((s) => ({ ...s, loading: true }))
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [depKey])
  return state
}
