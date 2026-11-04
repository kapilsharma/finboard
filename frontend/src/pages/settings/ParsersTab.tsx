import { useState } from 'react'
import { errorMessage } from '../../api/client'
import { useParsers, useUpdateParser } from '../../api/hooks'
import type { Parser } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { ParserOptionsForm } from './ParserOptionsForm'
import styles from './settings.module.css'

function ParserRow({ parser }: { parser: Parser }) {
  const update = useUpdateParser()
  const [editing, setEditing] = useState(false)
  const hasOptions = Object.keys(parser.options_schema?.properties ?? {}).length > 0
  return (
    <tr className={parser.enabled ? undefined : styles.inactive}>
      <td>
        {parser.name}
        {parser.fallback && <span className={styles.badge}>fallback</span>}
        <div className={styles.muted}>
          <code>{parser.id}</code>
        </div>
        {editing && <ParserOptionsForm parser={parser} onDone={() => setEditing(false)} />}
        <ErrorText>{update.isError ? errorMessage(update.error) : null}</ErrorText>
      </td>
      <td className={styles.hideNarrow}>
        {parser.institutions.length ? parser.institutions.join(', ') : 'Any'}
      </td>
      <td>{parser.version}</td>
      <td className={styles.actions}>
        <label className={styles.checkboxField}>
          <input
            type="checkbox"
            checked={parser.enabled}
            disabled={update.isPending}
            onChange={(e) =>
              update.mutate({ id: parser.id, changes: { enabled: e.target.checked } })
            }
          />
          On<span className="visually-hidden">: {parser.name}</span>
        </label>
        {hasOptions && !editing && (
          <button
            className="link"
            onClick={() => setEditing(true)}
            aria-label={`Options for ${parser.name}`}
          >
            Options
          </button>
        )}
      </td>
    </tr>
  )
}

/** Installed statement parsers, with your choices: which ones detection may pick, and each
 *  one's options (ARCHITECTURE §8). */
export function ParsersTab() {
  const parsers = useParsers()

  return (
    <div className={styles.stack}>
      <Card title="Statement parsers">
        <p className={styles.muted}>
          Each parser reads one bank&apos;s statement layout. Finboard picks the best match for
          every file; a fallback parser is used only when no bank-specific one recognises it. Switch
          a parser off to keep it from being picked; you can still choose it by hand when re-parsing
          a statement.
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
                  <th>
                    <span className="visually-hidden">Settings</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {parsers.data.items.map((p) => (
                  <ParserRow key={p.id} parser={p} />
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
