import { useState, type FormEvent } from 'react'
import { errorMessage } from '../../../api/client'
import { useImportRules } from '../../../api/hooks'
import { Modal } from '../../../components/Modal'
import { ErrorText } from '../../../components/ui'
import styles from './rules.module.css'

/** Load a YAML/JSON rule pack from a file or pasted text. The file is read in the browser. */
export function ImportRulesDialog({ onClose }: { onClose: () => void }) {
  const [content, setContent] = useState('')
  const [mode, setMode] = useState<'merge' | 'replace'>('merge')
  const importRules = useImportRules()

  async function readFile(file: File | undefined) {
    if (file) setContent(await file.text())
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    importRules.mutate({ content, mode })
  }

  const result = importRules.data
  return (
    <Modal title="Import rules" onClose={onClose} wide>
      {result ? (
        <div className={styles.dialogBody}>
          <p role="status">
            Added {result.added} rule{result.added === 1 ? '' : 's'}
            {result.skipped > 0 && `, skipped ${result.skipped} you already had`}
            {result.replaced > 0 && `, replaced ${result.replaced}`}
            {result.categories_created > 0 &&
              `, created ${result.categories_created} categor${result.categories_created === 1 ? 'y' : 'ies'}`}
            .
          </p>
          <div className={styles.actions}>
            <button className="primary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className={styles.dialogBody} aria-label="Import rules">
          <p className={styles.muted}>
            A Finboard rule pack (YAML or JSON), for example one exported from another machine.
            Categories are matched by name and created if missing.
          </p>
          <label className={styles.field}>
            File
            <input
              type="file"
              accept=".yaml,.yml,.json,application/json,application/yaml,text/yaml"
              onChange={(e) => void readFile(e.target.files?.[0])}
            />
          </label>
          <label className={styles.field}>
            Or paste it
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              spellCheck={false}
              className={styles.textarea}
            />
          </label>
          <fieldset className={styles.choices}>
            <legend>Your current rules</legend>
            <label>
              <input type="radio" checked={mode === 'merge'} onChange={() => setMode('merge')} />
              Keep them; add the pack's rules after them
            </label>
            <label>
              <input
                type="radio"
                checked={mode === 'replace'}
                onChange={() => setMode('replace')}
              />
              Replace them with the pack's rules
            </label>
          </fieldset>
          <ErrorText>{importRules.isError ? errorMessage(importRules.error) : null}</ErrorText>
          <div className={styles.actions}>
            <button
              type="submit"
              className="primary"
              disabled={!content.trim() || importRules.isPending}
            >
              Import
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
