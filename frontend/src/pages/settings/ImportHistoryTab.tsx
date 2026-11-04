import { Link } from 'react-router'
import { errorMessage } from '../../api/client'
import { useImportHistory, useRollbackImport } from '../../api/hooks'
import { IMPORT_STATUS_LABELS } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { formatDate } from '../../lib/format'
import styles from './settings.module.css'

export function ImportHistoryTab() {
  const history = useImportHistory()
  const rollback = useRollbackImport()
  const items = history.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <Card title="Import history">
      {history.isPending && <p className={styles.muted}>Loading…</p>}
      <ErrorText>{history.isError ? errorMessage(history.error) : null}</ErrorText>
      {history.data && items.length === 0 && (
        <p className={styles.muted}>
          Nothing imported yet. <Link to="/import">Import a statement</Link>.
        </p>
      )}
      {items.length > 0 && (
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th className={styles.hideNarrow}>Period</th>
                <th>Status</th>
                <th className={styles.hideNarrow}>Rows</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link to={`/import/${item.id}`}>{item.file_name}</Link>
                    <div className={styles.muted}>
                      {formatDate(item.created_at)}
                      {item.account ? ` · ${item.account.name}` : ''}
                    </div>
                  </td>
                  <td className={styles.hideNarrow}>
                    {item.period
                      ? `${formatDate(item.period.start)} – ${formatDate(item.period.end)}`
                      : '—'}
                  </td>
                  <td>{IMPORT_STATUS_LABELS[item.status]}</td>
                  <td className={styles.hideNarrow}>
                    {item.result
                      ? `${item.result.inserted} added, ${item.result.skipped} skipped`
                      : (item.counts?.parsed ?? '—')}
                  </td>
                  <td className={styles.actions}>
                    {item.status === 'committed' && (
                      <button
                        className="link danger"
                        aria-label={`Roll back ${item.file_name}`}
                        disabled={rollback.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Roll back “${item.file_name}”? Its transactions are removed, except rows a later import also contains.`,
                            )
                          )
                            rollback.mutate(item.id)
                        }}
                      >
                        Roll back
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {history.hasNextPage && (
        <button onClick={() => history.fetchNextPage()} disabled={history.isFetchingNextPage}>
          Show older imports
        </button>
      )}
      <ErrorText>{rollback.isError ? errorMessage(rollback.error) : null}</ErrorText>
    </Card>
  )
}
