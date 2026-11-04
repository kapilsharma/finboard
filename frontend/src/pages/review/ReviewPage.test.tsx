import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ACCOUNTS, CATEGORIES, JOB_DONE, txn } from '../../test/fixtures'
import { ME, mockApi, renderRoute } from '../../test/utils'

const SWIGGY_1 = txn('t1', 'UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment', '250.00')
const SWIGGY_2 = txn('t2', 'UPI/DR/598765432109/SWIGGY LTD/YESB/swiggy@ybl/Payment', '410.50')
const ODD = txn('t3', 'UPI/CR/412345678000/YESB/Payment', '75.00', { direction: 'credit' })

const GROUPS = {
  total: 3,
  groups: [
    {
      key: 'SWIGGY',
      suggestion: { match_kind: 'contains', pattern: 'SWIGGY' },
      count: 2,
      debits: '660.50',
      credits: '0.00',
      transactions: [SWIGGY_1, SWIGGY_2],
    },
    {
      key: 'Other',
      suggestion: null,
      count: 1,
      debits: '0.00',
      credits: '75.00',
      transactions: [ODD],
    },
  ],
}

const TEST_RESULT = {
  match_count: 3,
  would_change: 3,
  uncategorised: 3,
  shadowed: 0,
  shadowed_by: [],
  sample: [],
}

const TRANSFER = {
  id: 'p1',
  status: 'suggested',
  score: 0.9,
  days_apart: 2,
  created_at: '2026-10-01T10:00:00Z',
  decided_at: null,
  debit: {
    transaction: txn('t8', 'NEFT CC BILL PAYMENT', '12000.00'),
    account: { id: 'a-sav', name: 'ICICI savings', type: 'savings', masked_number: '1234' },
  },
  credit: {
    transaction: txn('t9', 'PAYMENT RECEIVED THANK YOU', '12000.00', {
      account_id: 'a-card',
      direction: 'credit',
    }),
    account: { id: 'a-card', name: 'ICICI card', type: 'credit_card', masked_number: '9012' },
  },
}

function api(extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) {
  return mockApi({
    'GET /me': () => ({ body: ME }),
    'GET /review/groups': () => ({ body: GROUPS }),
    'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
    'GET /categories': () => ({ body: { items: CATEGORIES } }),
    'GET /transfers?status=suggested': () => ({ body: { items: [TRANSFER] } }),
    'POST /rules/test': ({ body }) => ({
      body: (body as { rule_id?: string }).rule_id
        ? { ...TEST_RESULT, uncategorised: 1 }
        : TEST_RESULT,
    }),
    ...extra,
  })
}

describe('Review page', () => {
  it('groups uncategorised transactions by suggested merchant', async () => {
    api()
    renderRoute('/review')
    const swiggy = await screen.findByRole('region', { name: 'SWIGGY' })
    expect(within(swiggy).getByText(/2 transactions · ₹660.50 out/)).toBeInTheDocument()
    expect(within(swiggy).getAllByRole('listitem')).toHaveLength(2)
    expect(within(swiggy).getAllByText('ICICI savings')).toHaveLength(2)
    const other = screen.getByRole('region', { name: 'Other transactions' })
    expect(within(other).getByText('+₹75.00', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('3 transactions need a category.')).toBeInTheDocument()
  })

  it('categorises a group, creates the suggested rule and offers to apply it', async () => {
    const calls = api({
      'POST /transactions/bulk': () => ({ body: { updated: 2 } }),
      'POST /rules': ({ body }) => ({ status: 201, body: { id: 'r-new', ...(body as object) } }),
      'POST /rules/apply': () => ({
        status: 202,
        body: { job: { ...JOB_DONE({}), status: 'queued' } },
      }),
      'GET /jobs/j1': () => ({ body: JOB_DONE({ changed: 1 }) }),
    })
    renderRoute('/review')
    const swiggy = await screen.findByRole('region', { name: 'SWIGGY' })
    await userEvent.click(within(swiggy).getByRole('button', { name: 'Categorise all 2' }))

    const dialog = await screen.findByRole('dialog', { name: 'Categorise 2 transactions' })
    expect(within(dialog).getByLabelText('Pattern')).toHaveValue('SWIGGY')
    expect(
      await within(dialog).findByText(/Would match 3 transactions \(3 currently different\)/),
    ).toBeInTheDocument()
    await userEvent.selectOptions(within(dialog).getByLabelText('Category'), 'c-food')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and create rule' }))

    const apply = await within(dialog).findByRole('button', { name: 'Apply to 1 uncategorised' })
    expect(calls.find((c) => c.path === '/transactions/bulk')?.body).toEqual({
      ids: ['t1', 't2'],
      category_id: 'c-food',
    })
    expect(calls.find((c) => c.method === 'POST' && c.path === '/rules')?.body).toMatchObject({
      match_kind: 'contains',
      pattern: 'SWIGGY',
      category_id: 'c-food',
    })
    await userEvent.click(apply)
    expect(await within(dialog).findByText('Done: 1 transactions categorised.')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/rules/apply')?.body).toEqual({
      scope: 'uncategorised',
      include_manual: false,
      dry_run: false,
    })
  })

  it('categorises one transaction without a rule', async () => {
    const calls = api({ 'POST /transactions/bulk': () => ({ body: { updated: 1 } }) })
    renderRoute('/review')
    const other = await screen.findByRole('region', { name: 'Other transactions' })
    await userEvent.click(within(other).getByRole('button', { name: /Categorise UPI\/CR/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Categorise transaction' })
    expect(within(dialog).getByRole('checkbox', { name: /Create a rule/ })).not.toBeChecked()
    await userEvent.selectOptions(within(dialog).getByLabelText('Category'), 'c-salary')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
      '/transactions/bulk',
    ])
  })

  it('confirms a suggested transfer', async () => {
    const calls = api({
      'POST /transfers/p1/confirm': () => ({ body: { ...TRANSFER, status: 'confirmed' } }),
    })
    renderRoute('/review')
    const pair = await screen.findByRole('listitem', {
      name: '₹12,000.00 from ICICI savings to ICICI card',
    })
    expect(within(pair).getByText(/2 days apart/)).toBeInTheDocument()
    await userEvent.click(within(pair).getByRole('button', { name: /Confirm transfer/ }))
    await waitFor(() => expect(calls.some((c) => c.path === '/transfers/p1/confirm')).toBe(true))
  })

  it('filters by month through the URL', async () => {
    const calls = api({
      'GET /review/groups?month=2026-08': () => ({ body: { total: 0, groups: [] } }),
    })
    renderRoute('/review?month=2026-08')
    expect(await screen.findByText(/All caught up for this month/)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/review/groups?month=2026-08')).toBe(true)
  })
})
