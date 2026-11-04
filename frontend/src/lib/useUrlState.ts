import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/** Transaction filters and the selected month live in the URL (ADR-0013), so they survive
 *  reloads and month changes, and links can be shared. */
export const FILTER_KEYS = ['q', 'account', 'category', 'review'] as const

export interface UrlState {
  month: string | null
  from: string | null
  to: string | null
  q: string
  account: string | null
  category: string | null
  review: boolean
  sort: string | null
  order: 'asc' | 'desc' | null
}

export function useUrlState(): [
  UrlState,
  (changes: Partial<Record<keyof UrlState, string | boolean | null>>) => void,
] {
  const [params, setParams] = useSearchParams()
  const order = params.get('order')
  const state: UrlState = {
    month: params.get('month'),
    from: params.get('from'),
    to: params.get('to'),
    q: params.get('q') ?? '',
    account: params.get('account'),
    category: params.get('category'),
    review: params.get('review') === '1',
    sort: params.get('sort'),
    order: order === 'asc' || order === 'desc' ? order : null,
  }
  const update = useCallback(
    (changes: Partial<Record<keyof UrlState, string | boolean | null>>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === false || value === '') next.delete(key)
            else next.set(key, value === true ? '1' : String(value))
          }
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )
  return [state, update]
}
