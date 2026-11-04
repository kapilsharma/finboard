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
export type ImportResource = Schemas['ImportOut']
export type ImportStatus = Schemas['ImportStatus']
export type ImportList = Schemas['ImportList']
export type StagedRow = Schemas['StagedRowOut']
export type AccountDraft = Schemas['AccountDraft']
export type CommitBody = Schemas['CommitIn']
export type ReparseBody = Schemas['ReparseIn']
export type Parser = Schemas['ParserOut']
export type ParserList = Schemas['ParserList']

/** Statuses during which the server is still working on an import. */
export const IMPORT_IN_FLIGHT: ReadonlySet<ImportStatus> = new Set([
  'uploaded',
  'queued',
  'processing',
])

export const IMPORT_STATUS_LABELS: Record<ImportStatus, string> = {
  uploaded: 'Waiting',
  queued: 'Queued',
  processing: 'Reading',
  needs_password: 'Needs password',
  parsed: 'Ready to review',
  committed: 'Imported',
  rolled_back: 'Rolled back',
  discarded: 'Discarded',
  failed: 'Failed',
}

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
