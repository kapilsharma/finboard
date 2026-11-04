import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Rule } from '../../../api/types'
import { ACCOUNTS, CATEGORIES, JOB_DONE, rule } from '../../../test/fixtures'
import { mockApi, renderWithQuery } from '../../../test/utils'
import { RulesTab } from './RulesTab'

const RULES: Rule[] = [
  rule('r1', 'SWIGGY', 0, { hits: 12, direction: 'debit' }),
  rule('r2', 'AMAZON', 1, { category_id: 'c-shop', amount_max: '5000.00' }),
  rule('r3', '(A|AA)+$', 2, {
    match_kind: 'regex',
    enabled: false,
    error: 'Switched off: its regular expression took too long (over 50 ms) to run',
  }),
]

const TEST = {
  match_count: 7,
  would_change: 4,
  uncategorised: 4,
  shadowed: 0,
  shadowed_by: [],
  sample: [],
}

function api(extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) {
  return mockApi({
    'GET /rules': () => ({ body: { items: RULES } }),
    'GET /categories': () => ({ body: { items: CATEGORIES } }),
    'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
    'POST /rules/test': () => ({ body: TEST }),
    ...extra,
  })
}

function rows() {
  return within(screen.getByRole('list', { name: 'Rules, in the order they run' })).getAllByRole(
    'listitem',
  )
}

describe('Settings › Rules', () => {
  it('lists rules in the order they run, with category, constraints, hits and errors', async () => {
    api()
    renderWithQuery(<RulesTab />)
    const first = await screen.findByRole('listitem', { name: 'Rule 1: contains SWIGGY' })
    expect(within(first).getByText('Dining out')).toBeInTheDocument()
    expect(within(first).getByText('Money out')).toBeInTheDocument()
    expect(within(first).getByText('12 hits')).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: 'Rule 2: contains AMAZON' })).toHaveTextContent(
      'up to ₹5,000.00',
    )
    const broken = screen.getByRole('listitem', { name: 'Rule 3: matches regex (A|AA)+$' })
    expect(within(broken).getByText(/took too long/)).toBeInTheDocument()
    expect(within(broken).getByRole('checkbox', { name: /On/ })).not.toBeChecked()
  })

  it('moves a rule down with the keyboard-accessible arrow buttons', async () => {
    const calls = api({
      'POST /rules/reorder': ({ body }) => {
        const ids = (body as { ids: string[] }).ids
        return {
          body: {
            items: ids.map((id, i) => ({ ...RULES.find((r) => r.id === id)!, priority: i })),
          },
        }
      },
    })
    renderWithQuery(<RulesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Move down: contains SWIGGY' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/rules/reorder')?.body).toEqual({
        ids: ['r2', 'r1', 'r3'],
      }),
    )
    await waitFor(() => expect(rows()[0]).toHaveAccessibleName('Rule 1: contains AMAZON'))
    expect(screen.getByRole('button', { name: 'Move up: contains AMAZON' })).toBeDisabled()
  })

  it('searches, and only offers reordering on the full list', async () => {
    api()
    renderWithQuery(<RulesTab />)
    await screen.findByRole('listitem', { name: /SWIGGY/ })
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search rules' }), 'shopping')
    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toHaveAccessibleName('Rule 2: contains AMAZON')
    expect(screen.queryByRole('button', { name: /Move|Drag/ })).not.toBeInTheDocument()
  })

  it('switches a rule on and off', async () => {
    const calls = api({ 'PATCH /rules/r1': () => ({ body: { ...RULES[0], enabled: false } }) })
    renderWithQuery(<RulesTab />)
    const first = await screen.findByRole('listitem', { name: /SWIGGY/ })
    await userEvent.click(within(first).getByRole('checkbox', { name: /On/ }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ enabled: false }),
    )
  })

  it('tests a new rule before saving, then asks to apply it to uncategorised transactions', async () => {
    const calls = api({
      'POST /rules': ({ body }) => ({
        status: 201,
        body: rule('r9', 'ZOMATO', 3, body as Partial<Rule>),
      }),
      'POST /rules/apply': () => ({
        status: 202,
        body: { job: { ...JOB_DONE({}), status: 'queued' } },
      }),
      'GET /jobs/j1': () => ({ body: JOB_DONE({ changed: 4 }) }),
    })
    renderWithQuery(<RulesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add rule' }))
    const form = screen.getByRole('form', { name: 'Add rule' })
    await userEvent.type(within(form).getByLabelText('Pattern'), 'zomato')
    await userEvent.selectOptions(within(form).getByLabelText('Category'), 'c-food')
    await userEvent.selectOptions(within(form).getByLabelText('Direction'), 'debit')
    expect(
      await within(form).findByText(/Would match 7 transactions \(4 currently different\)/),
    ).toBeInTheDocument()
    await userEvent.click(within(form).getByRole('button', { name: 'Add rule' }))

    const prompt = await screen.findByRole('group', { name: 'Apply the rule' })
    expect(calls.find((c) => c.method === 'POST' && c.path === '/rules')?.body).toMatchObject({
      match_kind: 'contains',
      pattern: 'zomato',
      category_id: 'c-food',
      direction: 'debit',
      amount_min: null,
    })
    await userEvent.click(within(prompt).getByRole('button', { name: 'Apply to 4 uncategorised' }))
    expect(await within(prompt).findByText('Done: 4 transactions categorised.')).toBeInTheDocument()
  })

  it('rejects malformed amounts before saving', async () => {
    api()
    renderWithQuery(<RulesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add rule' }))
    const form = screen.getByRole('form', { name: 'Add rule' })
    await userEvent.type(within(form).getByLabelText('Amount from (₹)'), '12.345')
    expect(within(form).getByText('Amounts look like 1500 or 1500.50')).toBeInTheDocument()
    expect(within(form).getByRole('button', { name: 'Add rule' })).toBeDisabled()
  })

  it('previews a re-apply before applying it', async () => {
    let dryRun = true
    const calls = api({
      'POST /rules/apply': ({ body }) => {
        dryRun = (body as { dry_run: boolean }).dry_run
        return { status: 202, body: { job: { ...JOB_DONE({}), status: 'queued' } } }
      },
      'GET /jobs/j1': () => ({
        body: JOB_DONE({
          dry_run: dryRun,
          changed: 5,
          transitions: [{ from_category_id: 'c-uncat', to_category_id: 'c-food', count: 5 }],
        }),
      }),
    })
    renderWithQuery(<RulesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Re-apply rules…' }))
    const dialog = screen.getByRole('dialog', { name: 'Re-apply rules' })
    await userEvent.click(within(dialog).getByRole('radio', { name: /Also ones a rule/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview changes' }))
    expect(await within(dialog).findByText('5 × Uncategorized → Dining out')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/rules/apply')?.body).toEqual({
      scope: 'all',
      include_manual: false,
      dry_run: true,
    })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply 5 changes' }))
    expect(await within(dialog).findByText('Done: 5 transactions changed.')).toBeInTheDocument()
  })
})
