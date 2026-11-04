import { useSuggestRule } from '../../api/hooks'
import type { Txn } from '../../api/types'
import { CategoriseDialog } from '../categorise/CategoriseDialog'

/** Re-categorise one committed transaction: the same dialog as the review queue, with the
 *  rule the suggester proposes for it. */
export function RecategoriseDialog({ txn, onClose }: { txn: Txn; onClose: () => void }) {
  const suggestion = useSuggestRule(txn.id)
  if (suggestion.isPending) return null
  return (
    <CategoriseDialog
      transactions={[txn]}
      suggestion={txn.needs_review ? (suggestion.data?.suggestion ?? null) : null}
      onClose={onClose}
    />
  )
}
