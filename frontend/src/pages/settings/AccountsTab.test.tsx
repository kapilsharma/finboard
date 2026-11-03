import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { mockApi, renderWithQuery } from '../../test/utils'
import { AccountsTab } from './AccountsTab'

const ICICI = {
  id: 'a1',
  name: 'ICICI Savings',
  type: 'savings',
  institution: 'ICICI Bank',
  masked_number: '4321',
  parser_id: null,
  currency: 'INR',
  active: true,
  colour: null,
  created_at: '2026-10-18T00:00:00Z',
  updated_at: '2026-10-18T00:00:00Z',
}

describe('AccountsTab', () => {
  it('lists accounts with masked numbers', async () => {
    mockApi({ 'GET /accounts': () => ({ body: { items: [ICICI] } }) })
    renderWithQuery(<AccountsTab />)
    const row = (await screen.findByRole('cell', { name: 'ICICI Savings' })).closest('tr')!
    expect(within(row).getByText('Savings')).toBeInTheDocument()
    expect(within(row).getByText('••4321')).toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    mockApi({ 'GET /accounts': () => ({ body: { items: [] } }) })
    renderWithQuery(<AccountsTab />)
    expect(await screen.findByText(/No accounts yet/)).toBeInTheDocument()
  })

  it('creates an account and sends only the last 4 digits', async () => {
    const items: unknown[] = []
    const calls = mockApi({
      'GET /accounts': () => ({ body: { items } }),
      'POST /accounts': ({ body }) => {
        const created = { ...ICICI, ...(body as object), id: 'a2' }
        items.push(created)
        return { status: 201, body: created }
      },
    })
    renderWithQuery(<AccountsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add account' }))
    const form = screen.getByRole('form', { name: 'Save account' })
    await userEvent.type(within(form).getByLabelText('Name'), 'ICICI Credit Card')
    await userEvent.selectOptions(within(form).getByLabelText('Type'), 'credit_card')
    await userEvent.type(within(form).getByLabelText('Last 4 digits'), '9876')
    await userEvent.click(within(form).getByRole('button', { name: 'Save account' }))

    expect(await screen.findByRole('cell', { name: 'ICICI Credit Card' })).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.body).toEqual({
      name: 'ICICI Credit Card',
      type: 'credit_card',
      institution: null,
      masked_number: '9876',
      active: true,
    })
    expect(screen.queryByRole('form', { name: 'Save account' })).not.toBeInTheDocument()
  })

  it('shows the server error when the name is taken', async () => {
    mockApi({
      'GET /accounts': () => ({ body: { items: [ICICI] } }),
      'POST /accounts': () => ({
        status: 409,
        body: {
          status: 409,
          code: 'conflict',
          title: 'Conflict',
          detail: "An account called 'ICICI Savings' already exists",
        },
      }),
    })
    renderWithQuery(<AccountsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add account' }))
    const form = screen.getByRole('form', { name: 'Save account' })
    await userEvent.type(within(form).getByLabelText('Name'), 'ICICI Savings')
    await userEvent.click(within(form).getByRole('button', { name: 'Save account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  })
})
