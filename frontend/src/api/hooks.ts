/** Server state lives only in TanStack Query (ADR-0013). One hook per endpoint. */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import {
  IMPORT_IN_FLIGHT,
  type Account,
  type AccountCreate,
  type AccountUpdate,
  type Category,
  type CategoryCreate,
  type CategoryUpdate,
  type CommitBody,
  type ImportList,
  type ImportResource,
  type ImportStatus,
  type Job,
  type Me,
  type ParserList,
  type Preferences,
  type ReparseBody,
} from './types'

export const queryKeys = {
  me: ['me'] as const,
  accounts: ['accounts'] as const,
  categories: ['categories'] as const,
  preferences: ['preferences'] as const,
  job: (id: string) => ['jobs', id] as const,
  imports: ['imports'] as const,
  importList: (statuses: readonly ImportStatus[]) => ['imports', 'list', ...statuses] as const,
  import: (id: string) => ['imports', 'one', id] as const,
  parsers: ['parsers'] as const,
}

/** How often in-flight work is polled. Tests shorten it. */
export const polling = { ms: 1000 }

export function useMe() {
  return useQuery({ queryKey: queryKeys.me, queryFn: () => api<Me>('/me') })
}

// ------------------------------------------------------------------ accounts

export function useAccounts() {
  return useQuery({
    queryKey: queryKeys.accounts,
    queryFn: async () => (await api<{ items: Account[] }>('/accounts')).items,
  })
}

export function useCreateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AccountCreate) => api<Account>('/accounts', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.accounts }),
  })
}

export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: AccountUpdate }) =>
      api<Account>(`/accounts/${id}`, { method: 'PATCH', body: changes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.accounts }),
  })
}

export function useDeleteAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/accounts/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.accounts }),
  })
}

// ------------------------------------------------------------------ categories

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: async () => (await api<{ items: Category[] }>('/categories')).items,
  })
}

export function useCreateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryCreate) => api<Category>('/categories', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.categories }),
  })
}

export function useUpdateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: CategoryUpdate }) =>
      api<Category>(`/categories/${id}`, { method: 'PATCH', body: changes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.categories }),
  })
}

export function useDeleteCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/categories/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.categories }),
  })
}

// ------------------------------------------------------------------ preferences

export function usePreferences() {
  return useQuery({ queryKey: queryKeys.preferences, queryFn: () => api<Preferences>('/settings') })
}

export function useUpdatePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (changes: Partial<Preferences>) =>
      api<Preferences>('/settings', { method: 'PATCH', body: changes }),
    onSuccess: (prefs) => qc.setQueryData(queryKeys.preferences, prefs),
  })
}

// ------------------------------------------------------------------ jobs

const FINISHED = new Set(['succeeded', 'failed', 'cancelled'])

/** Poll a background job every second until it finishes. */
export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.job(id ?? ''),
    queryFn: () => api<Job>(`/jobs/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && FINISHED.has(query.state.data.status) ? false : 1000,
  })
}

export function usePingWorker() {
  return useMutation({ mutationFn: () => api<Job>('/jobs/ping', { method: 'POST' }) })
}

// ------------------------------------------------------------------ imports (ARCHITECTURE §7)

/** One import; polls while the worker is still reading it. */
export function useImport(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.import(id ?? ''),
    queryFn: () => api<ImportResource>(`/imports/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && IMPORT_IN_FLIGHT.has(query.state.data.status) ? polling.ms : false,
  })
}

/** Imports in the given statuses (no rows). */
export function useImports(statuses: readonly ImportStatus[]) {
  const params = new URLSearchParams(statuses.map((s) => ['status', s]))
  return useQuery({
    queryKey: queryKeys.importList(statuses),
    queryFn: async () => (await api<ImportList>(`/imports?${params}`)).items,
  })
}

/** Import history, newest first, a page at a time. */
export function useImportHistory() {
  return useInfiniteQuery({
    queryKey: [...queryKeys.imports, 'history'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<ImportList>(`/imports?limit=25${pageParam ? `&cursor=${pageParam}` : ''}`),
    getNextPageParam: (last) => last.next_cursor,
  })
}

function useImportMutation<V>(request: (vars: V) => Promise<ImportResource>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (resource) => {
      qc.setQueryData(queryKeys.import(resource.id), resource)
      void qc.invalidateQueries({ queryKey: queryKeys.imports })
    },
  })
}

/** One request per file. A random Idempotency-Key makes a retried upload safe. */
export function useUploadImport() {
  return useImportMutation((file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return api<ImportResource>('/imports', {
      method: 'POST',
      form,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  })
}

export function useUnlockImport() {
  return useImportMutation(({ id, password }: { id: string; password: string }) =>
    api<ImportResource>(`/imports/${id}/unlock`, { method: 'POST', body: { password } }),
  )
}

export function useReparseImport() {
  return useImportMutation(({ id, body }: { id: string; body: ReparseBody }) =>
    api<ImportResource>(`/imports/${id}/reparse`, { method: 'POST', body }),
  )
}

export function useUpdateStagedRow() {
  return useImportMutation(({ id, seq, include }: { id: string; seq: number; include: boolean }) =>
    api<ImportResource>(`/imports/${id}/rows/${seq}`, { method: 'PATCH', body: { include } }),
  )
}

export function useCommitImport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CommitBody }) =>
      api<ImportResource>(`/imports/${id}/commit`, {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      }),
    onSuccess: (resource) => {
      qc.setQueryData(queryKeys.import(resource.id), resource)
      void qc.invalidateQueries({ queryKey: queryKeys.imports })
      void qc.invalidateQueries({ queryKey: queryKeys.accounts }) // may have created one
    },
  })
}

export function useDiscardImport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/imports/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.imports }),
  })
}

export function useRollbackImport() {
  return useImportMutation((id: string) =>
    api<ImportResource>(`/imports/${id}/rollback`, { method: 'POST' }),
  )
}

export function useParsers() {
  return useQuery({ queryKey: queryKeys.parsers, queryFn: () => api<ParserList>('/parsers') })
}
