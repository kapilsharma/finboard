import { useState, type FormEvent } from 'react'
import { ApiError, errorMessage } from '../api/client'
import { useLogin, useMeta, useSignup } from '../api/hooks'
import { ErrorText } from './ui'
import styles from './SignInPage.module.css'

const MIN_PASSWORD = 10

/** Server mode: sign in, or create an account when the operator has opened sign-up. */
export function SignInPage({ onSignedIn }: { onSignedIn: () => void }) {
  const meta = useMeta()
  const login = useLogin()
  const signup = useSignup()
  const signupOpen = meta.data?.signup_open ?? false
  const [creating, setCreating] = useState(false)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')

  const mode = creating && signupOpen ? 'signup' : 'login'
  const pending = login.isPending || signup.isPending
  const failure = mode === 'signup' ? signup.error : login.error

  function submit(event: FormEvent) {
    event.preventDefault()
    const done = { onSuccess: onSignedIn }
    if (mode === 'signup') {
      signup.mutate({ username, password, display_name: displayName || null }, done)
    } else {
      login.mutate({ username, password }, done)
    }
  }

  function switchMode() {
    setCreating(!creating)
    setPassword('')
    login.reset()
    signup.reset()
  }

  return (
    <main className={styles.page}>
      <form className={styles.card} onSubmit={submit} aria-labelledby="sign-in-title">
        <p className={styles.brand}>Finboard</p>
        <h1 id="sign-in-title">{mode === 'signup' ? 'Create your account' : 'Sign in'}</h1>

        <label className={styles.field}>
          Username
          <input
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            minLength={mode === 'signup' ? 3 : 1}
            maxLength={32}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        {mode === 'signup' && (
          <label className={styles.field}>
            Name shown in the app (optional)
            <input
              name="display_name"
              autoComplete="name"
              maxLength={120}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </label>
        )}
        <label className={styles.field}>
          Password
          <input
            name="password"
            type="password"
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            required
            minLength={mode === 'signup' ? MIN_PASSWORD : 1}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === 'signup' && (
            <span className={styles.hint}>
              At least {MIN_PASSWORD} characters. A few unrelated words work well.
            </span>
          )}
        </label>

        <ErrorText>{failure ? signInMessage(failure) : null}</ErrorText>
        <button className="primary" type="submit" disabled={pending}>
          {mode === 'signup' ? 'Create account' : 'Sign in'}
        </button>

        {signupOpen ? (
          <button className="link" type="button" onClick={switchMode}>
            {mode === 'signup' ? 'I already have an account' : 'Create an account'}
          </button>
        ) : (
          meta.data && (
            <p className={styles.hint}>
              No account? Ask whoever runs this server to create one for you.
            </p>
          )
        )}
      </form>
    </main>
  )
}

function signInMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'rate_limited') {
    return error.problem.detail ?? 'Too many attempts. Wait a few minutes, then try again.'
  }
  return errorMessage(error)
}
