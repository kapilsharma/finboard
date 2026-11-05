import { useState, type FormEvent } from 'react'
import { api, errorMessage } from '../../api/client'
import { useApplyRules, useBulkCategorise, useCreateRule, useTestRule } from '../../api/hooks'
import {
  MATCH_KIND_LABELS,
  type MatchKind,
  type RuleSuggestion,
  type RuleTest,
  type Txn,
} from '../../api/types'
import { formatDate, formatMoney } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'
import { CategoryPicker } from '../CategoryPicker'
import { Modal } from '../Modal'
import { ErrorText } from '../ui'
import { RuleTestSummary } from './RuleTestSummary'
import { SuggestionList } from './SuggestionList'
import { useJobRunner } from './useJobRunner'
import styles from './categorise.module.css'

const KINDS: MatchKind[] = ['contains', 'starts_with', 'equals', 'regex']

type Step = { name: 'form' } | { name: 'apply'; ruleId: string; count: number } | { name: 'done' }

/**
 * Categorise one or more transactions by hand, and optionally turn the choice into a rule
 * (ARCHITECTURE §9 "Rule from review"). After a rule is saved, offer to apply it to the other
 * uncategorised transactions it matches (OQ-12: ask, don't do it silently).
 */
export function CategoriseDialog({
  transactions,
  suggestion,
  onClose,
}: {
  transactions: Txn[]
  suggestion: RuleSuggestion | null
  onClose: () => void
}) {
  const [categoryId, setCategoryId] = useState('')
  const [makeRule, setMakeRule] = useState(suggestion !== null)
  const [matchKind, setMatchKind] = useState<MatchKind>(suggestion?.match_kind ?? 'contains')
  const [pattern, setPattern] = useState(suggestion?.pattern ?? '')
  const [step, setStep] = useState<Step>({ name: 'form' })
  const [error, setError] = useState<string | null>(null)

  const bulk = useBulkCategorise()
  const createRule = useCreateRule()
  const apply = useApplyRules()
  const runner = useJobRunner()

  const draft = useDebounced(
    makeRule && pattern.trim()
      ? { match_kind: matchKind, pattern, category_id: categoryId || null }
      : null,
  )
  const test = useTestRule(draft)
  const busy = bulk.isPending || createRule.isPending

  async function save(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await bulk.mutateAsync({ ids: transactions.map((t) => t.id), category_id: categoryId })
      if (!makeRule) {
        onClose()
        return
      }
      const rule = await createRule.mutateAsync({
        match_kind: matchKind,
        pattern,
        category_id: categoryId,
        enabled: true,
      })
      // How many *other* uncategorised transactions the new rule would now pick up.
      const after = await api<RuleTest>('/rules/test', {
        method: 'POST',
        body: { match_kind: matchKind, pattern, category_id: categoryId, rule_id: rule.id },
      })
      if (after.uncategorised > 0)
        setStep({ name: 'apply', ruleId: rule.id, count: after.uncategorised })
      else onClose()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function applyNow() {
    setError(null)
    try {
      const accepted = await apply.mutateAsync({
        scope: 'uncategorised',
        include_manual: false,
        dry_run: false,
      })
      runner.track(accepted.job.id)
      setStep({ name: 'done' })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function accept(id: string) {
    setError(null)
    try {
      await bulk.mutateAsync({ ids: transactions.map((t) => t.id), category_id: id })
      onClose()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const first = transactions[0]
  const title =
    transactions.length === 1
      ? 'Categorise transaction'
      : `Categorise ${transactions.length} transactions`

  return (
    <Modal title={title} onClose={onClose}>
      {step.name === 'form' && (
        <form onSubmit={save} aria-label={title} className={styles.form}>
          {first && (
            <p className={styles.example}>
              <span className={styles.exampleText}>{first.description}</span>
              <span className={styles.exampleMeta}>
                {formatDate(first.date)} · {formatMoney(first.amount)}
                {transactions.length > 1 && ` · and ${transactions.length - 1} more`}
              </span>
            </p>
          )}
          {first && (
            <SuggestionList
              transactionId={first.id}
              disabled={busy}
              onAccept={(s) => void accept(s.category.id)}
              onMakeRule={(s) => {
                setCategoryId(s.category.id)
                setMakeRule(true)
              }}
            />
          )}
          <label className={styles.field}>
            Category
            <CategoryPicker value={categoryId} onChange={setCategoryId} required />
          </label>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={makeRule}
              onChange={(e) => setMakeRule(e.target.checked)}
            />
            Create a rule for similar transactions
          </label>

          {makeRule && (
            <fieldset className={styles.rule}>
              <legend className="visually-hidden">Rule</legend>
              <div className={styles.ruleRow}>
                <label className={styles.field}>
                  Description
                  <select
                    value={matchKind}
                    onChange={(e) => setMatchKind(e.target.value as MatchKind)}
                  >
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {MATCH_KIND_LABELS[k]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={`${styles.field} ${styles.grow}`}>
                  Pattern
                  <input
                    value={pattern}
                    onChange={(e) => setPattern(e.target.value)}
                    required
                    maxLength={500}
                    spellCheck={false}
                  />
                </label>
              </div>
              <RuleTestSummary test={test} />
            </fieldset>
          )}

          <ErrorText>{error}</ErrorText>
          <div className={styles.actions}>
            <button type="submit" className="primary" disabled={busy || !categoryId}>
              {makeRule ? 'Save and create rule' : 'Save'}
            </button>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {step.name === 'apply' && (
        <div className={styles.form}>
          <p>
            Rule saved. Apply it to the {step.count} other uncategorised transaction
            {step.count === 1 ? '' : 's'} it matches?
          </p>
          <ErrorText>{error}</ErrorText>
          <div className={styles.actions}>
            <button className="primary" onClick={applyNow} disabled={apply.isPending}>
              Apply to {step.count} uncategorised
            </button>
            <button onClick={onClose}>Not now</button>
          </div>
        </div>
      )}

      {step.name === 'done' && (
        <div className={styles.form}>
          <p role="status">
            {runner.running && 'Applying the rule…'}
            {runner.job?.status === 'succeeded' &&
              `Done: ${String(runner.job.result?.changed ?? 0)} transactions categorised.`}
            {runner.job?.status === 'failed' && (runner.job.error ?? 'The job failed.')}
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
