import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { polling } from '../../api/hooks'
import type { ImportResource, ImportStatus, StagedRow } from '../../api/types'
import { ME, mockApi, renderRoute } from '../../test/utils'

const ROWS: StagedRow[] = [
  {
    seq: 0,
    date: '2026-09-02',
    value_date: null,
    description: 'UPI/412345678901/SWIGGY LTD',
    amount: '250.00',
    direction: 'debit',
    balance_after: '9750.00',
    include: true,
    duplicate: false,
    possible_duplicate: false,
    category_id: null,
    categorised_by: null,
  },
  {
    seq: 1,
    date: '2026-09-03',
    value_date: null,
    description: 'NEFT ACME CORP SALARY',
    amount: '50000.00',
    direction: 'credit',
    balance_after: '59750.00',
    include: false,
    duplicate: true,
    possible_duplicate: false,
    category_id: null,
    categorised_by: null,
  },
]

function resource(status: ImportStatus, extra: Partial<ImportResource> = {}): ImportResource {
  const parsed = status === 'parsed' || status === 'committed'
  return {
    id: 'i1',
    status,
    source: 'upload',
    file_name: 'sept.pdf',
    file_size: 1234,
    encrypted: true,
    archived: false,
    created_at: '2026-10-01T10:00:00Z',
    committed_at: status === 'committed' ? '2026-10-01T10:05:00Z' : null,
    rolled_back_at: null,
    error: null,
    job: null,
    parser: parsed ? { id: 'generic_table', version: '1.0.0', confidence: 0.85 } : null,
    candidates: [],
    institution: parsed ? 'Sample Co-operative Bank Ltd' : null,
    account: null,
    account_suggestion: parsed
      ? {
          create: {
            name: 'Sample Bank 1234',
            type: 'savings',
            institution: 'Sample Bank',
            masked_number: '1234',
          },
        }
      : null,
    period: parsed ? { start: '2026-09-01', end: '2026-09-30' } : null,
    opening: parsed ? '10000.00' : null,
    closing: parsed ? '59750.00' : null,
    reconciliation: parsed
      ? {
          status: 'ok',
          balance_kind: 'asset',
          credits: '50000.00',
          debits: '250.00',
          expected_closing: '59750.00',
          diff: '0.00',
          first_break_seq: null,
          overridden: false,
        }
      : null,
    counts: parsed
      ? {
          parsed: 2,
          new: 1,
          duplicate: 1,
          excluded: 0,
          possible_duplicate: 0,
          needs_review: 1,
        }
      : null,
    result: null,
    rows: parsed ? ROWS : null,
    warnings: [],
    file_already_imported: null,
    ...extra,
  }
}

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
    },
  ],
  failures: [],
}

beforeEach(() => {
  polling.ms = 10
})

afterEach(() => {
  polling.ms = 1000
})

