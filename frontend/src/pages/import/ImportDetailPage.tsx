import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { errorMessage } from '../../api/client'
import {
  useAccounts,
  useCommitImport,
  useDiscardImport,
  useImport,
  useParsers,
  useReparseImport,
  useRollbackImport,
  useUpdateStagedRow,
} from '../../api/hooks'
import {
  ACCOUNT_TYPE_LABELS,
  type AccountDraft,
  type AccountType,
  type ImportResource,
} from '../../api/types'
import { Card, ErrorText, PageHeader } from '../../components/ui'
import { formatDate, formatMoney } from '../../lib/format'
import { Amount, PasswordForm, StatusBadge } from './parts'
import { isInFlight, statusLine } from './status'
import styles from './import.module.css'

export function ImportDetailPage() {
  const { id } = useParams()
  const query = useImport(id)
  const resource = query.data

  if (query.isPending) return <p className={styles.muted}>Loading…</p>
  if (query.isError || !resource)
    return (
      <>
        <PageHeader title="Import" />
        <ErrorText>{errorMessage(query.error)}</ErrorText>
        <Link to="/import">Back to imports</Link>
      </>
    )

  return (
    <>
      <PageHeader
        title={resource.file_name}
        subtitle={
          <>
            <StatusBadge status={resource.status} /> <Link to="/import">All imports</Link>
          </>
        }
      />
      <div className={styles.stack}>
        {isInFlight(resource) && (
          <Card>
            <p className={styles.muted} role="status">
              {statusLine(resource)}
            </p>
          </Card>
        )}
        {resource.status === 'needs_password' && (
          <Card title="Password needed">
            <PasswordForm resource={resource} />
          </Card>
        )}
        {resource.status === 'failed' && <FailedCard resource={resource} />}
        {resource.status === 'parsed' && <Preview resource={resource} />}
        {resource.status === 'committed' && <CommittedCard resource={resource} />}
        {(resource.status === 'rolled_back' || resource.status === 'discarded') && (
          <Card>
            <p className={styles.muted}>{statusLine(resource)}</p>
          </Card>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------- failed

function FailedCard({ resource }: { resource: ImportResource }) {
  return (
    <Card title="This statement couldn't be imported">
      <p className={styles.error} role="alert">
        {resource.error ?? 'Unknown error'}
      </p>
      <ParserChooser resource={resource} />
      <DiscardButton id={resource.id} />
    </Card>
  )
}

// ---------------------------------------------------------------- preview

function ReconciliationBanner({ resource }: { resource: ImportResource }) {
  const recon = resource.reconciliation
  if (!recon) return null
  const kind = recon.balance_kind === 'liability' ? ' (credit card: what you owe)' : ''
  if (recon.status === 'ok')
    return (
      <div className={`${styles.banner} ${styles.ok}`} role="status">
        <p className={styles.bannerTitle}>Balances reconcile{kind}</p>
        <p className={styles.muted}>
          Opening {formatMoney(resource.opening)} + movements = closing{' '}
          {formatMoney(resource.closing)}.
        </p>
      </div>
    )
  if (recon.status === 'unverifiable')
    return (
      <div className={`${styles.banner} ${styles.unverifiable}`} role="status">
        <p className={styles.bannerTitle}>Can&apos;t check the balances</p>
        <p className={styles.muted}>
          The statement doesn&apos;t show an opening and closing balance. Check the rows below
          before committing.
        </p>
      </div>
    )
  return (
    <div className={`${styles.banner} ${styles.mismatch}`} role="alert">
      <p className={styles.bannerTitle}>The statement doesn&apos;t add up{kind}</p>
      {recon.expected_closing && (
        <p>
          Expected closing {formatMoney(recon.expected_closing)}, statement says{' '}
          {formatMoney(resource.closing)} (difference {formatMoney(recon.diff)}).
        </p>
      )}
      {recon.first_break_seq !== null && (
        <p>
          The running balance first breaks at{' '}
          <a href={`#row-${recon.first_break_seq}`}>row {recon.first_break_seq + 1}</a>: a row may
          have been misread. Try another parser, or commit anyway if you&apos;re sure.
        </p>
      )}
    </div>
  )
}

function ParserChooser({ resource }: { resource: ImportResource }) {
  const parsers = useParsers()
  const reparse = useReparseImport()
  const [parserId, setParserId] = useState(resource.parser?.id ?? '')
  const options = parsers.data?.items ?? []
  const confidence = new Map(resource.candidates.map((c) => [c.id, c.confidence]))

  return (
    <div className={styles.inlineForm}>
      <label className={styles.field}>
        Parser
        <select value={parserId} onChange={(e) => setParserId(e.target.value)}>
          <option value="" disabled>
            Choose a parser
          </option>
          {options.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {confidence.has(p.id) ? ` (match ${Math.round(confidence.get(p.id)! * 100)}%)` : ''}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={!parserId || parserId === resource.parser?.id || reparse.isPending}
        onClick={() => reparse.mutate({ id: resource.id, body: { parser_id: parserId } })}
      >
        Read again with this parser
      </button>
      {reparse.isError && <p className={styles.error}>{errorMessage(reparse.error)}</p>}
    </div>
  )
}

const NEW_ACCOUNT = '__new__'

function AccountChooser({
  resource,
  draft,
  onDraft,
}: {
  resource: ImportResource
  draft: AccountDraft | null
  onDraft: (draft: AccountDraft | null) => void
}) {
  const accounts = useAccounts()
  const reparse = useReparseImport()
  const value = resource.account?.id ?? (draft ? NEW_ACCOUNT : '')

  function choose(choice: string) {
    if (choice === NEW_ACCOUNT) {
      onDraft(resource.account_suggestion?.create ?? { name: '', type: 'savings' })
    } else if (choice) {
      onDraft(null)
      // An account change is applied at once: duplicates and reconciliation depend on it.
      reparse.mutate({ id: resource.id, body: { account_id: choice } })
    }
  }

  return (
    <div className={styles.grid}>
      <label className={styles.field}>
        Account
        <select value={value} onChange={(e) => choose(e.target.value)}>
          <option value="" disabled>
            Choose the account
          </option>
          {(accounts.data ?? [])
            .filter((a) => a.active || a.id === resource.account?.id)
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.masked_number ? ` ••${a.masked_number}` : ''}
              </option>
            ))}
          <option value={NEW_ACCOUNT}>Create a new account…</option>
        </select>
      </label>
      {draft && (
        <>
          <label className={styles.field}>
            New account name
            <input
              value={draft.name}
              maxLength={80}
              required
              onChange={(e) => onDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label className={styles.field}>
            Type
            <select
              value={draft.type}
              onChange={(e) => onDraft({ ...draft, type: e.target.value as AccountType })}
            >
              {Object.entries(ACCOUNT_TYPE_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {reparse.isError && <p className={styles.error}>{errorMessage(reparse.error)}</p>}
    </div>
  )
}

function PreviewTable({ resource }: { resource: ImportResource }) {
  const update = useUpdateStagedRow()
  const breakSeq = resource.reconciliation?.first_break_seq ?? null
  const rows = resource.rows ?? []

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} aria-label="Preview">
        <thead>
          <tr>
            <th>Import</th>
            <th>Date</th>
            <th>Description</th>
            <th className={styles.num}>Amount</th>
            <th className={`${styles.num} ${styles.hideNarrow}`}>Balance</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const classes = [
              row.duplicate ? styles.duplicate : !row.include ? styles.excluded : '',
              row.seq === breakSeq ? styles.breakRow : '',
            ].join(' ')
            return (
              <tr key={row.seq} id={`row-${row.seq}`} className={classes}>
                <td>
                  <input
                    type="checkbox"
                    checked={row.include}
                    disabled={row.duplicate || update.isPending}
                    aria-label={`Import row ${row.seq + 1}`}
                    onChange={(e) =>
                      update.mutate({ id: resource.id, seq: row.seq, include: e.target.checked })
                    }
                  />
                </td>
                <td className={styles.date}>{formatDate(row.date)}</td>
                <td className={styles.description}>
                  {row.description}
                  {(row.duplicate || row.possible_duplicate || row.seq === breakSeq) && (
                    <span className={styles.tags}>
                      {row.duplicate && <span className={styles.badge}>Already imported</span>}
                      {row.possible_duplicate && (
                        <span className={`${styles.badge} ${styles.attention}`}>
                          Possible duplicate
                        </span>
                      )}
                      {row.seq === breakSeq && (
                        <span className={`${styles.badge} ${styles.bad}`}>Balance breaks here</span>
                      )}
                    </span>
                  )}
                </td>
                <td className={styles.num}>
                  <Amount value={row.amount} direction={row.direction} />
                </td>
                <td className={`${styles.num} ${styles.hideNarrow}`}>
                  {formatMoney(row.balance_after)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {update.isError && <ErrorText>{errorMessage(update.error)}</ErrorText>}
    </div>
  )
}

function Preview({ resource }: { resource: ImportResource }) {
  const commit = useCommitImport()
  const [draft, setDraft] = useState<AccountDraft | null>(
    resource.account ? null : (resource.account_suggestion?.create ?? null),
  )
  const [override, setOverride] = useState(false)
  const mismatch = resource.reconciliation?.status === 'mismatch'
  const counts = resource.counts
  const needsAccount = !resource.account && !(draft && draft.name.trim())

  return (
    <>
      <ReconciliationBanner resource={resource} />
      {resource.file_already_imported && (
        <Card>
          <p className={styles.muted}>
            You already imported this exact file on{' '}
            {formatDate(resource.file_already_imported.committed_at)}. Its rows are marked as
            already imported below.
          </p>
        </Card>
      )}
      <Card title="Statement">
        <div className={styles.stack}>
          <p className={styles.muted}>
            {resource.institution ?? 'Unknown bank'} ·{' '}
            {resource.period
              ? `${formatDate(resource.period.start)} – ${formatDate(resource.period.end)}`
              : 'period unknown'}{' '}
            · read by {resource.parser?.id ?? 'unknown parser'}
            {resource.parser?.confidence != null &&
              ` (match ${Math.round(resource.parser.confidence * 100)}%)`}
          </p>
          <AccountChooser resource={resource} draft={draft} onDraft={setDraft} />
          <details>
            <summary>Wrong rows? Choose another parser</summary>
            <ParserChooser resource={resource} />
          </details>
          {resource.warnings.length > 0 && (
            <ul className={styles.warnings}>
              {resource.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card title="Preview">
        {counts && (
          <ul className={styles.counts} aria-label="Summary">
            <li>{counts.new} new</li>
            <li>{counts.duplicate} already imported</li>
            <li>{counts.excluded} excluded</li>
            {counts.possible_duplicate > 0 && (
              <li>{counts.possible_duplicate} possible duplicates</li>
            )}
          </ul>
        )}
        <PreviewTable resource={resource} />
      </Card>

      <Card>
        <div className={styles.stack}>
          {mismatch && (
            <label className={styles.actions}>
              <input
                type="checkbox"
                checked={override}
                onChange={(e) => setOverride(e.target.checked)}
              />
              Commit even though the balances don&apos;t add up (this is recorded)
            </label>
          )}
          <div className={styles.actions}>
            <button
              className="primary"
              disabled={commit.isPending || needsAccount || (mismatch && !override)}
              onClick={() =>
                commit.mutate({
                  id: resource.id,
                  body: {
                    override_reconciliation: override,
                    create_account: resource.account ? null : draft,
                  },
                })
              }
            >
              Commit {counts ? counts.new : ''} transactions
            </button>
            <DiscardButton id={resource.id} />
          </div>
          {needsAccount && <p className={styles.muted}>Choose or create the account first.</p>}
          <ErrorText>{commit.isError ? errorMessage(commit.error) : null}</ErrorText>
        </div>
      </Card>
    </>
  )
}

function DiscardButton({ id }: { id: string }) {
  const discard = useDiscardImport()
  const navigate = useNavigate()
  return (
    <>
      <button
        type="button"
        disabled={discard.isPending}
        onClick={() => {
          if (window.confirm('Discard this import? The uploaded file is deleted.'))
            discard.mutate(id, { onSuccess: () => navigate('/import') })
        }}
      >
        Discard
      </button>
      {discard.isError && <p className={styles.error}>{errorMessage(discard.error)}</p>}
    </>
  )
}

// ---------------------------------------------------------------- committed

function CommittedCard({ resource }: { resource: ImportResource }) {
  const rollback = useRollbackImport()
  return (
    <Card title="Imported">
      <p role="status">
        {resource.result?.inserted ?? 0} transactions added to{' '}
        {resource.account?.name ?? 'the account'}; {resource.result?.skipped ?? 0} already imported,{' '}
        {resource.result?.excluded ?? 0} excluded.
      </p>
      {resource.reconciliation?.overridden && (
        <p className={styles.muted}>Committed with a reconciliation override.</p>
      )}
      <div className={styles.actions}>
        <Link to="/import">Import another statement</Link>
        <button
          type="button"
          className="danger"
          disabled={rollback.isPending}
          onClick={() => {
            if (window.confirm('Roll back this import? Its transactions are removed.'))
              rollback.mutate(resource.id)
          }}
        >
          Roll back
        </button>
      </div>
      <ErrorText>{rollback.isError ? errorMessage(rollback.error) : null}</ErrorText>
    </Card>
  )
}
