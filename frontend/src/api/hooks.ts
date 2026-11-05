/** Server state lives only in TanStack Query (ADR-0013). One hook per endpoint. */

import { useCallback } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE, api } from './client'
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
  type ReviewGroups,
  type Rule,
  type RuleApplyBody,
  type RuleCreate,
  type RulePackImportResult,
  type RuleTest,
  type RuleTestBody,
  type RuleUpdate,
  type SuggestRule,
  type Transfer,
  type TransferStatus,
  type Txn,
  type TxnUpdate,
  type JobAccepted,
  type Dashboard,
  type Meta,
  type TxnList,
  type Budget,
  type CategoryMergeResult,
  type Parser,
  type ParserSettingUpdate,
  type AiSettings,
  type AiStatus,
  type AskAnswer,
  type AskHistory,
  type Suggestions,
  type Widget,
  type WidgetList,
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
  rules: ['rules'] as const,
  review: ['review'] as const,
  reviewGroups: (month: string | null) => ['review', 'groups', month ?? 'all'] as const,
  transfers: ['transfers'] as const,
  transferList: (status: TransferStatus | null) => ['transfers', status ?? 'all'] as const,
  meta: ['meta'] as const,
  dashboard: ['dashboard'] as const,
  dashboardMonth: (month: string | null) => ['dashboard', 'month', month ?? 'latest'] as const,
  dashboardMonths: ['dashboard', 'months'] as const,
  transactions: ['transactions'] as const,
  transactionList: (params: string) => ['transactions', 'list', params] as const,
  budgets: ['budgets'] as const,
  aiStatus: ['ai', 'status'] as const,
  suggestions: (txnId: string) => ['ai', 'suggestions', txnId] as const,
  askHistory: ['ai', 'ask', 'history'] as const,
  widgets: ['ai', 'widgets'] as const,
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

// ------------------------------------------------------------------ rules (ARCHITECTURE §9)

/** Everything a categorisation change can affect. */
function invalidateCategorisation(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: queryKeys.dashboard })
  void qc.invalidateQueries({ queryKey: queryKeys.transactions })
  void qc.invalidateQueries({ queryKey: queryKeys.rules })
  void qc.invalidateQueries({ queryKey: queryKeys.review })
  void qc.invalidateQueries({ queryKey: queryKeys.transfers })
  void qc.invalidateQueries({ queryKey: ['ai'] }) // suggestions and pinned widgets
}

export function useRules() {
  return useQuery({
    queryKey: queryKeys.rules,
    queryFn: async () => (await api<{ items: Rule[] }>('/rules')).items,
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RuleCreate) => api<Rule>('/rules', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

export function useUpdateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: RuleUpdate }) =>
      api<Rule>(`/rules/${id}`, { method: 'PATCH', body: changes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/rules/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

/** Optimistic: the list shows the new order at once and rolls back if the server refuses. */
export function useReorderRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) =>
      api<{ items: Rule[] }>('/rules/reorder', { method: 'POST', body: { ids } }),
    onMutate: async (ids) => {
      await qc.cancelQueries({ queryKey: queryKeys.rules })
      const previous = qc.getQueryData<Rule[]>(queryKeys.rules)
      if (previous) {
        const byId = new Map(previous.map((r) => [r.id, r]))
        qc.setQueryData(
          queryKeys.rules,
          ids.map((id) => byId.get(id)).filter((r): r is Rule => r !== undefined),
        )
      }
      return { previous }
    },
    onError: (_error, _ids, context) => {
      if (context?.previous) qc.setQueryData(queryKeys.rules, context.previous)
    },
    onSuccess: (result) => qc.setQueryData(queryKeys.rules, result.items),
  })
}

/** Dry-run a rule against committed transactions (changes nothing). */
export function useTestRule(body: RuleTestBody | null) {
  return useQuery({
    queryKey: ['rules', 'test', body] as const,
    queryFn: () => api<RuleTest>('/rules/test', { method: 'POST', body }),
    enabled: body !== null && body.pattern.trim() !== '',
    staleTime: 10_000,
    retry: false,
  })
}

export function useApplyRules() {
  return useMutation({
    mutationFn: (body: RuleApplyBody) => api<JobAccepted>('/rules/apply', { method: 'POST', body }),
  })
}

