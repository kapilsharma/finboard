import { useState } from 'react'
import { API_BASE, errorMessage } from '../../api/client'
import {
  useDeleteAll,
  useRefreshEverything,
  useStartDataImport,
  useStartExport,
} from '../../api/hooks'
import { useJobRunner } from '../../components/categorise/useJobRunner'
import { Card, ErrorText } from '../../components/ui'
import { formatBytes } from '../../lib/format'
import { SystemTab } from './SystemTab'
import styles from './settings.module.css'

const CONFIRMATION = 'DELETE ALL'

function JobStatusLine({
  runner,
  working,
  done,
}: {
  runner: ReturnType<typeof useJobRunner>
  working: string
  done: string
}) {
  if (!runner.job) return null
  return (
    <p role="status">
      {runner.running && working}
      {runner.job.status === 'succeeded' && <span className={styles.good}>{done}</span>}
      {runner.job.status === 'failed' && (
        <span className={styles.bad}>{runner.job.error ?? 'It failed.'}</span>
      )}
    </p>
  )
}

function ExportCard() {
  const start = useStartExport()
  const runner = useJobRunner()
  const size = Number(runner.job?.result?.size ?? 0)
  return (
    <Card title="Export">
      <div className={styles.dataSection}>
        <p className={styles.muted}>
          Everything you have in Finboard, as one zip: accounts, categories, rules, limits,
          transactions, import history and the archived statements (still protected by your
          bank&apos;s password). Keep it safe: anyone with the file can read your transactions.
        </p>
        <div className={styles.formActions}>
          <button
            onClick={async () => runner.track((await start.mutateAsync()).job.id)}
            disabled={start.isPending || runner.running}
          >
            Export all data
          </button>
          <a className={styles.buttonLink} href={`${API_BASE}/data/transactions.csv`} download>
            Download transactions (CSV)
          </a>
        </div>
        <JobStatusLine
          runner={runner}
          working="Preparing the export…"
          done={`Export ready (${formatBytes(size)}).`}
        />
        {runner.job?.status === 'succeeded' && (
          <a
            className={styles.buttonLink}
            href={`${API_BASE}/data/exports/${runner.job.id}`}
            download
          >
            Download the export
          </a>
        )}
        <ErrorText>{start.isError ? errorMessage(start.error) : null}</ErrorText>
      </div>
    </Card>
  )
}

function ImportCard() {
  const start = useStartDataImport()
  const runner = useJobRunner()
  const refresh = useRefreshEverything()
  const [file, setFile] = useState<File | null>(null)
  return (
    <Card title="Import an export">
      <div className={styles.dataSection}>
        <p className={styles.muted}>
          Restore a Finboard export, for example on a new computer. It only goes into an empty
          Finboard (no accounts, transactions or imports yet), and replaces its categories and
          rules.
        </p>
        <label className={styles.field}>
          Export file (.zip)
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <div className={styles.formActions}>
          <button
            onClick={async () => {
              if (!file) return
              runner.track((await start.mutateAsync(file)).job.id)
            }}
            disabled={!file || start.isPending || runner.running}
          >
            Import
          </button>
        </div>
        <JobStatusLine
          runner={runner}
          working="Checking and importing…"
          done="Imported. Everything is back."
        />
        {runner.job?.status === 'succeeded' && (
          <button className="link" onClick={refresh}>
            Refresh the app
          </button>
        )}
        <ErrorText>{start.isError ? errorMessage(start.error) : null}</ErrorText>
      </div>
    </Card>
  )
}

function DeleteAllCard() {
  const remove = useDeleteAll()
  const runner = useJobRunner()
  const refresh = useRefreshEverything()
  const [typed, setTyped] = useState('')
  return (
    <Card title="Delete all data">
      <div className={styles.dataSection}>
        <p>
          Deletes your accounts, transactions, imports, archived statements, rules, limits and
          settings. This can&apos;t be undone: export first if you might want them back. You get the
          default categories and starter rules again.
        </p>
        <label className={styles.field}>
          Type {CONFIRMATION} to confirm
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <div className={styles.formActions}>
          <button
            className={`danger ${styles.danger}`}
            disabled={typed !== CONFIRMATION || remove.isPending || runner.running}
            onClick={async () => {
              runner.track((await remove.mutateAsync(typed)).job.id)
              setTyped('')
            }}
          >
            Delete all my data
          </button>
        </div>
        <JobStatusLine runner={runner} working="Deleting…" done="All your data is deleted." />
        {runner.job?.status === 'succeeded' && (
          <button className="link" onClick={refresh}>
            Refresh the app
          </button>
        )}
        <ErrorText>{remove.isError ? errorMessage(remove.error) : null}</ErrorText>
      </div>
    </Card>
  )
}

/** Your data: export, import, CSV, delete-all, and the worker check (ARCHITECTURE §10). */
export function DataTab() {
  return (
    <div className={styles.stack}>
      <ExportCard />
      <ImportCard />
      <DeleteAllCard />
      <SystemTab />
    </div>
  )
}
