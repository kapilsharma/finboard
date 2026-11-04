import { errorMessage } from '../../api/client'
import { useTransactionList } from '../../api/hooks'
import { TransactionFilters } from '../../components/transactions/TransactionFilters'
import { TransactionsTable, type SortKey } from '../../components/transactions/TransactionsTable'
import { ErrorText } from '../../components/ui'
import type { UrlState } from '../../lib/useUrlState'
import styles from './dashboard.module.css'

type Update = (changes: Partial<Record<keyof UrlState, string | boolean | null>>) => void

/** Every transaction in the selected month, filtered and sorted from the URL. */
export function TransactionsPanel({
  month,
  state,
  update,
}: {
  month: string
  state: UrlState
  update: Update
}) {
  const sort = (state.sort ?? 'date') as SortKey
  const order = state.order ?? 'desc'
  const list = useTransactionList(
    {
      month,
      q: state.q,
      account: state.account,
      category: state.category,
      review: state.review,
      sort,
      order,
    },
    { pageSize: 200 },
  )
  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const total = list.data?.pages[0]?.total ?? 0

  return (
    <>
      <TransactionFilters state={state} update={update} />
      <ErrorText>{list.isError ? errorMessage(list.error) : null}</ErrorText>
      {list.isSuccess && total === 0 && (
        <p className={styles.muted}>No transactions match these filters.</p>
      )}
      {items.length > 0 && (
        <TransactionsTable
          items={items}
          sort={sort}
          order={order}
          onSort={(key, next) => {
            const isDefault = key === 'date' && next === 'desc'
            update({ sort: isDefault ? null : key, order: isDefault ? null : next })
          }}
        />
      )}
      {list.hasNextPage && (
        <button
          type="button"
          className={styles.more}
          onClick={() => void list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
        >
          Show more ({items.length} of {total})
        </button>
      )}
    </>
  )
}
