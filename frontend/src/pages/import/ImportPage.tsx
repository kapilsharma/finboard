import { useRef, useState, type DragEvent } from 'react'
import { errorMessage } from '../../api/client'
import { useImports, useUploadImport } from '../../api/hooks'
import { Card, PageHeader } from '../../components/ui'
import { ImportListItem } from './parts'
import styles from './import.module.css'

interface Upload {
  key: string
  name: string
  importId?: string
  error?: string
}

const ATTENTION = ['needs_password', 'parsed', 'uploaded', 'queued', 'processing'] as const

function isPdf(file: File) {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

/** Drop one or more statements; each file becomes its own import (ARCHITECTURE §7). */
export function ImportPage() {
  const upload = useUploadImport()
  const waiting = useImports(ATTENTION)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function update(key: string, changes: Partial<Upload>) {
    setUploads((list) => list.map((u) => (u.key === key ? { ...u, ...changes } : u)))
  }

  function addFiles(files: Iterable<File>) {
    for (const file of files) {
      const key = crypto.randomUUID()
      setUploads((list) => [{ key, name: file.name }, ...list])
      if (!isPdf(file)) {
        update(key, { error: 'Only PDF statements are supported.' })
        continue
      }
      upload.mutate(file, {
        onSuccess: (resource) => update(key, { importId: resource.id }),
        onError: (error) => update(key, { error: errorMessage(error) }),
      })
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files))
  }

  const sessionIds = new Set(uploads.map((u) => u.importId))
  const others = (waiting.data ?? []).filter((i) => !sessionIds.has(i.id))

  return (
    <>
      <PageHeader
        title="Import statements"
        subtitle="PDF statements from your bank. Each file is read on this computer and previewed before anything is saved."
      />
      <div className={styles.stack}>
        <label
          className={`${styles.dropZone} ${dragging ? styles.dragging : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          data-testid="drop-zone"
        >
          <span className={styles.dropTitle}>Drop PDF statements here</span>
          <span className={styles.muted}>
            or <span className={styles.chooseLink}>choose files</span> · up to 20 MB each
          </span>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="visually-hidden"
            aria-label="Choose PDF statements"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              if (inputRef.current) inputRef.current.value = ''
            }}
          />
        </label>

        {uploads.length > 0 && (
          <Card title="Just uploaded">
            <ul className={styles.list}>
              {uploads.map((u) =>
                u.importId ? (
                  <ImportListItem key={u.key} id={u.importId} fallbackName={u.name} />
                ) : (
                  <li key={u.key} className={styles.item} aria-label={u.name}>
                    <div className={styles.itemHead}>
                      <span className={styles.fileName}>{u.name}</span>
                    </div>
                    {u.error ? (
                      <p className={styles.error} role="alert">
                        {u.error}
                      </p>
                    ) : (
                      <p className={styles.muted} role="status">
                        Uploading…
                      </p>
                    )}
                  </li>
                ),
              )}
            </ul>
          </Card>
        )}

        {others.length > 0 && (
          <Card title="Waiting for you">
            <ul className={styles.list}>
              {others.map((i) => (
                <ImportListItem key={i.id} id={i.id} fallbackName={i.file_name} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  )
}
