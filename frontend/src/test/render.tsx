import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'
import { AuthProvider } from '../auth'

/** Render a page at `path`, matched against `route`, with fresh query and auth state. */
export function renderAt(ui: ReactElement, { path = '/', route = '/' } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path={route} element={ui} />
            <Route path="*" element={<p>Navigated away</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

type Handler = (init?: RequestInit) => { status?: number; body?: unknown }

/** Stub fetch with handlers keyed by "METHOD /api/path". Returns the mock for assertions. */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const key = `${init?.method ?? 'GET'} ${url.pathname}`
    const handler = routes[key]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    const { status = 200, body } = handler(init)
    return new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
