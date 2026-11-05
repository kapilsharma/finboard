import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ACCOUNTS, CATEGORIES } from '../../test/fixtures'
import { SEPTEMBER, TXNS } from '../../test/dashboard-fixture'
import { ME, mockApi, renderRoute } from '../../test/utils'

const STATUS = {
  suggestions_available: false,
  suggestions_enabled: false,
  suggest_method: 'auto',
  embed_model: 'm',
  embedded: 0,
  transactions: 0,
  ask_available: true,
  ask_enabled: true,
  ask_provider: 'gemini',
  ask_sql: false,
}

const QUERY = {
  id: 'q1',
  question: 'Eating out and groceries by month',
  status: 'ok',
  path: 'spec',
  spec: { metric: 'spending', categories: ['Dining out', 'Groceries'] },
  sql: null,
  chart: { kind: 'grouped_bar', x: 'month', series: 'category', y: 'spending' },
  clarification: null,
  error: null,
  retries: 0,
  latency_ms: 900,
  model: 'gemini-2.5-flash',
  tokens_in: 400,
  tokens_out: 60,
  created_at: '2026-11-05T10:00:00Z',
  pinned: false,
}

const RESULT = {
  columns: [
    { name: 'month', kind: 'month' },
    { name: 'category', kind: 'text' },
    { name: 'spending', kind: 'money' },
  ],
  rows: [
    ['2026-08', 'Dining out', '3800.00'],
    ['2026-08', 'Groceries', '11200.50'],
    ['2026-09', 'Dining out', '4093.94'],
    ['2026-09', 'Groceries', '12890.00'],
  ],
  truncated: false,
}

function api(status = STATUS, widgets: unknown[] = []) {
  return mockApi({
    'GET /me': () => ({ body: ME }),
    'GET /meta': () => ({
      body: { version: '0', api_version: 'v1', mode: 'local', metric_definitions: {} },
    }),
    'GET /dashboard': () => ({ body: SEPTEMBER }),
    'GET /dashboard/months': () => ({ body: { months: ['2026-09'] } }),
    'GET /transactions': () => ({ body: TXNS }),
    'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
    'GET /categories': () => ({ body: { items: CATEGORIES } }),
    'GET /ai/status': () => ({ body: status }),
    'POST /ask': () => ({
      body: {
        query: QUERY,
        answer: 'Spending on Dining out, Groceries by month and category: ₹31,984.44 in total.',
        result: RESULT,
      },
    }),
    'POST /ask/q1/pin': () => ({ status: 201, body: {} }),
    'GET /dashboard/widgets': () => ({ body: { items: widgets } }),
  })
}

describe('Ask Finboard on the dashboard', () => {
  it('is hidden unless the user turned it on', async () => {
    api({ ...STATUS, ask_enabled: false })
    renderRoute('/')
    await screen.findByText(/In September 2026 you saved/)
    expect(screen.queryByRole('region', { name: 'Ask Finboard' })).not.toBeInTheDocument()
  })

  it('says what is sent, answers as a chart, shows the query and pins it', async () => {
    const calls = api()
    renderRoute('/')
    const panel = await screen.findByRole('region', { name: 'Ask Finboard' })
    expect(panel).toHaveTextContent('Your question is sent to Google Gemini')
    expect(panel).toHaveTextContent('Your transactions, amounts and account names never are')
    expect(panel).toHaveTextContent('Google may use questions to improve its products')

    const user = userEvent.setup()
    await user.type(within(panel).getByLabelText('Question'), QUERY.question)
    await user.click(within(panel).getByRole('button', { name: 'Ask' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('₹31,984.44 in total')
    expect(within(panel).getByRole('img', { name: 'Bar chart' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/ask')?.body).toEqual({ question: QUERY.question })

    await user.click(within(panel).getByRole('button', { name: 'Show as table' }))
    const table = within(panel).getByRole('table')
    expect(table).toHaveTextContent('September 2026')
    expect(table).toHaveTextContent('₹12,890.00')

    await user.click(within(panel).getByText('Show query'))
    expect(panel).toHaveTextContent('"metric": "spending"')

    await user.click(within(panel).getByRole('button', { name: 'Pin to dashboard' }))
    expect(await within(panel).findByRole('button', { name: 'Pinned to dashboard' })).toBeDisabled()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/ask/q1/pin')).toBe(true)
  })

  it('shows pinned questions, and asks for an update when one is stale', async () => {
    api(STATUS, [
      {
        id: 'w1',
        title: 'Eating out',
        sort_order: 0,
        status: 'ok',
        message: null,
        query: { ...QUERY, pinned: true },
        chart: QUERY.chart,
        result: RESULT,
      },
      {
        id: 'w2',
        title: 'Old custom query',
        sort_order: 1,
        status: 'needs_update',
        message: 'This chart needs updating: ask the question again.',
        query: { ...QUERY, id: 'q2', path: 'sql', pinned: true },
        chart: null,
        result: null,
      },
    ])
    renderRoute('/')
    const pinned = await screen.findByRole('region', { name: 'Pinned questions' })
    await waitFor(() =>
      expect(within(pinned).getByRole('region', { name: 'Eating out' })).toBeInTheDocument(),
    )
    expect(within(pinned).getByRole('region', { name: 'Old custom query' })).toHaveTextContent(
      'This chart needs updating',
    )
    expect(
      within(pinned).getByRole('button', { name: 'Remove “Eating out” from the dashboard' }),
    ).toBeInTheDocument()
  })
})
