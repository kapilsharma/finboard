import { useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/client'
import { useMergeCategory } from '../../api/hooks'
import type { Category } from '../../api/types'
import { CategoryPicker } from '../../components/CategoryPicker'
import { Modal } from '../../components/Modal'
import { ErrorText } from '../../components/ui'
import styles from './settings.module.css'

/** Merge one category into another: its transactions, rules and limits move, then it goes. */
export function MergeCategoryDialog({
  category,
  onClose,
}: {
  category: Category
  onClose: () => void
}) {
  const merge = useMergeCategory()
  const [into, setInto] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    merge.mutate({ id: category.id, intoId: into })
  }

  const done = merge.data
  return (
    <Modal title={`Merge “${category.name}”`} onClose={onClose}>
      {done ? (
        <div className={styles.dataSection}>
          <p role="status">
            Moved {done.transactions} transaction{done.transactions === 1 ? '' : 's'}, {done.rules}{' '}
            rule
            {done.rules === 1 ? '' : 's'} and {done.budgets} limit change
            {done.budgets === 1 ? '' : 's'} to “{done.into.name}”. “{category.name}” is gone.
          </p>
          <div className={styles.formActions}>
            <button className="primary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      ) : (
        <form
          onSubmit={submit}
          className={styles.dataSection}
          aria-label={`Merge ${category.name}`}
        >
          <p>
            Its transactions, rules and monthly limits move to the category you choose, and “
            {category.name}” is deleted. Where both have a limit for the same month, the chosen
            category&apos;s stays.
          </p>
          <label className={styles.field}>
            Merge into
            <CategoryPicker value={into} onChange={setInto} required />
          </label>
          {into === category.id && <ErrorText>Choose a different category.</ErrorText>}
          <ErrorText>{merge.isError ? errorMessage(merge.error) : null}</ErrorText>
          <div className={styles.formActions}>
            <button
              type="submit"
              className="primary"
              disabled={!into || into === category.id || merge.isPending}
            >
              Merge
            </button>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
