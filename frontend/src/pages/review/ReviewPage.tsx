import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { errorMessage } from '../../api/client'
import {
  useAccounts,
  useConfirmTransfer,
  useRejectTransfer,
  useReviewGroups,
  useSuggestTransfers,
  useTransfers,
} from '../../api/hooks'
import type { ReviewGroup, RuleSuggestion, Transfer, Txn } from '../../api/types'
import { CategoriseDialog } from '../../components/categorise/CategoriseDialog'
import { useJobRunner } from '../../components/categorise/useJobRunner'
import { Card, ErrorText, PageHeader } from '../../components/ui'
import { formatDate, formatMoney } from '../../lib/format'
import styles from './review.module.css'

const PREVIEW_ROWS = 5

type Dialog = { transactions: Txn[]; suggestion: RuleSuggestion | null } | null

function Amount({ txn }: { txn: Pick<Txn, 'amount' | 'direction'> }) {
  const credit = txn.direction === 'credit'
  return (
    <span className={credit ? styles.credit : undefined}>
      <span className="visually-hidden">{credit ? 'In: ' : 'Out: '}</span>
      {credit ? '+' : '−'}
      {formatMoney(txn.amount)}
    </span>
  )
}

function GroupCard({
  group,
  accountName,
  onCategorise,
}: {
  group: ReviewGroup
  accountName: (id: string) => string
  onCategorise: (dialog: NonNullable<Dialog>) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const rows = expanded ? group.transactions : group.transactions.slice(0, PREVIEW_ROWS)
  const label = group.suggestion ? group.key : 'Other transactions'

  return (
    <section className={styles.group} aria-label={label}>
      <div className={styles.groupHeader}>
        <div>
          <h3 className={styles.groupTitle}>{label}</h3>
          <p className={styles.muted}>
            {group.count} transaction{group.count === 1 ? '' : 's'}
            {group.debits !== '0.00' && ` · ${formatMoney(group.debits)} out`}
            {group.credits !== '0.00' && ` · ${formatMoney(group.credits)} in`}
          </p>
        </div>
        {group.count > 1 && (
          <button
            className="primary"
            onClick={() =>
              onCategorise({ transactions: group.transactions, suggestion: group.suggestion })
            }
          >
            Categorise all {group.count}
          </button>
        )}
      </div>
      <ul className={styles.rows}>
        {rows.map((txn) => (
          <li key={txn.id} className={styles.row}>
            <span className={styles.date}>{formatDate(txn.date)}</span>
            <span className={styles.description}>
              {txn.description}
              <span className={styles.account}>{accountName(txn.account_id)}</span>
            </span>
            <span className={styles.amount}>
              <Amount txn={txn} />
            </span>
            <button
              className="link"
              onClick={() => onCategorise({ transactions: [txn], suggestion: group.suggestion })}
              aria-label={`Categorise ${txn.description}`}
            >
              Categorise
            </button>
          </li>
        ))}
      </ul>
      {group.count > PREVIEW_ROWS && (
        <button className="link" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? 'Show fewer' : `Show all ${group.count}`}
        </button>
      )}
    </section>
  )
}

function TransferSideView({ side, label }: { side: Transfer['debit']; label: string }) {
  return (
    <div className={styles.side}>
      <span className={styles.sideLabel}>{label}</span>
      <strong>{side.account.name}</strong>
      <span className={styles.muted}>{formatDate(side.transaction.date)}</span>
      <span className={styles.description}>{side.transaction.description}</span>
    </div>
  )
}

