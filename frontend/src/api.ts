export type Granularity = 'hour' | 'day' | 'week'

export type Filters = {
  start?: string
  end?: string
  app: string[]
  user_role: string[]
  prompt_language: string[]
  topic: string[]
}

export const emptyFilters: Filters = { app: [], user_role: [], prompt_language: [], topic: [] }

export type FilterOptions = {
  range: { start: string; end: string; rows: number }
  app: string[]
  user_role: string[]
  prompt_language: string[]
  topic: string[]
}

export type Summary = {
  prompts: number
  sessions: number
  users: number
  organizations: number
  avg_latency_s: number | null
  p95_latency_s: number | null
  total_tokens: number | null
  avg_tokens_per_prompt: number | null
  avg_prompt_words: number | null
  on_topic_rate: number | null
  language_match_rate: number | null
  prompts_per_session: number | null
}

export type VolumePoint = { bucket: string; prompts: number; sessions: number; total_tokens: number }
export type BreakdownRow = { key: string | number | null; prompts: number; avg_latency_s: number; avg_tokens: number; on_topic_rate: number }
export type HistogramBin = { from: number; to: number; count: number }
export type TokenPoint = { bucket: string; input_tokens: number; output_tokens: number; avg_latency_s: number }
export type TopPrompt = {
  prompt: string
  prompt_english: string
  language: string
  topic: string
  intent: string
  count: number
  on_topic_rate: number
}
export type AlignmentCell = { topic: string; response_topic: string | null; count: number }
export type SessionRow = {
  session_id: string
  user_id: string
  app: string
  user_role: string
  started_at: string
  turns: number
  duration_s: number
  total_tokens: number
  avg_latency_s: number
  languages: string
  topics: string
}

export type ChartSpec = {
  type: 'kpi' | 'bar' | 'line' | 'pie' | 'table'
  x: string | null
  y: string[]
  title: string
  dashboard_section: string | null
  source: 'llm' | 'rule'
}

export type DataTable = { columns: string[]; rows: unknown[][]; total_rows: number }

export type AgentStep = {
  agent: string
  model: string | null
  latency_s: number
  prompt_tokens: number
  completion_tokens: number
  llm_calls: number
  output: unknown
  error: string | null
}

export type ChatMode = 'mas' | 'baseline'

export type ChatResponse = {
  id: string
  conversation_id: string
  mode: ChatMode
  profile: string
  question: string
  answer: string
  status: 'ok' | 'out_of_scope' | 'error'
  data: DataTable | null
  chart: ChartSpec | null
  sql: string | null
  query_spec: Record<string, unknown> | null
  steps: AgentStep[]
  total_latency_s: number
  prompt_tokens: number
  completion_tokens: number
  llm_calls: number
  error: string | null
}

export type UiMode = ChatMode | 'compare'

export type ChatSummary = { id: string; title: string; created_at: string; updated_at: string; messages: number }

export type SavedMessage = { id: string; question: string; mode: UiMode; created_at: string; responses: ChatResponse[] }

export type SavedChat = Omit<ChatSummary, 'messages'> & { messages: SavedMessage[] }

export type Health = { database: boolean; data_version: string | null; ollama: boolean; profiles: string[]; default_profile: string }

export type ModelRole = 'query_understanding' | 'visualization_planning' | 'answer_generation' | 'baseline'

export type InstalledModel = {
  name: string
  size: number
  parameter_size: string | null
  quantization: string | null
  family: string | null
  embedding: boolean
}

export type ModelProfile = { name: string; builtin: boolean; description: string; models: Record<ModelRole, string | null> }

export type ModelsOverview = {
  roles: ModelRole[]
  installed: InstalledModel[]
  loaded: { name: string; size: number; size_vram: number }[]
  profiles: ModelProfile[]
  default_profile: string
  data_processing_model: string
  embedding_model: string
  ollama: { running: boolean; installed: boolean; version: string | null; url: string }
  pulls: ModelPull[]
  suggested: { name: string; size_gb: number; note: string }[]
}

export type ModelPull = {
  name: string
  state: 'running' | 'done' | 'error' | 'cancelled'
  status: string
  completed: number
  total: number
  error: string | null
  started_at: number
  finished_at: number | null
}

export type SyncRun = {
  id: string
  trigger: string
  status: 'running' | 'ok' | 'error'
  started_at: string
  finished_at: string | null
  files: number | null
  rows_before: number | null
  rows_after: number | null
  new_traces: number | null
  message: string | null
}

export type DataStatus = {
  data: { start: string; end: string; rows: number } | null
  version: string | null
  running: boolean
  last_sync: SyncRun | null
}

export type SourceFile = { id: string; name: string; size: number; rows: number; added_at: string; missing: boolean }