export function useImportRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { content: string; mode: 'merge' | 'replace' }) =>
      api<RulePackImportResult>('/rules/import', { method: 'POST', body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rules })
      void qc.invalidateQueries({ queryKey: queryKeys.categories }) // may have created some
    },
  })
}

export function useAddStarterRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<RulePackImportResult>('/rules/starter-pack', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

/** Download the rule pack as a file (the browser saves it; nothing leaves the machine). */
export async function downloadRulePack(format: 'yaml' | 'json') {
  const response = await fetch(`${API_BASE}/rules/export?format=${format}`)
  if (!response.ok) throw new Error('Export failed')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `finboard-rules.${format}`
  link.click()
  URL.revokeObjectURL(url)
}

// ------------------------------------------------------------------ review and transactions

export function useReviewGroups(month: string | null) {
  return useQuery({
    queryKey: queryKeys.reviewGroups(month),
    queryFn: () => api<ReviewGroups>(`/review/groups${month ? `?month=${month}` : ''}`),
  })
}

export function useSuggestRule(transactionId: string | null) {
  return useQuery({
    queryKey: ['review', 'suggest', transactionId] as const,
    queryFn: () =>
      api<SuggestRule>('/review/suggest-rule', {
        method: 'POST',
        body: { transaction_id: transactionId },
      }),
    enabled: transactionId !== null,
  })
}

export function useUpdateTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: TxnUpdate }) =>
      api<Txn>(`/transactions/${id}`, { method: 'PATCH', body: changes }),
    onSuccess: () => invalidateCategorisation(qc),
  })
}

export function useBulkCategorise() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { ids: string[]; category_id: string }) =>
      api<{ updated: number }>('/transactions/bulk', { method: 'POST', body }),
    onSuccess: () => invalidateCategorisation(qc),
  })
}

// ------------------------------------------------------------------ transfers

export function useTransfers(status: TransferStatus | null) {
  return useQuery({
    queryKey: queryKeys.transferList(status),
    queryFn: async () =>
      (await api<{ items: Transfer[] }>(`/transfers${status ? `?status=${status}` : ''}`)).items,
  })
}

export function useSuggestTransfers() {
  return useMutation({
    mutationFn: () => api<JobAccepted>('/transfers/suggest', { method: 'POST' }),
  })
}

function useTransferAction(action: 'confirm' | 'reject') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<Transfer>(`/transfers/${id}/${action}`, { method: 'POST' }),
    onSuccess: () => invalidateCategorisation(qc),
  })
}

export const useConfirmTransfer = () => useTransferAction('confirm')
export const useRejectTransfer = () => useTransferAction('reject')

/** Invalidate whatever a finished background job may have changed. */
export function useRefreshAfterJob() {
  const qc = useQueryClient()
  return useCallback(() => invalidateCategorisation(qc), [qc])
}

// ------------------------------------------------------------------ dashboard (ARCHITECTURE §10)

export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta,
    queryFn: () => api<Meta>('/meta'),
    staleTime: Infinity,
  })
}

export function useDashboardMonths() {
  return useQuery({
    queryKey: queryKeys.dashboardMonths,
    queryFn: async () => (await api<{ months: string[] }>('/dashboard/months')).months,
  })
}

/** `null` data = no transactions yet. The browser revalidates with the ETag (304s are free). */
export function useDashboard(month: string | null) {
  return useQuery({
    queryKey: queryKeys.dashboardMonth(month),
    queryFn: () => api<Dashboard | null>(`/dashboard${month ? `?month=${month}` : ''}`),
    placeholderData: (previous) => previous, // keep the old month on screen while switching
  })
}

export interface TxnQuery {
  month?: string | null
  from?: string | null
  to?: string | null
  account?: string | null
  category?: string | null
  q?: string | null
  review?: boolean
  sort?: string | null
  order?: 'asc' | 'desc' | null
}

export function transactionParams(query: TxnQuery, pageSize: number): URLSearchParams {
  const params = new URLSearchParams()
  if (query.month) params.set('month', query.month)
  if (query.from) params.set('from', query.from)
  if (query.to) params.set('to', query.to)
  if (query.account) params.set('account_id', query.account)
  if (query.category) params.set('category_id', query.category)
  if (query.q?.trim()) params.set('q', query.q.trim())
  if (query.review) params.set('needs_review', 'true')
  if (query.sort) params.set('sort', query.sort)
  if (query.order) params.set('order', query.order)
  params.set('limit', String(pageSize))
  return params
}