describe('Import page', () => {
  it('drop → password → progress → preview → commit', async () => {
    let state: ImportStatus = 'queued'
    const sequence: Partial<Record<ImportStatus, ImportStatus>> = {
      queued: 'needs_password',
      processing: 'parsed',
    }
    const committed = resource('committed', {
      result: { inserted: 1, skipped: 1, excluded: 0 },
      account: { id: 'a1', name: 'Sample Bank 1234', type: 'savings', masked_number: '1234' },
    })
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /imports': () => ({ body: { items: [], next_cursor: null } }),
      'POST /imports': () => ({ status: 202, body: resource('queued') }),
      'GET /imports/i1': () => {
        const current = state === 'committed' ? committed : resource(state)
        state = sequence[state] ?? state
        return { body: current }
      },
      'POST /imports/i1/unlock': () => {
        state = 'processing'
        return { status: 202, body: resource('processing') }
      },
      'GET /accounts': () => ({ body: { items: [] } }),
      'GET /parsers': () => ({ body: PARSERS }),
      'POST /imports/i1/commit': () => {
        state = 'committed'
        return { body: committed }
      },
    })

    renderRoute('/import')
    const file = new File(['%PDF-1.4 fake'], 'sept.pdf', { type: 'application/pdf' })
    await userEvent.upload(await screen.findByLabelText('Choose PDF statements'), file)

    // One request per file, retry-safe.
    const post = calls.find((c) => c.method === 'POST' && c.path === '/imports')
    expect(post?.headers['Idempotency-Key']).toBeTruthy()

    // The worker finds the file encrypted: ask for the password.
    const item = await screen.findByRole('listitem', { name: 'sept.pdf' })
    const password = await within(item).findByLabelText('Statement password')
    await userEvent.type(password, 'secret-pw')
    await userEvent.click(within(item).getByRole('button', { name: 'Unlock' }))
    const unlock = calls.find((c) => c.path === '/imports/i1/unlock')
    expect(unlock?.body).toEqual({ password: 'secret-pw' })

    // Progress, then the preview is ready.
    const review = await within(item).findByRole('link', { name: 'Review and commit' })
    expect(within(item).getByRole('status')).toHaveTextContent('1 new, 1 already imported')
    // The password went to /unlock only.
    expect(calls.filter((c) => JSON.stringify(c.body ?? '').includes('secret-pw'))).toHaveLength(1)

    await userEvent.click(review)
    expect(await screen.findByText('Balances reconcile')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Preview' })
    expect(within(table).getByText('UPI/412345678901/SWIGGY LTD')).toBeInTheDocument()
    expect(within(table).getByText('−₹250.00')).toBeInTheDocument()
    expect(within(table).getByText('+₹50,000.00')).toBeInTheDocument()
    // The duplicate is greyed out, labelled, and can't be included.
    expect(within(table).getByText('Already imported')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Import row 2' })).toBeDisabled()
    // No account yet: the suggestion is pre-filled.
    expect(screen.getByLabelText('New account name')).toHaveValue('Sample Bank 1234')

    await userEvent.click(screen.getByRole('button', { name: 'Commit 1 transactions' }))
    expect(await screen.findByText(/1 transactions added to Sample Bank 1234/)).toBeInTheDocument()
    const commit = calls.find((c) => c.path === '/imports/i1/commit')
    expect(commit?.body).toMatchObject({
      override_reconciliation: false,
      create_account: { name: 'Sample Bank 1234', type: 'savings' },
    })
    expect(commit?.headers['Idempotency-Key']).toBeTruthy()
  })

  it('rejects non-PDF files without uploading them', async () => {
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /imports': () => ({ body: { items: [], next_cursor: null } }),
    })
    renderRoute('/import')
    const input = await screen.findByLabelText('Choose PDF statements')
    const csv = new File(['a,b'], 'export.csv', { type: 'text/csv' })
    await userEvent.upload(input, csv, { applyAccept: false })
    expect(await screen.findByRole('alert')).toHaveTextContent('Only PDF statements')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('a mismatch blocks commit until overridden, and points at the broken row', async () => {
    const mismatch = resource('parsed', {
      account: { id: 'a1', name: 'Main', type: 'savings', masked_number: '1234' },
      account_suggestion: null,
      reconciliation: {
        status: 'mismatch',
        balance_kind: 'asset',
        credits: '50000.00',
        debits: '250.00',
        expected_closing: '59750.00',
        diff: '10.00',
        first_break_seq: 0,
        overridden: false,
      },
    })
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /imports/i1': () => ({ body: mismatch }),
      'GET /accounts': () => ({
        body: {
          items: [
            {
              id: 'a1',
              name: 'Main',
              type: 'savings',
              institution: null,
              masked_number: '1234',
              parser_id: null,
              currency: 'INR',
              active: true,
              colour: null,
              created_at: '',
              updated_at: '',
            },
          ],
        },
      }),
      'GET /parsers': () => ({ body: PARSERS }),
      'POST /imports/i1/commit': () => ({ body: resource('committed') }),
    })
    renderRoute('/import/i1')
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent("doesn't add up")
    expect(banner).toHaveTextContent('difference ₹10.00')
    expect(within(banner).getByRole('link', { name: 'row 1' })).toHaveAttribute('href', '#row-0')
    expect(screen.getByText('Balance breaks here')).toBeInTheDocument()

    const commit = screen.getByRole('button', { name: 'Commit 1 transactions' })
    expect(commit).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/Commit even though/))
    await userEvent.click(commit)
    const sent = calls.find((c) => c.path === '/imports/i1/commit')
    expect(sent?.body).toMatchObject({ override_reconciliation: true, create_account: null })
  })

  it('excludes a row from the import', async () => {
    let current = resource('parsed', {
      account: { id: 'a1', name: 'Main', type: 'savings', masked_number: '1234' },
    })
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /imports/i1': () => ({ body: current }),
      'GET /accounts': () => ({ body: { items: [] } }),
      'GET /parsers': () => ({ body: PARSERS }),
      'PATCH /imports/i1/rows/0': ({ body }) => {
        const include = (body as { include: boolean }).include
        current = {
          ...current,
          rows: ROWS.map((r) => (r.seq === 0 ? { ...r, include } : r)),
          counts: { ...current.counts!, new: 0, excluded: 1 },
        }
        return { body: current }
      },
    })
    renderRoute('/import/i1')
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Import row 1' }))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ include: false })
    expect(await screen.findByText('1 excluded')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Import row 1' })).not.toBeChecked()
  })
})

describe('Settings › Parsers and Import history', () => {
  it('lists parsers and load failures', async () => {
    mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /parsers': () => ({
        body: { ...PARSERS, failures: [{ source: 'acme = acme:Parser', reason: 'import failed' }] },
      }),
    })
    renderRoute('/settings/parsers')
    expect(await screen.findByText('Generic table statement (PDF)')).toBeInTheDocument()
    expect(screen.getByText('fallback')).toBeInTheDocument()
    expect(screen.getByText('import failed')).toBeInTheDocument()
  })

  it('rolls back a committed import from the history', async () => {
    const committed = resource('committed', {
      result: { inserted: 12, skipped: 0, excluded: 0 },
    })
    const calls = mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /imports': () => ({ body: { items: [committed], next_cursor: null } }),
      'POST /imports/i1/rollback': () => ({ body: resource('rolled_back') }),
    })
    window.confirm = () => true
    renderRoute('/settings/imports')
    expect(await screen.findByText('12 added, 0 skipped')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Roll back sept.pdf' }))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/imports/i1/rollback')).toBe(true)
  })
})
