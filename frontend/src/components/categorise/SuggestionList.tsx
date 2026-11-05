import { useAiStatus, useSuggestions } from '../../api/hooks'
import type { CategorySuggestion } from '../../api/types'
import { formatDate, formatMoney } from '../../lib/format'
import styles from './categorise.module.css'

/**
 * Category suggestions (M3a), shown only when the user turned them on in Settings › AI.
 * Nothing is applied until they choose: Accept is an ordinary manual categorisation, and
 * "Make a rule" opens the rule editor with the category filled in.
 */
export function SuggestionList({
  transactionId,
  disabled,
  onAccept,
  onMakeRule,
}: {
  transactionId: string
  disabled: boolean
  onAccept: (s: CategorySuggestion) => void
  onMakeRule: (s: CategorySuggestion) => void
}) {
  const status = useAiStatus()
  const enabled = status.data?.suggestions_enabled === true
  const suggestions = useSuggestions(transactionId, enabled)
  if (!enabled) return null
  const items = suggestions.data?.items ?? []

  return (
    <section className={styles.suggestions} aria-label="Suggested categories">
      <h3 className={styles.suggestionsTitle}>Suggested</h3>
      {suggestions.isPending && (
        <p className={styles.exampleMeta}>Looking for similar transactions…</p>
      )}
      {suggestions.isSuccess && items.length === 0 && (
        <p className={styles.exampleMeta}>Nothing similar categorised yet.</p>
      )}
      <ul className={styles.suggestionList}>
        {items.map((s) => (
          <li key={s.category.id} className={styles.suggestion}>
            <div className={styles.suggestionHead}>
              <span>
                <strong>{s.category.name}</strong>{' '}
                <span className={styles.exampleMeta}>
                  {Math.round(s.confidence * 100)}% of matches
                </span>
              </span>
              <span className={styles.suggestionButtons}>
                <button type="button" disabled={disabled} onClick={() => onAccept(s)}>
                  Accept
                </button>
                <button type="button" disabled={disabled} onClick={() => onMakeRule(s)}>
                  Make a rule
                </button>
              </span>
            </div>
            <details>
              <summary className={styles.exampleMeta}>
                Why: {s.examples.length} similar transaction{s.examples.length === 1 ? '' : 's'}
              </summary>
              <ul className={styles.suggestionExamples}>
                {s.examples.map((e) => (
                  <li key={e.id}>
                    <span className={styles.exampleText}>{e.description}</span>
                    <span className={styles.exampleMeta}>
                      {formatDate(e.date)} · {formatMoney(e.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ul>
    </section>
  )
}
