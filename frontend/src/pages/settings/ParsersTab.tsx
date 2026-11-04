import { errorMessage } from '../../api/client'
import { useParsers } from '../../api/hooks'
import { Card, ErrorText } from '../../components/ui'
import styles from './settings.module.css'

/** Installed statement parsers (read-only in M2; enabling per user arrives in M5). */
export function ParsersTab() {
  const parsers = useParsers()

  return (
    <div className={styles.stack}>
      <Card title="Statement parsers">
        <p className={styles.muted}>
          Each parser reads one bank&apos;s statement layout. Finboard picks the best match for
          every file; a fallback parser is used only when no bank-specific one recognises it.
        </p>
        {parsers.isPending && <p className={styles.muted}>Loading…</p>}
        <ErrorText>{parsers.isError ? errorMessage(parsers.error) : null}</ErrorText>
        {parsers.data && (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Parser</th>
                  <th className={styles.hideNarrow}>Banks</th>
                  <th>Version</th>
                </tr>
              </thead>
              <tbody>
                {parsers.data.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name}
                      {p.fallback && <span className={styles.badge}>fallback</span>}
                      <div className={styles.muted}>
                        <code>{p.id}</code>
                      </div>
                    </td>
                    <td className={styles.hideNarrow}>
                      {p.institutions.length ? p.institutions.join(', ') : 'Any'}
                    </td>
                    <td>{p.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {parsers.data && parsers.data.failures.length > 0 && (
        <Card title="Parsers that failed to load">
          <ul>
            {parsers.data.failures.map((f) => (
              <li key={f.source}>
                <code>{f.source}</code>: <span className={styles.bad}>{f.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
