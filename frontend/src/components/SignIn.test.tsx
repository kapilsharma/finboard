import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { setCsrfToken } from '../api/client'
import { ME, mockApi, renderRoute } from '../test/utils'

const SIGNED_OUT = {
  status: 401,
  body: { status: 401, code: 'unauthenticated', title: 'Not signed in' },
}
const SERVER_ME = {
  ...ME,
  username: 'carol',
  display_name: 'Carol',
  mode: 'server',
  csrf_token: 'tok-1',
}
const META = { version: '1', api_version: 'v1', mode: 'server', metric_definitions: {} }
const SHELL = {
  'GET /settings': () => ({ body: { theme: 'system' } }),
  'GET /dashboard': () => ({ body: null }),
  'GET /dashboard/months': () => ({ body: { months: [] } }),
}

afterEach(() => setCsrfToken(null))

describe('sign-in (server mode)', () => {
  it('shows the sign-in page when nobody is signed in, then the app after signing in', async () => {
    let signedIn = false
    const calls = mockApi({
      ...SHELL,
      'GET /me': () => (signedIn ? { body: SERVER_ME } : SIGNED_OUT),
      'GET /meta': () => ({ body: { ...META, signup_open: false } }),
      'POST /auth/login': () => {
        signedIn = true
        return { body: { id: 'u1', username: 'carol', display_name: 'Carol', csrf_token: 'tok-1' } }
      },
    })
    renderRoute('/')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    // Sign-up is closed: no way to create an account, and the page says who to ask.
    expect(await screen.findByText(/Ask whoever runs this server/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create an account' })).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Username'), 'carol')
    await userEvent.type(screen.getByLabelText('Password'), 'a long enough passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByText('Carol')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/login')?.body).toEqual({
      username: 'carol',
      password: 'a long enough passphrase',
    })
  })

  it('says so when the password is wrong, and stays on the page', async () => {
    mockApi({
      'GET /me': () => SIGNED_OUT,
      'GET /meta': () => ({ body: { ...META, signup_open: false } }),
      'POST /auth/login': () => ({
        status: 401,
        body: { status: 401, code: 'invalid_credentials', title: 'Wrong username or password' },
      }),
    })
    renderRoute('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'carol')
    await userEvent.type(screen.getByLabelText('Password'), 'not the password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password')
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('offers sign-up only when the server has it open', async () => {
    let signedIn = false
    const calls = mockApi({
      ...SHELL,
      'GET /me': () => (signedIn ? { body: SERVER_ME } : SIGNED_OUT),
      'GET /meta': () => ({ body: { ...META, signup_open: true } }),
      'POST /auth/signup': () => {
        signedIn = true
        return {
          status: 201,
          body: { id: 'u1', username: 'carol', display_name: 'Carol', csrf_token: 'tok-1' },
        }
      },
    })
    renderRoute('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Username'), 'carol')
    await userEvent.type(screen.getByLabelText(/Name shown in the app/), 'Carol')
    await userEvent.type(screen.getByLabelText(/^Password/), 'a long enough passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/signup')?.body).toEqual({
      username: 'carol',
      display_name: 'Carol',
      password: 'a long enough passphrase',
    })
  })

  it('sends the session CSRF token on changes, and signs out', async () => {
    let signedIn = true
    const calls = mockApi({
      ...SHELL,
      'GET /me': () => (signedIn ? { body: SERVER_ME } : SIGNED_OUT),
      'GET /meta': () => ({ body: { ...META, signup_open: false } }),
      'POST /auth/logout': () => {
        signedIn = false
        return { status: 204 }
      },
    })
    renderRoute('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    const logout = calls.find((c) => c.path === '/auth/logout')
    expect(logout?.headers['X-CSRF-Token']).toBe('tok-1')
    expect(logout?.headers['X-Finboard-Client']).toBe('1')
  })

  it('changes the password from Settings › Preferences', async () => {
    const calls = mockApi({
      ...SHELL,
      'GET /me': () => ({ body: SERVER_ME }),
      'POST /auth/password': () => ({ status: 204 }),
    })
    renderRoute('/settings/preferences')
    await userEvent.type(await screen.findByLabelText('Current password'), 'the old passphrase')
    await userEvent.type(screen.getByLabelText('New password'), 'a brand new passphrase')
    await userEvent.type(screen.getByLabelText('New password again'), 'a brand new passphrasX')
    expect(screen.getByRole('alert')).toHaveTextContent('The two new passwords differ.')
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('New password again'))
    await userEvent.type(screen.getByLabelText('New password again'), 'a brand new passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByText('Password changed.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Current password')).toHaveValue(''))
    expect(calls.find((c) => c.path === '/auth/password')?.body).toEqual({
      current_password: 'the old passphrase',
      new_password: 'a brand new passphrase',
    })
  })
})

describe('local mode', () => {
  it('has no sign-out and no password form', async () => {
    const calls = mockApi({ ...SHELL, 'GET /me': () => ({ body: ME }) })
    renderRoute('/settings/preferences')
    expect(await screen.findByRole('heading', { name: 'Preferences' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Password' })).not.toBeInTheDocument()
    expect(calls.every((c) => !('X-CSRF-Token' in c.headers))).toBe(true)
  })
})
