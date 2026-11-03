import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockApi, renderWithQuery } from '../../test/utils'
import { CategoriesTab } from './CategoriesTab'

const base = {
  colour: '#888888',
  sort_order: 0,
  archived: false,
  system_key: null,
  is_system: false,
}
const CATEGORIES = [
  { ...base, id: 'c1', name: 'Salary', type: 'income', parent_id: null },
  { ...base, id: 'c2', name: 'Investments', type: 'investment', parent_id: null },
  { ...base, id: 'c3', name: 'Flexi cap', type: 'investment', parent_id: 'c2' },
  {
    ...base,
    id: 'c4',
    name: 'Card payment',
    type: 'transfer',
    parent_id: null,
    is_system: true,
    system_key: 'card_payment',
  },
]

describe('CategoriesTab', () => {
  it('groups categories by type and nests children', async () => {
    mockApi({ 'GET /categories': () => ({ body: { items: CATEGORIES } }) })
    renderWithQuery(<CategoriesTab />)
    const investment = await screen.findByRole('region', { name: 'Investment' })
    const rows = within(investment).getAllByRole('row')
    expect(rows.map((r) => r.querySelector('td')?.textContent)).toEqual([
      'Investments',
      'Flexi cap',
    ])
    expect(screen.getByRole('region', { name: 'Income' })).toHaveTextContent('Salary')
  })

  it('does not offer delete for system categories', async () => {
    mockApi({ 'GET /categories': () => ({ body: { items: CATEGORIES } }) })
    renderWithQuery(<CategoriesTab />)
    const transfer = await screen.findByRole('region', { name: 'Transfer' })
    expect(within(transfer).getByText('system')).toBeInTheDocument()
    expect(within(transfer).queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
    expect(within(transfer).getByRole('button', { name: /Rename/ })).toBeInTheDocument()
  })
})
