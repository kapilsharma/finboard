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
export type Txn = Schemas['TxnOut']
export type TxnUpdate = Schemas['TxnUpdate']
export type MatchKind = Schemas['MatchKind']
export type Direction = Schemas['Direction']
export type Rule = Schemas['RuleOut']
export type RuleCreate = Schemas['RuleCreate']
export type RuleUpdate = Schemas['RuleUpdate']
export type RuleTestBody = Schemas['RuleTestIn']
export type RuleTest = Schemas['RuleTestOut']
export type RuleApplyBody = Schemas['RuleApplyIn']
export type RulePackImportResult = Schemas['RulePackImportOut']
export type RuleSuggestion = Schemas['RuleSuggestionOut']
export type SuggestRule = Schemas['SuggestRuleOut']
export type ReviewGroup = Schemas['ReviewGroupOut']
export type ReviewGroups = Schemas['ReviewGroupsOut']
export type Transfer = Schemas['TransferOut']
export type TransferStatus = Schemas['TransferStatus']
export type JobAccepted = Schemas['JobAccepted']
export type Dashboard = Schemas['DashboardOut']
export type CategoryLimit = Schemas['CategoryLimitOut']
export type LimitsSummary = Schemas['LimitsSummaryOut']
export type IncomeSource = Schemas['IncomeSourceOut']
export type AccountTotals = Schemas['AccountTotalsOut']
export type CashflowMonth = Schemas['CashflowMonthOut']
export type TxnListItem = Schemas['TxnListItem']
export type TxnList = Schemas['TxnListOut']
export type Meta = Schemas['MetaOut']
export type MetricDefinition = Schemas['MetricDefinitionOut']

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

export const MATCH_KIND_LABELS: Record<MatchKind, string> = {
  contains: 'contains',
  starts_with: 'starts with',
  equals: 'is exactly',
  regex: 'matches regex',
}

export const DIRECTION_LABELS: Record<Direction, string> = {
  debit: 'Money out',
  credit: 'Money in',
}
