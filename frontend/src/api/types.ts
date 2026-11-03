import type { components } from './schema'

type Schemas = components['schemas']

export type Me = Schemas['MeOut']
export type Account = Schemas['AccountOut']
export type AccountCreate = Schemas['AccountCreate']
export type AccountUpdate = Schemas['AccountUpdate']
export type AccountType = Schemas['AccountType']
export type Category = Schemas['CategoryOut']
export type CategoryCreate = Schemas['CategoryCreate']
export type CategoryUpdate = Schemas['CategoryUpdate']
export type CategoryType = Schemas['CategoryType']
export type Job = Schemas['JobOut']
export type Preferences = Schemas['Preferences']
export type Theme = Schemas['Theme']

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  savings: 'Savings',
  current: 'Current',
  credit_card: 'Credit card',
  loan: 'Loan',
  mutual_fund: 'Mutual fund',
  insurance: 'Insurance',
  cash: 'Cash',
  other: 'Other',
}

export const CATEGORY_TYPE_LABELS: Record<CategoryType, string> = {
  income: 'Income',
  expense: 'Expense',
  investment: 'Investment',
  transfer: 'Transfer',
}
