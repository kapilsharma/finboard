import { errorMessage } from '../../api/client'
import {
  useAiStatus,
  useAskHistory,
  useClearAskHistory,
  useUpdateAiSettings,
} from '../../api/hooks'
import type { AiStatus } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { AskDisclosure } from '../dashboard/AskPanel'
import styles from './settings.module.css'

function Toggle({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  disabled: boolean
  label: string
  onChange: (on: boolean) => void
}) {
  return (
    <label className={styles.aiToggle}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}

function Unavailable({ children }: { children: React.ReactNode }) {
  return <p className={styles.muted}>Not available on this server. {children}</p>
}

function Suggestions({ status }: { status: AiStatus }) {
  const update = useUpdateAiSettings()
  return (
    <Card title="Category suggestions">
      <p>
        When a transaction needs a category, suggest one from your own transactions that look alike,
        with examples. Nothing is ever applied for you, and this runs entirely on this computer:
        nothing is sent anywhere.
      </p>
      {status.suggestions_available ? (
        <>
          <Toggle
            label="Suggest categories"
            checked={status.suggestions_enabled}
            disabled={update.isPending}
            onChange={(on) => update.mutate({ suggestions: on })}
          />
          {status.suggestions_enabled && status.suggest_method !== 'trigram' && (
            <p className={styles.muted} role="status">
              {status.embedded} of {status.transactions} transactions prepared for matching
              {status.embedded < status.transactions &&
                ' (the rest are prepared in the background)'}
              .
            </p>
          )}
        </>
      ) : (
        <Unavailable>
          The operator turns it on with <code>FINBOARD_AI_SUGGESTIONS=on</code> after{' '}
          <code>uv sync --extra ai</code> and <code>finboard ai fetch-model</code>.
        </Unavailable>
      )}
      <ErrorText>{update.isError ? errorMessage(update.error) : null}</ErrorText>
    </Card>
  )
}

function Ask({ status }: { status: AiStatus }) {
  const update = useUpdateAiSettings()
  const history = useAskHistory(status.ask_enabled)
  const clear = useClearAskHistory()
  const unpinned = history.data?.items.filter((q) => !q.pinned).length ?? 0
  return (
    <Card title="Ask Finboard">
      <p>
        Ask questions in plain English on the dashboard, answered as a chart or table you can pin.
      </p>
      {status.ask_available ? (
        <>
          <AskDisclosure provider={status.ask_provider} />
          <Toggle
            label="Use Ask Finboard"
            checked={status.ask_enabled}
            disabled={update.isPending}
            onChange={(on) => update.mutate({ ask: on })}
          />
          {status.ask_enabled && (
            <p className={styles.muted}>
              {unpinned} question{unpinned === 1 ? '' : 's'} in your history (results are never
              stored).{' '}
              <button
                type="button"
                onClick={() => clear.mutate()}
                disabled={clear.isPending || unpinned === 0}
              >
                Clear history
              </button>
            </p>
          )}
        </>
      ) : (
        <Unavailable>
          The operator turns it on with <code>FINBOARD_AI_ASK=gemini</code> (and{' '}
          <code>FINBOARD_GEMINI_API_KEY</code>) or <code>FINBOARD_AI_ASK=ollama</code>.
        </Unavailable>
      )}
      <ErrorText>
        {update.isError
          ? errorMessage(update.error)
          : clear.isError
            ? errorMessage(clear.error)
            : null}
      </ErrorText>
    </Card>
  )
}

/** Settings › AI (ADR-0030): both features off until the server offers them and you opt in. */
export function AiTab() {
  const status = useAiStatus()
  if (status.isPending) return <p className={styles.muted}>Loading…</p>
  if (status.isError) return <ErrorText>{errorMessage(status.error)}</ErrorText>
  return (
    <div className={styles.aiStack}>
      <Suggestions status={status.data} />
      <Ask status={status.data} />
    </div>
  )
}
