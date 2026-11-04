/** Small pieces shared by the import pages. */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { errorMessage } from '../../api/client'
import { useImport, useUnlockImport } from '../../api/hooks'
import { IMPORT_STATUS_LABELS, type ImportResource, type ImportStatus } from '../../api/types'
import { formatMoney } from '../../lib/format'
import { statusLine } from './status'
import styles from './import.module.css'

const BADGE_TONE: Partial<Record<ImportStatus, string>> = {
  needs_password: styles.attention,
  parsed: styles.attention,
  committed: styles.good,
  failed: styles.bad,
}

export function StatusBadge({ status }: { status: ImportStatus }) {
  return (
    <span className={`${styles.badge} ${BADGE_TONE[status] ?? ''}`}>
      {IMPORT_STATUS_LABELS[status]}
    </span>
  )
}

/** The statement password goes to `/unlock` only and is never stored (ADR-0027). */
export function PasswordForm({ resource }: { resource: ImportResource }) {
  const unlock = useUnlockImport()
  const [password, setPassword] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    unlock.mutate({ id: resource.id, password }, { onSuccess: () => setPassword('') })
  }

  return (
    <form onSubmit={submit} aria-label={`Unlock ${resource.file_name}`}>
      <div className={styles.inlineForm}>
        <label className={styles.field}>
          Statement password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="off"
            required
          />
        </label>
        <button type="submit" className="primary" disabled={unlock.isPending || !password}>
          Unlock
        </button>
      </div>
      {resource.error && <p className={styles.error}>{resource.error}</p>}
      {unlock.isError && <p className={styles.error}>{errorMessage(unlock.error)}</p>}
      <p className={styles.muted}>Used once to read this file. Finboard never saves it.</p>
    </form>
  )
}

/** One import with live status, the password prompt when needed, and where to go next. */
export function ImportListItem({ id, fallbackName }: { id: string; fallbackName?: string }) {
  const query = useImport(id)
  const resource = query.data
  const name = resource?.file_name ?? fallbackName ?? 'Statement'

  return (
    <li className={styles.item} aria-label={name}>
      <div className={styles.itemHead}>
        <span className={styles.fileName}>{name}</span>
        {resource && <StatusBadge status={resource.status} />}
        {resource?.status === 'parsed' && <Link to={`/import/${id}`}>Review and commit</Link>}
        {resource && ['failed', 'committed'].includes(resource.status) && (
          <Link to={`/import/${id}`}>Details</Link>
        )}
      </div>
      <p className={styles.muted} role="status">
        {resource ? statusLine(resource) : 'Uploading…'}
      </p>
      {resource?.status === 'needs_password' && <PasswordForm resource={resource} />}
    </li>
  )
}

export function Amount({ value, direction }: { value: string; direction: 'debit' | 'credit' }) {
  return direction === 'credit' ? (
    <span className={styles.credit}>+{formatMoney(value)}</span>
  ) : (
    <span>−{formatMoney(value)}</span>
  )
}
