import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ACCOUNTS, CATEGORIES, txn } from '../../test/fixtures'
import { ME, mockApi, renderRoute } from '../../test/utils'

const OFF = {
  suggestions_available: false,
  suggestions_enabled: false,
  suggest_method: 'auto',
  embed_model: 'sentence-transformers/all-MiniLM-L6-v2',
  embedded: 0,
  transactions: 0,
  ask_available: false,
  ask_enabled: false,
  ask_provider: 'off',
  ask_sql: false,
}

describe('Settings › AI', () => {
  it('explains that both features are off on this server', async () => {
    mockApi({ 'GET /me': () => ({ body: ME }), 'GET /ai/status': () => ({ body: OFF }) })
    renderRoute('/settings/ai')
    const suggestions = await screen.findByRole('region', { name: 'Category suggestions' })
    expect(suggestions).toHaveTextContent('Not available on this server')
    expect(suggestions).toHaveTextContent('nothing is sent anywhere')
    expect(within(suggestions).queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Ask Finboard' })).toHaveTextContent(
      'FINBOARD_AI_ASK=gemini',
    )
  })

  it('turns suggestions on and shows preparation progress', async () => {
    let status = { ...OFF, suggestions_available: true, transactions: 120 }
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /ai/status': () => ({ body: status }),
      'PATCH /ai/settings': ({ body }) => {
        status = {
          ...status,
          suggestions_enabled: (body as { suggestions: boolean }).suggestions,
          embedded: 40,
        }
        return { body: status }
      },
    })
    renderRoute('/settings/ai')
    const toggle = await screen.findByRole('switch', { name: 'Suggest categories' })
    expect(toggle).not.toBeChecked()
    await userEvent.click(toggle)
    await waitFor(() => expect(toggle).toBeChecked())
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ suggestions: true })
    expect(await screen.findByText(/40 of 120 transactions prepared/)).toBeInTheDocument()
  })
})

describe('Suggestions in the categorise dialog', () => {
  const ODD = txn('t3', 'UPI/DR/412345678000/ZEPTO/Payment', '75.00')
  const SUGGESTIONS = {
    method: 'embedding',
    items: [
      {
        category: { id: 'c-food', name: CATEGORIES[0]!.name, type: 'expense', colour: null },
        confidence: 0.82,
        examples: [
          {
            id: 'e1',
            date: '2026-09-02',
            description: 'UPI/DR/1/ZEPTO MARKETPLACE/Payment',
            amount: '120.00',
            direction: 'debit',
            similarity: 0.91,
          },
        ],
      },
    ],
  }

  function api(extra: Parameters<typeof mockApi>[0] = {}) {
    return mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'GET /transfers?status=suggested': () => ({ body: { items: [] } }),
      'GET /review/groups': () => ({
        body: {
          total: 1,
          groups: [
            {
              key: 'Other',
              suggestion: null,
              count: 1,
              debits: '75.00',
              credits: '0.00',
              transactions: [ODD],
            },
          ],
        },
      }),
      'GET /ai/status': () => ({
        body: { ...OFF, suggestions_available: true, suggestions_enabled: true },
      }),
      'GET /transactions/t3/suggestions': () => ({ body: SUGGESTIONS }),
      'POST /transactions/bulk': () => ({ body: { updated: 1 } }),
      'POST /rules/test': () => ({
        body: {
          match_count: 1,
          would_change: 1,
          uncategorised: 1,
          shadowed: 0,
          shadowed_by: [],
          sample: [],
        },
      }),
      ...extra,
    })
  }

  async function openDialog() {
    renderRoute('/review')
    const other = await screen.findByRole('region', { name: 'Other transactions' })
    await userEvent.click(within(other).getByRole('button', { name: /Categorise UPI/ }))
    return screen.findByRole('dialog', { name: 'Categorise transaction' })
  }

  it('shows the suggestion with its examples, and Accept categorises by hand', async () => {
    const calls = api()
    const dialog = await openDialog()
    const list = await within(dialog).findByRole('region', { name: 'Suggested categories' })
    expect(list).toHaveTextContent(`${CATEGORIES[0]!.name} 82% of matches`)
    await userEvent.click(within(list).getByText(/Why: 1 similar transaction/))
    expect(list).toHaveTextContent('UPI/DR/1/ZEPTO MARKETPLACE/Payment')
    await userEvent.click(within(list).getByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.find((c) => c.path === '/transactions/bulk')?.body).toEqual({
      ids: ['t3'],
      category_id: 'c-food',
    })
  })

  it('Make a rule fills in the category and opens the rule editor', async () => {
    const calls = api()
    const dialog = await openDialog()
    const list = await within(dialog).findByRole('region', { name: 'Suggested categories' })
    await userEvent.click(within(list).getByRole('button', { name: 'Make a rule' }))
    expect(within(dialog).getByRole('checkbox', { name: /Create a rule/ })).toBeChecked()
    expect(within(dialog).getByLabelText('Category')).toHaveValue('c-food')
    expect(calls.some((c) => c.path === '/transactions/bulk')).toBe(false) // nothing applied
  })
})
