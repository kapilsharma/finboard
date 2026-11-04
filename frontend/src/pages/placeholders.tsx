import { Link } from 'react-router'
import { ComingSoon, PageHeader } from '../components/ui'

export function DashboardPage() {
  return (
    <ComingSoon title="Personal finance" milestone="M4">
      Income, spending, savings rate, budgets and per-account totals will appear here once
      statements are imported. Start by <Link to="/import">importing a statement</Link>.
    </ComingSoon>
  )
}

export function TransactionsPage() {
  return (
    <ComingSoon title="Transactions" milestone="M4">
      Every imported transaction, with search, filters and sorting.
    </ComingSoon>
  )
}

export function ReviewPage() {
  return (
    <ComingSoon title="Review" milestone="M3">
      Transactions no rule could categorise, and suggested transfers between your own accounts.
    </ComingSoon>
  )
}

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Link to="/">Back to the dashboard</Link>
    </>
  )
}
