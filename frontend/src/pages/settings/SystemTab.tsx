import { useJob, usePingWorker } from '../../api/hooks'
import { errorMessage } from '../../api/client'
import { Card, ErrorText } from '../../components/ui'
import styles from './settings.module.css'

/** Checks the background-job pipeline end to end: API → Redis → worker → database. */
export function SystemTab() {
  const ping = usePingWorker()
  const job = useJob(ping.data?.id)
  const status = job.data?.status ?? ping.data?.status

  return (
    <Card title="Background worker">
      <p className={styles.muted}>
        Statement imports and other slow work run in a separate worker process. Use this to check
        that it is running.
      </p>
      <button
        onClick={() => ping.mutate()}
        disabled={ping.isPending || status === 'queued' || status === 'running'}
      >
        Check worker
      </button>
      <p className={styles.status} role="status">
        {status === 'queued' && 'Waiting for the worker…'}
        {status === 'running' && 'Worker is running the check…'}
        {status === 'succeeded' && <span className={styles.good}>Worker is running.</span>}
        {status === 'failed' && (
          <span className={styles.bad}>The check failed: {job.data?.error ?? 'unknown error'}</span>
        )}
      </p>
      <ErrorText>{ping.isError ? errorMessage(ping.error) : null}</ErrorText>
    </Card>
  )
}
