import { useEffect, useId, useRef, type ReactNode } from 'react'
import styles from './Modal.module.css'

/** An accessible modal: labelled by its title, Escape closes, focus moves in and comes back. */
export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const first = panel.current?.querySelector<HTMLElement>(
      'input, select, textarea, button:not([data-close])',
    )
    ;(first ?? panel.current)?.focus()
    return () => previous?.focus?.()
  }, [])

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${styles.panel} ${wide ? styles.wide : ''}`}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation()
            onClose()
          }
        }}
      >
        <div className={styles.header}>
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="link" data-close onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
