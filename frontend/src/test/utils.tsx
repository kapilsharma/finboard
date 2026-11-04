import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { routes } from '../routes'

type Handler = (init: { method: string; body: unknown }) => { status?: number; body?: unknown }

/** Minimal fetch fake: `{'GET /accounts': () => ({ body: {...} })}`. Records every call. */
export function mockApi(handlers: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown; headers: Record<string, string> }[] =
    []
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = url.replace('/api/v1', '')
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    calls.push({ method, path, body, headers: (init.headers ?? {}) as Record<string, string> })
    // Exact match first (path with query string), then the path alone.
    const handler = handlers[`${method} ${path}`] ?? handlers[`${method} ${path.split('?')[0]}`]
    if (!handler) {
      return new Response(JSON.stringify({ status: 404, code: 'not_found', title: 'Not found' }), {
        status: 404,
      })
    }
    const result = handler({ method, body })
    const status = result.status ?? 200
    return new Response(
      status === 204 ? null : JSON.stringify('body' in result ? result.body : {}),
      { status },
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

export const ME = { id: 'u1', username: 'local', display_name: 'Me', mode: 'local' }

function newQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

export function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(
    <QueryClientProvider client={newQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

export function renderWithQuery(ui: ReactElement) {
  return render(<QueryClientProvider client={newQueryClient()}>{ui}</QueryClientProvider>)
}
