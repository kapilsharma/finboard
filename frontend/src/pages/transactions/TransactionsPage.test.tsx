import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TxnList } from '../../api/types'
import { TXNS } from '../../test/dashboard-fixture'
import { ACCOUNTS, CATEGORIES } from '../../test/fixtures'
import { ME, mockApi, renderRoute } from '../../test/utils'

function page(start: number, count: number, next: string | null): TxnList {
  const base = TXNS.items[0]!
  return {
    ...TXNS,
    total: 250,
    next_cursor: next,
    items: Array.from({ length: count }, (_, i) => ({
      ...base,
      id: `t${start + i}`,
      description: `ROW ${start + i}`,
    })),
  }
}

beforeEach(() => {
  // jsdom has no layout: give elements a size so the virtualiser renders rows.
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1000)
})

describe('Transactions page', () => {
  it('lists a date range with totals and renders only the visible rows', async () => {
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /dashboard/months': () => ({ body: { months: ['2026-09', '2026-08'] } }),
      'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'GET /transactions': () => {
        const last = calls[calls.length - 1]!
        const cursor = new URLSearchParams(last.path.split('?')[1]).get('cursor')
        return { body: cursor ? page(100, 100, null) : page(0, 100, 'c1') }
      },
    })
    renderRoute('/transactions?from=2026-08-01&to=2026-09-30')
    expect(await screen.findByText(/250 transactions/)).toHaveTextContent(
      '250 transactions · income ₹702',
    )
    expect(screen.getByText('ROW 0')).toBeInTheDocument()
    const first = calls.find((c) => c.path.startsWith('/transactions?'))!
    const query = new URLSearchParams(first.path.split('?')[1])
    expect(query.get('from')).toBe('2026-08-01')
    expect(query.get('to')).toBe('2026-09-30')
    expect(query.get('month')).toBeNull()
    // Only the visible rows are in the DOM.
    expect(screen.getAllByRole('row').length).toBeLessThan(60)
  })

  it('switching to a month clears the range', async () => {
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /dashboard/months': () => ({ body: { months: ['2026-09', '2026-08'] } }),
      'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'GET /transactions': () => ({ body: TXNS }),
    })
    renderRoute('/transactions?from=2026-08-01')
    await screen.findByRole('option', { name: 'September 2026' })
    await userEvent.selectOptions(screen.getByLabelText('Month'), '2026-09')
    await waitFor(() => {
      const last = [...calls].reverse().find((c) => c.path.startsWith('/transactions?'))!
      const query = new URLSearchParams(last.path.split('?')[1])
      expect(query.get('month')).toBe('2026-09')
      expect(query.get('from')).toBeNull()
    })
  })
})
