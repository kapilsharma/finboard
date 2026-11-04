import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ACCOUNTS, CATEGORIES, JOB_DONE } from '../../test/fixtures'
import { mockApi, renderWithQuery } from '../../test/utils'
import { BudgetsTab } from './BudgetsTab'
import { CategoriesTab } from './CategoriesTab'
import { DataTab } from './DataTab'
import { ParsersTab } from './ParsersTab'

const HISTORY = [
  { category_id: 'c-food', effective_from: '2026-07-01', monthly_limit: '4000.00' },
  { category_id: 'c-food', effective_from: '2026-09-01', monthly_limit: '5000.00' },
  { category_id: 'c-shop', effective_from: '2026-07-01', monthly_limit: null },
]

describe('Settings › Budgets', () => {
  it('shows each limit in force and its history, and sets a change from a month', async () => {
    vi.setSystemTime(new Date('2026-10-15T12:00:00Z'))
    const calls = mockApi({
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'GET /budgets/history': () => ({ body: { items: HISTORY } }),
      'PUT /budgets/c-food': ({ body }) => ({
        body: { category_id: 'c-food', ...(body as object) },
      }),
    })
    renderWithQuery(<BudgetsTab />)
    const food = (await screen.findByRole('rowheader', { name: 'Dining out' })).closest('tr')!
    expect(food).toHaveTextContent('₹5,000')
    expect(
      within(food).getByRole('list', { name: 'Limit changes for Dining out' }),
    ).toHaveTextContent('₹4,000 from July 2026Undo₹5,000 from September 2026Undo')
    expect(screen.getByRole('rowheader', { name: 'Shopping' }).closest('tr')).toHaveTextContent(
      'No limit',
    )
    expect(screen.queryByRole('rowheader', { name: 'Salary' })).not.toBeInTheDocument() // income

    await userEvent.click(
      within(food).getByRole('button', { name: 'Change the limit for Dining out' }),
    )
    const form = screen.getByRole('form', { name: 'Change the limit for Dining out' })
    await userEvent.clear(within(form).getByLabelText('From'))
    await userEvent.type(within(form).getByLabelText('From'), '2026-11')
    await userEvent.type(within(form).getByLabelText('Monthly limit (₹)'), '4500')
    expect(form).toHaveTextContent('Months before November 2026 keep their limit.')
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
        effective_from: '2026-11',
        monthly_limit: '4500',
      }),
    )
    vi.useRealTimers()
  })

  it('"No limit" sends null, and a change can be undone', async () => {
    const calls = mockApi({
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'GET /budgets/history': () => ({ body: { items: HISTORY } }),
      'PUT /budgets/c-food': () => ({ body: {} }),
      'DELETE /budgets/c-food/2026-09': () => ({ status: 204 }),
    })
    renderWithQuery(<BudgetsTab />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Undo the Dining out change from September 2026' }),
    )
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: 'Change the limit for Dining out' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'No limit' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ monthly_limit: null }),
    )
  })
})

describe('Settings › Categories merge', () => {
  it('merges a category into another and reports what moved', async () => {
    const calls = mockApi({
      'GET /categories': () => ({ body: { items: CATEGORIES } }),
      'POST /categories/c-shop/merge': () => ({
        body: { into: CATEGORIES[0], transactions: 12, rules: 2, budgets: 1 },
      }),
    })
    renderWithQuery(<CategoriesTab />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Merge Shopping into another category' }),
    )
    const dialog = screen.getByRole('dialog', { name: 'Merge “Shopping”' })
    await userEvent.selectOptions(within(dialog).getByLabelText('Merge into'), 'c-food')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Merge' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent(
      'Moved 12 transactions, 2 rules and 1 limit change to “Dining out”. “Shopping” is gone.',
    )
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ into_id: 'c-food' })
    // System categories can't be merged away.
    expect(
      screen.queryByRole('button', { name: 'Merge Uncategorized into another category' }),
    ).not.toBeInTheDocument()
  })
})

const PARSERS = {
  items: [
    {
      id: 'generic_table',
      name: 'Generic table statement (PDF)',
      version: '1.0.0',
      institutions: [],
      account_types: ['savings'],
      file_types: ['.pdf'],
      fallback: true,
      enabled: true,
      options: {},
      options_schema: null,
    },
    {
      id: 'kotak_savings_pdf',
      name: 'Kotak savings (PDF)',
      version: '1.2.0',
      institutions: ['Kotak'],
      account_types: ['savings'],
      file_types: ['.pdf'],
      fallback: false,
      enabled: false,
      options: { date_order: 'dmy', skip_zero_rows: true },
      options_schema: {
        properties: {
          date_order: { title: 'Date order', enum: ['dmy', 'mdy'] },
          skip_zero_rows: { title: 'Skip zero rows', type: 'boolean' },
        },
      },
    },
  ],
  failures: [],
}

