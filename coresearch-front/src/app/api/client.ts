export interface Project {
  id: number
  name: string
  uuid: string
  user_id: number
  created_at: string
  updated_at: string
  llm_provider: string
  llm_model: string
  project_root: string
}

export interface Seed {
  id: number
  uuid: string
  project_id: number
  name: string
  repository_url: string
  branch: string
  commit: string
  created_at: string
}

export interface Runner {
  id: number
  name: string
  url: string
  status: string
  capabilities: Record<string, unknown>
  registered_at: string
  last_heartbeat: string | null
}

export interface Session {
  id: number
  branch_id: number
  kind: string  // session multiplexer kind, e.g. "tmux" (was: runner — collided with branches.runner_id)
  attach_command: string
  agent: string
  status: string
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export interface Branch {
  id: number
  uuid: string
  seed_id: number
  runner_id: number | null
  name: string
  path: string
  sync_command: string
  description: string
  commit: string
  git_branch: string
  created_at: string
  parent_branch_id: number | null
  parent_iteration_id: number | null
  parent_iteration_hash: string | null  // denormalized via JOIN, kept for layout keying
  session: Session | null
}

export interface IterationMetric {
  id: number
  iteration_id: number
  key: string
  value: number
  recorded_at: string
}

export interface IterationVisual {
  id: number
  iteration_id: number
  filename: string
  format: string
  path: string
  created_at: string
}

export interface IterationComment {
  id: number
  iteration_id: number
  user_id: number
  user_name: string
  body: string
  created_at: string
}

export interface Iteration {
  id: number
  branch_id: number
  hash: string
  name: string
  description: string | null
  hypothesis: string | null
  analysis: string | null
  guidelines_version: string | null
  created_at: string
  metrics: IterationMetric[]
  visuals: IterationVisual[]
  comments: IterationComment[]
}

const BASE = '/api'

async function request<T>(method: string, path: string, body?: unknown, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: controller.signal,
  }).finally(() => clearTimeout(timer))
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  runners: {
    list: () => request<Runner[]>('GET', '/runners'),
    branches: (runner_id: number) => request<Branch[]>('GET', `/runners/${runner_id}/branches`),
    rename: (runner_id: number, name: string) => request<void>('PATCH', `/runners/${runner_id}`, { name }),
  },
  projects: {
    list: () => request<Project[]>('GET', '/projects'),
    create: (name: string, llm_provider?: string, llm_model?: string) =>
      request<Project>('POST', '/projects', { name, llm_provider, llm_model }),
  },
  seeds: {
    list: (project_id: number) => request<Seed[]>('GET', `/projects/${project_id}/seeds`),
    create: (project_id: number, name: string, repository_url: string, branch?: string, commit?: string, access_token?: string) =>
      request<Seed>('POST', `/projects/${project_id}/seeds`, { name, repository_url, branch, commit, access_token }),
    fromIteration: (project_id: number, name: string, branch_id: number, iteration_hash: string) =>
      request<Seed>('POST', `/projects/${project_id}/seeds/from-iteration`, { name, branch_id, iteration_hash }),
    delete: (seed_id: number) => request<void>('DELETE', `/seeds/${seed_id}`),
  },
  branches: {
    list: (seed_id: number) => request<Branch[]>('GET', `/seeds/${seed_id}/branches`),
    create: (seed_id: number, name: string, kind?: string, agent?: string, description?: string, runner_id?: number) =>
      request<Branch>('POST', `/seeds/${seed_id}/branches`, { name, description, kind, agent, runner_id }),
    renew: (branch_id: number) => request<Branch>('POST', `/branches/${branch_id}/renew`),
    kill: (branch_id: number) => request<void>('POST', `/branches/${branch_id}/kill`),
    push: (branch_id: number, commit?: string) =>
      request<{ message: string }>('POST', `/branches/${branch_id}/push${commit ? `?commit=${encodeURIComponent(commit)}` : ''}`),
    update: (branch_id: number, description: string) =>
      request<void>('PATCH', `/branches/${branch_id}`, { description }),
    fork: (branch_id: number, name: string, iteration_hash: string, agent?: string) =>
      request<Branch>('POST', `/branches/${branch_id}/fork`, { name, iteration_hash, agent }),
    sessionAlive: (branch_id: number) => request<{ alive: boolean }>('GET', `/branches/${branch_id}/session-alive`),
    delete: (branch_id: number) => request<void>('DELETE', `/branches/${branch_id}`),
  },
  iterations: {
    list: (branch_id: number) => request<Iteration[]>('GET', `/branches/${branch_id}/iterations`),
    visualUrl: (iteration_id: number, filename: string) =>
      `${BASE}/iterations/${iteration_id}/visuals/${encodeURIComponent(filename)}`,
    updateDescription: (iteration_id: number, description: string | null) =>
      request<void>('PATCH', `/iterations/${iteration_id}`, { description }),
    addComment: (iteration_id: number, body: string) =>
      request<{ id: number }>('POST', `/iterations/${iteration_id}/comments`, { body }),
    deleteComment: (iteration_id: number, comment_id: number) =>
      request<void>('DELETE', `/iterations/${iteration_id}/comments/${comment_id}`),
  },
  diff: {
    get: async (branch_id: number, from_hash: string, to_hash: string): Promise<string> => {
      const res = await fetch(`${BASE}/branches/${branch_id}/diff?from_hash=${encodeURIComponent(from_hash)}&to_hash=${encodeURIComponent(to_hash)}`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail ?? res.statusText)
      }
      return res.text()
    },
  },
  workdir: {
    list: (branch_id: number) =>
      request<string[]>('GET', `/branches/${branch_id}/workdir`),
    readFile: async (branch_id: number, path: string): Promise<string> => {
      const res = await fetch(`${BASE}/branches/${branch_id}/workdir/file?path=${encodeURIComponent(path)}`)
      if (!res.ok) throw new Error((await res.json().catch(() => ({ detail: res.statusText }))).detail)
      return res.text()
    },
    writeFile: (branch_id: number, path: string, content: string) =>
      request<void>('PUT', `/branches/${branch_id}/workdir/file`, { path, content }),
    commit: (branch_id: number) =>
      request<void>('POST', `/branches/${branch_id}/workdir/commit`),
  },
  tree: {
    list: (branch_id: number, hash: string) =>
      request<string[]>('GET', `/branches/${branch_id}/tree?hash=${encodeURIComponent(hash)}`),
    file: async (branch_id: number, hash: string, path: string): Promise<string> => {
      const res = await fetch(`${BASE}/branches/${branch_id}/file?hash=${encodeURIComponent(hash)}&path=${encodeURIComponent(path)}`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail ?? res.statusText)
      }
      return res.text()
    },
  },
}
