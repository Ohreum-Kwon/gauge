import type {
  Item,
  Progress,
  Project,
  ProjectCreate,
  ProjectSummary,
  Task,
  UploadResult,
  User,
} from './types'

// Empty in development (Vite proxies /api); the API's origin in production.
const BASE_URL = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'gauge.token'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json')

  const response = await fetch(`${BASE_URL}/api${path}`, { ...init, headers })
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    // FastAPI validation errors: a list of {loc, msg}.
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join('; ')
  } catch {
    // Not JSON; fall through.
  }
  return `Request failed (${response.status})`
}

const json = (body: unknown) => JSON.stringify(body)

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: new URLSearchParams({ username: email, password }),
    }),
  me: () => request<User>('/auth/me'),

  users: (role?: User['role']) => request<User[]>(`/users${role ? `?role=${role}` : ''}`),

  projects: () => request<Project[]>('/projects'),
  project: (id: number) => request<ProjectSummary>(`/projects/${id}`),
  createProject: (body: ProjectCreate) =>
    request<Project>('/projects', { method: 'POST', body: json(body) }),
  members: (id: number) => request<User[]>(`/projects/${id}/members`),
  setMembers: (id: number, userIds: number[]) =>
    request<User[]>(`/projects/${id}/members`, {
      method: 'PUT',
      body: json({ user_ids: userIds }),
    }),
  items: (id: number) => request<Item[]>(`/projects/${id}/items?limit=60`),
  uploadItems: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResult>(`/projects/${id}/items`, { method: 'POST', body: form })
  },

  /** Resolves to null when the queue is empty. */
  nextTask: async (projectId: number) =>
    (await request<Task | undefined>(`/projects/${projectId}/queue/next`)) ?? null,
  progress: (projectId: number) => request<Progress>(`/projects/${projectId}/queue/progress`),
  submitLabel: (assignmentId: number, value: string, timeSpentMs: number) =>
    request(`/assignments/${assignmentId}/label`, {
      method: 'POST',
      body: json({ value, time_spent_ms: timeSpentMs }),
    }),
}
