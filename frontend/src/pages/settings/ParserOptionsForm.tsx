import { useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/client'
import { useUpdateParser } from '../../api/hooks'
import type { Parser } from '../../api/types'
import { ErrorText } from '../../components/ui'
import styles from './settings.module.css'

interface Property {
  type?: string
  title?: string
  description?: string
  enum?: (string | number)[]
  maxLength?: number
  minimum?: number
  maximum?: number
}

type Value = string | number | boolean

/** A form for a parser's options, generated from its JSON Schema (booleans, text, numbers
 *  and choices). The server validates against the parser's own schema again on save. */
export function ParserOptionsForm({ parser, onDone }: { parser: Parser; onDone: () => void }) {
  const update = useUpdateParser()
  const properties = (parser.options_schema?.properties ?? {}) as Record<string, Property>
  const [values, setValues] = useState<Record<string, Value>>(
    parser.options as Record<string, Value>,
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    update.mutate({ id: parser.id, changes: { options: values } }, { onSuccess: onDone })
  }

  const set = (key: string, value: Value) => setValues((v) => ({ ...v, [key]: value }))

  return (
    <form onSubmit={submit} aria-label={`Options for ${parser.name}`} className={styles.inlineForm}>
      {Object.entries(properties).map(([key, prop]) => {
        const label = prop.title ?? key
        const value = values[key]
        if (prop.type === 'boolean')
          return (
            <label key={key} className={styles.checkboxField}>
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => set(key, e.target.checked)}
              />
              {label}
            </label>
          )
        if (prop.enum)
          return (
            <label key={key} className={styles.field}>
              {label}
              <select value={String(value ?? '')} onChange={(e) => set(key, e.target.value)}>
                {prop.enum.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
            </label>
          )
        const numeric = prop.type === 'integer' || prop.type === 'number'
        return (
          <label key={key} className={styles.field}>
            {label}
            <input
              type={numeric ? 'number' : 'text'}
              value={String(value ?? '')}
              maxLength={prop.maxLength}
              min={prop.minimum}
              max={prop.maximum}
              step={prop.type === 'integer' ? 1 : 'any'}
              onChange={(e) => set(key, numeric ? Number(e.target.value) : e.target.value)}
            />
          </label>
        )
      })}
      <div className={styles.formActions}>
        <button type="submit" className="primary" disabled={update.isPending}>
          Save options
        </button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ErrorText>{update.isError ? errorMessage(update.error) : null}</ErrorText>
    </form>
  )
}
