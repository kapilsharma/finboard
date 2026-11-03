/** Server state lives only in TanStack Query (ADR-0013). One hook per endpoint. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  Account,
  AccountCreate,
  AccountUpdate,
  Category,
  CategoryCreate,
  CategoryUpdate,
  Job,
  Me,
  Preferences,
} from './types'

export const queryKeys = {
  me: ['me'] as const,
  accounts: ['accounts'] as const,
  categories: ['categories'] as const,
  preferences: ['preferences'] as const,
  job: (id: string) => ['jobs', id] as const,
}

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
