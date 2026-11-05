import { useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/client'
import { useAsk, useDeleteWidget, usePinQuestion, useWidgets } from '../../api/hooks'
import type { AiStatus, AskAnswer, AskQuery, Widget } from '../../api/types'
import { ResultChart, ResultTable } from '../../charts/ResultChart'
import { Card, ErrorText } from '../../components/ui'
import styles from './dashboard.module.css'

const PROVIDERS: Record<string, string> = { gemini: 'Google Gemini', ollama: 'your local Ollama' }

/** What leaves the machine, said next to the input (ADR-0030, ARCHITECTURE §18). */
export function AskDisclosure({ provider }: { provider: string }) {
  return (
    <p className={styles.note}>
      Your question is sent to {PROVIDERS[provider] ?? provider}, with your category names and
      account types. Your transactions, amounts and account names never are: the answer is worked
      out on this computer.
      {provider === 'gemini' &&
        " On Gemini's free tier, Google may use questions to improve its products, which can include human review."}
    </p>
  )
}

function QueryDetails({ query }: { query: AskQuery }) {
  if (!query.spec && !query.sql) return null
  return (
    <details className={styles.queryDetails}>
      <summary>Show query</summary>
      <pre>{query.sql ?? JSON.stringify(query.spec, null, 2)}</pre>
    </details>
  )
}

function Answer({ answer }: { answer: AskAnswer }) {
  const [asTable, setAsTable] = useState(false)
  const [pinned, setPinned] = useState(false)
  const pin = usePinQuestion()
  const { query, result } = answer

  if (query.status === 'clarify')
    return <p role="status">{query.clarification ?? 'Could you say a bit more?'}</p>
  if (query.status === 'failed' || !result)
    return <ErrorText>{query.error ?? 'Finboard couldn’t answer that.'}</ErrorText>

  return (
    <div className={styles.askAnswer}>
      <p role="status">{answer.answer}</p>
      {asTable ? (
        <ResultTable result={result} />
      ) : (
        <ResultChart result={result} chart={query.chart} />
      )}
      <div className={styles.askActions}>
        <button type="button" onClick={() => setAsTable(!asTable)}>
          {asTable ? 'Show as chart' : 'Show as table'}
        </button>
        <button
          type="button"
          disabled={pinned || pin.isPending}
          onClick={() => pin.mutate({ id: query.id }, { onSuccess: () => setPinned(true) })}
        >
          {pinned ? 'Pinned to dashboard' : 'Pin to dashboard'}
        </button>
      </div>
      <ErrorText>{pin.error ? errorMessage(pin.error) : null}</ErrorText>
      <QueryDetails query={query} />
    </div>
  )
}

/** "Ask Finboard" (M4a): a plain-English question answered as a chart or table. */
export function AskPanel({ status }: { status: AiStatus }) {
  const [question, setQuestion] = useState('')
  const ask = useAsk()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (question.trim().length >= 3) ask.mutate(question.trim())
  }

  return (
    <Card title="Ask Finboard">
      <form className={styles.askForm} onSubmit={submit} aria-label="Ask Finboard">
        <label className="visually-hidden" htmlFor="ask-question">
          Question
        </label>
        <input
          id="ask-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Monthly eating out and groceries for the last six months"
          maxLength={500}
          autoComplete="off"
        />
        <button type="submit" className="primary" disabled={ask.isPending}>
          {ask.isPending ? 'Asking…' : 'Ask'}
        </button>
      </form>
      <AskDisclosure provider={status.ask_provider} />
      <ErrorText>{ask.error ? errorMessage(ask.error) : null}</ErrorText>
      {ask.data && <Answer key={ask.data.query.id} answer={ask.data} />}
    </Card>
  )
}

function WidgetCard({ widget }: { widget: Widget }) {
  const remove = useDeleteWidget()
  return (
    <Card title={widget.title}>
      {widget.status === 'ok' && widget.result ? (
        <ResultChart result={widget.result} chart={widget.chart} />
      ) : (
        <p className={styles.note} role="status">
          {widget.message ?? 'This chart can’t be shown right now.'}
        </p>
      )}
      <div className={styles.askActions}>
        <button
          type="button"
          onClick={() => remove.mutate(widget.id)}
          disabled={remove.isPending}
          aria-label={`Remove “${widget.title}” from the dashboard`}
        >
          Remove
        </button>
      </div>
    </Card>
  )
}

/** Pinned questions, re-run locally on each visit (no AI call). */
export function PinnedWidgets() {
  const widgets = useWidgets(true)
  if (!widgets.data?.items.length) return null
  return (
    <section aria-label="Pinned questions" className={styles.widgets}>
      {widgets.data.items.map((w) => (
        <WidgetCard key={w.id} widget={w} />
      ))}
    </section>
  )
}
