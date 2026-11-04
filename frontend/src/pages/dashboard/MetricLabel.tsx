import { useId } from 'react'
import { useMeta } from '../../api/hooks'
import styles from './dashboard.module.css'

/** A metric's name with its definition from GET /meta (ARCHITECTURE §12) as a tooltip, shown
 *  on hover and keyboard focus and read out as the button's description. */
export function MetricLabel({ metric, children }: { metric: string; children: string }) {
  const meta = useMeta()
  const id = useId()
  const definition = meta.data?.metric_definitions[metric]
  if (!definition) return <span>{children}</span>
  return (
    <span className={styles.metric}>
      {children}
      <button
        type="button"
        className={styles.info}
        aria-label={`How ${children} is worked out`}
        aria-describedby={id}
      >
        ?
      </button>
      <span role="tooltip" id={id} className={styles.tooltip}>
        <strong>{definition.formula}</strong>
        <br />
        {definition.tooltip}
      </span>
    </span>
  )
}
