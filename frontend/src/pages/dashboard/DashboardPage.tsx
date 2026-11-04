import { Link } from 'react-router'
import { errorMessage } from '../../api/client'
import { useDashboard, useDashboardMonths } from '../../api/hooks'
import { CashflowChart } from '../../charts/CashflowChart'
import { Card, ErrorText } from '../../components/ui'
import { useUrlState } from '../../lib/useUrlState'
import { MonthSelect, ReviewBanner, Takeaway } from './DashboardHeader'
import { HeadlineCards } from './HeadlineCards'
import { AccountTable, CategoryLimits, IncomeBySource } from './Sections'
import { TransactionsPanel } from './TransactionsPanel'
import styles from './dashboard.module.css'

function scrollToTransactions() {
  document.getElementById('transactions')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

/** The approved dashboard (docs/handover/design/dashboard-mockup.png), section by section. */
export function DashboardPage() {
  const [state, update] = useUrlState()
  const dashboard = useDashboard(state.month)
  const months = useDashboardMonths()
  const data = dashboard.data

  if (dashboard.isPending) return <p className={styles.muted}>Loading…</p>
  if (dashboard.isError)
    return (
      <>
        <h1>Personal finance</h1>
        <ErrorText>{errorMessage(dashboard.error)}</ErrorText>
      </>
    )
  if (!data)
    return (
      <>
        <h1 className={styles.title}>Personal finance</h1>
        <Card>
          <p>
            No transactions yet. <Link to="/import">Import a statement</Link> to see your income,
            spending and savings here.
          </p>
          <p className={styles.muted}>
            To look around with made-up data first, run <code>finboard demo-data</code>.
          </p>
        </Card>
      </>
    )

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Personal finance</h1>
          <Takeaway data={data} />
        </div>
        <MonthSelect
          months={months.data ?? [data.month]}
          value={state.month ?? data.month}
          onChange={(month) => update({ month })}
        />
      </header>

      <ReviewBanner
        count={data.review_count}
        month={data.month}
        onShow={() => {
          update({ review: true })
          scrollToTransactions()
        }}
      />

      <HeadlineCards data={data} />

      <Card title="Cash flow by month">
        <p className={styles.note}>
          Income and spending each month, with net saving (income minus spending). Click a month to
          look at it.
        </p>
        <CashflowChart
          months={data.cashflow}
          selected={data.month}
          onSelect={(month) => update({ month })}
        />
      </Card>

      <div className={styles.twoUp}>
        <Card title="Spending by category vs limit">
          <p className={styles.note}>
            Each bar is one category's monthly limit: green while there is money left, red once it
            goes over (the tick marks the limit). Click one to see its transactions.
          </p>
          <CategoryLimits
            data={data}
            selected={state.category}
            onSelect={(category) => {
              update({ category })
              if (category) scrollToTransactions()
            }}
          />
        </Card>
        <Card title="Income by source">
          <p className={styles.note}>Selected month; the thin line is the month before.</p>
          <IncomeBySource data={data} />
        </Card>
      </div>

      <Card title="By account">
        <p className={styles.note}>
          Selected month. Card bill payments and moves between your own accounts are left out so
          nothing counts twice.
        </p>
        <AccountTable data={data} />
      </Card>

      <section
        id="transactions"
        className={styles.transactions}
        aria-labelledby="transactions-title"
      >
        <Card>
          <h2 id="transactions-title" className={styles.cardTitle}>
            Transactions
          </h2>
          <p className={styles.note}>
            Every entry in the selected month. A yellow edge marks one that still needs a category.
          </p>
          <TransactionsPanel month={state.month ?? data.month} state={state} update={update} />
        </Card>
      </section>
    </div>
  )
}