function TransfersCard() {
  const transfers = useTransfers('suggested')
  const confirm = useConfirmTransfer()
  const reject = useRejectTransfer()
  const suggest = useSuggestTransfers()
  const runner = useJobRunner()
  const items = transfers.data ?? []

  async function lookAgain() {
    const accepted = await suggest.mutateAsync()
    runner.track(accepted.job.id)
  }

  return (
    <Card title="Possible transfers">
      <div className={styles.cardToolbar}>
        <p className={styles.muted}>
          Money that left one of your accounts and arrived in another. Confirmed transfers count as
          neither spending nor income.
        </p>
        <button onClick={lookAgain} disabled={suggest.isPending || runner.running}>
          {runner.running ? 'Looking…' : 'Look for transfers'}
        </button>
      </div>
      <ErrorText>
        {transfers.isError
          ? errorMessage(transfers.error)
          : confirm.isError
            ? errorMessage(confirm.error)
            : reject.isError
              ? errorMessage(reject.error)
              : suggest.isError
                ? errorMessage(suggest.error)
                : null}
      </ErrorText>
      {transfers.isSuccess && items.length === 0 && (
        <p className={styles.muted}>No transfers to check.</p>
      )}
      <ul className={styles.transfers}>
        {items.map((pair) => {
          const name = `${formatMoney(pair.debit.transaction.amount)} from ${pair.debit.account.name} to ${pair.credit.account.name}`
          return (
            <li key={pair.id} className={styles.transfer} aria-label={name}>
              <div className={styles.transferAmount}>
                {formatMoney(pair.debit.transaction.amount)}
                {pair.days_apart > 0 && (
                  <span className={styles.muted}>
                    {' '}
                    · {pair.days_apart} day{pair.days_apart === 1 ? '' : 's'} apart
                  </span>
                )}
              </div>
              <div className={styles.sides}>
                <TransferSideView side={pair.debit} label="From" />
                <span className={styles.arrow} aria-hidden>
                  →
                </span>
                <TransferSideView side={pair.credit} label="To" />
              </div>
              <div className={styles.transferActions}>
                <button
                  className="primary"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate(pair.id)}
                  aria-label={`Confirm transfer: ${name}`}
                >
                  Confirm transfer
                </button>
                <button
                  disabled={reject.isPending}
                  onClick={() => reject.mutate(pair.id)}
                  aria-label={`Not a transfer: ${name}`}
                >
                  Not a transfer
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export function ReviewPage() {
  const [params, setParams] = useSearchParams()
  const month = params.get('month')
  const groups = useReviewGroups(month)
  const accounts = useAccounts()
  const [dialog, setDialog] = useState<Dialog>(null)
  const names = new Map((accounts.data ?? []).map((a) => [a.id, a.name]))
  const total = groups.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Review"
        subtitle={
          groups.isSuccess
            ? total === 0
              ? 'Nothing needs a category.'
              : `${total} transaction${total === 1 ? '' : 's'} need${total === 1 ? 's' : ''} a category.`
            : undefined
        }
      />
      <div className={styles.stack}>
        <Card title="Needs category">
          <div className={styles.cardToolbar}>
            <p className={styles.muted}>
              Grouped by the merchant a rule would look for. Categorise a group once and make it a
              rule, so next month's statements are categorised for you. Manage rules in{' '}
              <Link to="/settings/rules">Settings › Rules</Link>.
            </p>
            <label className={styles.monthFilter}>
              Month
              <input
                type="month"
                value={month ?? ''}
                onChange={(e) => {
                  const next = new URLSearchParams(params)
                  if (e.target.value) next.set('month', e.target.value)
                  else next.delete('month')
                  setParams(next, { replace: true })
                }}
              />
            </label>
          </div>
          {groups.isPending && <p className={styles.muted}>Loading…</p>}
          <ErrorText>{groups.isError ? errorMessage(groups.error) : null}</ErrorText>
          {groups.isSuccess && total === 0 && (
            <p className={styles.muted}>
              All caught up{month ? ' for this month' : ''}.{' '}
              {!month && <Link to="/import">Import a statement</Link>}
            </p>
          )}
          {groups.data?.groups.map((group) => (
            <GroupCard
              key={group.key}
              group={group}
              accountName={(id) => names.get(id) ?? ''}
              onCategorise={setDialog}
            />
          ))}
        </Card>
        <TransfersCard />
      </div>
      {dialog && (
        <CategoriseDialog
          transactions={dialog.transactions}
          suggestion={dialog.suggestion}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  )
}
