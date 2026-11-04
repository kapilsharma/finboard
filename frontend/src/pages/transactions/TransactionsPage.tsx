import { useCallback } from 'react'
import { errorMessage } from '../../api/client'
import { useDashboardMonths, useTransactionList } from '../../api/hooks'
import { TransactionFilters } from '../../components/transactions/TransactionFilters'
import { TransactionsTable, type SortKey } from '../../components/transactions/TransactionsTable'
import { Card, ErrorText, PageHeader } from '../../components/ui'
import { formatMonth, formatRupees } from '../../lib/format'
import { useUrlState } from '../../lib/useUrlState'
import styles from './transactions-page.module.css'

/** Every transaction, any month or date range, virtualised and loaded a page at a time. */
export function TransactionsPage() {
  const [state, update] = useUrlState()
  const months = useDashboardMonths()
  const sort = (state.sort ?? 'date') as SortKey
  const order = state.order ?? 'desc'
  const range = state.from || state.to
  const list = useTransactionList(
    {
      month: range ? null : state.month,
      from: state.from,
      to: state.to,
      q: state.q,
      account: state.account,
      category: state.category,
      review: state.review,
      sort,
      order,
    },
    { pageSize: 100 },
  )
  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const first = list.data?.pages[0]
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <>
      <PageHeader title="Transactions" />
      <Card>
        <div className={styles.range}>
          <label className={styles.field}>
            Month
            <select
              value={range ? '' : (state.month ?? '')}
              onChange={(e) => update({ month: e.target.value || null, from: null, to: null })}
            >
              <option value="">{range ? 'Date range' : 'All months'}</option>
              {(months.data ?? []).map((m) => (
                <option key={m} value={m}>
                  {formatMonth(m)}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            From
            <input
              type="date"
              value={state.from ?? ''}
              onChange={(e) => update({ from: e.target.value || null, month: null })}
            />
          </label>
          <label className={styles.field}>
            To
            <input
              type="date"
              value={state.to ?? ''}
              onChange={(e) => update({ to: e.target.value || null, month: null })}
            />
          </label>
        </div>
        <TransactionFilters state={state} update={update} />
        <ErrorText>{list.isError ? errorMessage(list.error) : null}</ErrorText>
        {first && (
          <p className={styles.totals} role="status">
            {first.total} transaction{first.total === 1 ? '' : 's'} · income{' '}
            <b>{formatRupees(first.sums.income)}</b> · spending{' '}
            <b>{formatRupees(first.sums.spending)}</b> · invested{' '}
            <b>{formatRupees(first.sums.invested)}</b>
            {first.sums.transfers !== '0.00' && (
              <>
                {' '}
                · transfers <b>{formatRupees(first.sums.transfers)}</b> (not counted)
              </>
            )}
          </p>
        )}
        {list.isPending && <p className={styles.muted}>Loading…</p>}
        {list.isSuccess && items.length === 0 && (
          <p className={styles.muted}>No transactions match.</p>
        )}
        {items.length > 0 && (
          <TransactionsTable
            items={items}
            sort={sort}
            order={order}
            virtual
            onEndReached={loadMore}
            onSort={(key, next) => {
              const isDefault = key === 'date' && next === 'desc'
              update({ sort: isDefault ? null : key, order: isDefault ? null : next })
            }}
          />
        )}
        {isFetchingNextPage && <p className={styles.muted}>Loading more…</p>}
      </Card>
    </>
  )
}
