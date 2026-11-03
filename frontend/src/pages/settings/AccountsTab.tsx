import { useState, type FormEvent } from 'react'
import { useAccounts, useCreateAccount, useDeleteAccount, useUpdateAccount } from '../../api/hooks'
import { errorMessage } from '../../api/client'
import { ACCOUNT_TYPE_LABELS, type Account, type AccountType } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import styles from './settings.module.css'

interface FormState {
  name: string
  type: AccountType
  institution: string
  masked_number: string
  active: boolean
}

const EMPTY: FormState = {
  name: '',
  type: 'savings',
  institution: '',
  masked_number: '',
  active: true,
}

function toForm(account: Account): FormState {
  return {
    name: account.name,
    type: account.type,
    institution: account.institution ?? '',
    masked_number: account.masked_number ?? '',
    active: account.active,
  }
}

function toBody(form: FormState) {
  return {
    name: form.name.trim(),
    type: form.type,
    institution: form.institution.trim() || null,
    masked_number: form.masked_number.trim() || null,
    active: form.active,
  }
}

function AccountForm({
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  initial: FormState
  submitLabel: string
  pending: boolean
  error: unknown
  onSubmit: (form: FormState) => void
  onCancel?: () => void
}) {
  const [form, setForm] = useState(initial)
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  function submit(event: FormEvent) {
    event.preventDefault()
    onSubmit(form)
  }

  return (
    <form onSubmit={submit} aria-label={submitLabel}>
      <div className={styles.form}>
        <label className={styles.field}>
          Name
          <input
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            required
            maxLength={80}
          />
        </label>
        <label className={styles.field}>
          Type
          <select value={form.type} onChange={(e) => set('type', e.target.value as AccountType)}>
            {Object.entries(ACCOUNT_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Bank / institution
          <input
            value={form.institution}
            onChange={(e) => set('institution', e.target.value)}
            maxLength={80}
            placeholder="e.g. ICICI Bank"
          />
        </label>
        <label className={styles.field}>
          Last 4 digits
          <input
            value={form.masked_number}
            onChange={(e) => set('masked_number', e.target.value)}
            inputMode="numeric"
            pattern="[0-9]{1,4}"
            maxLength={4}
            title="Up to 4 digits — never the full account number"
          />
        </label>
        <label className={styles.checkboxField}>
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => set('active', e.target.checked)}
          />
          Active
        </label>
        <div className={styles.formActions}>
          <button type="submit" className="primary" disabled={pending}>
            {submitLabel}
          </button>
          {onCancel && (
            <button type="button" onClick={onCancel}>
              Cancel
            </button>
          )}
        </div>
      </div>
      <ErrorText>{error ? errorMessage(error) : null}</ErrorText>
    </form>
  )
}

export function AccountsTab() {
  const accounts = useAccounts()
  const create = useCreateAccount()
  const update = useUpdateAccount()
  const remove = useDeleteAccount()
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  return (
    <div className={styles.stack}>
      <Card>
        <div className={styles.toolbar}>
          <h2>Accounts</h2>
          {!adding && (
            <button className="primary" onClick={() => setAdding(true)}>
              Add account
            </button>
          )}
        </div>
        {adding && (
          <AccountForm
            initial={EMPTY}
            submitLabel="Save account"
            pending={create.isPending}
            error={create.error}
            onSubmit={(form) => create.mutate(toBody(form), { onSuccess: () => setAdding(false) })}
            onCancel={() => {
              create.reset()
              setAdding(false)
            }}
          />
        )}

        {accounts.isPending && <p className={styles.muted}>Loading…</p>}
        <ErrorText>{accounts.isError ? errorMessage(accounts.error) : null}</ErrorText>
        {accounts.data?.length === 0 && !adding && (
          <p className={styles.muted}>
            No accounts yet. Add your savings accounts and credit cards; statements are matched to
            them by the last 4 digits.
          </p>
        )}
        {accounts.data && accounts.data.length > 0 && (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th className={styles.hideNarrow}>Institution</th>
                  <th>Last 4</th>
                  <th className={styles.hideNarrow}>Status</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.map((account) =>
                  editingId === account.id ? (
                    <tr key={account.id}>
                      <td colSpan={6}>
                        <AccountForm
                          initial={toForm(account)}
                          submitLabel="Save changes"
                          pending={update.isPending}
                          error={update.error}
                          onSubmit={(form) =>
                            update.mutate(
                              { id: account.id, changes: toBody(form) },
                              { onSuccess: () => setEditingId(null) },
                            )
                          }
                          onCancel={() => {
                            update.reset()
                            setEditingId(null)
                          }}
                        />
                      </td>
                    </tr>
                  ) : (
                    <tr key={account.id} className={account.active ? undefined : styles.inactive}>
                      <td>{account.name}</td>
                      <td>{ACCOUNT_TYPE_LABELS[account.type]}</td>
                      <td className={styles.hideNarrow}>{account.institution ?? '—'}</td>
                      <td>{account.masked_number ? `••${account.masked_number}` : '—'}</td>
                      <td className={styles.hideNarrow}>
                        {account.active ? 'Active' : 'Inactive'}
                      </td>
                      <td className={styles.actions}>
                        <button className="link" onClick={() => setEditingId(account.id)}>
                          Edit<span className="visually-hidden"> {account.name}</span>
                        </button>
                        <button
                          className="link danger"
                          disabled={remove.isPending}
                          onClick={() => {
                            if (window.confirm(`Delete the account “${account.name}”?`))
                              remove.mutate(account.id)
                          }}
                        >
                          Delete<span className="visually-hidden"> {account.name}</span>
                        </button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
        <ErrorText>{remove.isError ? errorMessage(remove.error) : null}</ErrorText>
      </Card>
    </div>
  )
}
