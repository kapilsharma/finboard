import { useState } from 'react'
import { errorMessage } from '../../../api/client'
import { useApplyRules } from '../../../api/hooks'
import { Modal } from '../../../components/Modal'
import { useJobRunner } from '../../../components/categorise/useJobRunner'
import { ErrorText } from '../../../components/ui'
import { useCategoryNames } from '../../../components/useCategoryNames'
import styles from './rules.module.css'

interface Transition {
  from_category_id: string
  to_category_id: string
  count: number
}

/** Re-apply the rules to committed transactions: preview the changes (dry run), then apply. */
export function ReapplyDialog({ onClose }: { onClose: () => void }) {
  const [scope, setScope] = useState<'uncategorised' | 'all'>('uncategorised')
  const [includeManual, setIncludeManual] = useState(false)
  const apply = useApplyRules()
  const preview = useJobRunner()
  const real = useJobRunner()
  const names = useCategoryNames()

  async function run(dryRun: boolean) {
    const accepted = await apply.mutateAsync({
      scope,
      include_manual: includeManual,
      dry_run: dryRun,
    })
    ;(dryRun ? preview : real).track(accepted.job.id)
  }

  const result = preview.job?.status === 'succeeded' ? preview.job.result : null
  const changed = Number(result?.changed ?? 0)
  const transitions = (result?.transitions ?? []) as Transition[]

  return (
    <Modal title="Re-apply rules" onClose={onClose} wide>
      {!real.job && (
        <div className={styles.dialogBody}>
          <fieldset className={styles.choices} disabled={preview.running}>
            <legend>Which transactions?</legend>
            <label>
              <input
                type="radio"
                name="scope"
                checked={scope === 'uncategorised'}
                onChange={() => {
                  setScope('uncategorised')
                  preview.reset()
                }}
              />
              Only uncategorised ones
            </label>
            <label>
              <input
                type="radio"
                name="scope"
                checked={scope === 'all'}
                onChange={() => {
                  setScope('all')
                  preview.reset()
                }}
              />
              Also ones a rule categorised before (picks up rule edits and new order)
            </label>
            <label>
              <input
                type="checkbox"
                checked={includeManual}
                onChange={(e) => {
                  setIncludeManual(e.target.checked)
                  preview.reset()
                }}
              />
              Also change ones I categorised by hand, where a rule matches
            </label>
            <p className={styles.muted}>Confirmed transfers are never changed.</p>
          </fieldset>

          {result && (
            <div role="status" className={styles.preview}>
              {changed === 0 ? (
                <p>Nothing would change.</p>
              ) : (
                <>
                  <p>
                    {changed} transaction{changed === 1 ? '' : 's'} would change category:
                  </p>
                  <ul>
                    {transitions.slice(0, 12).map((t) => (
                      <li key={`${t.from_category_id}-${t.to_category_id}`}>
                        {t.count} × {names.get(t.from_category_id) ?? '?'} →{' '}
                        {names.get(t.to_category_id) ?? '?'}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
          {preview.running && <p role="status">Working out what would change…</p>}
          <ErrorText>
            {apply.isError
              ? errorMessage(apply.error)
              : preview.job?.status === 'failed'
                ? preview.job.error
                : null}
          </ErrorText>
          <div className={styles.actions}>
            {!result ? (
              <button
                className="primary"
                onClick={() => run(true)}
                disabled={apply.isPending || preview.running}
              >
                Preview changes
              </button>
            ) : (
              <button
                className="primary"
                onClick={() => run(false)}
                disabled={apply.isPending || changed === 0}
              >
                Apply {changed} change{changed === 1 ? '' : 's'}
              </button>
            )}
            <button onClick={onClose}>Cancel</button>
          </div>
        </div>
      )}
      {real.job && (
        <div className={styles.dialogBody}>
          <p role="status">
            {real.running && 'Applying…'}
            {real.job.status === 'succeeded' &&
              `Done: ${String(real.job.result?.changed ?? 0)} transactions changed.`}
            {real.job.status === 'failed' && (real.job.error ?? 'The job failed.')}
          </p>
          <div className={styles.actions}>
            <button className="primary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
