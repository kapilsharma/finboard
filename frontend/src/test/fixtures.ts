/** Shared API fixtures for page tests (made-up data). */
import type { Category, Rule, Txn } from '../api/types'

const categoryBase = { colour: '#888888', sort_order: 0, archived: false, parent_id: null }

export const CATEGORIES: Category[] = [
  {
    ...categoryBase,
    id: 'c-food',
    name: 'Dining out',
    type: 'expense',
    is_system: false,
    system_key: null,
  },
  {
    ...categoryBase,
    id: 'c-shop',
    name: 'Shopping',
    type: 'expense',
    is_system: false,
    system_key: null,
  },
  {
    ...categoryBase,
    id: 'c-salary',
    name: 'Salary',
    type: 'income',
    is_system: false,
    system_key: null,
  },
  {
    ...categoryBase,
    id: 'c-uncat',
    name: 'Uncategorized',
    type: 'expense',
    is_system: true,
    system_key: 'uncategorized',
  },
]

export const ACCOUNTS = [
  {
    id: 'a-sav',
    name: 'ICICI savings',
    type: 'savings',
    institution: null,
    masked_number: '1234',
    parser_id: null,
    currency: 'INR',
    active: true,
    colour: null,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
  },
  {
    id: 'a-card',
    name: 'ICICI card',
    type: 'credit_card',
    institution: null,
    masked_number: '9012',
    parser_id: null,
    currency: 'INR',
    active: true,
    colour: null,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
  },
]

export function txn(
  id: string,
  description: string,
  amount: string,
  extra: Partial<Txn> = {},
): Txn {
  return {
    id,
    account_id: 'a-sav',
    import_id: null,
    date: '2026-09-05',
    description,
    description_norm: description.toUpperCase(),
    payee_label: null,
    amount,
    direction: 'debit',
    category_id: 'c-uncat',
    type: 'expense',
    categorised_by: 'default',
    rule_id: null,
    needs_review: true,
    notes: null,
    ...extra,
  }
}

export function rule(
  id: string,
  pattern: string,
  priority: number,
  extra: Partial<Rule> = {},
): Rule {
  return {
    id,
    priority,
    match_kind: 'contains',
    pattern,
    category_id: 'c-food',
    account_id: null,
    direction: null,
    amount_min: null,
    amount_max: null,
    label: null,
    enabled: true,
    hits: 0,
    last_hit_at: null,
    error: null,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    ...extra,
  }
}

export const JOB_DONE = (result: Record<string, unknown>) => ({
  id: 'j1',
  kind: 'rules.apply',
  status: 'succeeded',
  progress: 100,
  result,
  error: null,
  created_at: '2026-10-01T10:00:00Z',
  started_at: '2026-10-01T10:00:00Z',
  finished_at: '2026-10-01T10:00:01Z',
})