export type DataSource = {
  id: string
  name: string
  kind: 'upload' | 'folder'
  path: string | null
  sync_interval_min: number | null
  enabled: boolean
  created_at: string
  last_checked_at: string | null
  files: SourceFile[]
}

export type UploadResult = { file: { id: string; name: string; rows: number; new_traces: number; start: string; end: string }; sync_id: string | null }

function query(f: Filters, extra: Record<string, string | number> = {}): string {
  const p = new URLSearchParams()
  if (f.start) p.set('start', f.start)
  if (f.end) p.set('end', f.end)
  for (const key of ['app', 'user_role', 'prompt_language', 'topic'] as const) {
    for (const v of f[key]) p.append(key, v)
  }
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const api = {
  health: () => get<Health>('/api/health'),
  filters: () => get<FilterOptions>('/api/dashboard/filters'),
  summary: (f: Filters) => get<Summary>(`/api/dashboard/summary${query(f)}`),
  volume: (f: Filters, granularity: Granularity) => get<VolumePoint[]>(`/api/dashboard/volume${query(f, { granularity })}`),
  breakdown: (f: Filters, dimension: string) => get<BreakdownRow[]>(`/api/dashboard/breakdown/${dimension}${query(f)}`),
  histogram: (f: Filters, column: string, bins = 12) => get<HistogramBin[]>(`/api/dashboard/histogram/${column}${query(f, { bins })}`),
  tokens: (f: Filters, granularity: Granularity) => get<TokenPoint[]>(`/api/dashboard/tokens${query(f, { granularity })}`),
  topPrompts: (f: Filters, limit = 20) => get<TopPrompt[]>(`/api/dashboard/top-prompts${query(f, { limit })}`),
  topicAlignment: (f: Filters) => get<AlignmentCell[]>(`/api/dashboard/topic-alignment${query(f)}`),
  sessions: (f: Filters, limit = 25, offset = 0) =>
    get<{ total: number; rows: SessionRow[] }>(`/api/dashboard/sessions${query(f, { limit, offset })}`),
  ask: (body: { question: string; mode: ChatMode; profile?: string; chat_id: string; message_id: string; ui_mode: UiMode }) =>
    send<ChatResponse>('POST', '/api/chat', body),
  chats: () => get<ChatSummary[]>('/api/chats'),
  chat: (id: string) => get<SavedChat>(`/api/chats/${id}`),
  renameChat: (id: string, title: string) => send<{ ok: boolean }>('PATCH', `/api/chats/${id}`, { title }),
  deleteChat: (id: string) => send<{ ok: boolean }>('DELETE', `/api/chats/${id}`),
  dataStatus: () => get<DataStatus>('/api/data/status'),
  sources: () => get<DataSource[]>('/api/data/sources'),
  syncs: (limit = 15) => get<SyncRun[]>(`/api/data/syncs?limit=${limit}`),
  sync: () => send<{ sync_id: string | null; queued: boolean }>('POST', '/api/data/sync'),
  upload: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return check<UploadResult>(await fetch('/api/data/upload', { method: 'POST', body: form }))
  },
  addFolder: (body: { name: string; path: string; sync_interval_min: number | null }) =>
    send<{ source: DataSource; imported: unknown[]; problems: string[]; sync_id: string | null }>('POST', '/api/data/sources', body),
  updateSource: (id: string, body: { name?: string; sync_interval_min?: number | null; enabled?: boolean }) =>
    send<DataSource>('PATCH', `/api/data/sources/${id}`, body),
  deleteSource: (id: string) => send<{ ok: boolean }>('DELETE', `/api/data/sources/${id}`),
  deleteFile: (id: string) => send<{ ok: boolean }>('DELETE', `/api/data/files/${id}`),
  models: () => get<ModelsOverview>('/api/models'),
  saveProfile: (name: string, models: Record<ModelRole, string>, description = '') =>
    send<ModelsOverview>('PUT', `/api/models/profiles/${encodeURIComponent(name)}`, { models, description }),
  deleteProfile: (name: string) => send<ModelsOverview>('DELETE', `/api/models/profiles/${encodeURIComponent(name)}`),
  setDefaultProfile: (profile: string) => send<ModelsOverview>('PUT', '/api/models/default', { profile }),
  pullModel: (name: string) => send<ModelPull>('POST', '/api/models/pull', { name }),
  cancelPull: (name: string) => send<{ ok: boolean }>('DELETE', `/api/models/pulls/${name}`),
  deleteModel: (name: string) => send<ModelsOverview>('DELETE', `/api/models/installed/${name}`),
}

async function check<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text
    } catch {
      // not JSON
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return check<T>(
    await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}
