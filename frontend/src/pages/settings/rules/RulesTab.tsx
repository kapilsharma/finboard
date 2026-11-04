import { useState } from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { errorMessage } from '../../../api/client'
import {
  downloadRulePack,
  useAccounts,
  useAddStarterRules,
  useDeleteRule,
  useReorderRules,
  useRules,
  useUpdateRule,
} from '../../../api/hooks'
import { DIRECTION_LABELS, MATCH_KIND_LABELS, type Rule } from '../../../api/types'
import { Card, ErrorText } from '../../../components/ui'
import { useCategoryNames } from '../../../components/useCategoryNames'
import { formatMoney } from '../../../lib/format'
import { ImportRulesDialog } from './ImportRulesDialog'
import { ReapplyDialog } from './ReapplyDialog'
import { RuleForm } from './RuleForm'
import styles from './rules.module.css'

function describe(rule: Rule): string {
  return `${MATCH_KIND_LABELS[rule.match_kind]} ${rule.pattern}`
}

function RuleItem({
  rule,
  position,
  total,
  sortable,
  categoryName,
  accountName,
  onMove,
}: {
  rule: Rule
  position: number
  total: number
  sortable: boolean
  categoryName: string
  accountName: string | null
  onMove: (rule: Rule, to: number) => void
}) {
  const update = useUpdateRule()
  const remove = useDeleteRule()
  const [editing, setEditing] = useState(false)
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: rule.id,
    disabled: !sortable,
  })
  const name = describe(rule)
  const constraints = [
    rule.direction && DIRECTION_LABELS[rule.direction],
    accountName && `in ${accountName}`,
    rule.amount_min && rule.amount_max
      ? `${formatMoney(rule.amount_min)}–${formatMoney(rule.amount_max)}`
      : rule.amount_min
        ? `from ${formatMoney(rule.amount_min)}`
        : rule.amount_max && `up to ${formatMoney(rule.amount_max)}`,
  ].filter(Boolean)

  if (editing) {
    return (
      <li ref={setNodeRef} className={styles.item}>
        <RuleForm rule={rule} onDone={() => setEditing(false)} />
      </li>
    )
  }

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`${styles.item} ${isDragging ? styles.dragging : ''} ${rule.enabled ? '' : styles.disabled}`}
      aria-label={`Rule ${position + 1}: ${name}`}
    >
      {sortable && (
        <button
          type="button"
          className={styles.handle}
          aria-label={`Drag to reorder: ${name}`}
          {...attributes}
          {...listeners}
        >
          ⠿
        </button>
      )}
      <span className={styles.position} aria-hidden>
        {position + 1}
      </span>
      <div className={styles.summary}>
        <div>
          <span className={styles.kind}>{MATCH_KIND_LABELS[rule.match_kind]}</span>{' '}
          <code className={styles.pattern}>{rule.pattern}</code> → <strong>{categoryName}</strong>
        </div>
        <div className={styles.meta}>
          {constraints.map((c) => (
            <span key={c} className={styles.chip}>
              {c}
            </span>
          ))}
          {rule.label && <span>{rule.label}</span>}
          <span>
            {rule.hits} hit{rule.hits === 1 ? '' : 's'}
          </span>
        </div>
        {rule.error && <p className={styles.ruleError}>{rule.error}</p>}
        <ErrorText>
          {update.isError
            ? errorMessage(update.error)
            : remove.isError
              ? errorMessage(remove.error)
              : null}
        </ErrorText>
      </div>
      <div className={styles.itemActions}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={rule.enabled}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ id: rule.id, changes: { enabled: e.target.checked } })}
          />
          On<span className="visually-hidden">: {name}</span>
        </label>
        {sortable && (
          <>
            <button
              className="link"
              disabled={position === 0}
              onClick={() => onMove(rule, position - 1)}
              aria-label={`Move up: ${name}`}
            >
              ↑
            </button>
            <button
              className="link"
              disabled={position === total - 1}
              onClick={() => onMove(rule, position + 1)}
              aria-label={`Move down: ${name}`}
            >
              ↓
            </button>
          </>
        )}
        <button className="link" onClick={() => setEditing(true)} aria-label={`Edit: ${name}`}>
          Edit
        </button>
        <button
          className="link danger"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Delete the rule “${name}”?`)) remove.mutate(rule.id)
          }}
          aria-label={`Delete: ${name}`}
        >
          Delete
        </button>
      </div>
    </li>
  )
}

export function RulesTab() {
  const rules = useRules()
  const accounts = useAccounts()
  const reorder = useReorderRules()
  const starter = useAddStarterRules()
  const categoryNames = useCategoryNames()
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const [dialog, setDialog] = useState<'reapply' | 'import' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const all = rules.data ?? []
  const accountNames = new Map((accounts.data ?? []).map((a) => [a.id, a.name]))
  const query = search.trim().toLowerCase()
  const visible = query
    ? all.filter((r) =>
        [r.pattern, r.label ?? '', categoryNames.get(r.category_id) ?? '']
          .join(' ')
          .toLowerCase()
          .includes(query),
      )
    : all
  // Reordering a filtered list would be ambiguous: only the full list can be reordered.
  const sortable = !query

  function move(rule: Rule, to: number) {
    const from = all.findIndex((r) => r.id === rule.id)
    reorder.mutate(arrayMove(all, from, to).map((r) => r.id))
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return
    const to = all.findIndex((r) => r.id === over.id)
    const rule = all.find((r) => r.id === active.id)
    if (rule && to >= 0) move(rule, to)
  }

  async function exportPack(format: 'yaml' | 'json') {
    setExportError(null)
    try {
      await downloadRulePack(format)
    } catch (e) {
      setExportError(errorMessage(e))
    }
  }

  return (
    <Card>
      <div className={styles.toolbar}>
        <h2>Rules</h2>
        {!adding && (
          <button className="primary" onClick={() => setAdding(true)}>
            Add rule
          </button>
        )}
      </div>
      <p className={styles.muted}>
        Rules run from the top; the first one that matches a transaction's description decides its
        category. Patterns ignore case and reference numbers. Drag rules, or use the arrows, to
        change the order.
      </p>
      <div className={styles.secondary}>
        <label className={styles.search}>
          <span className="visually-hidden">Search rules</span>
          <input
            type="search"
            placeholder="Search rules"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <button onClick={() => setDialog('reapply')}>Re-apply rules…</button>
        <button onClick={() => setDialog('import')}>Import…</button>
        <button onClick={() => void exportPack('yaml')}>Export YAML</button>
        <button onClick={() => void exportPack('json')}>Export JSON</button>
        <button onClick={() => starter.mutate()} disabled={starter.isPending}>
          Add starter rules
        </button>
      </div>
      {starter.data && (
        <p role="status" className={styles.muted}>
          {starter.data.added === 0
            ? 'You already have all the starter rules.'
            : `Added ${starter.data.added} starter rules.`}
        </p>
      )}
      <ErrorText>
        {rules.isError
          ? errorMessage(rules.error)
          : reorder.isError
            ? errorMessage(reorder.error)
            : starter.isError
              ? errorMessage(starter.error)
              : exportError}
      </ErrorText>
      {adding && <RuleForm onDone={() => setAdding(false)} />}
      {rules.isPending && <p className={styles.muted}>Loading…</p>}
      {rules.isSuccess && all.length === 0 && (
        <p className={styles.muted}>
          No rules yet. Add one, or start from the starter rules for common Indian merchants.
        </p>
      )}
      {query && visible.length === 0 && all.length > 0 && (
        <p className={styles.muted}>No rules match “{search}”.</p>
      )}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={visible.map((r) => r.id)} strategy={verticalListSortingStrategy}>
          <ol className={styles.list} aria-label="Rules, in the order they run">
            {visible.map((rule) => {
              const position = all.findIndex((r) => r.id === rule.id)
              return (
                <RuleItem
                  key={rule.id}
                  rule={rule}
                  position={position}
                  total={all.length}
                  sortable={sortable}
                  categoryName={categoryNames.get(rule.category_id) ?? '…'}
                  accountName={rule.account_id ? (accountNames.get(rule.account_id) ?? null) : null}
                  onMove={move}
                />
              )
            })}
          </ol>
        </SortableContext>
      </DndContext>
      {dialog === 'reapply' && <ReapplyDialog onClose={() => setDialog(null)} />}
      {dialog === 'import' && <ImportRulesDialog onClose={() => setDialog(null)} />}
    </Card>
  )
}