describe('Settings › Parsers', () => {
  it('switches parsers on and off and edits their options from the schema', async () => {
    const calls = mockApi({
      'GET /parsers': () => ({ body: PARSERS }),
      'PATCH /parsers/generic_table': () => ({ body: { ...PARSERS.items[0], enabled: false } }),
      'PATCH /parsers/kotak_savings_pdf': () => ({ body: PARSERS.items[1] }),
    })
    renderWithQuery(<ParsersTab />)
    const toggle = await screen.findByRole('checkbox', {
      name: 'On: Generic table statement (PDF)',
    })
    expect(toggle).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'On: Kotak savings (PDF)' })).not.toBeChecked()
    expect(
      screen.queryByRole('button', { name: 'Options for Generic table statement (PDF)' }),
    ).not.toBeInTheDocument()
    await userEvent.click(toggle)
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/parsers/generic_table')?.body).toEqual({
        enabled: false,
      }),
    )

    await userEvent.click(screen.getByRole('button', { name: 'Options for Kotak savings (PDF)' }))
    const form = screen.getByRole('form', { name: 'Options for Kotak savings (PDF)' })
    await userEvent.selectOptions(within(form).getByLabelText('Date order'), 'mdy')
    await userEvent.click(within(form).getByLabelText('Skip zero rows'))
    await userEvent.click(within(form).getByRole('button', { name: 'Save options' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/parsers/kotak_savings_pdf')?.body).toEqual({
        options: { date_order: 'mdy', skip_zero_rows: false },
      }),
    )
  })
})

describe('Settings › Data', () => {
  function api(extra: Parameters<typeof mockApi>[0] = {}) {
    return mockApi({
      'GET /accounts': () => ({ body: { items: ACCOUNTS } }),
      ...extra,
    })
  }

  it('exports, then offers the download', async () => {
    api({
      'POST /data/export': () => ({
        status: 202,
        body: { job: { ...JOB_DONE({}), id: 'e1', status: 'queued' } },
      }),
      'GET /jobs/e1': () => ({
        body: { ...JOB_DONE({ size: 2048 }), id: 'e1', kind: 'data.export' },
      }),
    })
    renderWithQuery(<DataTab />)
    expect(screen.getByRole('link', { name: 'Download transactions (CSV)' })).toHaveAttribute(
      'href',
      '/api/v1/data/transactions.csv',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Export all data' }))
    expect(await screen.findByText('Export ready (2 KB).')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download the export' })).toHaveAttribute(
      'href',
      '/api/v1/data/exports/e1',
    )
  })

  it('delete-all needs the exact typed confirmation', async () => {
    const calls = api({
      'POST /data/delete-all': () => ({
        status: 202,
        body: { job: { ...JOB_DONE({}), id: 'd1', status: 'queued' } },
      }),
      'GET /jobs/d1': () => ({ body: { ...JOB_DONE({ rows: 10, files: 2 }), id: 'd1' } }),
    })
    renderWithQuery(<DataTab />)
    const button = screen.getByRole('button', { name: 'Delete all my data' })
    const input = screen.getByLabelText('Type DELETE ALL to confirm')
    await userEvent.type(input, 'delete all')
    expect(button).toBeDisabled()
    await userEvent.clear(input)
    await userEvent.type(input, 'DELETE ALL')
    await userEvent.click(button)
    expect(await screen.findByText('All your data is deleted.')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/data/delete-all')?.body).toEqual({
      confirm: 'DELETE ALL',
    })
  })

  it('shows why an import was refused', async () => {
    api({
      'POST /data/import': () => ({
        status: 202,
        body: { job: { ...JOB_DONE({}), id: 'i1', status: 'queued' } },
      }),
      'GET /jobs/i1': () => ({
        body: {
          ...JOB_DONE({}),
          id: 'i1',
          status: 'failed',
          error: 'This export is from a newer Finboard (format 2)',
        },
      }),
    })
    renderWithQuery(<DataTab />)
    const file = new File(['PK'], 'export.zip', { type: 'application/zip' })
    await userEvent.upload(screen.getByLabelText('Export file (.zip)'), file)
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText(/newer Finboard/)).toBeInTheDocument()
  })
})