/** Transactions, a page at a time (keyset cursor). */
export function useTransactionList(query: TxnQuery, { pageSize = 100, enabled = true } = {}) {
  const params = transactionParams(query, pageSize)
  return useInfiniteQuery({
    queryKey: queryKeys.transactionList(params.toString()),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const page = new URLSearchParams(params)
      if (pageParam) page.set('cursor', pageParam)
      return api<TxnList>(`/transactions?${page}`)
    },
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: (previous) => previous,
    enabled,
  })
}

// ------------------------------------------------------------------ settings (M5)

export function useBudgetHistory() {
  return useQuery({
    queryKey: queryKeys.budgets,
    queryFn: async () => (await api<{ items: Budget[] }>('/budgets/history')).items,
  })
}

function useBudgetMutation<V>(request: (vars: V) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.budgets })
      void qc.invalidateQueries({ queryKey: queryKeys.dashboard })
    },
  })
}

export function usePutBudget() {
  return useBudgetMutation(
    ({ categoryId, month, limit }: { categoryId: string; month: string; limit: string | null }) =>
      api<Budget>(`/budgets/${categoryId}`, {
        method: 'PUT',
        body: { effective_from: month, monthly_limit: limit },
      }),
  )
}

export function useDeleteBudgetChange() {
  return useBudgetMutation(({ categoryId, month }: { categoryId: string; month: string }) =>
    api<void>(`/budgets/${categoryId}/${month}`, { method: 'DELETE' }),
  )
}

export function useMergeCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, intoId }: { id: string; intoId: string }) =>
      api<CategoryMergeResult>(`/categories/${id}/merge`, {
        method: 'POST',
        body: { into_id: intoId },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.categories })
      void qc.invalidateQueries({ queryKey: queryKeys.budgets })
      invalidateCategorisation(qc)
    },
  })
}

export function useUpdateParser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: ParserSettingUpdate }) =>
      api<Parser>(`/parsers/${id}`, { method: 'PATCH', body: changes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.parsers }),
  })
}

export function useStartExport() {
  return useMutation({ mutationFn: () => api<JobAccepted>('/data/export', { method: 'POST' }) })
}

export function useStartDataImport() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file, file.name)
      return api<JobAccepted>('/data/import', { method: 'POST', form })
    },
  })
}

export function useDeleteAll() {
  return useMutation({
    mutationFn: (confirm: string) =>
      api<JobAccepted>('/data/delete-all', { method: 'POST', body: { confirm } }),
  })
}

/** After an import or delete-all, everything the user sees may have changed. */
export function useRefreshEverything() {
  const qc = useQueryClient()
  return useCallback(() => void qc.invalidateQueries(), [qc])
}

// ------------------------------------------------------------------ optional AI (M3a, M4a)

export function useAiStatus() {
  return useQuery({ queryKey: queryKeys.aiStatus, queryFn: () => api<AiStatus>('/ai/status') })
}

export function useUpdateAiSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AiSettings) => api<AiStatus>('/ai/settings', { method: 'PATCH', body }),
    onSuccess: (status) => {
      qc.setQueryData(queryKeys.aiStatus, status)
      void qc.invalidateQueries({ queryKey: ['ai'] })
    },
  })
}

/** Suggestions for one transaction; only asked for when the user turned them on. */
export function useSuggestions(txnId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.suggestions(txnId ?? ''),
    queryFn: () => api<Suggestions>(`/transactions/${txnId}/suggestions`),
    enabled: enabled && txnId !== null,
    staleTime: 60_000,
  })
}

export function useAsk() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (question: string) =>
      api<AskAnswer>('/ask', { method: 'POST', body: { question } }),
    onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.askHistory }),
  })
}

export function useAskHistory(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.askHistory,
    queryFn: () => api<AskHistory>('/ask/history'),
    enabled,
  })
}

export function useClearAskHistory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('/ask/history', { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.askHistory }),
  })
}

export function usePinQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title?: string }) =>
      api<Widget>(`/ask/${id}/pin`, { method: 'POST', body: { title: title ?? null } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai'] }),
  })
}

/** Pinned questions, re-run on the server with no AI call. Refreshed with the dashboard. */
export function useWidgets(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.widgets,
    queryFn: () => api<WidgetList>('/dashboard/widgets'),
    enabled,
  })
}

export function useDeleteWidget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/dashboard/widgets/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai'] }),
  })
}
