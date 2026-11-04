import { useState, type FormEvent } from 'react'
import { api, errorMessage } from '../../../api/client'
import {
  useAccounts,
  useApplyRules,
  useCreateRule,
  useTestRule,
  useUpdateRule,
} from '../../../api/hooks'
import {
  DIRECTION_LABELS,
  MATCH_KIND_LABELS,
  type Direction,
  type MatchKind,
  type Rule,
  type RuleTest,
} from '../../../api/types'
import { CategoryPicker } from '../../../components/CategoryPicker'
import { RuleTestSummary } from '../../../components/categorise/RuleTestSummary'
import { useJobRunner } from '../../../components/categorise/useJobRunner'
import { ErrorText } from '../../../components/ui'
import { useDebounced } from '../../../lib/useDebounced'
import styles from './rules.module.css'

const KINDS: MatchKind[] = ['contains', 'starts_with', 'equals', 'regex']
const AMOUNT = /^\d{1,12}(\.\d{1,2})?$/

/** Add or edit a rule. Tests it live before saving; after saving, asks whether to apply it to
 *  the uncategorised transactions it matches (OQ-12). */
export function RuleForm({ rule, onDone }: { rule?: Rule; onDone: () => void }) {
  const accounts = useAccounts()
  const create = useCreateRule()
  const update = useUpdateRule()
  const apply = useApplyRules()
  const runner = useJobRunner()

  const [matchKind, setMatchKind] = useState<MatchKind>(rule?.match_kind ?? 'contains')
  const [pattern, setPattern] = useState(rule?.pattern ?? '')
  const [categoryId, setCategoryId] = useState(rule?.category_id ?? '')
  const [direction, setDirection] = useState<Direction | ''>(rule?.direction ?? '')
  const [accountId, setAccountId] = useState(rule?.account_id ?? '')
  const [amountMin, setAmountMin] = useState(rule?.amount_min ?? '')
  const [amountMax, setAmountMax] = useState(rule?.amount_max ?? '')
  const [label, setLabel] = useState(rule?.label ?? '')
  const [error, setError] = useState<string | null>(null)
  const [ask, setAsk] = useState<number | null>(null)

  const amountsValid = [amountMin, amountMax].every((a) => a === '' || AMOUNT.test(a))
  const fields = {
    match_kind: matchKind,
    pattern,
    category_id: categoryId || null,
    direction: direction || null,
    account_id: accountId || null,
    amount_min: amountMin || null,
    amount_max: amountMax || null,
  }
  const draft = useDebounced(pattern.trim() && amountsValid ? fields : null)
  const test = useTestRule(draft ? { ...draft, rule_id: rule?.id ?? null } : null)
  const saving = create.isPending || update.isPending

  async function save(event: FormEvent) {
    event.preventDefault()
    setError(null)
    const body = { ...fields, category_id: categoryId, label: label.trim() || null }
    try {
      const saved = rule
        ? await update.mutateAsync({ id: rule.id, changes: body })
        : await create.mutateAsync({ ...body, enabled: true })
      const after = await api<RuleTest>('/rules/test', {
        method: 'POST',
        body: { ...fields, category_id: categoryId, rule_id: saved.id },
      })
      if (saved.enabled && after.uncategorised > 0) setAsk(after.uncategorised)
      else onDone()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function applyNow() {
    try {
      const accepted = await apply.mutateAsync({
        scope: 'uncategorised',
        include_manual: false,
        dry_run: false,
      })
      runner.track(accepted.job.id)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (ask !== null) {
    return (
      <div className={styles.formBox} role="group" aria-label="Apply the rule">
        {runner.job ? (
          <p role="status">
            {runner.running && 'Applying…'}
            {runner.job.status === 'succeeded' &&
              `Done: ${String(runner.job.result?.changed ?? 0)} transactions categorised.`}
            {runner.job.status === 'failed' && (runner.job.error ?? 'The job failed.')}
          </p>
        ) : (
          <p>
            Rule saved. Apply it to {ask} uncategorised transaction{ask === 1 ? '' : 's'}?
          </p>
        )}
        <ErrorText>{error}</ErrorText>
        <div className={styles.actions}>
          {!runner.job && (
            <button className="primary" onClick={applyNow} disabled={apply.isPending}>
              Apply to {ask} uncategorised
            </button>
          )}
          <button onClick={onDone}>{runner.job ? 'Close' : 'Not now'}</button>
        </div>
      </div>
    )
  }

  return (
    <form
      onSubmit={save}
      className={styles.formBox}
      aria-label={rule ? `Edit rule ${rule.pattern}` : 'Add rule'}
    >
      <div className={styles.formGrid}>
        <label className={styles.field}>
          Description
          <select value={matchKind} onChange={(e) => setMatchKind(e.target.value as MatchKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {MATCH_KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <label className={`${styles.field} ${styles.wide}`}>
          Pattern
          <input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            required
            maxLength={500}
            spellCheck={false}
            placeholder={matchKind === 'regex' ? String.raw`\bSWIGGY\b` : 'SWIGGY'}
          />
        </label>
        <label className={styles.field}>
          Category
          <CategoryPicker value={categoryId} onChange={setCategoryId} required />
        </label>
        <label className={styles.field}>
          Direction
          <select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
            <option value="">Any</option>
            <option value="debit">{DIRECTION_LABELS.debit}</option>
            <option value="credit">{DIRECTION_LABELS.credit}</option>
          </select>
        </label>
        <label className={styles.field}>
          Account
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Any</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Amount from (₹)
          <input
            inputMode="decimal"
            value={amountMin}
            onChange={(e) => setAmountMin(e.target.value.trim())}
            aria-invalid={amountMin !== '' && !AMOUNT.test(amountMin)}
          />
        </label>
        <label className={styles.field}>
          Amount to (₹)
          <input
            inputMode="decimal"
            value={amountMax}
            onChange={(e) => setAmountMax(e.target.value.trim())}
            aria-invalid={amountMax !== '' && !AMOUNT.test(amountMax)}
          />
        </label>
        <label className={styles.field}>
          Label (optional)
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} />
        </label>
      </div>
      {!amountsValid && <ErrorText>Amounts look like 1500 or 1500.50</ErrorText>}
      <RuleTestSummary test={test} />
      <ErrorText>{error}</ErrorText>
      <div className={styles.actions}>
        <button type="submit" className="primary" disabled={saving || !amountsValid}>
          {rule ? 'Save rule' : 'Add rule'}
        </button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}
