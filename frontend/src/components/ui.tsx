import type { ReactNode } from 'react'
import styles from './ui.module.css'

export function PageHeader({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <div className={styles.pageHeader}>
      <h1>{title}</h1>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </div>
  )
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className={styles.card} aria-label={title}>
      {title && <h2 className={styles.cardTitle}>{title}</h2>}
      {children}
    </section>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p className={styles.error} role="alert">
      {children}
    </p>
  )
}

export function ComingSoon({
  title,
  milestone,
  children,
}: {
  title: string
  milestone: string
  children: ReactNode
}) {
  return (
    <>
      <PageHeader title={title} />
      <Card>
        <p className={styles.muted}>{children}</p>
        <p className={styles.muted}>Planned for {milestone} (see docs/ROADMAP.md).</p>
      </Card>
    </>
  )
}
