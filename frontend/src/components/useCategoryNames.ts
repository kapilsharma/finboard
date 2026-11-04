import { useCategories } from '../api/hooks'

/** id → name, for showing categories in lists. */
export function useCategoryNames(): Map<string, string> {
  const categories = useCategories()
  const all = categories.data ?? []
  const byId = new Map(all.map((c) => [c.id, c]))
  return new Map(
    all.map((c) => {
      const parent = c.parent_id ? byId.get(c.parent_id) : undefined
      return [c.id, parent ? `${parent.name} › ${c.name}` : c.name]
    }),
  )
}
