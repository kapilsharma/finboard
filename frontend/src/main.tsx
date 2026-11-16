import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter } from 'react-router'
import { ApiError } from './api/client'
import { routes } from './routes'
import './theme/global.css'

/** Server mode: a 401 on any request means the session ended (signed out elsewhere, or it
 *  expired). Asking /me again makes AuthGate show the sign-in page. */
function sessionEnded(error: unknown, isMeQuery = false) {
  if (!isMeQuery && error instanceof ApiError && error.status === 401) {
    void queryClient.resetQueries({ queryKey: ['me'] })
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => sessionEnded(error, query.queryKey[0] === 'me'),
  }),
  mutationCache: new MutationCache({
    // A wrong password at sign-in is a 401 too, but there is no session to end then.
    onError: (error, _vars, _ctx, mutation) =>
      sessionEnded(error, mutation.options.mutationKey?.[0] === 'auth'),
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Don't retry client errors (404, 422…): they won't fix themselves.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter(routes)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
