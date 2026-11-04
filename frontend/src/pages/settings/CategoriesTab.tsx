import { useState, type FormEvent } from 'react'
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from '../../api/hooks'
import { errorMessage } from '../../api/client'
import { CATEGORY_TYPE_LABELS, type Category, type CategoryType } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { MergeCategoryDialog } from './MergeCategoryDialog'
import styles from './settings.module.css'

const TYPE_ORDER: CategoryType[] = ['income', 'expense', 'investment', 'transfer']

function AddCategoryForm({ topLevel, onDone }: { topLevel: Category[]; onDone: () => void }) {
  const create = useCreateCategory()
  const [name, setName] = useState('')
  const [type, setType] = useState<CategoryType>('expense')
  const [parentId, setParentId] = useState('')
  const [colour, setColour] = useState('#8a8f7a')

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { name: name.trim(), type, parent_id: parentId || null, colour },
      { onSuccess: onDone },
    )
  }

  return (
    <form onSubmit={submit} aria-label="Add category">
      <div className={styles.form}>
        <label className={styles.field}>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} />
        </label>
        <label className={styles.field}>
          Type
          <select value={type} onChange={(e) => setType(e.target.value as CategoryType)}>
            {TYPE_ORDER.map((t) => (
              <option key={t} value={t}>
                {CATEGORY_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Inside (optional)
          <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">— top level —</option>
            {topLevel.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Colour
          <input type="color" value={colour} onChange={(e) => setColour(e.target.value)} />
        </label>
        <div className={styles.formActions}>
          <button type="submit" className="primary" disabled={create.isPending}>
            Save category
          </button>
          <button type="button" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
      <ErrorText>{create.isError ? errorMessage(create.error) : null}</ErrorText>
    </form>
  )
}

function CategoryRow({
  category,
  isChild,
  hasChildren,
}: {
  category: Category
  isChild: boolean
  hasChildren: boolean
}) {
  const update = useUpdateCategory()
  const remove = useDeleteCategory()
  const [editing, setEditing] = useState(false)
  const [merging, setMerging] = useState(false)
  const [name, setName] = useState(category.name)

  function save(event: FormEvent) {
    event.preventDefault()
    update.mutate(
      { id: category.id, changes: { name: name.trim() } },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <tr>
      <td className={isChild ? styles.child : undefined}>
        {editing ? (
          <form
            onSubmit={save}
            className={styles.formActions}
            aria-label={`Rename ${category.name}`}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={60}
              autoFocus
            />
            <button type="submit" className="primary" disabled={update.isPending}>
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setName(category.name)
                update.reset()
                setEditing(false)
              }}
            >
              Cancel
            </button>
          </form>
        ) : (
          <>
            <span
              className={styles.swatch}
              style={{ background: category.colour ?? 'transparent' }}
              aria-hidden
            />
            {category.name}
            {category.is_system && <span className={styles.badge}>system</span>}
          </>
        )}
        <ErrorText>
          {update.isError
            ? errorMessage(update.error)
            : remove.isError
              ? errorMessage(remove.error)
              : null}
        </ErrorText>
      </td>
      <td className={styles.actions}>
        {!editing && (
          <button
            className="link"
            onClick={() => setEditing(true)}
            aria-label={`Rename ${category.name}`}
          >
            Rename
          </button>
        )}
        {!category.is_system && !hasChildren && (
          <button
            className="link"
            onClick={() => setMerging(true)}
            aria-label={`Merge ${category.name} into another category`}
          >
            Merge…
          </button>
        )}
        {merging && <MergeCategoryDialog category={category} onClose={() => setMerging(false)} />}
        {!category.is_system && (
          <button
            className="link danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete the category “${category.name}”?`))
                remove.mutate(category.id)
            }}
            aria-label={`Delete ${category.name}`}
          >
            Delete
          </button>
        )}
      </td>
    </tr>
  )
}

export function CategoriesTab() {
  const categories = useCategories()
  const [adding, setAdding] = useState(false)
  const all = categories.data ?? []
  const topLevel = all.filter((c) => c.parent_id === null)

  return (
    <Card>
      <div className={styles.toolbar}>
        <h2>Categories</h2>
        {!adding && (
          <button className="primary" onClick={() => setAdding(true)}>
            Add category
          </button>
        )}
      </div>
      <p className={styles.muted}>
        A transaction's category decides whether it counts as income, spending, investment or a
        transfer between your own accounts (excluded from both).
      </p>
      {adding && <AddCategoryForm topLevel={topLevel} onDone={() => setAdding(false)} />}
      {categories.isPending && <p className={styles.muted}>Loading…</p>}
      <ErrorText>{categories.isError ? errorMessage(categories.error) : null}</ErrorText>

      {TYPE_ORDER.map((type) => {
        const parents = topLevel.filter((c) => c.type === type)
        if (parents.length === 0) return null
        return (
          <section key={type} aria-label={CATEGORY_TYPE_LABELS[type]}>
            <h3 className={styles.groupTitle}>{CATEGORY_TYPE_LABELS[type]}</h3>
            <table>
              <tbody>
                {parents.flatMap((parent) => [
                  <CategoryRow
                    key={parent.id}
                    category={parent}
                    isChild={false}
                    hasChildren={all.some((c) => c.parent_id === parent.id)}
                  />,
                  ...all
                    .filter((c) => c.parent_id === parent.id)
                    .map((child) => (
                      <CategoryRow key={child.id} category={child} isChild hasChildren={false} />
                    )),
                ])}
              </tbody>
            </table>
          </section>
        )
      })}
    </Card>
  )
}
