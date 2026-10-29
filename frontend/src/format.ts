const LANGUAGES: Record<string, string> = { en: 'English', fi: 'Finnish', sv: 'Swedish' }

export const language = (code: string) => LANGUAGES[code] ?? code

export function number(v: unknown, digits = 0): string {
  if (v === null || v === undefined || v === '') return '–'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export function compact(v: unknown): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '–'
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

export const percent = (v: unknown, digits = 1) =>
  v === null || v === undefined ? '–' : `${(Number(v) * 100).toFixed(digits)}%`

export function dateTime(v: unknown, withTime = true): string {
  if (!v) return '–'
  const d = new Date(String(v))
  if (Number.isNaN(d.getTime())) return String(v)
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  })
}

export const label = (col: string) => col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const RATE_COLUMNS = /(_rate|share_of_prompts)$/

export function cell(col: string, v: unknown): string {
  if (v === null || v === undefined) return '–'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') return RATE_COLUMNS.test(col) ? percent(v) : number(v, 3)
  if (/^\d{4}-\d{2}-\d{2}T/.test(String(v))) return dateTime(v)
  return String(v)
}

export const PALETTE = ['#4f46e5', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#64748b']
