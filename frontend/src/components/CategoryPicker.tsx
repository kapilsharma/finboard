import { useCategories } from '../api/hooks'
import { CATEGORY_TYPE_LABELS, type Category, type CategoryType } from '../api/types'

const TYPE_ORDER: CategoryType[] = ['expense', 'income', 'investment', 'transfer']

/** A category <select>, grouped by type, sub-categories under their parent. */
export function CategoryPicker({
  value,
  onChange,
  id,
  required = false,
  placeholder = 'Choose a category…',
}: {
  value: string
  onChange: (id: string) => void
  id?: string
  required?: boolean
  placeholder?: string
}) {
  const categories = useCategories()
  const all = (categories.data ?? []).filter((c) => !c.archived || c.id === value)
  const topLevel = all.filter((c) => c.parent_id === null)
  const ordered = (type: CategoryType): { category: Category; child: boolean }[] =>
    topLevel
      .filter((c) => c.type === type)
      .flatMap((parent) => [
        { category: parent, child: false },
        ...all.filter((c) => c.parent_id === parent.id).map((c) => ({ category: c, child: true })),
      ])

  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} required={required}>
      <option value="">{categories.isPending ? 'Loading…' : placeholder}</option>
      {TYPE_ORDER.map((type) => {
        const options = ordered(type)
        if (options.length === 0) return null
        return (
          <optgroup key={type} label={CATEGORY_TYPE_LABELS[type]}>
            {options.map(({ category, child }) => (
              <option key={category.id} value={category.id}>
                {child ? ` ${category.name}` : category.name}
              </option>
            ))}
          </optgroup>
        )
      })}
    </select>
  )
}
