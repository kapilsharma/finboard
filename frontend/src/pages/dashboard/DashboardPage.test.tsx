import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ACCOUNTS, CATEGORIES } from '../../test/fixtures'
import { SEPTEMBER, TXNS } from '../../test/dashboard-fixture'
import { ME, mockApi, renderRoute } from '../../test/utils'

function api() {
  return mockApi({
    'GET /me': () => ({ body: ME }),
    'GET /meta': () => ({
      body: {
        version: '0',
        api_version: 'v1',
        mode: 'local',
        metric_definitions: {
          income: {
            label: 'Income',
            formula: 'Σ income credits − Σ income debits',
            tooltip: 'Money in.',
          },
        },
      },
    }),
    'GET /dashboard': () => ({ body: SEPTEMBER }),
    'GET /dashboard/months': () => ({ body: { months: ['2026-09', '2026-08', '2026-07'] } }),
    'GET /transactions': () => ({ body: TXNS }),
    'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
    'GET /categories': () => ({ body: { items: CATEGORIES } }),
  })
}

function lastTransactionsQuery(calls: ReturnType<typeof api>) {
  const call = [...calls].reverse().find((c) => c.path.startsWith('/transactions?'))
  return new URLSearchParams(call?.path.split('?')[1])
}

describe('Dashboard', () => {
  it('shows every mockup section for the selected month', async () => {
    api()
    renderRoute('/')
    expect(await screen.findByText(/In September 2026 you saved/)).toHaveTextContent(
      'In September 2026 you saved ₹46,662, 32.7% of your income. Spending was 4.6% higher than Aug. Biggest spend: Rent at ₹32,000.',
    )
    const income = screen.getByRole('region', { name: 'Income' })
    expect(income).toHaveTextContent('₹1,42,702')
    expect(income).toHaveTextContent('−11.3% (worse) vs Aug')
    expect(screen.getByRole('region', { name: 'Spending' })).toHaveTextContent(
      '+4.6% (worse) vs Aug',
    )
    expect(screen.getByRole('region', { name: 'Net saving' })).toHaveTextContent('−₹22,330')
    expect(screen.getByRole('region', { name: 'Savings rate' })).toHaveTextContent('−10.2 pts')
    expect(screen.getByRole('region', { name: 'Invested' })).toHaveTextContent(
      '32.1% of net saving',
    )
    expect(screen.getByText(/₹89,190/).closest('p')).toHaveTextContent(
      '₹89,190 spent of ₹95,000 in limits, ₹5,810 left · 2 categories over their limit',
    )
    expect(screen.getByText('₹94 over')).toBeInTheDocument()
    const accounts = screen.getByRole('region', { name: 'By account' })
    expect(within(accounts).getByRole('row', { name: /Credit card/ })).toHaveTextContent('−₹32,750')
    expect(
      screen.getByRole('button', { name: /September 2026: income ₹1,42,702/ }),
    ).toHaveAttribute('aria-pressed', 'true')
    // A hidden table gives screen readers the chart's numbers.
    expect(screen.getByRole('table', { name: 'Cash flow by month' })).toBeInTheDocument()
    const flagged = (await screen.findByText('POS 4471 MERCHANT')).closest('tr')
    expect(flagged).toHaveTextContent('needs a category')
    expect(flagged?.className).toMatch(/review/)
    expect(screen.getByText('CC BILL PAYMENT').closest('tr')?.className).toMatch(/transfer/)
    expect(screen.getByText('₹702.04').className).toMatch(/income/)
  })

  it('the review banner filters the transactions to "needs review"', async () => {
    const calls = api()
    renderRoute('/')
    await userEvent.click(
      await screen.findByRole('button', {
        name: /2 transactions in September 2026 still need a category/,
      }),
    )
    await waitFor(() => expect(lastTransactionsQuery(calls).get('needs_review')).toBe('true'))
    expect(screen.getByRole('button', { name: 'Needs review only' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('a category bar filters the transactions, and filters survive a month change', async () => {
    const calls = api()
    renderRoute('/')
    await userEvent.click(await screen.findByRole('button', { name: /Dining out/ }))
    await waitFor(() => expect(lastTransactionsQuery(calls).get('category_id')).toBe('c-food'))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Month' }), '2026-08')
    await waitFor(() => expect(calls.some((c) => c.path === '/dashboard?month=2026-08')).toBe(true))
    await waitFor(() => {
      const query = lastTransactionsQuery(calls)
      expect(query.get('month')).toBe('2026-08')
      expect(query.get('category_id')).toBe('c-food')
    })
  })

  it('sorts by a column and reports it with aria-sort', async () => {
    const calls = api()
    renderRoute('/?month=2026-09')
    const header = await screen.findByRole('columnheader', { name: /Amount/ })
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(screen.getByRole('columnheader', { name: /Date/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    await userEvent.click(within(header).getByRole('button'))
    await waitFor(() => expect(lastTransactionsQuery(calls).get('sort')).toBe('amount'))
    expect(screen.getByRole('columnheader', { name: /Amount/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
  })

  it('selects a month from the chart with the keyboard', async () => {
    const calls = api()
    renderRoute('/')
    const august = await screen.findByRole('button', { name: /August 2026: income/ })
    august.focus()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(calls.some((c) => c.path === '/dashboard?month=2026-08')).toBe(true))
  })

  it('shows metric definitions from /meta as tooltips', async () => {
    api()
    renderRoute('/')
    const help = await screen.findByRole('button', { name: 'How Income is worked out' })
    expect(help).toHaveAccessibleDescription(/Σ income credits − Σ income debits/)
  })
})
