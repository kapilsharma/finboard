/** A dashboard response shaped like the golden September 2026 (made-up data). */
import type { Dashboard, TxnList } from '../api/types'

const cat = (id: string, name: string, type: 'income' | 'expense' = 'expense') => ({
  id,
  name,
  type,
  colour: null,
})

export const SEPTEMBER: Dashboard = {
  month: '2026-09',
  prev_month: '2026-08',
  headline: {
    income: { value: '142702.04', prev: '160791.67', delta_pct: -11.3 },
    spending: { value: '96040.38', prev: '91825.30', delta_pct: 4.6 },
    net_saving: { value: '46661.66', prev: '68991.94', delta: '-22330.28' },
    savings_rate: { value: 32.7, prev: 42.9, delta_pts: -10.2 },
    invested: { value: '15000.00', pct_of_net_saving: 32.1 },
  },
  biggest_spend: { category: cat('c-rent', 'Rent'), amount: '32000.00' },
  review_count: 2,
  cashflow: [
    {
      month: '2026-07',
      income: '142697.15',
      spending: '93000.00',
      net_saving: '49697.15',
      invested: '15000.00',
    },
    {
      month: '2026-08',
      income: '160791.67',
      spending: '91825.30',
      net_saving: '68966.37',
      invested: '15000.00',
    },
    {
      month: '2026-09',
      income: '142702.04',
      spending: '96040.38',
      net_saving: '46661.66',
      invested: '15000.00',
    },
  ],
  categories: {
    summary: {
      spent_in_limits: '89190.38',
      limits_total: '95000.00',
      left: '5809.62',
      over_count: 2,
    },
    items: [
      {
        category: cat('c-food', 'Dining out'),
        spent: '4093.94',
        limit: '4000.00',
        remaining: '-93.94',
        pct_used: 102.3,
        status: 'over',
      },
      {
        category: cat('c-groc', 'Groceries'),
        spent: '12268.00',
        limit: '12000.00',
        remaining: '-268.00',
        pct_used: 102.2,
        status: 'over',
      },
      {
        category: cat('c-rent', 'Rent'),
        spent: '32000.00',
        limit: '32000.00',
        remaining: '0.00',
        pct_used: 100,
        status: 'under',
      },
      {
        category: cat('c-unc', 'Uncategorized'),
        spent: '6850.00',
        limit: null,
        remaining: null,
        pct_used: null,
        status: 'no_limit',
      },
    ],
  },
  income_sources: [
    { category: cat('c-sal', 'Salary', 'income'), amount: '142000.00', prev_amount: '142000.00' },
    { category: cat('c-int', 'Interest', 'income'), amount: '702.04', prev_amount: '697.15' },
  ],
  accounts: [
    {
      account: { id: 'a-card', name: 'Credit card', type: 'credit_card', masked_number: null },
      income: '0.00',
      spending: '32750.04',
      invested: '0.00',
      net: '-32750.04',
    },
    {
      account: { id: 'a-sav', name: 'Savings account', type: 'savings', masked_number: null },
      income: '142702.04',
      spending: '63290.34',
      invested: '15000.00',
      net: '64411.70',
    },
  ],
}

const row = (
  id: string,
  description: string,
  amount: string,
  extra: Partial<TxnList['items'][number]> = {},
) => ({
  id,
  account_id: 'a-sav',
  import_id: null,
  date: '2026-09-28',
  description,
  description_norm: description,
  payee_label: null,
  amount,
  direction: 'debit' as const,
  category_id: 'c-food',
  type: 'expense' as const,
  categorised_by: 'manual' as const,
  rule_id: null,
  needs_review: false,
  notes: null,
  account_name: 'Savings account',
  category_name: 'Dining out',
  ...extra,
})

export const TXNS: TxnList = {
  items: [
    row('t1', 'INTEREST CREDITED', '702.04', {
      type: 'income',
      direction: 'credit',
      category_name: 'Interest',
    }),
    row('t2', 'POS 4471 MERCHANT', '2350.00', {
      needs_review: true,
      category_name: 'Uncategorized',
      account_name: 'Credit card',
    }),
    row('t3', 'CC BILL PAYMENT', '24966.75', { type: 'transfer', category_name: 'Card payment' }),
  ],
  next_cursor: null,
  total: 3,
  sums: { income: '702.04', spending: '2350.00', invested: '0.00', transfers: '24966.75' },
}
